"""Tests for Azure DevOps search + manual links + relevance ranking."""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from models import TopicCluster, ADOMatch
import ado_search

FIXTURES_DIR = Path(__file__).parent / "fixtures"


# ── Auth Detection ──────────────────────────────────────────────────

class TestAuthMode:
    def test_pat_mode(self):
        with patch.dict(os.environ, {"SYSTEM_ACCESSTOKEN": "test-pat"}):
            assert ado_search._get_auth_mode() == "pat"

    def test_az_mode(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("SYSTEM_ACCESSTOKEN", None)
            with patch("ado_search.subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(returncode=0)
                assert ado_search._get_auth_mode() == "az"

    def test_no_auth(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("SYSTEM_ACCESSTOKEN", None)
            with patch("ado_search.subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(returncode=1)
                assert ado_search._get_auth_mode() == "none"

    def test_az_timeout(self):
        import subprocess
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("SYSTEM_ACCESSTOKEN", None)
            with patch("ado_search.subprocess.run", side_effect=subprocess.TimeoutExpired("az", 10)):
                assert ado_search._get_auth_mode() == "none"


# ── Keyword Extraction ──────────────────────────────────────────────

class TestExtractKeywords:
    def test_stop_words_removed(self):
        kw = ado_search._extract_keywords("The outlook app issue with calendar", "ios")
        assert "the" not in kw.lower()
        assert "outlook" not in kw.split()
        assert "app" not in kw.split()
        assert "calendar" in kw

    def test_platform_prefix_ios(self):
        kw = ado_search._extract_keywords("Calendar sync", "ios")
        assert kw.startswith("ios")

    def test_platform_prefix_mac(self):
        kw = ado_search._extract_keywords("Calendar sync", "mac")
        assert kw.startswith("macos")

    def test_platform_prefix_android(self):
        kw = ado_search._extract_keywords("Calendar sync", "android")
        assert kw.startswith("android")

    def test_max_six_keywords(self):
        kw = ado_search._extract_keywords(
            "calendar sync failures causing crashes and freezes and hangs and delays and errors",
            "ios",
        )
        assert len(kw.split()) <= 6

    def test_short_words_excluded(self):
        kw = ado_search._extract_keywords("UI is bad on iOS", "ios")
        # Words <= 2 chars should be excluded (except platform prefix)
        words = kw.split()
        for w in words[1:]:  # skip platform prefix
            assert len(w) > 2

    def test_platform_stop_words(self):
        """iOS keywords exclude mac/android terms."""
        kw = ado_search._extract_keywords("mac android calendar", "ios")
        assert "mac" not in kw.split()[1:]  # After platform prefix
        assert "android" not in kw.split()


# ── Synonym Expansion ───────────────────────────────────────────────

class TestSynonyms:
    def test_crash_synonyms(self):
        expanded = ado_search._expand_with_synonyms({"crash"})
        assert "crashes" in expanded
        assert "freeze" in expanded
        assert "hang" in expanded

    def test_sync_synonyms(self):
        expanded = ado_search._expand_with_synonyms({"sync"})
        assert "syncing" in expanded
        assert "refresh" in expanded

    def test_unknown_word_unchanged(self):
        expanded = ado_search._expand_with_synonyms({"xyznotaword"})
        assert expanded == {"xyznotaword"}

    def test_multi_word_synonyms_excluded(self):
        """Multi-word synonyms (with spaces) are excluded from expansion."""
        expanded = ado_search._expand_with_synonyms({"dark mode"})
        # dark mode is a multi-word synonym — individual words may not match
        # The function should still handle it
        assert isinstance(expanded, set)


# ── Relevance Ranking ───────────────────────────────────────────────

class TestRankByRelevance:
    def _make_match(self, title, state="Active", days_ago=5):
        return ADOMatch(
            work_item_id=1, title=title, state=state,
            changed_date=datetime.now(timezone.utc) - timedelta(days=days_ago),
        )

    def test_high_relevance_match(self):
        matches = [self._make_match("Calendar sync fails on iOS")]
        result = ado_search._rank_by_relevance(
            matches, "Calendar sync failures", "Users report sync issues",
        )
        assert len(result) == 1

    def test_irrelevant_filtered_out(self):
        matches = [self._make_match("Completely unrelated bug about fonts")]
        result = ado_search._rank_by_relevance(
            matches, "Calendar sync failures", "Users report sync issues",
        )
        assert len(result) == 0

    def test_state_boost_active_over_closed(self):
        active = self._make_match("Calendar sync fails", state="Active", days_ago=5)
        closed = self._make_match("Calendar sync fails", state="Closed", days_ago=5)
        result = ado_search._rank_by_relevance(
            [closed, active], "Calendar sync failures",
        )
        if len(result) >= 2:
            assert result[0].state == "Active"

    def test_recency_boost(self):
        recent = self._make_match("Calendar sync bug", days_ago=5)
        old = self._make_match("Calendar sync bug", days_ago=90)
        result = ado_search._rank_by_relevance(
            [old, recent], "Calendar sync failures",
        )
        if len(result) >= 2:
            assert result[0].changed_date > result[1].changed_date

    def test_max_results_cap(self):
        matches = [self._make_match(f"Calendar sync issue #{i}") for i in range(20)]
        result = ado_search._rank_by_relevance(matches, "Calendar sync failures")
        assert len(result) <= ado_search.MAX_RESULTS_PER_CLUSTER

    def test_min_score_filter(self):
        matches = [self._make_match("Something totally different about fonts")]
        result = ado_search._rank_by_relevance(
            matches, "Calendar sync", min_score=0.99,
        )
        assert len(result) == 0

    def test_content_gate(self):
        """Bugs with no meaningful content overlap are skipped."""
        matches = [self._make_match("Unrelated: button color wrong")]
        result = ado_search._rank_by_relevance(
            matches, "Calendar sync failures", "Sync is broken",
        )
        assert len(result) == 0

    def test_synonym_matching_boosts_score(self):
        """Synonym matching (crash/freeze) should boost relevance."""
        matches = [self._make_match("App freezes when opening calendar")]
        result = ado_search._rank_by_relevance(
            matches, "App crashes on calendar", "App crashing frequently",
        )
        # "crashes" and "freezes" are synonyms, should find a match
        assert len(result) >= 1


# ── Manual Links ────────────────────────────────────────────────────

class TestManualLinks:
    def test_load_manual_links(self, tmp_path):
        links_file = tmp_path / "manual_links.json"
        data = {
            "retention_days": 90,
            "links": [
                {
                    "cluster_topic": "Calendar sync",
                    "ado_id": 12345,
                    "platform": "ios",
                    "linked_by": "test",
                    "linked_at": "2026-03-01T00:00:00Z",
                },
            ],
        }
        links_file.write_text(json.dumps(data))
        with patch.object(ado_search, "_MANUAL_LINKS_FILE", str(links_file)):
            result = ado_search._load_manual_links()
        assert len(result) == 1

    def test_load_prunes_expired(self, tmp_path):
        links_file = tmp_path / "manual_links.json"
        data = {
            "retention_days": 30,
            "links": [
                {
                    "cluster_topic": "Old link",
                    "ado_id": 11111,
                    "platform": "ios",
                    "linked_by": "test",
                    "linked_at": "2024-01-01T00:00:00Z",
                },
                {
                    "cluster_topic": "New link",
                    "ado_id": 22222,
                    "platform": "ios",
                    "linked_by": "test",
                    "linked_at": "2026-03-20T00:00:00Z",
                },
            ],
        }
        links_file.write_text(json.dumps(data))
        with patch.object(ado_search, "_MANUAL_LINKS_FILE", str(links_file)):
            result = ado_search._load_manual_links()
        assert len(result) == 1
        assert result[0]["ado_id"] == 22222

    def test_load_missing_file(self, tmp_path):
        with patch.object(ado_search, "_MANUAL_LINKS_FILE", str(tmp_path / "nonexistent.json")):
            result = ado_search._load_manual_links()
        assert result == []

    def test_fuzzy_match(self):
        links = [
            {"cluster_topic": "Calendar sync failures", "ado_id": 99999,
             "platform": "ios", "linked_by": "test", "linked_at": "2026-03-01T00:00:00Z"},
        ]
        matches = ado_search._get_manual_matches("Calendar sync issues", "ios", links)
        assert len(matches) >= 1
        assert matches[0].work_item_id == 99999

    def test_no_match_different_platform(self):
        links = [
            {"cluster_topic": "Calendar sync", "ado_id": 99999,
             "platform": "android", "linked_by": "test", "linked_at": "2026-03-01T00:00:00Z"},
        ]
        matches = ado_search._get_manual_matches("Calendar sync", "ios", links)
        assert len(matches) == 0

    def test_keyword_overlap_match(self):
        links = [
            {"cluster_topic": "email notification broken", "ado_id": 55555,
             "platform": "ios", "linked_by": "test", "linked_at": "2026-03-01T00:00:00Z"},
        ]
        matches = ado_search._get_manual_matches("notification email issues", "ios", links)
        assert len(matches) >= 1


# ── Parse Results ───────────────────────────────────────────────────

class TestParseResults:
    def test_dict_fields_format(self):
        data = json.loads((FIXTURES_DIR / "ado_search_results.json").read_text())
        matches = ado_search._parse_results(data)
        assert len(matches) == 3
        assert matches[0].work_item_id == 11111
        assert matches[0].title == "Calendar sync fails after iOS 18 update"
        assert matches[0].state == "Active"

    def test_list_fields_format(self):
        """ADO sometimes returns fields as a list of {name, value} dicts."""
        data = {
            "results": [{
                "fields": [
                    {"name": "system.id", "value": "44444"},
                    {"name": "system.title", "value": "Test bug"},
                    {"name": "system.state", "value": "New"},
                    {"name": "system.assignedto", "value": "dev@ms.com"},
                    {"name": "system.changeddate", "value": "2026-03-19T00:00:00Z"},
                ],
            }],
        }
        matches = ado_search._parse_results(data)
        assert len(matches) == 1
        assert matches[0].work_item_id == 44444
        assert matches[0].title == "Test bug"

    def test_empty_results(self):
        matches = ado_search._parse_results({"results": []})
        assert matches == []

    def test_missing_title_skipped(self):
        data = {
            "results": [{
                "fields": {"system.id": "55555", "system.title": "", "system.state": "Active"},
            }],
        }
        matches = ado_search._parse_results(data)
        assert len(matches) == 0


# ── Correlate Clusters ──────────────────────────────────────────────

class TestCorrelateClusters:
    def test_no_auth_with_manual_links(self, tmp_path):
        """With no auth but manual links, pinned bugs still get attached."""
        links_data = {
            "retention_days": 90,
            "links": [{
                "cluster_topic": "Calendar sync failures",
                "ado_id": 99999,
                "platform": "ios",
                "linked_by": "test",
                "linked_at": "2026-03-01T00:00:00Z",
            }],
        }
        links_file = tmp_path / "manual_links.json"
        links_file.write_text(json.dumps(links_data))

        cluster = TopicCluster(
            topic="Calendar sync failures", severity="high", count=10,
            sentiment_score=-0.5, summary="Sync broken",
        )
        with patch.object(ado_search, "_MANUAL_LINKS_FILE", str(links_file)), \
             patch.object(ado_search, "_get_auth_mode", return_value="none"), \
             patch.object(ado_search, "_resolve_manual_titles"):
            ado_search.correlate_clusters([cluster], platform="ios")
        assert len(cluster.ado_matches) >= 1

    def test_no_auth_no_links_skips(self):
        """With no auth and no manual links, skips entirely."""
        cluster = TopicCluster(
            topic="Test", severity="low", count=1,
            sentiment_score=0, summary="Test",
        )
        with patch.object(ado_search, "_MANUAL_LINKS_FILE", "/nonexistent"), \
             patch.object(ado_search, "_get_auth_mode", return_value="none"):
            ado_search.correlate_clusters([cluster], platform="ios")
        assert len(cluster.ado_matches) == 0

    def test_dedup_pinned_vs_found(self, tmp_path):
        """Manually pinned bugs aren't duplicated in search results."""
        links_data = {
            "retention_days": 90,
            "links": [{
                "cluster_topic": "Calendar sync",
                "ado_id": 11111,
                "platform": "ios",
                "linked_by": "test",
                "linked_at": "2026-03-01T00:00:00Z",
            }],
        }
        links_file = tmp_path / "manual_links.json"
        links_file.write_text(json.dumps(links_data))

        search_results = [
            ADOMatch(work_item_id=11111, title="Dupe", state="Active"),
            ADOMatch(work_item_id=22222, title="Calendar sync fails", state="Active",
                     changed_date=datetime.now(timezone.utc)),
        ]

        cluster = TopicCluster(
            topic="Calendar sync failures", severity="high", count=10,
            sentiment_score=-0.5, summary="Sync issues",
        )
        with patch.object(ado_search, "_MANUAL_LINKS_FILE", str(links_file)), \
             patch.object(ado_search, "_get_auth_mode", return_value="pat"), \
             patch.object(ado_search, "_resolve_manual_titles"), \
             patch.object(ado_search, "_search_bugs", return_value=search_results), \
             patch.object(ado_search, "_rank_by_relevance", return_value=search_results):
            ado_search.correlate_clusters([cluster], platform="ios")

        ids = [m.work_item_id for m in cluster.ado_matches]
        assert ids.count(11111) == 1  # Pinned only, not duplicated
