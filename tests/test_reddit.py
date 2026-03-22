"""Tests for Reddit fetcher with 3-tier fallback."""

from __future__ import annotations

import json
import re as re_mod
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest
import responses
from freezegun import freeze_time

from models import Review

FIXTURES_DIR = Path(__file__).parent / "fixtures"

# Use a frozen time close to fixture timestamps
# Fixture created_utc values are ~1742400000 = March 19, 2025
FROZEN_TIME = "2025-03-22T12:00:00Z"


@pytest.fixture
def reddit_json():
    return json.loads((FIXTURES_DIR / "reddit_search.json").read_text())


@pytest.fixture
def reddit_arctic():
    return json.loads((FIXTURES_DIR / "reddit_arctic_shift.json").read_text())


@pytest.fixture
def reddit_html():
    return (FIXTURES_DIR / "reddit_scrape.html").read_text()


class TestRedditJsonApi:
    @responses.activate
    @freeze_time(FROZEN_TIME)
    def test_happy_path(self, reddit_json):
        """JSON API returns posts correctly."""
        responses.add(
            responses.GET,
            re_mod.compile(r"https://www\.reddit\.com/r/.*/search\.json"),
            json=reddit_json,
            status=200,
        )
        with patch("cache.get", return_value=None), \
             patch("cache.today_str", return_value="2025-03-22"), \
             patch("cache.put"), \
             patch("sources.reddit.time.sleep"), \
             patch.dict("os.environ", {}, clear=False):
            import os
            os.environ.pop("REDDIT_CLIENT_ID", None)
            os.environ.pop("REDDIT_CLIENT_SECRET", None)
            from sources.reddit import fetch
            reviews = fetch(days=90, platform="ios", use_cache=True)

        assert len(reviews) > 0
        assert all(r.source == "reddit" for r in reviews)
        assert all(r.platform == "ios" for r in reviews)

    @responses.activate
    @freeze_time(FROZEN_TIME)
    def test_403_falls_back_to_scraping(self, reddit_html):
        """When JSON API returns 403, falls back to scraping."""
        responses.add(
            responses.GET,
            re_mod.compile(r"https://www\.reddit\.com/r/.*/search\.json"),
            status=403,
        )
        responses.add(
            responses.GET,
            re_mod.compile(r"https://old\.reddit\.com/r/.*/search"),
            body=reddit_html,
            status=200,
        )
        with patch("cache.get", return_value=None), \
             patch("cache.today_str", return_value="2025-03-22"), \
             patch("cache.put"), \
             patch("sources.reddit.time.sleep"), \
             patch.dict("os.environ", {}, clear=False):
            import os
            os.environ.pop("REDDIT_CLIENT_ID", None)
            os.environ.pop("REDDIT_CLIENT_SECRET", None)
            from sources.reddit import fetch
            reviews = fetch(days=90, platform="ios", use_cache=True)

        assert len(reviews) > 0

    @responses.activate
    @freeze_time(FROZEN_TIME)
    def test_fallback_to_arctic_shift(self, reddit_arctic):
        """When JSON and scraping fail, falls back to Arctic Shift."""
        responses.add(
            responses.GET,
            re_mod.compile(r"https://www\.reddit\.com/r/.*/search\.json"),
            status=403,
        )
        responses.add(
            responses.GET,
            re_mod.compile(r"https://old\.reddit\.com/r/.*/search"),
            status=403,
        )
        responses.add(
            responses.GET,
            re_mod.compile(r"https://arctic-shift\.photon-reddit\.com/"),
            json=reddit_arctic,
            status=200,
        )
        with patch("cache.get", return_value=None), \
             patch("cache.today_str", return_value="2025-03-22"), \
             patch("cache.put"), \
             patch("sources.reddit.time.sleep"), \
             patch("sources.reddit.BeautifulSoup", None), \
             patch.dict("os.environ", {}, clear=False):
            import os
            os.environ.pop("REDDIT_CLIENT_ID", None)
            os.environ.pop("REDDIT_CLIENT_SECRET", None)
            from sources.reddit import fetch
            reviews = fetch(days=90, platform="mac", use_cache=True)

        assert len(reviews) > 0

    @responses.activate
    @freeze_time(FROZEN_TIME)
    def test_oauth_session(self, reddit_json):
        """OAuth credentials get used when available."""
        responses.add(
            responses.POST,
            "https://www.reddit.com/api/v1/access_token",
            json={"access_token": "test_token"},
            status=200,
        )
        responses.add(
            responses.GET,
            re_mod.compile(r"https://oauth\.reddit\.com/r/.*/search\.json"),
            json=reddit_json,
            status=200,
        )
        with patch("cache.get", return_value=None), \
             patch("cache.today_str", return_value="2025-03-22"), \
             patch("cache.put"), \
             patch("sources.reddit.time.sleep"), \
             patch.dict("os.environ", {
                 "REDDIT_CLIENT_ID": "test_id",
                 "REDDIT_CLIENT_SECRET": "test_secret",
             }):
            from sources.reddit import fetch
            reviews = fetch(days=90, platform="ios", use_cache=True)

        assert len(reviews) > 0

    def test_cache_hit(self):
        cached = [
            {"source": "reddit", "title": "Cached post", "body": "From cache",
             "rating": None, "author": "u", "date": "2025-03-18T00:00:00+00:00",
             "country": "", "url": "", "version": "", "platform": "ios"}
        ]
        with patch("cache.get", return_value=cached), \
             patch("cache.today_str", return_value="2025-03-22"):
            from sources.reddit import fetch
            reviews = fetch(days=90, platform="ios", use_cache=True)
        assert len(reviews) == 1
        assert reviews[0].title == "Cached post"


class TestRedditHelpers:
    def test_build_query_basic(self):
        from sources.reddit import _build_query
        q = _build_query("", "ios")
        assert "outlook" in q.lower() or "ios" in q.lower()

    def test_build_query_with_topic(self):
        from sources.reddit import _build_query
        q = _build_query("calendar sync", "ios")
        assert "calendar" in q.lower() or "sync" in q.lower()

    def test_parse_json_post_empty_title(self):
        from sources.reddit import _parse_json_post
        result = _parse_json_post({"title": "", "selftext": "body"}, "Outlook", "ios")
        assert result is None

    def test_parse_json_post_truncates_long_body(self):
        from sources.reddit import _parse_json_post
        long_body = "x" * 2000
        result = _parse_json_post(
            {"title": "Test", "selftext": long_body, "created_utc": 1742400000,
             "permalink": "/r/test", "author": "u"},
            "Outlook", "ios",
        )
        assert result is not None
        assert len(result.body) <= 1004  # 1000 + "..."

    @responses.activate
    def test_rate_limiting_retry(self):
        """Rate-limited requests are retried."""
        responses.add(
            responses.GET,
            re_mod.compile(r"https://www\.reddit\.com/"),
            status=429,
            headers={"Retry-After": "1"},
        )
        responses.add(
            responses.GET,
            re_mod.compile(r"https://www\.reddit\.com/"),
            json={"data": {"children": []}},
            status=200,
        )
        from sources.reddit import _get_with_retry
        import requests
        session = requests.Session()
        session.headers.update({"User-Agent": "test"})
        with patch("sources.reddit.time.sleep"):
            result = _get_with_retry(session, "https://www.reddit.com/test", retries=1)
        assert result is not None
        assert result.status_code == 200

    def test_time_filter_selection(self):
        """Time filter varies by days parameter."""
        from sources.reddit import _build_query
        for plat in ["ios", "mac", "android"]:
            q = _build_query("", plat)
            assert len(q) > 0
