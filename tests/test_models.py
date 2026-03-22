"""Tests for data models (Review, ADOMatch, TopicCluster, CompositePulseReport)."""

from __future__ import annotations

from datetime import datetime, timezone, timedelta
from unittest.mock import patch

import pytest

from models import Review, ADOMatch, TopicCluster, PulseReport, CompositePulseReport


# ── Review ──────────────────────────────────────────────────────────

class TestReview:
    def test_to_dict_from_dict_roundtrip(self):
        r = Review(
            source="appstore", title="Great app", body="Works well",
            rating=5, author="user1",
            date=datetime(2026, 3, 15, 10, 0, tzinfo=timezone.utc),
            country="us", url="https://example.com", version="4.2501.0",
            platform="ios",
        )
        d = r.to_dict()
        r2 = Review.from_dict(d)
        assert r2.source == r.source
        assert r2.title == r.title
        assert r2.body == r.body
        assert r2.rating == r.rating
        assert r2.author == r.author
        assert r2.date.isoformat() == r.date.isoformat()
        assert r2.country == r.country
        assert r2.url == r.url
        assert r2.version == r.version
        assert r2.platform == r.platform

    def test_text_property_title_and_body(self):
        r = Review(source="appstore", title="Title", body="Body", rating=1,
                   author="u", date=None)
        assert r.text == "Title — Body"

    def test_text_property_title_only(self):
        r = Review(source="reddit", title="Just title", body="", rating=None,
                   author="u", date=None)
        assert r.text == "Just title"

    def test_text_property_body_only(self):
        r = Review(source="reddit", title="", body="Just body", rating=None,
                   author="u", date=None)
        assert r.text == "Just body"

    def test_text_property_both_empty(self):
        r = Review(source="reddit", title="", body="", rating=None,
                   author="u", date=None)
        assert r.text == ""

    def test_compact_with_rating_and_country(self):
        r = Review(source="appstore", title="Test", body="Body", rating=3,
                   author="u", date=None, country="gb", version="4.0")
        result = r.compact()
        assert "[appstore/gb [3★] v4.0]" in result
        assert "Test — Body" in result

    def test_compact_without_rating(self):
        r = Review(source="reddit", title="Post", body="", rating=None,
                   author="u", date=None)
        assert "★" not in r.compact()
        assert "[reddit]" in r.compact()

    def test_compact_without_version(self):
        r = Review(source="appstore", title="Test", body="", rating=5,
                   author="u", date=None, country="us")
        result = r.compact()
        assert " v" not in result.replace("[appstore/us [5★]]", "")

    def test_from_dict_missing_fields(self):
        r = Review.from_dict({"source": "test"})
        assert r.title == ""
        assert r.body == ""
        assert r.rating is None
        assert r.author == ""
        assert r.date is None

    def test_from_dict_invalid_date(self):
        r = Review.from_dict({"source": "test", "date": "not-a-date"})
        assert r.date is None

    def test_to_dict_none_date(self):
        r = Review(source="test", title="t", body="b", rating=None,
                   author="a", date=None)
        d = r.to_dict()
        assert d["date"] is None

    def test_from_dict_preserves_all_fields(self):
        d = {
            "source": "msqa", "title": "Q", "body": "Detail",
            "rating": None, "author": "author1", "date": None,
            "country": "", "url": "https://example.com",
            "version": "", "platform": "mac",
        }
        r = Review.from_dict(d)
        assert r.platform == "mac"
        assert r.url == "https://example.com"


# ── ADOMatch ────────────────────────────────────────────────────────

class TestADOMatch:
    def test_activity_age_days_recent(self):
        now = datetime(2026, 3, 22, 12, 0, tzinfo=timezone.utc)
        m = ADOMatch(work_item_id=1, title="Bug", state="Active",
                     changed_date=now)
        with patch("models.datetime") as mock_dt:
            mock_dt.now.return_value = now
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            # Use freezegun instead of mocking
            pass
        # Direct test — activity_age_days uses datetime.now(timezone.utc)
        age = m.activity_age_days
        assert age is not None
        assert age >= 0

    def test_activity_age_days_none_when_no_date(self):
        m = ADOMatch(work_item_id=1, title="Bug", state="Active",
                     changed_date=None)
        assert m.activity_age_days is None

    def test_activity_label_today(self):
        m = ADOMatch(work_item_id=1, title="Bug", state="Active",
                     changed_date=datetime.now(timezone.utc))
        assert m.activity_label == "today"

    def test_activity_label_yesterday(self):
        m = ADOMatch(work_item_id=1, title="Bug", state="Active",
                     changed_date=datetime.now(timezone.utc) - timedelta(days=1))
        assert m.activity_label == "yesterday"

    def test_activity_label_days_ago(self):
        m = ADOMatch(work_item_id=1, title="Bug", state="Active",
                     changed_date=datetime.now(timezone.utc) - timedelta(days=5))
        assert m.activity_label == "5d ago"

    def test_activity_label_none_date(self):
        m = ADOMatch(work_item_id=1, title="Bug", state="Active",
                     changed_date=None)
        assert m.activity_label == ""

    def test_to_dict(self):
        m = ADOMatch(work_item_id=42, title="Bug title", state="New",
                     assigned_to="dev@ms.com",
                     url="https://ado.com/42",
                     changed_date=datetime(2026, 3, 20, tzinfo=timezone.utc))
        d = m.to_dict()
        assert d["work_item_id"] == 42
        assert d["title"] == "Bug title"
        assert d["changed_date"] == "2026-03-20T00:00:00+00:00"

    def test_to_dict_none_date(self):
        m = ADOMatch(work_item_id=1, title="Bug", state="Active")
        assert m.to_dict()["changed_date"] is None


# ── TopicCluster ────────────────────────────────────────────────────

class TestTopicCluster:
    def test_to_dict_includes_all_fields(self):
        c = TopicCluster(
            topic="Crashes", severity="critical", count=10,
            sentiment_score=-0.8, summary="App crashes",
            quotes=["it crashed"], source_breakdown={"appstore": 10},
            ado_matches=[ADOMatch(work_item_id=1, title="B", state="Active")],
            trend="up", previous_count=5, count_delta=5,
            weekly_counts={"Mar 01": 3, "Mar 08": 7},
        )
        d = c.to_dict()
        assert d["topic"] == "Crashes"
        assert d["trend"] == "up"
        assert d["count_delta"] == 5
        assert len(d["ado_matches"]) == 1
        assert d["weekly_counts"]["Mar 01"] == 3

    def test_defaults(self):
        c = TopicCluster(topic="T", severity="low", count=1,
                         sentiment_score=0.0, summary="S")
        assert c.quotes == []
        assert c.ado_matches == []
        assert c.trend == ""
        assert c.weekly_counts == {}


# ── CompositePulseReport ────────────────────────────────────────────

class TestCompositePulseReport:
    def _make_report(self, platform, period):
        return PulseReport(
            generated_at=datetime(2026, 3, 22, tzinfo=timezone.utc),
            days_analyzed=15, total_reviews=50, overall_sentiment=-0.2,
            overall_summary="Test", platform=platform, period_label=period,
        )

    def test_put_and_get(self):
        comp = CompositePulseReport(generated_at=datetime(2026, 3, 22, tzinfo=timezone.utc))
        rpt = self._make_report("ios", "15d")
        comp.put("ios", "15d", rpt)
        assert comp.get("ios", "15d") is rpt
        assert comp.get("ios", "90d") is None

    def test_platforms_dedup(self):
        comp = CompositePulseReport(generated_at=datetime(2026, 3, 22, tzinfo=timezone.utc))
        comp.put("ios", "15d", self._make_report("ios", "15d"))
        comp.put("ios", "90d", self._make_report("ios", "90d"))
        comp.put("mac", "15d", self._make_report("mac", "15d"))
        assert comp.platforms == ["ios", "mac"]

    def test_periods_order(self):
        comp = CompositePulseReport(generated_at=datetime(2026, 3, 22, tzinfo=timezone.utc))
        comp.put("ios", "90d", self._make_report("ios", "90d"))
        comp.put("ios", "15d", self._make_report("ios", "15d"))
        assert comp.periods == ["90d", "15d"]

    def test_empty(self):
        comp = CompositePulseReport(generated_at=datetime(2026, 3, 22, tzinfo=timezone.utc))
        assert comp.platforms == []
        assert comp.periods == []
        assert comp.get("ios", "15d") is None
