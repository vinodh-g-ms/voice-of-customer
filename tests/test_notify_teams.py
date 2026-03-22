"""Tests for Teams webhook notification."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest
import responses

from notify_teams import build_summary, build_adaptive_card, _detect_warnings, _get_pipeline_status

FIXTURES_DIR = Path(__file__).parent / "fixtures"


class TestBuildSummary:
    def test_parses_platforms(self, tmp_path):
        sample_md = (FIXTURES_DIR / "sample_report.md").read_text()
        md_file = tmp_path / "pulse_report_v3_20260322.md"
        md_file.write_text(sample_md)
        with patch("notify_teams.OUTPUT_DIR", tmp_path):
            summary = build_summary()
        assert "iOS" in summary["platforms"]
        assert "MacOS" in summary["platforms"]
        assert "Android" in summary["platforms"]

    def test_parses_review_counts(self, tmp_path):
        sample_md = (FIXTURES_DIR / "sample_report.md").read_text()
        md_file = tmp_path / "pulse_report_v3_20260322.md"
        md_file.write_text(sample_md)
        with patch("notify_teams.OUTPUT_DIR", tmp_path):
            summary = build_summary()
        assert summary["total_reviews"] > 0

    def test_parses_issues(self, tmp_path):
        sample_md = (FIXTURES_DIR / "sample_report.md").read_text()
        md_file = tmp_path / "pulse_report_v3_20260322.md"
        md_file.write_text(sample_md)
        with patch("notify_teams.OUTPUT_DIR", tmp_path):
            summary = build_summary()
        assert "iOS" in summary["platform_issues"]
        ios_issues = summary["platform_issues"]["iOS"]
        assert len(ios_issues) >= 1

    def test_empty_dir(self, tmp_path):
        with patch("notify_teams.OUTPUT_DIR", tmp_path):
            summary = build_summary()
        assert summary["platforms"] == []
        assert summary["total_reviews"] == 0

    def test_severity_detection(self, tmp_path):
        sample_md = (FIXTURES_DIR / "sample_report.md").read_text()
        md_file = tmp_path / "pulse_report_v3_20260322.md"
        md_file.write_text(sample_md)
        with patch("notify_teams.OUTPUT_DIR", tmp_path):
            summary = build_summary()
        ios_issues = summary["platform_issues"].get("iOS", [])
        severities = [i["severity"] for i in ios_issues]
        assert "critical" in severities


class TestPipelineStatus:
    def test_success(self):
        with patch.dict(os.environ, {"PIPELINE_STATUS": "success"}):
            status = _get_pipeline_status()
        assert "success" in status["text"].lower()
        assert not status["failed"]

    def test_failed(self):
        with patch.dict(os.environ, {
            "PIPELINE_STATUS": "failed",
            "PIPELINE_FIRST_ERROR_TIME": "2026-03-22 05:00",
        }):
            status = _get_pipeline_status()
        assert status["failed"] is True
        assert "failed" in status["text"].lower()

    def test_success_after_retry(self):
        with patch.dict(os.environ, {
            "PIPELINE_STATUS": "success_after_retry",
            "PIPELINE_FIRST_ERROR_TIME": "2026-03-22 05:00",
        }):
            status = _get_pipeline_status()
        assert "retry" in status["text"].lower()
        assert not status["failed"]


class TestDetectWarnings:
    def test_missing_ado_token(self):
        with patch.dict(os.environ, {"ANALYSIS_PROVIDER": "copilot", "GITHUB_TOKEN": "t"}, clear=False):
            os.environ.pop("SYSTEM_ACCESSTOKEN", None)
            warnings = _detect_warnings()
        assert any("ADO" in w["text"] for w in warnings)

    def test_missing_copilot_token(self):
        with patch.dict(os.environ, {"ANALYSIS_PROVIDER": "copilot"}, clear=False):
            os.environ.pop("GITHUB_TOKEN", None)
            os.environ.pop("GH_MODELS_TOKEN", None)
            os.environ.pop("SYSTEM_ACCESSTOKEN", None)
            warnings = _detect_warnings()
        assert any("GitHub" in w["text"] for w in warnings)

    def test_missing_claude_key(self):
        with patch.dict(os.environ, {"ANALYSIS_PROVIDER": "claude"}, clear=False):
            os.environ.pop("ANTHROPIC_API_KEY", None)
            os.environ.pop("SYSTEM_ACCESSTOKEN", None)
            warnings = _detect_warnings()
        assert any("Anthropic" in w["text"] for w in warnings)

    def test_no_warnings_when_configured(self):
        with patch.dict(os.environ, {
            "ANALYSIS_PROVIDER": "copilot",
            "GITHUB_TOKEN": "token",
            "SYSTEM_ACCESSTOKEN": "pat",
        }):
            warnings = _detect_warnings()
        assert len(warnings) == 0


class TestAdaptiveCard:
    def test_card_structure(self):
        summary = {
            "timestamp": "2026-03-22 06:00 UTC",
            "platforms": ["iOS"],
            "total_reviews": 100,
            "platform_issues": {"iOS": [{"title": "Sync fails", "severity": "critical", "count": "25"}]},
        }
        with patch.dict(os.environ, {"PIPELINE_STATUS": "success", "ANALYSIS_PROVIDER": "copilot", "GITHUB_TOKEN": "t", "SYSTEM_ACCESSTOKEN": "p"}):
            card = build_adaptive_card(summary, "https://dashboard.example.com")
        assert card["type"] == "message"
        assert len(card["attachments"]) == 1
        content = card["attachments"][0]["content"]
        assert content["type"] == "AdaptiveCard"
        assert len(content["body"]) > 0
        assert len(content["actions"]) > 0

    def test_failed_pipeline_has_rerun_action(self):
        summary = {
            "timestamp": "now", "platforms": [], "total_reviews": 0,
            "platform_issues": {},
        }
        with patch.dict(os.environ, {"PIPELINE_STATUS": "failed", "ANALYSIS_PROVIDER": "copilot", "GITHUB_TOKEN": "t", "SYSTEM_ACCESSTOKEN": "p"}):
            card = build_adaptive_card(summary, "")
        actions = card["attachments"][0]["content"]["actions"]
        assert any("Re-run" in a.get("title", "") for a in actions)

    @responses.activate
    def test_webhook_send(self):
        responses.add(
            responses.POST,
            "https://webhook.example.com/test",
            status=200,
        )
        import requests
        resp = requests.post(
            "https://webhook.example.com/test",
            json={"type": "message"},
            headers={"Content-Type": "application/json"},
            timeout=30,
        )
        assert resp.status_code == 200

    def test_warnings_section_in_card(self):
        summary = {
            "timestamp": "now", "platforms": [], "total_reviews": 0,
            "platform_issues": {},
        }
        with patch.dict(os.environ, {"ANALYSIS_PROVIDER": "copilot", "PIPELINE_STATUS": "success"}, clear=False):
            os.environ.pop("GITHUB_TOKEN", None)
            os.environ.pop("GH_MODELS_TOKEN", None)
            os.environ.pop("SYSTEM_ACCESSTOKEN", None)
            card = build_adaptive_card(summary, "")
        body_texts = [b.get("text", "") for b in card["attachments"][0]["content"]["body"]]
        assert any("Action Required" in t for t in body_texts)
