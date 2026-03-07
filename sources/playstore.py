"""Google Play Store review fetcher for Android."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import config
from models import Review

try:
    from google_play_scraper import reviews, Sort
except ImportError:
    reviews = None
    Sort = None


def fetch(days: int = 90, use_cache: bool = True) -> list[Review]:
    """Fetch Google Play Store reviews for Outlook Android."""
    import cache

    if reviews is None:
        print("  [warn] google-play-scraper not installed, skipping Play Store")
        return []

    cache_key = "playstore_android"
    date_str = cache.today_str()
    if use_cache:
        cached = cache.get(cache_key, date_str)
        if cached is not None:
            print(f"  [cache hit] Play Store (android): {len(cached)} reviews")
            return [Review.from_dict(r) for r in cached]

    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    all_reviews: list[Review] = []

    for country in config.PLAYSTORE_COUNTRIES:
        try:
            result, _ = reviews(
                config.PLAYSTORE_APP_ID,
                lang="en",
                country=country,
                sort=Sort.NEWEST,
                count=config.PLAYSTORE_REVIEWS_PER_COUNTRY,
            )
            country_count = 0
            for r in result:
                review = _parse_review(r, country)
                if review.date and review.date < cutoff:
                    continue
                all_reviews.append(review)
                country_count += 1

            if country_count > 0:
                print(f"  Play Store/android/{country}: {country_count} reviews")

        except Exception as e:
            print(f"  [warn] Play Store {country}: {e}")

    if all_reviews:
        cache.put(cache_key, date_str, [r.to_dict() for r in all_reviews])

    return all_reviews


def _parse_review(r: dict, country: str) -> Review:
    """Parse a google-play-scraper review dict into a Review."""
    date = None
    if r.get("at"):
        dt = r["at"]
        if isinstance(dt, datetime):
            date = dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt
        else:
            try:
                date = datetime.fromisoformat(str(dt))
            except (ValueError, TypeError):
                pass

    version = r.get("reviewCreatedVersion", "") or ""

    return Review(
        source="playstore",
        title="",
        body=r.get("content", ""),
        rating=r.get("score"),
        author=r.get("userName", ""),
        date=date,
        country=country,
        url=f"https://play.google.com/store/apps/details?id={config.PLAYSTORE_APP_ID}&reviewId={r.get('reviewId', '')}",
        version=str(version),
        platform="android",
    )
