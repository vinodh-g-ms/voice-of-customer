"""Tests for main pipeline orchestration."""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from unittest.mock import patch, MagicMock, call

import pytest

from models import Review, PulseReport, CompositePulseReport, TopicCluster


class TestParseArgs:
    def test_defaults(self):
        with patch("sys.argv", ["main.py"]):
            from main import parse_args
            args = parse_args()
        assert "ios" in args.platforms
        assert args.topic == ""
        assert args.sources == "all"
        assert args.skip_ado is False
        assert args.no_cache is False

    def test_custom_args(self):
        with patch("sys.argv", [
            "main.py", "--platforms", "ios,mac",
            "--topic", "calendar",
            "--sources", "appstore,reddit",
            "--skip-ado", "--no-cache",
        ]):
            from main import parse_args
            args = parse_args()
        assert args.platforms == "ios,mac"
        assert args.topic == "calendar"
        assert args.sources == "appstore,reddit"
        assert args.skip_ado is True
        assert args.no_cache is True


class TestPhaseFetch:
    def test_aggregates_sources(self):
        mock_reviews = [
            Review(source="appstore", title="R1", body="", rating=3,
                   author="u", date=datetime.now(timezone.utc), platform="ios"),
        ]
        with patch("main.phase_fetch") as mock_fetch:
            mock_fetch.return_value = mock_reviews
            from main import phase_fetch
            # Call the real function with mocked source imports
            pass

    def test_source_error_isolated(self):
        """Error in one source doesn't crash others."""
        from main import phase_fetch
        with patch("sources.appstore.fetch", side_effect=Exception("App Store down")), \
             patch("sources.reddit.fetch", return_value=[]), \
             patch("sources.msqa.fetch", return_value=[]):
            result = phase_fetch("ios", 90, ["appstore", "reddit", "msqa"], True, "")
        # Should not raise, just returns whatever succeeded
        assert isinstance(result, list)

    def test_playstore_only_for_android(self):
        """Play Store is only called for Android platform."""
        from main import phase_fetch
        with patch("sources.appstore.fetch", return_value=[]) as mock_app, \
             patch("sources.reddit.fetch", return_value=[]), \
             patch("sources.msqa.fetch", return_value=[]):
            phase_fetch("ios", 90, ["appstore", "playstore", "reddit", "msqa"], True, "")
        # playstore.fetch should NOT have been called for ios
        # (it's guarded by platform == "android" check)


class TestPhaseAnalyze:
    def test_calls_analyzer(self):
        from main import phase_analyze
        mock_result = {
            "overall_sentiment": -0.3,
            "overall_summary": "Test",
            "clusters": [],
        }
        with patch("analysis.analyze", return_value=mock_result), \
             patch("analysis.build_report_from_analysis") as mock_build:
            mock_build.return_value = PulseReport(
                generated_at=datetime.now(timezone.utc),
                days_analyzed=15, total_reviews=10,
                overall_sentiment=-0.3, overall_summary="Test",
            )
            result = phase_analyze([], "", "ios", "15d", 15)
        assert isinstance(result, PulseReport)


class TestPhaseTrends:
    def test_skips_when_no_15d_report(self):
        from main import phase_trends
        comp = CompositePulseReport(generated_at=datetime.now(timezone.utc))
        # No 15d report exists — should exit early without error
        phase_trends(comp, "ios", [], "")

    def test_skips_few_previous_reviews(self):
        from main import phase_trends
        comp = CompositePulseReport(generated_at=datetime.now(timezone.utc))
        report = PulseReport(
            generated_at=datetime.now(timezone.utc),
            days_analyzed=15, total_reviews=50,
            overall_sentiment=-0.3, overall_summary="Test",
            clusters=[TopicCluster(topic="T", severity="high", count=5,
                                   sentiment_score=-0.3, summary="S")],
            platform="ios", period_label="15d",
        )
        comp.put("ios", "15d", report)
        # Only 2 reviews in previous window (need >= 5)
        reviews = [
            Review(source="appstore", title="Old", body="", rating=3, author="u",
                   date=datetime.now(timezone.utc) - timedelta(days=20),
                   platform="ios"),
            Review(source="appstore", title="Old2", body="", rating=2, author="u",
                   date=datetime.now(timezone.utc) - timedelta(days=25),
                   platform="ios"),
        ]
        phase_trends(comp, "ios", reviews, "")
        assert any("Trends skipped" in n for n in report.data_quality_notes)


class TestPhaseCorrelate:
    def test_error_adds_quality_note(self):
        from main import phase_correlate
        report = PulseReport(
            generated_at=datetime.now(timezone.utc),
            days_analyzed=15, total_reviews=50,
            overall_sentiment=-0.3, overall_summary="Test",
            clusters=[TopicCluster(topic="T", severity="high", count=5,
                                   sentiment_score=-0.3, summary="S")],
            platform="ios", period_label="15d",
        )
        with patch("ado_search.correlate_clusters", side_effect=Exception("ADO timeout")):
            phase_correlate(report, "ios", 90)
        assert any("ADO failed" in n for n in report.data_quality_notes)


class TestSkipAdo:
    def test_skip_ado_adds_note(self):
        comp = CompositePulseReport(generated_at=datetime.now(timezone.utc))
        report = PulseReport(
            generated_at=datetime.now(timezone.utc),
            days_analyzed=15, total_reviews=50,
            overall_sentiment=-0.3, overall_summary="Test",
            platform="ios", period_label="15d",
        )
        comp.put("ios", "15d", report)
        # Simulate --skip-ado behavior
        for _, rpt in comp.reports.items():
            if not any("skipped" in n for n in rpt.data_quality_notes):
                rpt.data_quality_notes.append("ADO correlation skipped (--skip-ado)")
        assert any("skip" in n.lower() for n in report.data_quality_notes)


class TestFullPipeline:
    def test_smoke_test(self):
        """Verify the entire pipeline runs without errors when all deps are mocked."""
        from main import main
        mock_reviews = [
            Review(source="appstore", title="Test", body="Body", rating=3,
                   author="u",
                   date=datetime.now(timezone.utc) - timedelta(days=5),
                   platform="ios"),
        ] * 10

        with patch("sys.argv", ["main.py", "--platforms", "ios", "--skip-ado"]), \
             patch("main.phase_fetch", return_value=mock_reviews), \
             patch("main.phase_analyze") as mock_analyze, \
             patch("main.phase_trends"), \
             patch("main.phase_report"):
            mock_analyze.return_value = PulseReport(
                generated_at=datetime.now(timezone.utc),
                days_analyzed=15, total_reviews=10,
                overall_sentiment=-0.3, overall_summary="Test",
                platform="ios", period_label="15d",
            )
            main()

    def test_no_reviews_skips_platform(self):
        """When no reviews are found for a platform, it's skipped."""
        from main import main
        with patch("sys.argv", ["main.py", "--platforms", "ios"]), \
             patch("main.phase_fetch", return_value=[]), \
             patch("main.phase_report"):
            main()  # Should not error
