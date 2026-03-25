"""Tests for semantic ADO matcher (embeddings + LLM re-rank)."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from unittest.mock import patch, MagicMock

import pytest

from models import TopicCluster, ADOMatch
from tests.conftest import make_cluster


# ── Helpers ──────────────────────────────────────────────────────────


def _sample_ado_items():
    return [
        {
            "id": 100,
            "title": "Calendar sync broken on iOS",
            "description": "Users report calendar not syncing after update",
            "state": "Active",
            "assigned_to": "dev@microsoft.com",
            "changed_date": "2026-03-20T10:00:00Z",
            "tags": "iOS;Calendar",
            "work_item_type": "Bug",
        },
        {
            "id": 200,
            "title": "Mail notifications delayed",
            "description": "Push notifications arrive late",
            "state": "New",
            "assigned_to": "",
            "changed_date": "2026-03-18T08:00:00Z",
            "tags": "",
            "work_item_type": "Bug",
        },
    ]


def _mock_embedding(dim=3):
    """Return a small fake embedding vector."""
    return [0.1, 0.2, 0.3][:dim]


# ── Auth detection ───────────────────────────────────────────────────


class TestGetAuthMode:
    def test_pat_when_env_set(self):
        from ado_matcher import _get_auth_mode
        with patch.dict(os.environ, {"SYSTEM_ACCESSTOKEN": "fake-pat"}):
            assert _get_auth_mode() == "pat"

    def test_az_cli_when_available(self):
        from ado_matcher import _get_auth_mode
        with patch.dict(os.environ, {}, clear=True), \
             patch("ado_matcher.os.environ", new={}), \
             patch("ado_matcher.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            # Also ensure SYSTEM_ACCESSTOKEN is not set
            with patch.dict(os.environ, {}, clear=False):
                os.environ.pop("SYSTEM_ACCESSTOKEN", None)
                assert _get_auth_mode() == "az"

    def test_none_when_no_auth(self):
        from ado_matcher import _get_auth_mode
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("SYSTEM_ACCESSTOKEN", None)
            with patch("ado_matcher.subprocess.run", side_effect=FileNotFoundError):
                assert _get_auth_mode() == "none"

    def test_none_when_az_timeout(self):
        from ado_matcher import _get_auth_mode
        import subprocess
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("SYSTEM_ACCESSTOKEN", None)
            with patch("ado_matcher.subprocess.run", side_effect=subprocess.TimeoutExpired("az", 10)):
                assert _get_auth_mode() == "none"


# ── PAT headers ──────────────────────────────────────────────────────


class TestAdoHeadersPat:
    def test_returns_basic_auth(self):
        from ado_matcher import _ado_headers_pat
        with patch.dict(os.environ, {"SYSTEM_ACCESSTOKEN": "my-token"}):
            headers = _ado_headers_pat()
        assert "Authorization" in headers
        assert headers["Authorization"].startswith("Basic ")
        assert headers["Content-Type"] == "application/json"


# ── WIQL ─────────────────────────────────────────────────────────────


class TestBuildWiql:
    def test_includes_area_path_for_ios(self):
        from ado_matcher import _build_wiql
        wiql = _build_wiql("ios", 90)
        assert "Outlook Mobile\\iOS" in wiql
        assert "Bug" in wiql
        assert "@today - 90" in wiql

    def test_no_area_path_for_unknown_platform(self):
        from ado_matcher import _build_wiql
        wiql = _build_wiql("unknown_platform", 30)
        assert "UNDER" not in wiql

    def test_includes_work_item_types(self):
        from ado_matcher import _build_wiql
        wiql = _build_wiql("mac", 60)
        assert "Bug" in wiql
        assert "Task" in wiql
        assert "User Story" in wiql


class TestRunWiql:
    def test_pat_mode(self):
        from ado_matcher import _run_wiql
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"workItems": [{"id": 1}, {"id": 2}]}
        mock_resp.raise_for_status = MagicMock()
        with patch.dict(os.environ, {"SYSTEM_ACCESSTOKEN": "token"}), \
             patch("ado_matcher.http_requests.post", return_value=mock_resp):
            ids = _run_wiql("SELECT ...", "pat")
        assert ids == [1, 2]

    def test_az_mode(self):
        from ado_matcher import _run_wiql
        mock_result = MagicMock(
            returncode=0,
            stdout=json.dumps({"workItems": [{"id": 10}]}),
        )
        with patch("ado_matcher.subprocess.run", return_value=mock_result):
            ids = _run_wiql("SELECT ...", "az")
        assert ids == [10]

    def test_az_mode_failure(self):
        from ado_matcher import _run_wiql
        mock_result = MagicMock(returncode=1, stderr="error msg")
        with patch("ado_matcher.subprocess.run", return_value=mock_result):
            with pytest.raises(RuntimeError, match="WIQL query failed"):
                _run_wiql("SELECT ...", "az")

    def test_empty_results(self):
        from ado_matcher import _run_wiql
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"workItems": []}
        mock_resp.raise_for_status = MagicMock()
        with patch.dict(os.environ, {"SYSTEM_ACCESSTOKEN": "token"}), \
             patch("ado_matcher.http_requests.post", return_value=mock_resp):
            ids = _run_wiql("SELECT ...", "pat")
        assert ids == []


# ── Fetch work items ─────────────────────────────────────────────────


class TestFetchWorkItems:
    def test_empty_ids_returns_empty(self):
        from ado_matcher import _fetch_work_items
        assert _fetch_work_items([], "pat") == []

    def test_pat_mode_parses_fields(self):
        from ado_matcher import _fetch_work_items
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "value": [{
                "id": 100,
                "fields": {
                    "System.Title": "Test Bug",
                    "System.Description": "<b>Bold</b> text",
                    "System.State": "Active",
                    "System.AssignedTo": {"displayName": "Dev User"},
                    "System.ChangedDate": "2026-03-20T10:00:00Z",
                    "System.Tags": "iOS",
                    "System.WorkItemType": "Bug",
                },
            }],
        }
        mock_resp.raise_for_status = MagicMock()
        with patch.dict(os.environ, {"SYSTEM_ACCESSTOKEN": "token"}), \
             patch("ado_matcher.http_requests.get", return_value=mock_resp):
            items = _fetch_work_items([100], "pat")
        assert len(items) == 1
        assert items[0]["title"] == "Test Bug"
        assert items[0]["assigned_to"] == "Dev User"
        assert "<b>" not in items[0]["description"]  # HTML stripped

    def test_assigned_to_string(self):
        from ado_matcher import _fetch_work_items
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "value": [{
                "id": 101,
                "fields": {
                    "System.Title": "Bug",
                    "System.AssignedTo": "plain@email.com",
                    "System.State": "New",
                },
            }],
        }
        mock_resp.raise_for_status = MagicMock()
        with patch.dict(os.environ, {"SYSTEM_ACCESSTOKEN": "token"}), \
             patch("ado_matcher.http_requests.get", return_value=mock_resp):
            items = _fetch_work_items([101], "pat")
        assert items[0]["assigned_to"] == "plain@email.com"

    def test_az_mode_continues_on_error(self):
        from ado_matcher import _fetch_work_items
        mock_result = MagicMock(returncode=1, stderr="error")
        with patch("ado_matcher.subprocess.run", return_value=mock_result):
            items = _fetch_work_items([1, 2], "az")
        assert items == []

    def test_batches_200_ids(self):
        from ado_matcher import _fetch_work_items
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"value": []}
        mock_resp.raise_for_status = MagicMock()
        with patch.dict(os.environ, {"SYSTEM_ACCESSTOKEN": "token"}), \
             patch("ado_matcher.http_requests.get", return_value=mock_resp) as mock_get:
            _fetch_work_items(list(range(250)), "pat")
        assert mock_get.call_count == 2  # 200 + 50


# ── Strip HTML ───────────────────────────────────────────────────────


class TestStripHtml:
    def test_removes_tags(self):
        from ado_matcher import _strip_html
        assert _strip_html("<p>Hello <b>world</b></p>") == "Hello world"

    def test_empty_string(self):
        from ado_matcher import _strip_html
        assert _strip_html("") == ""

    def test_collapses_whitespace(self):
        from ado_matcher import _strip_html
        assert _strip_html("<p>Hello</p>  <p>World</p>") == "Hello World"


# ── Text representations ─────────────────────────────────────────────


class TestAdoItemToText:
    def test_basic(self):
        from ado_matcher import _ado_item_to_text
        item = {"title": "Bug title", "description": "Desc", "tags": "iOS;Calendar"}
        text = _ado_item_to_text(item)
        assert "Bug title" in text
        assert "Desc" in text
        assert "Tags: iOS;Calendar" in text

    def test_no_description_or_tags(self):
        from ado_matcher import _ado_item_to_text
        item = {"title": "Bug title", "description": "", "tags": ""}
        text = _ado_item_to_text(item)
        assert text == "Bug title"

    def test_truncates_long_description(self):
        from ado_matcher import _ado_item_to_text
        item = {"title": "T", "description": "x" * 1000, "tags": ""}
        text = _ado_item_to_text(item)
        # Description should be truncated to 500 chars
        assert len(text) < 600


class TestClusterToText:
    def test_basic(self):
        from ado_matcher import _cluster_to_text
        cluster = make_cluster(
            topic="Calendar sync",
            summary="Sync fails after update",
            quotes=["Quote 1", "Quote 2", "Quote 3", "Quote 4"],
        )
        text = _cluster_to_text(cluster)
        assert "Calendar sync" in text
        assert "Sync fails" in text
        assert "Quote 1" in text
        assert "Quote 3" in text
        # Only 3 quotes should be included
        assert "Quote 4" not in text

    def test_empty_summary(self):
        from ado_matcher import _cluster_to_text
        cluster = make_cluster(topic="Test", summary="", quotes=[])
        text = _cluster_to_text(cluster)
        assert text == "Test"


# ── Cosine similarity ────────────────────────────────────────────────


class TestCosineSimilarity:
    def test_identical_vectors(self):
        from ado_matcher import _cosine_similarity
        assert _cosine_similarity([1, 0, 0], [1, 0, 0]) == pytest.approx(1.0)

    def test_orthogonal_vectors(self):
        from ado_matcher import _cosine_similarity
        assert _cosine_similarity([1, 0], [0, 1]) == pytest.approx(0.0)

    def test_opposite_vectors(self):
        from ado_matcher import _cosine_similarity
        assert _cosine_similarity([1, 0], [-1, 0]) == pytest.approx(-1.0)

    def test_zero_vector(self):
        from ado_matcher import _cosine_similarity
        assert _cosine_similarity([0, 0], [1, 1]) == 0.0

    def test_matrix(self):
        from ado_matcher import _cosine_similarity_matrix
        cluster_emb = [[1, 0], [0, 1]]
        ado_emb = [[1, 0], [0, 1], [1, 1]]
        matrix = _cosine_similarity_matrix(cluster_emb, ado_emb)
        assert len(matrix) == 2
        assert len(matrix[0]) == 3
        assert matrix[0][0] == pytest.approx(1.0)  # identical
        assert matrix[0][1] == pytest.approx(0.0)  # orthogonal


# ── Get embeddings ───────────────────────────────────────────────────


class TestGetEmbeddings:
    def test_success(self):
        from ado_matcher import _get_embeddings
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "data": [
                {"index": 0, "embedding": [0.1, 0.2]},
                {"index": 1, "embedding": [0.3, 0.4]},
            ]
        }
        mock_resp.raise_for_status = MagicMock()
        with patch.dict(os.environ, {"GITHUB_TOKEN": "test-token"}), \
             patch("ado_matcher.http_requests.post", return_value=mock_resp):
            result = _get_embeddings(["text1", "text2"])
        assert len(result) == 2
        assert result[0] == [0.1, 0.2]

    def test_no_token_raises(self):
        from ado_matcher import _get_embeddings
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("GITHUB_TOKEN", None)
            os.environ.pop("GH_MODELS_TOKEN", None)
            with pytest.raises(RuntimeError, match="GITHUB_TOKEN"):
                _get_embeddings(["test"])

    def test_batches_over_100(self):
        from ado_matcher import _get_embeddings
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"data": [{"index": i, "embedding": [0.1]} for i in range(100)]}
        mock_resp.raise_for_status = MagicMock()
        with patch.dict(os.environ, {"GITHUB_TOKEN": "token"}), \
             patch("ado_matcher.http_requests.post", return_value=mock_resp) as mock_post:
            _get_embeddings(["t"] * 150)
        assert mock_post.call_count == 2

    def test_sorts_by_index(self):
        from ado_matcher import _get_embeddings
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "data": [
                {"index": 1, "embedding": [0.3, 0.4]},
                {"index": 0, "embedding": [0.1, 0.2]},
            ]
        }
        mock_resp.raise_for_status = MagicMock()
        with patch.dict(os.environ, {"GITHUB_TOKEN": "token"}), \
             patch("ado_matcher.http_requests.post", return_value=mock_resp):
            result = _get_embeddings(["a", "b"])
        assert result[0] == [0.1, 0.2]  # index 0 first


# ── LLM re-rank ─────────────────────────────────────────────────────


class TestLlmRerank:
    def test_success(self):
        from ado_matcher import _llm_rerank
        cluster = make_cluster(topic="Calendar sync", summary="Sync fails")
        candidates = [
            {"id": 100, "title": "Cal bug", "state": "Active", "description": "", "work_item_type": "Bug"},
            {"id": 200, "title": "Mail bug", "state": "New", "description": "", "work_item_type": "Bug"},
        ]
        llm_response = json.dumps([
            {"id": 100, "confidence": "high", "rationale": "Direct match"},
        ])
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "output": [{"type": "message", "content": [{"type": "output_text", "text": llm_response}]}]
        }
        mock_resp.raise_for_status = MagicMock()
        with patch.dict(os.environ, {"GITHUB_TOKEN": "token"}), \
             patch("ado_matcher.http_requests.post", return_value=mock_resp):
            result = _llm_rerank(cluster, candidates, "ios")
        assert len(result) == 1
        assert result[0]["id"] == 100
        assert result[0]["llm_confidence"] == "high"

    def test_no_token_returns_candidates(self):
        from ado_matcher import _llm_rerank
        cluster = make_cluster()
        candidates = [{"id": 1, "title": "T", "state": "New", "description": "", "work_item_type": "Bug"}]
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("GITHUB_TOKEN", None)
            os.environ.pop("GH_MODELS_TOKEN", None)
            result = _llm_rerank(cluster, candidates, "ios")
        assert result == candidates

    def test_api_error_falls_back(self):
        from ado_matcher import _llm_rerank
        cluster = make_cluster()
        candidates = [{"id": 1, "title": "T", "state": "New", "description": "", "work_item_type": "Bug"}]
        with patch.dict(os.environ, {"GITHUB_TOKEN": "token"}), \
             patch("ado_matcher.http_requests.post", side_effect=Exception("API down")):
            result = _llm_rerank(cluster, candidates, "ios")
        assert result == candidates

    def test_empty_llm_response_returns_candidates(self):
        from ado_matcher import _llm_rerank
        cluster = make_cluster()
        candidates = [{"id": 1, "title": "T", "state": "New", "description": "", "work_item_type": "Bug"}]
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"output": []}
        mock_resp.raise_for_status = MagicMock()
        with patch.dict(os.environ, {"GITHUB_TOKEN": "token"}), \
             patch("ado_matcher.http_requests.post", return_value=mock_resp):
            result = _llm_rerank(cluster, candidates, "ios")
        assert result == candidates

    def test_markdown_fences_stripped(self):
        from ado_matcher import _llm_rerank
        cluster = make_cluster()
        candidates = [{"id": 1, "title": "T", "state": "New", "description": "", "work_item_type": "Bug"}]
        llm_text = '```json\n[{"id": 1, "confidence": "medium", "rationale": "Match"}]\n```'
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "output": [{"type": "message", "content": [{"type": "output_text", "text": llm_text}]}]
        }
        mock_resp.raise_for_status = MagicMock()
        with patch.dict(os.environ, {"GITHUB_TOKEN": "token"}), \
             patch("ado_matcher.http_requests.post", return_value=mock_resp):
            result = _llm_rerank(cluster, candidates, "ios")
        assert len(result) == 1
        assert result[0]["llm_confidence"] == "medium"

    def test_invalid_json_returns_candidates(self):
        from ado_matcher import _llm_rerank
        cluster = make_cluster()
        candidates = [{"id": 1, "title": "T", "state": "New", "description": "", "work_item_type": "Bug"}]
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "output": [{"type": "message", "content": [{"type": "output_text", "text": "not json"}]}]
        }
        mock_resp.raise_for_status = MagicMock()
        with patch.dict(os.environ, {"GITHUB_TOKEN": "token"}), \
             patch("ado_matcher.http_requests.post", return_value=mock_resp):
            result = _llm_rerank(cluster, candidates, "ios")
        assert result == candidates

    def test_non_list_json_returns_candidates(self):
        from ado_matcher import _llm_rerank
        cluster = make_cluster()
        candidates = [{"id": 1, "title": "T", "state": "New", "description": "", "work_item_type": "Bug"}]
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "output": [{"type": "message", "content": [{"type": "output_text", "text": '{"not": "a list"}'}]}]
        }
        mock_resp.raise_for_status = MagicMock()
        with patch.dict(os.environ, {"GITHUB_TOKEN": "token"}), \
             patch("ado_matcher.http_requests.post", return_value=mock_resp):
            result = _llm_rerank(cluster, candidates, "ios")
        assert result == candidates


# ── Main entry point: match_clusters_semantic ────────────────────────


class TestMatchClustersSemantic:
    def test_empty_clusters_returns_empty(self):
        from ado_matcher import match_clusters_semantic
        result = match_clusters_semantic([], platform="ios")
        assert result == []

    def test_no_auth_returns_clusters_unchanged(self):
        from ado_matcher import match_clusters_semantic
        clusters = [make_cluster()]
        with patch("ado_matcher._get_auth_mode", return_value="none"):
            result = match_clusters_semantic(clusters, platform="ios")
        assert result == clusters
        assert len(result[0].ado_matches) == 0

    def test_wiql_failure_returns_clusters_unchanged(self):
        from ado_matcher import match_clusters_semantic
        clusters = [make_cluster()]
        with patch("ado_matcher._get_auth_mode", return_value="pat"), \
             patch("ado_matcher._run_wiql", side_effect=Exception("WIQL error")):
            result = match_clusters_semantic(clusters, platform="ios")
        assert len(result[0].ado_matches) == 0

    def test_no_wiql_results_returns_clusters_unchanged(self):
        from ado_matcher import match_clusters_semantic
        clusters = [make_cluster()]
        with patch("ado_matcher._get_auth_mode", return_value="pat"), \
             patch("ado_matcher._run_wiql", return_value=[]):
            result = match_clusters_semantic(clusters, platform="ios")
        assert len(result[0].ado_matches) == 0

    def test_no_ado_items_returns_clusters_unchanged(self):
        from ado_matcher import match_clusters_semantic
        clusters = [make_cluster()]
        with patch("ado_matcher._get_auth_mode", return_value="pat"), \
             patch("ado_matcher._run_wiql", return_value=[1, 2]), \
             patch("ado_matcher._fetch_work_items", return_value=[]):
            result = match_clusters_semantic(clusters, platform="ios")
        assert len(result[0].ado_matches) == 0

    def test_embedding_failure_returns_clusters_unchanged(self):
        from ado_matcher import match_clusters_semantic
        clusters = [make_cluster()]
        with patch("ado_matcher._get_auth_mode", return_value="pat"), \
             patch("ado_matcher._run_wiql", return_value=[1]), \
             patch("ado_matcher._fetch_work_items", return_value=_sample_ado_items()[:1]), \
             patch("ado_matcher._get_embeddings", side_effect=Exception("Embedding API down")):
            result = match_clusters_semantic(clusters, platform="ios")
        assert len(result[0].ado_matches) == 0

    def test_full_pipeline_attaches_matches(self):
        from ado_matcher import match_clusters_semantic
        clusters = [make_cluster(topic="Calendar sync failures")]
        ado_items = _sample_ado_items()

        # 1 cluster + 2 ADO items = 3 embeddings needed
        # Make cluster embedding very similar to first ADO item
        embeddings = [
            [1.0, 0.0, 0.0],  # cluster
            [0.99, 0.1, 0.0],  # ADO item 1 (high similarity)
            [0.0, 0.0, 1.0],  # ADO item 2 (low similarity)
        ]

        # LLM rerank returns item 100 as high confidence
        llm_response = json.dumps([
            {"id": 100, "confidence": "high", "rationale": "Calendar sync match"},
        ])
        mock_llm_resp = MagicMock()
        mock_llm_resp.json.return_value = {
            "output": [{"type": "message", "content": [{"type": "output_text", "text": llm_response}]}]
        }
        mock_llm_resp.raise_for_status = MagicMock()

        with patch("ado_matcher._get_auth_mode", return_value="pat"), \
             patch("ado_matcher._run_wiql", return_value=[100, 200]), \
             patch("ado_matcher._fetch_work_items", return_value=ado_items), \
             patch("ado_matcher._get_embeddings", return_value=embeddings), \
             patch.dict(os.environ, {"GITHUB_TOKEN": "token"}), \
             patch("ado_matcher.http_requests.post", return_value=mock_llm_resp):
            result = match_clusters_semantic(clusters, platform="ios")

        assert len(result[0].ado_matches) >= 1
        match = result[0].ado_matches[0]
        assert isinstance(match, ADOMatch)
        assert match.work_item_id == 100
        assert match.title == "Calendar sync broken on iOS"

    def test_custom_max_age_days(self):
        from ado_matcher import match_clusters_semantic
        clusters = [make_cluster()]
        with patch("ado_matcher._get_auth_mode", return_value="pat"), \
             patch("ado_matcher._run_wiql", return_value=[]) as mock_wiql, \
             patch("ado_matcher._build_wiql") as mock_build:
            mock_build.return_value = "SELECT ..."
            match_clusters_semantic(clusters, platform="ios", max_age_days=30)
            mock_build.assert_called_once_with("ios", 30)

    def test_no_candidates_above_threshold(self):
        """When all similarities are below threshold, no matches are attached."""
        from ado_matcher import match_clusters_semantic
        clusters = [make_cluster()]
        ado_items = _sample_ado_items()[:1]

        # Very low similarity
        embeddings = [
            [1.0, 0.0, 0.0],  # cluster
            [0.0, 1.0, 0.0],  # ADO item (orthogonal = 0.0 similarity)
        ]

        with patch("ado_matcher._get_auth_mode", return_value="pat"), \
             patch("ado_matcher._run_wiql", return_value=[100]), \
             patch("ado_matcher._fetch_work_items", return_value=ado_items), \
             patch("ado_matcher._get_embeddings", return_value=embeddings):
            result = match_clusters_semantic(clusters, platform="ios")
        assert len(result[0].ado_matches) == 0

    def test_changed_date_parsed(self):
        """Verify that changed_date is properly parsed into datetime."""
        from ado_matcher import match_clusters_semantic
        clusters = [make_cluster()]
        ado_items = [{
            "id": 100, "title": "Bug", "description": "",
            "state": "Active", "assigned_to": "",
            "changed_date": "2026-03-20T10:00:00Z",
            "tags": "", "work_item_type": "Bug",
        }]
        embeddings = [[1.0, 0.0], [0.99, 0.1]]

        llm_response = json.dumps([{"id": 100, "confidence": "high", "rationale": "Match"}])
        mock_llm_resp = MagicMock()
        mock_llm_resp.json.return_value = {
            "output": [{"type": "message", "content": [{"type": "output_text", "text": llm_response}]}]
        }
        mock_llm_resp.raise_for_status = MagicMock()

        with patch("ado_matcher._get_auth_mode", return_value="pat"), \
             patch("ado_matcher._run_wiql", return_value=[100]), \
             patch("ado_matcher._fetch_work_items", return_value=ado_items), \
             patch("ado_matcher._get_embeddings", return_value=embeddings), \
             patch.dict(os.environ, {"GITHUB_TOKEN": "token"}), \
             patch("ado_matcher.http_requests.post", return_value=mock_llm_resp):
            result = match_clusters_semantic(clusters, platform="ios")

        assert result[0].ado_matches[0].changed_date is not None
        assert isinstance(result[0].ado_matches[0].changed_date, datetime)

    def test_invalid_changed_date_handled(self):
        """Invalid changed_date doesn't crash, just sets None."""
        from ado_matcher import match_clusters_semantic
        clusters = [make_cluster()]
        ado_items = [{
            "id": 100, "title": "Bug", "description": "",
            "state": "Active", "assigned_to": "",
            "changed_date": "not-a-date",
            "tags": "", "work_item_type": "Bug",
        }]
        embeddings = [[1.0, 0.0], [0.99, 0.1]]

        llm_response = json.dumps([{"id": 100, "confidence": "high", "rationale": "Match"}])
        mock_llm_resp = MagicMock()
        mock_llm_resp.json.return_value = {
            "output": [{"type": "message", "content": [{"type": "output_text", "text": llm_response}]}]
        }
        mock_llm_resp.raise_for_status = MagicMock()

        with patch("ado_matcher._get_auth_mode", return_value="pat"), \
             patch("ado_matcher._run_wiql", return_value=[100]), \
             patch("ado_matcher._fetch_work_items", return_value=ado_items), \
             patch("ado_matcher._get_embeddings", return_value=embeddings), \
             patch.dict(os.environ, {"GITHUB_TOKEN": "token"}), \
             patch("ado_matcher.http_requests.post", return_value=mock_llm_resp):
            result = match_clusters_semantic(clusters, platform="ios")

        assert result[0].ado_matches[0].changed_date is None

    def test_fetch_work_items_failure_returns_clusters(self):
        from ado_matcher import match_clusters_semantic
        clusters = [make_cluster()]
        with patch("ado_matcher._get_auth_mode", return_value="pat"), \
             patch("ado_matcher._run_wiql", return_value=[1, 2]), \
             patch("ado_matcher._fetch_work_items", side_effect=Exception("fetch error")):
            result = match_clusters_semantic(clusters, platform="ios")
        assert len(result[0].ado_matches) == 0
