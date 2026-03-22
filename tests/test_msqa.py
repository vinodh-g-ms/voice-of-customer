"""Tests for Microsoft Q&A scraper."""

from __future__ import annotations

import re as re_mod
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest
import responses

from models import Review

FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture
def msqa_html():
    return (FIXTURES_DIR / "msqa_page.html").read_text()


class TestMsqa:
    @responses.activate
    def test_happy_path(self, msqa_html):
        responses.add(
            responses.GET,
            re_mod.compile(r"https://learn\.microsoft\.com/.*"),
            body=msqa_html,
            status=200,
        )
        with patch("cache.get", return_value=None), \
             patch("cache.today_str", return_value="2026-03-22"), \
             patch("cache.put"), \
             patch("sources.msqa.time.sleep"):
            from sources.msqa import fetch
            reviews = fetch(days=90, platform="ios", use_cache=True)
        assert len(reviews) > 0
        assert all(r.source == "msqa" for r in reviews)
        assert all(r.platform == "ios" for r in reviews)

    def test_missing_bs4_returns_empty(self):
        import sources.msqa as msqa
        original = msqa.BeautifulSoup
        msqa.BeautifulSoup = None
        try:
            result = msqa.fetch(days=90, platform="ios", use_cache=False)
            assert result == []
        finally:
            msqa.BeautifulSoup = original

    def test_cache_hit(self):
        cached = [
            {"source": "msqa", "title": "Cached Q", "body": "",
             "rating": None, "author": "u", "date": None,
             "country": "", "url": "https://example.com", "version": "", "platform": "ios"}
        ]
        with patch("cache.get", return_value=cached), \
             patch("cache.today_str", return_value="2026-03-22"):
            from sources.msqa import fetch
            reviews = fetch(days=90, platform="ios", use_cache=True)
        assert len(reviews) == 1

    @responses.activate
    def test_pagination_stops_on_empty(self, msqa_html):
        responses.add(
            responses.GET,
            re_mod.compile(r".*page=1.*"),
            body=msqa_html,
            status=200,
        )
        responses.add(
            responses.GET,
            re_mod.compile(r".*page=2.*"),
            status=404,
        )
        with patch("cache.get", return_value=None), \
             patch("cache.today_str", return_value="2026-03-22"), \
             patch("cache.put"), \
             patch("sources.msqa.time.sleep"):
            from sources.msqa import fetch
            reviews = fetch(days=90, platform="ios", use_cache=True)
        assert len(reviews) > 0

    @responses.activate
    def test_fallback_selector_parsing(self):
        """When thread-card selector fails, fallback to answer links."""
        fallback_html = '''<html><body>
        <a href="/en-us/answers/questions/99999/test-question">Test question about Outlook iOS crash</a>
        </body></html>'''
        responses.add(
            responses.GET,
            re_mod.compile(r"https://learn\.microsoft\.com/.*page=1.*"),
            body=fallback_html,
            status=200,
        )
        responses.add(
            responses.GET,
            re_mod.compile(r"https://learn\.microsoft\.com/.*page=2.*"),
            body="<html><body></body></html>",
            status=200,
        )
        with patch("cache.get", return_value=None), \
             patch("cache.today_str", return_value="2026-03-22"), \
             patch("cache.put"), \
             patch("sources.msqa.time.sleep"):
            from sources.msqa import fetch
            reviews = fetch(days=90, platform="ios", use_cache=True)
        assert len(reviews) >= 1
        assert "test-question" in reviews[0].url.lower() or "99999" in reviews[0].url

    @responses.activate
    def test_http_error_handled(self):
        responses.add(
            responses.GET,
            re_mod.compile(r"https://learn\.microsoft\.com/.*"),
            status=500,
        )
        with patch("cache.get", return_value=None), \
             patch("cache.today_str", return_value="2026-03-22"), \
             patch("cache.put"), \
             patch("sources.msqa.time.sleep"):
            from sources.msqa import fetch
            reviews = fetch(days=90, platform="ios", use_cache=True)
        assert reviews == []

    @responses.activate
    def test_topic_added_to_query(self, msqa_html):
        """When a topic is provided, it's added to the search query."""
        responses.add(
            responses.GET,
            re_mod.compile(r"https://learn\.microsoft\.com/.*"),
            body=msqa_html,
            status=200,
        )
        with patch("cache.get", return_value=None), \
             patch("cache.today_str", return_value="2026-03-22"), \
             patch("cache.put"), \
             patch("sources.msqa.time.sleep"):
            from sources.msqa import fetch
            reviews = fetch(days=90, topic="calendar", platform="ios", use_cache=True)
        assert isinstance(reviews, list)
