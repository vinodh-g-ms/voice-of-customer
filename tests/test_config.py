"""Tests for configuration module."""

from __future__ import annotations

import config


class TestConfig:
    def test_appstore_platforms_has_ios_and_mac(self):
        assert "ios" in config.APPSTORE_PLATFORMS
        assert "mac" in config.APPSTORE_PLATFORMS
        assert "app_id" in config.APPSTORE_PLATFORMS["ios"]
        assert "app_id" in config.APPSTORE_PLATFORMS["mac"]

    def test_appstore_countries_not_empty(self):
        assert len(config.APPSTORE_COUNTRIES) > 0
        assert "us" in config.APPSTORE_COUNTRIES

    def test_time_windows_structure(self):
        assert len(config.TIME_WINDOWS) >= 2
        names = [w["name"] for w in config.TIME_WINDOWS]
        assert "15d" in names
        assert "90d" in names
        for w in config.TIME_WINDOWS:
            assert "days" in w
            assert isinstance(w["days"], int)

    def test_reddit_subreddits_not_empty(self):
        assert len(config.REDDIT_SUBREDDITS) > 0

    def test_reddit_platform_queries(self):
        for plat in ("ios", "mac", "android"):
            assert plat in config.REDDIT_PLATFORM_QUERIES

    def test_ado_area_paths(self):
        for plat in ("ios", "mac", "android"):
            assert plat in config.ADO_AREA_PATHS
            assert len(config.ADO_AREA_PATHS[plat]) > 0

    def test_default_platforms(self):
        assert "ios" in config.DEFAULT_PLATFORMS
        assert "mac" in config.DEFAULT_PLATFORMS
        assert "android" in config.DEFAULT_PLATFORMS

    def test_default_sources(self):
        assert "appstore" in config.DEFAULT_SOURCES
        assert "reddit" in config.DEFAULT_SOURCES

    def test_cache_ttl_positive(self):
        assert config.CACHE_TTL_HOURS > 0

    def test_claude_model_set(self):
        assert config.CLAUDE_MODEL
        assert config.CLAUDE_MAX_TOKENS > 0

    def test_copilot_config(self):
        assert config.COPILOT_BASE_URL
        assert config.COPILOT_MAX_TOKENS > 0
