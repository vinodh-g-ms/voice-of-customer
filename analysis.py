"""Sentiment analysis, topic clustering, and trend computation (v2).

Uses a pluggable analyzer backend. Set ANALYSIS_PROVIDER env var to choose:
  - "claude"  → Anthropic Claude API
  - "copilot" → GitHub Models API
"""

from __future__ import annotations

import json
import os
import re
import sys
from difflib import SequenceMatcher

import config
from analyzers import get_analyzer
from models import Review, TopicCluster, PulseReport

# Module-level analyzer instance (lazy-initialized)
_analyzer = None


def _get_analyzer():
    global _analyzer
    if _analyzer is None:
        _analyzer = get_analyzer()
    return _analyzer


def _get_max_reviews() -> int:
    provider = os.environ.get("ANALYSIS_PROVIDER", "claude").lower()
    return getattr(config, f"{provider.upper()}_MAX_REVIEWS", config.CLAUDE_MAX_REVIEWS)


def analyze(
    reviews: list[Review], topic: str = "",
    platform: str = "", period_label: str = "",
) -> dict:
    analyzer = _get_analyzer()
    selected = _prioritize_reviews(reviews)
    review_text = "\n".join(r.compact() for r in selected)

    provider = os.environ.get("ANALYSIS_PROVIDER", "claude")
    print(f"  Sending {len(selected)} reviews to {provider} [{platform}/{period_label}]...")

    raw = analyzer.analyze(review_text, platform, period_label, topic, len(selected))

    result = _parse_response(raw)
    print(f"  Analysis [{platform}/{period_label}]: {len(result.get('clusters', []))} clusters")
    return result


def _prioritize_reviews(reviews: list[Review]) -> list[Review]:
    max_reviews = _get_max_reviews()
    if len(reviews) <= max_reviews:
        return reviews
    neg_app, neg_other, neutral, positive = [], [], [], []
    for r in reviews:
        if r.rating is not None and r.rating <= 2:
            (neg_app if r.source == "appstore" else neg_other).append(r)
        elif r.rating is not None and r.rating >= 4:
            positive.append(r)
        else:
            neutral.append(r)
    selected: list[Review] = []
    for bucket in [neg_app, neg_other, neutral, positive]:
        remaining = max_reviews - len(selected)
        if remaining <= 0:
            break
        selected.extend(bucket[:remaining])
    return selected


def _parse_response(text: str) -> dict:
    text = text.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        lines = [l for l in lines[1:] if not l.strip().startswith("```")]
        text = "\n".join(lines)
    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        print(f"  [warn] JSON parse failed: {e}")
        return {"overall_sentiment": 0.0, "overall_summary": "Analysis parse failed.", "clusters": []}


def build_report_from_analysis(
    analysis_result: dict, reviews: list[Review], days: int,
    platform: str = "", period_label: str = "",
) -> PulseReport:
    from datetime import datetime, timedelta, timezone

    clusters = []
    for c in analysis_result.get("clusters", []):
        clusters.append(TopicCluster(
            topic=c.get("topic", "Unknown"), severity=c.get("severity", "medium"),
            count=c.get("count", 0), sentiment_score=c.get("sentiment_score", 0.0),
            summary=c.get("summary", ""), quotes=c.get("quotes", []),
            source_breakdown=c.get("source_breakdown", {}),
            version_breakdown={},  # computed from actual reviews below
        ))

    source_counts: dict[str, int] = {}
    for r in reviews:
        source_counts[r.source] = source_counts.get(r.source, 0) + 1

    dated = [r for r in reviews if r.date is not None]
    earliest = min((r.date for r in dated), default=None) if dated else None
    latest = max((r.date for r in dated), default=None) if dated else None

    # Match reviews to clusters and compute per-cluster weekly volumes + verified versions
    now = datetime.now(timezone.utc)
    _assign_reviews_to_clusters(clusters, reviews, now)

    # Compute overall weekly volume
    weekly_volume: dict[str, int] = {}
    for w in range(4, 0, -1):
        ws = now - timedelta(weeks=w)
        we = now - timedelta(weeks=w - 1)
        label = ws.strftime("%b %d")
        weekly_volume[label] = sum(1 for r in reviews if r.date and ws <= r.date < we)

    return PulseReport(
        generated_at=datetime.now(timezone.utc), days_analyzed=days,
        total_reviews=len(reviews),
        overall_sentiment=analysis_result.get("overall_sentiment", 0.0),
        overall_summary=analysis_result.get("overall_summary", ""),
        clusters=clusters, source_counts=source_counts,
        platform=platform, period_label=period_label,
        earliest_review_date=earliest, latest_review_date=latest,
        weekly_volume=weekly_volume,
    )


def compute_trends(current: PulseReport, previous: PulseReport) -> None:
    """Compare current 15d vs previous 15d. Mutates current.clusters."""
    prev_topics = {c.topic: c for c in previous.clusters}

    for cluster in current.clusters:
        best = _find_best_match(cluster.topic, prev_topics)
        if best:
            prev = prev_topics[best]
            cluster.previous_count = prev.count
            cluster.count_delta = cluster.count - prev.count
            cluster.trend = "up" if cluster.count_delta > 0 else ("down" if cluster.count_delta < 0 else "")
        else:
            cluster.trend = "new"
            cluster.previous_count = 0
            cluster.count_delta = cluster.count


def _find_best_match(topic: str, candidates: dict[str, TopicCluster]) -> str | None:
    best_name, best_ratio = None, 0.0
    topic_lower = topic.lower()
    for name in candidates:
        ratio = SequenceMatcher(None, topic_lower, name.lower()).ratio()
        if ratio > best_ratio:
            best_ratio = ratio
            best_name = name
    return best_name if best_ratio >= 0.5 else None


def _assign_reviews_to_clusters(clusters: list[TopicCluster], reviews: list[Review], now) -> None:
    """Match reviews to clusters by keyword overlap. Compute per-cluster weekly volumes + verified versions."""
    from datetime import timedelta

    stop = {
        "the", "a", "an", "is", "are", "was", "were", "in", "on", "at",
        "to", "for", "of", "with", "not", "and", "or", "but", "this", "that",
        "outlook", "app", "issue", "problem", "bug", "issues", "problems",
        "after", "update", "new", "just", "like", "get", "can", "even",
    }

    for cluster in clusters:
        # Extract meaningful keywords from topic
        words = set(re.findall(r'\b[a-z]{3,}\b', cluster.topic.lower()))
        keywords = words - stop
        if not keywords:
            continue

        # Match reviews: require at least half of keywords present
        threshold = max(1, len(keywords) // 2)
        matched = []
        for r in reviews:
            text = r.text.lower()
            hits = sum(1 for kw in keywords if kw in text)
            if hits >= threshold:
                matched.append(r)

        cluster.matched_reviews = matched[:20]  # keep top 20 for display

        # Compute weekly counts from matched reviews
        weekly = {}
        for w in range(4, 0, -1):
            ws = now - timedelta(weeks=w)
            we = now - timedelta(weeks=w - 1)
            label = ws.strftime("%b %d")
            weekly[label] = sum(1 for r in matched if r.date and ws <= r.date < we)
        cluster.weekly_counts = weekly

        # Compute verified version breakdown (only from reviews with actual version data)
        ver_counts: dict[str, int] = {}
        for r in matched:
            if r.version:
                ver_counts[r.version] = ver_counts.get(r.version, 0) + 1
        cluster.version_breakdown = ver_counts
