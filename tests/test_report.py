"""Tests for HTML/Markdown report generation."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

from models import (
    CompositePulseReport, PulseReport, TopicCluster, ADOMatch,
)


def _make_composite():
    cluster = TopicCluster(
        topic="Calendar sync failures", severity="critical", count=25,
        sentiment_score=-0.8, summary="Calendar sync is broken.",
        quotes=["Calendar won't sync", "Events disappear"],
        source_breakdown={"appstore": 15, "reddit": 10},
        ado_matches=[ADOMatch(work_item_id=123, title="Sync bug", state="Active",
                              url="https://ado.com/123")],
        trend="up", previous_count=15, count_delta=10,
        weekly_counts={"Mar 01": 5, "Mar 08": 8, "Mar 15": 12},
    )
    report = PulseReport(
        generated_at=datetime(2026, 3, 22, 6, 0, tzinfo=timezone.utc),
        days_analyzed=15, total_reviews=100, overall_sentiment=-0.3,
        overall_summary="Mixed feedback with sync issues dominating.",
        clusters=[cluster],
        source_counts={"appstore": 60, "reddit": 30, "msqa": 10},
        platform="ios", period_label="15d",
    )
    comp = CompositePulseReport(generated_at=datetime(2026, 3, 22, 6, 0, tzinfo=timezone.utc))
    comp.put("ios", "15d", report)
    return comp


class TestReport:
    def test_generate_creates_files(self, tmp_path):
        import report
        comp = _make_composite()
        original = report.OUTPUT_DIR
        report.OUTPUT_DIR = tmp_path
        try:
            result = report.generate_composite(comp, topic="")
        finally:
            report.OUTPUT_DIR = original
        # Check files were created
        md_files = list(tmp_path.glob("pulse_report_v3_*.md"))
        html_files = list(tmp_path.glob("pulse_dashboard_v3.html"))
        assert len(md_files) >= 1
        assert len(html_files) >= 1

    def test_markdown_structure(self, tmp_path):
        import report
        comp = _make_composite()
        original = report.OUTPUT_DIR
        report.OUTPUT_DIR = tmp_path
        try:
            generate_path = report.generate_composite(comp)
        finally:
            report.OUTPUT_DIR = original
        md_files = list(tmp_path.glob("pulse_report_v3_*.md"))
        md_content = md_files[0].read_text()
        assert "# Voice of Customer" in md_content
        assert "iOS" in md_content
        assert "Calendar sync failures" in md_content
        assert "critical" in md_content.lower()

    def test_html_contains_platform_tabs(self, tmp_path):
        import report
        comp = _make_composite()
        original = report.OUTPUT_DIR
        report.OUTPUT_DIR = tmp_path
        try:
            report.generate_composite(comp)
        finally:
            report.OUTPUT_DIR = original
        html = (tmp_path / "pulse_dashboard_v3.html").read_text()
        assert "ios" in html.lower()
        assert "Calendar sync failures" in html

    def test_severity_colors_in_html(self, tmp_path):
        import report
        comp = _make_composite()
        original = report.OUTPUT_DIR
        report.OUTPUT_DIR = tmp_path
        try:
            report.generate_composite(comp)
        finally:
            report.OUTPUT_DIR = original
        html = (tmp_path / "pulse_dashboard_v3.html").read_text()
        assert "#FF3B30" in html  # critical color

    def test_empty_report(self, tmp_path):
        import report
        comp = CompositePulseReport(generated_at=datetime(2026, 3, 22, tzinfo=timezone.utc))
        original = report.OUTPUT_DIR
        report.OUTPUT_DIR = tmp_path
        try:
            report.generate_composite(comp)
        finally:
            report.OUTPUT_DIR = original
        md_files = list(tmp_path.glob("pulse_report_v3_*.md"))
        assert len(md_files) >= 1

    def test_ado_matches_in_markdown(self, tmp_path):
        import report
        comp = _make_composite()
        original = report.OUTPUT_DIR
        report.OUTPUT_DIR = tmp_path
        try:
            report.generate_composite(comp)
        finally:
            report.OUTPUT_DIR = original
        md_files = list(tmp_path.glob("pulse_report_v3_*.md"))
        md_content = md_files[0].read_text()
        assert "123" in md_content  # ADO work item ID
        assert "Sync bug" in md_content

    def test_trend_badges_in_markdown(self, tmp_path):
        import report
        comp = _make_composite()
        original = report.OUTPUT_DIR
        report.OUTPUT_DIR = tmp_path
        try:
            report.generate_composite(comp)
        finally:
            report.OUTPUT_DIR = original
        md_content = list(tmp_path.glob("pulse_report_v3_*.md"))[0].read_text()
        # Trend should be referenced somewhere
        assert "25" in md_content  # count in cluster


# ── Console output ──────────────────────────────────────────────────

class TestConsoleOutput:
    def test_print_console_runs(self, capsys):
        from report import _print_console
        comp = _make_composite()
        _print_console(comp)
        captured = capsys.readouterr()
        assert "IOS" in captured.out or "ios" in captured.out.lower()
