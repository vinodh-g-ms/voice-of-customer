"""Microsoft Q&A feedback scraper — platform-aware (v3)."""

from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone

import requests

import config
from models import Review

try:
    from bs4 import BeautifulSoup
except ImportError:
    BeautifulSoup = None


def fetch(days: int = 90, topic: str = "", platform: str = "ios", use_cache: bool = True) -> list[Review]:
    """Scrape MS Q&A listing pages for Outlook questions."""
    if BeautifulSoup is None:
        print("  [warn] MS Q&A: beautifulsoup4 not installed, skipping")
        return []

    import cache

    cache_key = f"msqa_{platform}_{topic}" if topic else f"msqa_{platform}"
    date_str = cache.today_str()
    if use_cache:
        cached = cache.get(cache_key, date_str)
        if cached is not None:
            print(f"  [cache hit] MS Q&A ({platform}): {len(cached)} questions")
            return [Review.from_dict(r) for r in cached]

    base_url = config.MSQA_PLATFORM_URLS.get(platform, config.MSQA_PLATFORM_URLS["ios"])
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    all_reviews: list[Review] = []
    session = requests.Session()
    session.headers.update({"User-Agent": "Mozilla/5.0 CustomerPulse/3.0"})

    # Add platform-specific search term
    platform_term = {"ios": "iOS", "mac": "Mac", "android": "Android"}.get(platform, "")

    for page in range(1, config.MSQA_MAX_PAGES + 1):
        params = f"?page={page}&orderby=newest"
        if topic:
            params += f"&q={requests.utils.quote(topic + ' ' + platform_term)}"
        elif platform_term:
            params += f"&q={requests.utils.quote(platform_term)}"
        url = base_url + params
        try:
            resp = session.get(url, timeout=15)
            if resp.status_code != 200:
                break
            questions = _parse_page(resp.text, cutoff, platform)
            if not questions:
                break
            all_reviews.extend(questions)
            print(f"  MS Q&A page {page} ({platform}): {len(questions)} questions")
        except (requests.RequestException, ValueError) as e:
            print(f"  [warn] MS Q&A page {page}: {e}")
            break
        time.sleep(1.5)

    if all_reviews:
        cache.put(cache_key, date_str, [r.to_dict() for r in all_reviews])
    return all_reviews


def _parse_page(html: str, cutoff: datetime, platform: str) -> list[Review]:
    soup = BeautifulSoup(html, "lxml")
    reviews: list[Review] = []

    cards = soup.select("article.thread-card, div.question-summary, li.question-summary")
    if not cards:
        for link in soup.select("a[href*='/answers/questions/']"):
            title = link.get_text(strip=True)
            if not title or len(title) < 10:
                continue
            href = link.get("href", "")
            if not href.startswith("http"):
                href = f"https://learn.microsoft.com{href}"
            reviews.append(Review(
                source="msqa", title=title, body="", rating=None,
                author="", date=None, url=href, platform=platform,
            ))
        return reviews

    for card in cards:
        title_el = card.select_one("h3 a, h2 a, a.question-title, a.thread-title")
        if not title_el:
            continue
        title = title_el.get_text(strip=True)
        if not title:
            continue
        href = title_el.get("href", "")
        if not href.startswith("http"):
            href = f"https://learn.microsoft.com{href}"
        date = None
        time_el = card.select_one("time, span.asked-date, span.date")
        if time_el:
            dt_attr = time_el.get("datetime", "")
            if dt_attr:
                try:
                    date = datetime.fromisoformat(dt_attr.replace("Z", "+00:00"))
                except (ValueError, TypeError):
                    pass
        if date and date < cutoff:
            continue
        author_el = card.select_one("a.author, span.username, a[href*='/users/']")
        author = author_el.get_text(strip=True) if author_el else ""
        reviews.append(Review(
            source="msqa", title=title, body="", rating=None,
            author=author, date=date, url=href, platform=platform,
        ))
    return reviews
