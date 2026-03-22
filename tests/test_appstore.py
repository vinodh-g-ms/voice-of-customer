"""Tests for App Store review fetcher."""

from __future__ import annotations

import json
import re as re_mod
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest
import responses

from models import Review

FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture
def appstore_feed():
    return json.loads((FIXTURES_DIR / "appstore_feed.json").read_text())


class TestAppStore:
    @responses.activate
    def test_happy_path(self, appstore_feed):
        """Mocked RSS feed returns reviews."""
        responses.add(
            responses.GET,
            re_mod.compile(r"https://itunes\.apple\.com/.*/page=1/.*"),
            json=appstore_feed,
            status=200,
        )
        responses.add(
            responses.GET,
            re_mod.compile(r"https://itunes\.apple\.com/.*/page=[2-9]/.*"),
            json={"feed": {"entry": []}},
            status=200,
        )
        responses.add(
            responses.GET,
            re_mod.compile(r"https://itunes\.apple\.com/.*/page=10/.*"),
            json={"feed": {"entry": []}},
            status=200,
        )

        with patch("cache.get", return_value=None), \
             patch("cache.today_str", return_value="2026-03-22"), \
             patch("cache.put"), \
             patch("time.sleep"):
            from sources.appstore import fetch
            reviews = fetch(days=90, platform="ios", use_cache=True)

        assert len(reviews) > 0
        assert all(isinstance(r, Review) for r in reviews)
        assert all(r.source == "appstore" for r in reviews)
        assert all(r.platform == "ios" for r in reviews)

    def test_cache_hit_skips_http(self):
        """When cache has data, no HTTP requests are made."""
        cached = [
            {"source": "appstore", "title": "Cached", "body": "From cache",
             "rating": 4, "author": "u", "date": "2026-03-15T00:00:00+00:00",
             "country": "us", "url": "", "version": "4.0", "platform": "ios"}
        ]
        with patch("cache.get", return_value=cached), \
             patch("cache.today_str", return_value="2026-03-22"):
            from sources.appstore import fetch
            reviews = fetch(days=90, platform="ios", use_cache=True)
        assert len(reviews) == 1
        assert reviews[0].title == "Cached"

    @responses.activate
    def test_date_cutoff_filters_old_reviews(self):
        """Reviews older than the cutoff are excluded."""
        old_feed = {
            "feed": {
                "entry": [{
                    "title": {"label": "Old review"},
                    "content": [{"label": "Very old"}],
                    "im:rating": {"label": "3"},
                    "im:version": {"label": "3.0"},
                    "author": {"name": {"label": "old_user"}},
                    "updated": {"label": "2024-01-01T00:00:00+00:00"},
                    "id": {"label": "old-id"},
                }]
            }
        }
        responses.add(
            responses.GET,
            re_mod.compile(r"https://itunes\.apple\.com/.*"),
            json=old_feed,
            status=200,
        )
        with patch("cache.get", return_value=None), \
             patch("cache.today_str", return_value="2026-03-22"), \
             patch("cache.put"), \
             patch("time.sleep"):
            from sources.appstore import fetch
            reviews = fetch(days=15, platform="ios", use_cache=True)
        assert len(reviews) == 0

    @responses.activate
    def test_http_error_handled(self):
        """HTTP errors don't crash the fetcher."""
        responses.add(
            responses.GET,
            re_mod.compile(r"https://itunes\.apple\.com/.*"),
            status=500,
        )
        with patch("cache.get", return_value=None), \
             patch("cache.today_str", return_value="2026-03-22"), \
             patch("cache.put"), \
             patch("time.sleep"):
            from sources.appstore import fetch
            reviews = fetch(days=90, platform="ios", use_cache=True)
        assert reviews == []

    def test_unknown_platform_returns_empty(self):
        from sources.appstore import fetch
        reviews = fetch(days=90, platform="windows", use_cache=False)
        assert reviews == []

    @responses.activate
    def test_missing_rating_skips_entry(self):
        """Entries without im:rating are skipped."""
        feed_no_rating = {
            "feed": {
                "entry": [{
                    "title": {"label": "No rating"},
                    "content": [{"label": "Missing rating field"}],
                    "author": {"name": {"label": "user"}},
                    "updated": {"label": "2026-03-18T10:00:00+00:00"},
                    "id": {"label": "id-1"},
                }]
            }
        }
        responses.add(
            responses.GET,
            re_mod.compile(r"https://itunes\.apple\.com/.*/page=1/.*"),
            json=feed_no_rating,
            status=200,
        )
        responses.add(
            responses.GET,
            re_mod.compile(r"https://itunes\.apple\.com/.*/page=[2-9]/.*"),
            json={"feed": {"entry": []}},
            status=200,
        )
        responses.add(
            responses.GET,
            re_mod.compile(r"https://itunes\.apple\.com/.*/page=10/.*"),
            json={"feed": {"entry": []}},
            status=200,
        )
        with patch("cache.get", return_value=None), \
             patch("cache.today_str", return_value="2026-03-22"), \
             patch("cache.put"), \
             patch("time.sleep"):
            from sources.appstore import fetch
            reviews = fetch(days=90, platform="ios", use_cache=True)
        assert len(reviews) == 0

    def test_cache_disabled(self):
        """When use_cache=False, cache is not consulted."""
        import cache as cache_mod
        with patch("sources.appstore.requests.get") as mock_get, \
             patch("time.sleep"), \
             patch.object(cache_mod, "get") as mock_cache_get:
            mock_get.return_value = MagicMock(status_code=500)
            from sources.appstore import fetch
            fetch(days=90, platform="ios", use_cache=False)
            mock_cache_get.assert_not_called()
