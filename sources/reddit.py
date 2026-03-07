"""Reddit feedback fetcher — platform-aware queries (v3)."""

from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone

import requests

import config
from models import Review


def fetch(days: int = 90, topic: str = "", platform: str = "ios", use_cache: bool = True) -> list[Review]:
    """Fetch Reddit posts about Outlook for the given platform."""
    import cache

    cache_key = f"reddit_{platform}_{topic}" if topic else f"reddit_{platform}"
    date_str = cache.today_str()
    if use_cache:
        cached = cache.get(cache_key, date_str)
        if cached is not None:
            print(f"  [cache hit] Reddit ({platform}): {len(cached)} posts")
            return [Review.from_dict(r) for r in cached]

    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    all_reviews: list[Review] = []
    session = requests.Session()
    session.headers.update({"User-Agent": config.REDDIT_USER_AGENT})

    for subreddit in config.REDDIT_SUBREDDITS:
        query = _build_query(topic, platform)
        sub_count = 0
        url = (
            f"https://www.reddit.com/r/{subreddit}/search.json"
            f"?q={query}&restrict_sr=on&sort=new"
            f"&limit={config.REDDIT_POSTS_PER_QUERY}"
            f"&t={'week' if days <= 7 else 'month' if days <= 30 else 'year'}"
        )
        try:
            resp = _get_with_retry(session, url)
            if resp is None:
                continue
            data = resp.json()
            for post in data.get("data", {}).get("children", []):
                review = _parse_post(post.get("data", {}), subreddit, platform)
                if review is None:
                    continue
                if review.date and review.date < cutoff:
                    continue
                all_reviews.append(review)
                sub_count += 1
        except (requests.RequestException, ValueError, KeyError) as e:
            print(f"  [warn] Reddit r/{subreddit} ({platform}): {e}")
        if sub_count > 0:
            print(f"  Reddit/r/{subreddit} ({platform}): {sub_count} posts")
        time.sleep(config.REDDIT_DELAY)

    if all_reviews:
        cache.put(cache_key, date_str, [r.to_dict() for r in all_reviews])
    return all_reviews


def _build_query(topic: str, platform: str) -> str:
    base = config.REDDIT_PLATFORM_QUERIES.get(platform, "outlook mobile")
    if topic:
        base = f"({base}) AND ({topic})"
    return requests.utils.quote(base)


def _get_with_retry(session, url, retries=1):
    for attempt in range(retries + 1):
        try:
            resp = session.get(url, timeout=15)
            if resp.status_code == 200:
                return resp
            if resp.status_code == 429 and attempt < retries:
                time.sleep(10)
                continue
            return None
        except requests.RequestException:
            if attempt < retries:
                time.sleep(5)
                continue
            return None
    return None


def _parse_post(data: dict, subreddit: str, platform: str) -> Review | None:
    title = data.get("title", "")
    if not title:
        return None
    body = data.get("selftext", "")
    if len(body) > 1000:
        body = body[:1000] + "..."
    date = None
    created = data.get("created_utc")
    if created:
        try:
            date = datetime.fromtimestamp(float(created), tz=timezone.utc)
        except (ValueError, TypeError, OSError):
            pass
    permalink = data.get("permalink", "")
    url = f"https://www.reddit.com{permalink}" if permalink else ""
    return Review(
        source="reddit", title=title, body=body, rating=None,
        author=data.get("author", "[deleted]"), date=date, url=url,
        platform=platform,
    )
