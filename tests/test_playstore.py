"""Tests for Google Play Store review fetcher."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import patch, MagicMock

import pytest

from models import Review


class TestPlayStore:
    def _make_play_review(self, **overrides):
        defaults = {
            "content": "Great app for email",
            "score": 4,
            "userName": "playuser",
            "at": datetime(2026, 3, 18, tzinfo=timezone.utc),
            "reviewCreatedVersion": "4.2501.0",
            "reviewId": "play-review-1",
        }
        defaults.update(overrides)
        return defaults

    def test_happy_path(self):
        mock_reviews_fn = MagicMock(return_value=([self._make_play_review()], None))
        mock_sort = MagicMock()
        mock_sort.NEWEST = "NEWEST"

        import sources.playstore as ps
        orig_reviews, orig_sort = ps.reviews, ps.Sort
        ps.reviews = mock_reviews_fn
        ps.Sort = mock_sort
        try:
            with patch("cache.get", return_value=None), \
                 patch("cache.today_str", return_value="2026-03-22"), \
                 patch("cache.put"):
                result = ps.fetch(days=90, use_cache=True)
        finally:
            ps.reviews, ps.Sort = orig_reviews, orig_sort

        assert len(result) > 0
        assert all(isinstance(r, Review) for r in result)
        assert all(r.platform == "android" for r in result)
        assert all(r.source == "playstore" for r in result)

    def test_cache_hit(self):
        cached = [
            {"source": "playstore", "title": "", "body": "Cached review",
             "rating": 4, "author": "u", "date": "2026-03-18T00:00:00+00:00",
             "country": "us", "url": "", "version": "4.0", "platform": "android"}
        ]
        with patch("cache.get", return_value=cached), \
             patch("cache.today_str", return_value="2026-03-22"):
            from sources.playstore import fetch
            reviews = fetch(days=90, use_cache=True)
        assert len(reviews) == 1
        assert reviews[0].body == "Cached review"

    def test_date_cutoff(self):
        old_review = self._make_play_review(at=datetime(2024, 1, 1, tzinfo=timezone.utc))
        mock_reviews_fn = MagicMock(return_value=([old_review], None))
        mock_sort = MagicMock()
        mock_sort.NEWEST = "NEWEST"

        import sources.playstore as ps
        orig_reviews, orig_sort = ps.reviews, ps.Sort
        ps.reviews = mock_reviews_fn
        ps.Sort = mock_sort
        try:
            with patch("cache.get", return_value=None), \
                 patch("cache.today_str", return_value="2026-03-22"), \
                 patch("cache.put"):
                result = ps.fetch(days=15, use_cache=True)
        finally:
            ps.reviews, ps.Sort = orig_reviews, orig_sort

        assert len(result) == 0

    def test_missing_library_returns_empty(self):
        import sources.playstore as ps
        original = ps.reviews
        ps.reviews = None
        try:
            result = ps.fetch(days=90, use_cache=False)
            assert result == []
        finally:
            ps.reviews = original

    def test_per_country_error_handled(self):
        mock_reviews_fn = MagicMock(side_effect=Exception("Country blocked"))
        mock_sort = MagicMock()
        mock_sort.NEWEST = "NEWEST"

        import sources.playstore as ps
        orig_reviews, orig_sort = ps.reviews, ps.Sort
        ps.reviews = mock_reviews_fn
        ps.Sort = mock_sort
        try:
            with patch("cache.get", return_value=None), \
                 patch("cache.today_str", return_value="2026-03-22"), \
                 patch("cache.put"):
                result = ps.fetch(days=90, use_cache=True)
        finally:
            ps.reviews, ps.Sort = orig_reviews, orig_sort

        assert result == []

    def test_review_without_version(self):
        review_no_ver = self._make_play_review(reviewCreatedVersion=None)
        mock_reviews_fn = MagicMock(return_value=([review_no_ver], None))
        mock_sort = MagicMock()
        mock_sort.NEWEST = "NEWEST"

        import sources.playstore as ps
        orig_reviews, orig_sort = ps.reviews, ps.Sort
        ps.reviews = mock_reviews_fn
        ps.Sort = mock_sort
        try:
            with patch("cache.get", return_value=None), \
                 patch("cache.today_str", return_value="2026-03-22"), \
                 patch("cache.put"):
                result = ps.fetch(days=90, use_cache=True)
        finally:
            ps.reviews, ps.Sort = orig_reviews, orig_sort

        assert len(result) > 0
        assert result[0].version == ""

    def test_naive_datetime_gets_utc(self):
        naive_review = self._make_play_review(at=datetime(2026, 3, 18))
        mock_reviews_fn = MagicMock(return_value=([naive_review], None))
        mock_sort = MagicMock()
        mock_sort.NEWEST = "NEWEST"

        import sources.playstore as ps
        orig_reviews, orig_sort = ps.reviews, ps.Sort
        ps.reviews = mock_reviews_fn
        ps.Sort = mock_sort
        try:
            with patch("cache.get", return_value=None), \
                 patch("cache.today_str", return_value="2026-03-22"), \
                 patch("cache.put"):
                result = ps.fetch(days=90, use_cache=True)
        finally:
            ps.reviews, ps.Sort = orig_reviews, orig_sort

        assert len(result) > 0
        assert result[0].date.tzinfo is not None
