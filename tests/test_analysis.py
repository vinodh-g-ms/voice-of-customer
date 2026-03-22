"""Tests for analysis orchestration, prioritization, parsing, and trends."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from unittest.mock import patch, MagicMock

import pytest

from models import Review, TopicCluster, PulseReport
from analysis import (
    _prioritize_reviews, _parse_response, build_report_from_analysis,
    compute_trends, _assign_reviews_to_clusters,
)


# ── Factory helpers ─────────────────────────────────────────────────

def _make_review(source="appstore", rating=1, date_offset=5, platform="ios"):
    return Review(
        source=source, title="Test", body="Review body text",
        rating=rating, author="u",
        date=datetime.now(timezone.utc) - timedelta(days=date_offset),
        version="4.0", platform=platform,
    )


# ── Review Prioritization ──────────────────────────────────────────

class TestPrioritizeReviews:
    def test_under_limit_returns_all(self):
        reviews = [_make_review() for _ in range(5)]
        result = _prioritize_reviews(reviews)
        assert len(result) == 5

    def test_negative_appstore_first(self):
        """Negative appstore reviews are prioritized over others."""
        reviews = [
            _make_review(source="appstore", rating=1),
            _make_review(source="reddit", rating=None),
            _make_review(source="appstore", rating=5),
            _make_review(source="appstore", rating=2),
        ]
        with patch("analysis._get_max_reviews", return_value=2):
            result = _prioritize_reviews(reviews)
        assert len(result) == 2
        assert all(r.source == "appstore" and r.rating <= 2 for r in result)

    def test_bucket_ordering(self):
        """Buckets: neg_app -> neg_other -> neutral -> positive."""
        reviews = [
            _make_review(source="appstore", rating=5),  # positive
            _make_review(source="reddit", rating=None),  # neutral (no rating)
            _make_review(source="appstore", rating=1),  # neg_app
            _make_review(source="reddit", rating=2),     # neg_other
        ]
        with patch("analysis._get_max_reviews", return_value=3):
            result = _prioritize_reviews(reviews)
        # First should be negative appstore, then neg_other, then neutral
        assert result[0].source == "appstore" and result[0].rating == 1
        assert result[1].source == "reddit" and result[1].rating == 2

    def test_max_limit_enforced(self):
        reviews = [_make_review() for _ in range(100)]
        with patch("analysis._get_max_reviews", return_value=10):
            result = _prioritize_reviews(reviews)
        assert len(result) == 10


# ── JSON Parsing ────────────────────────────────────────────────────

class TestParseResponse:
    def test_clean_json(self):
        text = '{"overall_sentiment": -0.3, "clusters": []}'
        result = _parse_response(text)
        assert result["overall_sentiment"] == -0.3

    def test_fenced_json(self):
        text = '```json\n{"overall_sentiment": 0.5, "clusters": []}\n```'
        result = _parse_response(text)
        assert result["overall_sentiment"] == 0.5

    def test_invalid_json_returns_fallback(self):
        text = "This is not JSON at all"
        result = _parse_response(text)
        assert result["overall_sentiment"] == 0.0
        assert "parse failed" in result["overall_summary"].lower()
        assert result["clusters"] == []

    def test_fenced_with_language_tag(self):
        text = '```json\n{"clusters": [{"topic": "test"}]}\n```'
        result = _parse_response(text)
        assert len(result["clusters"]) == 1


# ── Trend Computation ───────────────────────────────────────────────

class TestComputeTrends:
    def _make_cluster(self, topic, count):
        return TopicCluster(
            topic=topic, severity="medium", count=count,
            sentiment_score=-0.3, summary="Test",
        )

    def test_trend_up(self):
        current = PulseReport(
            generated_at=datetime.now(timezone.utc), days_analyzed=15,
            total_reviews=100, overall_sentiment=-0.3, overall_summary="Test",
            clusters=[self._make_cluster("Calendar sync failures", 20)],
        )
        previous = PulseReport(
            generated_at=datetime.now(timezone.utc), days_analyzed=15,
            total_reviews=80, overall_sentiment=-0.3, overall_summary="Test",
            clusters=[self._make_cluster("Calendar sync failures", 10)],
        )
        compute_trends(current, previous)
        assert current.clusters[0].trend == "up"
        assert current.clusters[0].count_delta == 10

    def test_trend_down(self):
        current = PulseReport(
            generated_at=datetime.now(timezone.utc), days_analyzed=15,
            total_reviews=80, overall_sentiment=0.1, overall_summary="Test",
            clusters=[self._make_cluster("Calendar sync", 5)],
        )
        previous = PulseReport(
            generated_at=datetime.now(timezone.utc), days_analyzed=15,
            total_reviews=100, overall_sentiment=-0.3, overall_summary="Test",
            clusters=[self._make_cluster("Calendar sync issues", 15)],
        )
        compute_trends(current, previous)
        assert current.clusters[0].trend == "down"
        assert current.clusters[0].count_delta == -10

    def test_trend_new(self):
        current = PulseReport(
            generated_at=datetime.now(timezone.utc), days_analyzed=15,
            total_reviews=100, overall_sentiment=-0.3, overall_summary="Test",
            clusters=[self._make_cluster("Brand new issue", 10)],
        )
        previous = PulseReport(
            generated_at=datetime.now(timezone.utc), days_analyzed=15,
            total_reviews=80, overall_sentiment=-0.3, overall_summary="Test",
            clusters=[self._make_cluster("Completely different topic", 5)],
        )
        compute_trends(current, previous)
        assert current.clusters[0].trend == "new"

    def test_trend_no_change(self):
        current = PulseReport(
            generated_at=datetime.now(timezone.utc), days_analyzed=15,
            total_reviews=100, overall_sentiment=-0.3, overall_summary="Test",
            clusters=[self._make_cluster("Calendar sync", 10)],
        )
        previous = PulseReport(
            generated_at=datetime.now(timezone.utc), days_analyzed=15,
            total_reviews=100, overall_sentiment=-0.3, overall_summary="Test",
            clusters=[self._make_cluster("Calendar sync", 10)],
        )
        compute_trends(current, previous)
        assert current.clusters[0].trend == ""  # same count = no trend
        assert current.clusters[0].count_delta == 0


# ── Build Report ────────────────────────────────────────────────────

class TestBuildReport:
    def test_basic_report(self):
        analysis = {
            "overall_sentiment": -0.3,
            "overall_summary": "Issues found",
            "clusters": [
                {"topic": "Sync", "severity": "high", "count": 10,
                 "sentiment_score": -0.5, "summary": "Sync fails",
                 "quotes": ["it broke"], "source_breakdown": {"appstore": 10}},
            ],
        }
        reviews = [_make_review() for _ in range(10)]
        report = build_report_from_analysis(analysis, reviews, 15, "ios", "15d")
        assert report.total_reviews == 10
        assert report.platform == "ios"
        assert report.period_label == "15d"
        assert len(report.clusters) == 1
        assert report.clusters[0].topic == "Sync"

    def test_source_counts(self):
        reviews = [
            _make_review(source="appstore"),
            _make_review(source="appstore"),
            _make_review(source="reddit"),
        ]
        report = build_report_from_analysis(
            {"overall_sentiment": 0, "overall_summary": "", "clusters": []},
            reviews, 15, "ios", "15d",
        )
        assert report.source_counts["appstore"] == 2
        assert report.source_counts["reddit"] == 1

    def test_weekly_volume(self):
        reviews = [_make_review(date_offset=i) for i in range(28)]
        report = build_report_from_analysis(
            {"overall_sentiment": 0, "overall_summary": "", "clusters": []},
            reviews, 30, "ios", "15d",
        )
        assert len(report.weekly_volume) == 4

    def test_empty_clusters(self):
        report = build_report_from_analysis(
            {"overall_sentiment": 0, "overall_summary": "No issues", "clusters": []},
            [], 15, "ios", "15d",
        )
        assert report.clusters == []
        assert report.total_reviews == 0


# ── Assign Reviews to Clusters ──────────────────────────────────────

class TestAssignReviews:
    def test_keyword_matching(self):
        cluster = TopicCluster(
            topic="Calendar sync failures",
            severity="high", count=10,
            sentiment_score=-0.5, summary="",
        )
        reviews = [
            Review(source="appstore", title="Calendar won't sync",
                   body="Calendar sync is completely broken",
                   rating=1, author="u",
                   date=datetime.now(timezone.utc) - timedelta(days=1),
                   platform="ios"),
            Review(source="appstore", title="Love the new design",
                   body="Everything looks great",
                   rating=5, author="u",
                   date=datetime.now(timezone.utc) - timedelta(days=1),
                   platform="ios"),
        ]
        now = datetime.now(timezone.utc)
        _assign_reviews_to_clusters([cluster], reviews, now)
        assert len(cluster.matched_reviews) >= 1
        assert cluster.matched_reviews[0].title == "Calendar won't sync"

    def test_version_breakdown(self):
        cluster = TopicCluster(
            topic="Calendar sync failures",
            severity="high", count=10,
            sentiment_score=-0.5, summary="",
        )
        reviews = [
            Review(source="appstore", title="Calendar sync broken",
                   body="calendar sync fails", rating=1, author="u",
                   date=datetime.now(timezone.utc) - timedelta(days=1),
                   version="4.0", platform="ios"),
            Review(source="appstore", title="Calendar sync issue",
                   body="sync calendar problem", rating=2, author="u",
                   date=datetime.now(timezone.utc) - timedelta(days=2),
                   version="4.1", platform="ios"),
        ]
        now = datetime.now(timezone.utc)
        _assign_reviews_to_clusters([cluster], reviews, now)
        assert "4.0" in cluster.version_breakdown or "4.1" in cluster.version_breakdown

    def test_weekly_counts(self):
        cluster = TopicCluster(
            topic="Calendar sync failures",
            severity="high", count=10,
            sentiment_score=-0.5, summary="",
        )
        reviews = [
            Review(source="appstore", title="Calendar sync broken",
                   body="calendar failures sync", rating=1, author="u",
                   date=datetime.now(timezone.utc) - timedelta(days=3),
                   platform="ios"),
        ]
        now = datetime.now(timezone.utc)
        _assign_reviews_to_clusters([cluster], reviews, now)
        assert len(cluster.weekly_counts) == 4

    def test_max_matched_reviews(self):
        cluster = TopicCluster(
            topic="Calendar sync failures",
            severity="high", count=50,
            sentiment_score=-0.5, summary="",
        )
        reviews = [
            Review(source="appstore", title=f"Calendar sync broken #{i}",
                   body="calendar sync failures", rating=1, author="u",
                   date=datetime.now(timezone.utc) - timedelta(days=1),
                   platform="ios")
            for i in range(30)
        ]
        now = datetime.now(timezone.utc)
        _assign_reviews_to_clusters([cluster], reviews, now)
        assert len(cluster.matched_reviews) <= 20
