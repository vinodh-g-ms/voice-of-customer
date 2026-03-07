"""App Store review fetcher via iTunes RSS JSON feed (multi-platform)."""

from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone

import requests

import config
from models import Review


def fetch(days: int = 90, platform: str = "ios", use_cache: bool = True) -> list[Review]:
    """Fetch App Store reviews for the given platform."""
    import cache

    platform_info = config.APPSTORE_PLATFORMS.get(platform)
    if not platform_info:
        print(f"  [warn] Unknown platform '{platform}', skipping")
        return []

    app_id = platform_info["app_id"]
    cache_key = f"appstore_{platform}"
    date_str = cache.today_str()

    if use_cache:
        cached = cache.get(cache_key, date_str)
        if cached is not None:
            print(f"  [cache hit] App Store ({platform}): {len(cached)} reviews")
            return [Review.from_dict(r) for r in cached]

    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    all_reviews: list[Review] = []

    for country in config.APPSTORE_COUNTRIES:
        country_count = 0
        for page in range(1, config.APPSTORE_PAGES + 1):
            url = (
                f"https://itunes.apple.com/{country}/rss/customerreviews"
                f"/page={page}/id={app_id}/sortby=mostrecent/json"
            )
            try:
                resp = requests.get(url, timeout=15)
                if resp.status_code != 200:
                    break
                data = resp.json()
                entries = data.get("feed", {}).get("entry", [])
                if not entries:
                    break
                for entry in entries:
                    if "im:rating" not in entry:
                        continue
                    review = _parse_entry(entry, country, platform, app_id)
                    if review.date and review.date < cutoff:
                        continue
                    all_reviews.append(review)
                    country_count += 1
            except (requests.RequestException, ValueError, KeyError) as e:
                print(f"  [warn] App Store {platform}/{country} p{page}: {e}")
                break
            time.sleep(config.APPSTORE_DELAY)
        if country_count > 0:
            print(f"  App Store/{platform}/{country}: {country_count} reviews")

    if all_reviews:
        cache.put(cache_key, date_str, [r.to_dict() for r in all_reviews])
    return all_reviews


def _parse_entry(entry: dict, country: str, platform: str, app_id: str) -> Review:
    title = _label(entry.get("title", {}))
    body = _label(entry.get("content", [{}])[0] if isinstance(entry.get("content"), list) else entry.get("content", {}))
    rating = int(_label(entry.get("im:rating", {})) or 0)
    author = _label(entry.get("author", {}).get("name", {}))
    version = _label(entry.get("im:version", {}))

    date = None
    date_str = _label(entry.get("updated", {}))
    if date_str:
        try:
            date = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
        except (ValueError, TypeError):
            pass

    entry_id = _label(entry.get("id", {}))
    url = f"https://apps.apple.com/{country}/app/id{app_id}?see-all=reviews" if entry_id else ""

    return Review(
        source="appstore", title=title, body=body, rating=rating,
        author=author, date=date, country=country, url=url,
        version=version, platform=platform,
    )


def _label(obj) -> str:
    if isinstance(obj, dict):
        return str(obj.get("label", ""))
    return str(obj) if obj else ""
