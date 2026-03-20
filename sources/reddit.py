"""Reddit feedback fetcher — platform-aware queries (v3).

Supports two modes:
  1. OAuth API (recommended for CI/CD) — set REDDIT_CLIENT_ID and
     REDDIT_CLIENT_SECRET env vars. Uses oauth.reddit.com which works
     reliably from cloud/datacenter IPs.
  2. Public JSON API (fallback) — no credentials needed but may be
     blocked by Reddit on GitHub Actions runners.
"""

from __future__ import annotations

import os
import time
from datetime import datetime, timedelta, timezone

import requests

import config
from models import Review

_OAUTH_TOKEN_URL = "https://www.reddit.com/api/v1/access_token"
_OAUTH_BASE = "https://oauth.reddit.com"
_PUBLIC_BASE = "https://www.reddit.com"


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
    session = _build_session()

    for subreddit in config.REDDIT_SUBREDDITS:
        query = _build_query(topic, platform)
        sub_count = 0
        base_url = _OAUTH_BASE if _is_oauth(session) else _PUBLIC_BASE
        url = (
            f"{base_url}/r/{subreddit}/search.json"
            f"?q={query}&restrict_sr=on&sort=new"
            f"&limit={config.REDDIT_POSTS_PER_QUERY}"
            f"&t={'week' if days <= 7 else 'month' if days <= 30 else 'year'}"
        )
        try:
            resp = _get_with_retry(session, url)
            if resp is None:
                print(f"  [warn] Reddit r/{subreddit} ({platform}): no response (blocked or rate-limited)")
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
    else:
        print(f"  [warn] Reddit ({platform}): 0 posts collected")
    return all_reviews


def _build_session() -> requests.Session:
    """Create a session, using OAuth if credentials are available."""
    session = requests.Session()
    session.headers.update({"User-Agent": config.REDDIT_USER_AGENT})

    client_id = os.environ.get("REDDIT_CLIENT_ID", "")
    client_secret = os.environ.get("REDDIT_CLIENT_SECRET", "")
    if client_id and client_secret:
        try:
            resp = session.post(
                _OAUTH_TOKEN_URL,
                auth=(client_id, client_secret),
                data={"grant_type": "client_credentials"},
                timeout=15,
            )
            if resp.status_code == 200:
                token = resp.json().get("access_token", "")
                if token:
                    session.headers.update({"Authorization": f"Bearer {token}"})
                    print("  Reddit: using OAuth API")
                    return session
            print(f"  [warn] Reddit OAuth failed ({resp.status_code}), falling back to public API")
        except requests.RequestException as e:
            print(f"  [warn] Reddit OAuth error: {e}, falling back to public API")
    return session


def _is_oauth(session: requests.Session) -> bool:
    return "Authorization" in session.headers


def _build_query(topic: str, platform: str) -> str:
    base = config.REDDIT_PLATFORM_QUERIES.get(platform, "outlook mobile")
    if topic:
        base = f"({base}) AND ({topic})"
    return requests.utils.quote(base)


def _get_with_retry(session, url, retries=2):
    for attempt in range(retries + 1):
        try:
            resp = session.get(url, timeout=15)
            if resp.status_code == 200:
                return resp
            if resp.status_code == 429 and attempt < retries:
                wait = min(int(resp.headers.get("Retry-After", 10)), 30)
                print(f"  [warn] Reddit rate-limited, waiting {wait}s...")
                time.sleep(wait)
                continue
            if resp.status_code in (403, 429):
                print(f"  [warn] Reddit HTTP {resp.status_code}")
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
