"""JSON file caching with TTL support."""

from __future__ import annotations

import json
import os
import time
from datetime import datetime
from pathlib import Path

import config

CACHE_DIR = Path(__file__).parent / "cache"


def _cache_path(source: str, date_str: str) -> Path:
    """Build cache file path: cache/{source}_{date}.json"""
    return CACHE_DIR / f"{source}_{date_str}.json"


def get(source: str, date_str: str) -> list[dict] | None:
    """Read cached data if it exists and is within TTL.

    Returns list of review dicts, or None if cache miss.
    """
    path = _cache_path(source, date_str)
    if not path.exists():
        return None

    age_hours = (time.time() - path.stat().st_mtime) / 3600
    if age_hours > config.CACHE_TTL_HOURS:
        return None

    try:
        with open(path, "r") as f:
            data = json.load(f)
        return data if isinstance(data, list) else None
    except (json.JSONDecodeError, OSError):
        return None


def put(source: str, date_str: str, reviews: list[dict]) -> None:
    """Write review data to cache."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path = _cache_path(source, date_str)
    with open(path, "w") as f:
        json.dump(reviews, f, indent=2, default=str)


def today_str() -> str:
    """Today's date string for cache keys."""
    return datetime.now().strftime("%Y-%m-%d")
