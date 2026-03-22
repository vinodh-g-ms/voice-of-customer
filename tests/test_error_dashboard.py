"""Tests for error detection and dashboard generation."""

from __future__ import annotations

import os
from unittest.mock import patch

import pytest

from error_dashboard import detect_errors, _health_checks, generate_error_html


class TestDetectErrors:
    def test_copilot_missing_token(self):
        with patch.dict(os.environ, {"ANALYSIS_PROVIDER": "copilot"}, clear=False):
            os.environ.pop("GITHUB_TOKEN", None)
            os.environ.pop("GH_MODELS_TOKEN", None)
            os.environ.pop("SYSTEM_ACCESSTOKEN", None)
            errors = detect_errors()
        titles = [e["title"] for e in errors]
        assert any("GitHub Token Missing" in t for t in titles)

    def test_copilot_token_present_but_failed(self):
        with patch.dict(os.environ, {
            "ANALYSIS_PROVIDER": "copilot",
            "GITHUB_TOKEN": "some-token",
            "SYSTEM_ACCESSTOKEN": "pat",
        }):
            errors = detect_errors()
        titles = [e["title"] for e in errors]
        assert any("Invalid" in t or "Expired" in t for t in titles)

    def test_claude_missing_key(self):
        with patch.dict(os.environ, {"ANALYSIS_PROVIDER": "claude"}, clear=False):
            os.environ.pop("ANTHROPIC_API_KEY", None)
            os.environ.pop("SYSTEM_ACCESSTOKEN", None)
            errors = detect_errors()
        titles = [e["title"] for e in errors]
        assert any("Anthropic" in t for t in titles)

    def test_ado_token_missing(self):
        with patch.dict(os.environ, {"ANALYSIS_PROVIDER": "copilot", "GITHUB_TOKEN": "t"}, clear=False):
            os.environ.pop("SYSTEM_ACCESSTOKEN", None)
            errors = detect_errors()
        titles = [e["title"] for e in errors]
        assert any("ADO" in t for t in titles)

    def test_ado_token_present(self):
        with patch.dict(os.environ, {
            "ANALYSIS_PROVIDER": "copilot",
            "GITHUB_TOKEN": "t",
            "SYSTEM_ACCESSTOKEN": "pat",
        }):
            errors = detect_errors()
        titles = [e["title"] for e in errors]
        assert any("ADO" in t and "Expired" in t for t in titles)


class TestHealthChecks:
    def test_all_configured(self):
        with patch.dict(os.environ, {
            "ANALYSIS_PROVIDER": "copilot",
            "GITHUB_TOKEN": "token",
            "SYSTEM_ACCESSTOKEN": "pat",
            "TEAMS_WEBHOOK_URL": "https://webhook",
            "GRAPH_CLIENT_ID": "graph-id",
        }):
            checks = _health_checks()
        statuses = {c["name"]: c["status"] for c in checks}
        assert statuses["GitHub Copilot (AI Analysis)"] == "configured"
        assert statuses["Azure DevOps (Bug Linking)"] == "configured"
        assert statuses["Microsoft Teams Notifications"] == "configured"

    def test_missing_tokens(self):
        with patch.dict(os.environ, {"ANALYSIS_PROVIDER": "copilot"}, clear=False):
            os.environ.pop("GITHUB_TOKEN", None)
            os.environ.pop("GH_MODELS_TOKEN", None)
            os.environ.pop("SYSTEM_ACCESSTOKEN", None)
            os.environ.pop("TEAMS_WEBHOOK_URL", None)
            os.environ.pop("GRAPH_CLIENT_ID", None)
            checks = _health_checks()
        statuses = {c["name"]: c["status"] for c in checks}
        assert statuses["GitHub Copilot (AI Analysis)"] == "missing"


class TestGenerateHtml:
    def test_generates_valid_html(self):
        errors = [{
            "title": "Test Error", "icon": "⛔", "severity": "blocking",
            "time_to_fix": "~5 min", "description": "Test desc",
            "fix": ["Step 1", "Step 2"],
        }]
        checks = [{
            "name": "Test Check", "status": "missing",
            "required": True, "detail": "Not found",
        }]
        html = generate_error_html(errors, checks)
        assert "<!DOCTYPE html>" in html
        assert "Test Error" in html
        assert "Step 1" in html
        assert "Test Check" in html
