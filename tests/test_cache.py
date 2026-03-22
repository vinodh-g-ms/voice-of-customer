"""Tests for JSON file cache with TTL."""

from __future__ import annotations

import json
import time
from pathlib import Path
from unittest.mock import patch

import pytest

import cache
import config


class TestCache:
    def test_put_and_get(self, tmp_path):
        with patch.object(cache, "CACHE_DIR", tmp_path):
            cache.put("test_source", "2026-03-22", [{"title": "review1"}])
            result = cache.get("test_source", "2026-03-22")
            assert result is not None
            assert len(result) == 1
            assert result[0]["title"] == "review1"

    def test_miss_when_no_file(self, tmp_path):
        with patch.object(cache, "CACHE_DIR", tmp_path):
            assert cache.get("nonexistent", "2026-03-22") is None

    def test_expire_beyond_ttl(self, tmp_path):
        with patch.object(cache, "CACHE_DIR", tmp_path):
            cache.put("test", "2026-03-22", [{"data": "old"}])
            # Backdate the file modification time beyond TTL
            path = tmp_path / "test_2026-03-22.json"
            old_time = time.time() - (config.CACHE_TTL_HOURS * 3600 + 1)
            import os
            os.utime(path, (old_time, old_time))
            assert cache.get("test", "2026-03-22") is None

    def test_not_expired_within_ttl(self, tmp_path):
        with patch.object(cache, "CACHE_DIR", tmp_path):
            cache.put("test", "2026-03-22", [{"data": "fresh"}])
            result = cache.get("test", "2026-03-22")
            assert result is not None

    def test_corrupted_json_returns_none(self, tmp_path):
        with patch.object(cache, "CACHE_DIR", tmp_path):
            path = tmp_path / "bad_2026-03-22.json"
            path.write_text("not valid json{{{")
            assert cache.get("bad", "2026-03-22") is None

    def test_non_list_json_returns_none(self, tmp_path):
        with patch.object(cache, "CACHE_DIR", tmp_path):
            path = tmp_path / "dict_2026-03-22.json"
            path.write_text('{"not": "a list"}')
            assert cache.get("dict", "2026-03-22") is None

    def test_put_creates_directory(self, tmp_path):
        new_dir = tmp_path / "subdir" / "cache"
        with patch.object(cache, "CACHE_DIR", new_dir):
            cache.put("test", "2026-03-22", [{"ok": True}])
            assert new_dir.exists()

    def test_today_str_format(self):
        result = cache.today_str()
        # Should be YYYY-MM-DD format
        parts = result.split("-")
        assert len(parts) == 3
        assert len(parts[0]) == 4
