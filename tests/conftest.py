"""Shared fixtures and factory functions for Customer Pulse tests."""

from __future__ import annotations

import os
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

from models import Review, ADOMatch, TopicCluster, PulseReport, CompositePulseReport


FIXTURES_DIR = Path(__file__).parent / "fixtures"


# ── Factory functions ────────────────────────────────────────────────

def make_review(**overrides) -> Review:
    """Create a Review with sensible defaults."""
    defaults = {
        "source": "appstore",
        "title": "Great app",
        "body": "Works really well on my iPhone",
        "rating": 4,
        "author": "testuser",
        "date": datetime(2026, 3, 15, tzinfo=timezone.utc),
        "country": "us",
        "url": "https://apps.apple.com/us/app/id951937596",
        "version": "4.2501.0",
        "platform": "ios",
    }
    defaults.update(overrides)
    return Review(**defaults)


def make_ado_match(**overrides) -> ADOMatch:
    """Create an ADOMatch with sensible defaults."""
    defaults = {
        "work_item_id": 12345,
        "title": "Calendar sync fails on iOS",
        "state": "Active",
        "assigned_to": "dev@microsoft.com",
        "url": "https://office.visualstudio.com/Outlook Mobile/_workitems/edit/12345",
        "changed_date": datetime(2026, 3, 20, tzinfo=timezone.utc),
    }
    defaults.update(overrides)
    return ADOMatch(**defaults)


def make_cluster(**overrides) -> TopicCluster:
    """Create a TopicCluster with sensible defaults."""
    defaults = {
        "topic": "Calendar sync failures",
        "severity": "high",
        "count": 25,
        "sentiment_score": -0.6,
        "summary": "Users report calendar events not syncing properly.",
        "quotes": ["My calendar won't sync", "Events disappear after sync"],
        "source_breakdown": {"appstore": 15, "reddit": 10},
    }
    defaults.update(overrides)
    return TopicCluster(**defaults)


def make_report(**overrides) -> PulseReport:
    """Create a PulseReport with sensible defaults."""
    defaults = {
        "generated_at": datetime(2026, 3, 22, 6, 0, tzinfo=timezone.utc),
        "days_analyzed": 15,
        "total_reviews": 100,
        "overall_sentiment": -0.3,
        "overall_summary": "Mixed feedback with sync issues dominating.",
        "clusters": [make_cluster()],
        "source_counts": {"appstore": 60, "reddit": 30, "msqa": 10},
        "platform": "ios",
        "period_label": "15d",
    }
    defaults.update(overrides)
    return PulseReport(**defaults)


def make_composite(**reports_map) -> CompositePulseReport:
    """Create a CompositePulseReport from {key: PulseReport} pairs."""
    comp = CompositePulseReport(generated_at=datetime(2026, 3, 22, 6, 0, tzinfo=timezone.utc))
    for key, rpt in reports_map.items():
        comp.reports[key] = rpt
    return comp


# ── Fixtures ─────────────────────────────────────────────────────────

@pytest.fixture
def clean_env():
    """Remove pipeline-related env vars for test isolation."""
    keys = [
        "ANTHROPIC_API_KEY", "GITHUB_TOKEN", "GH_MODELS_TOKEN",
        "SYSTEM_ACCESSTOKEN", "ANALYSIS_PROVIDER", "TEAMS_WEBHOOK_URL",
        "REDDIT_CLIENT_ID", "REDDIT_CLIENT_SECRET",
        "SHAREPOINT_DASHBOARD_URL", "PIPELINE_STATUS", "PIPELINE_FIRST_ERROR_TIME",
        "COPILOT_MODEL", "COPILOT_MAX_REVIEWS",
        "GRAPH_CLIENT_ID", "GRAPH_CLIENT_SECRET", "GRAPH_TENANT_ID",
        "SHAREPOINT_SITE_ID",
    ]
    saved = {k: os.environ.pop(k, None) for k in keys}
    yield
    for k, v in saved.items():
        if v is not None:
            os.environ[k] = v
        else:
            os.environ.pop(k, None)


@pytest.fixture
def fixture_path():
    """Return path to test fixtures directory."""
    return FIXTURES_DIR


def load_fixture(name: str) -> str:
    """Load a fixture file as text."""
    return (FIXTURES_DIR / name).read_text()


def load_json_fixture(name: str) -> dict | list:
    """Load a fixture file as parsed JSON."""
    return json.loads((FIXTURES_DIR / name).read_text())
