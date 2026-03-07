"""Claude API sentiment analysis, topic clustering, and trend computation (v2)."""

from __future__ import annotations

import json
import os
import re
import sys
from difflib import SequenceMatcher

import config
from models import Review, TopicCluster, PulseReport

try:
    import anthropic
except ImportError:
    anthropic = None


def _build_system_prompt(platform: str = "", period_label: str = "") -> str:
    platform_name = {
        "ios": "iOS (iPhone/iPad)",
        "mac": "macOS (Mac desktop app)",
    }.get(platform, "all platforms")

    period_desc = ""
    if period_label == "15d":
        period_desc = " Focus on recent and emerging issues."
    elif period_label == "90d":
        period_desc = " Provide a broad landscape view of persistent themes."

    return f"""You are an expert product analyst for Microsoft Outlook on {platform_name}.
You analyze customer feedback to identify actionable themes.{period_desc}

Analyze the provided customer reviews and return a JSON object with this EXACT schema:

{{
  "overall_sentiment": <float from -1.0 (very negative) to 1.0 (very positive)>,
  "overall_summary": "<2-3 sentence summary of the feedback landscape>",
  "clusters": [
    {{
      "topic": "<short topic name, e.g. 'Calendar sync failures'>",
      "severity": "<critical|high|medium|low>",
      "count": <number of reviews in this cluster>,
      "sentiment_score": <float -1.0 to 1.0>,
      "summary": "<1-2 sentence description of the issue>",
      "quotes": ["<exact quote 1>", "<exact quote 2>"],
      "source_breakdown": {{"appstore": 5, "reddit": 3, "msqa": 1}},
      "version_breakdown": {{"4.2411.0": 3, "4.2412.1": 7}}
    }}
  ]
}}

Rules:
- Return ONLY valid JSON, no markdown fences or extra text
- Create 5-15 clusters, sorted by severity then count (descending)
- Each cluster should have 2-4 representative quotes (exact text from reviews)
- Severity: critical = app-breaking/data loss, high = major workflow blocker,
  medium = annoying but workaround exists, low = cosmetic/minor
- Merge similar topics
- source_breakdown counts should sum to the cluster's count
- version_breakdown: count reviews per app version when version info is available
- If a topic filter was specified, focus clusters on that topic area"""


def analyze(
    reviews: list[Review], topic: str = "",
    platform: str = "", period_label: str = "",
) -> dict:
    if anthropic is None:
        print("ERROR: anthropic package not installed. Run: pip install anthropic")
        sys.exit(1)

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("ERROR: ANTHROPIC_API_KEY not set.")
        sys.exit(1)

    selected = _prioritize_reviews(reviews)
    review_text = "\n".join(r.compact() for r in selected)

    plat = f" ({platform})" if platform else ""
    per = f" [{period_label}]" if period_label else ""
    user_prompt = f"Analyze these {len(selected)} customer reviews{plat}{per}"
    if topic:
        user_prompt += f" (focus on: {topic})"
    user_prompt += f":\n\n{review_text}"

    print(f"  Sending {len(selected)} reviews to Claude [{platform}/{period_label}]...")

    client = anthropic.Anthropic(api_key=api_key)
    message = client.messages.create(
        model=config.CLAUDE_MODEL, max_tokens=config.CLAUDE_MAX_TOKENS,
        system=_build_system_prompt(platform, period_label),
        messages=[{"role": "user", "content": user_prompt}],
    )

    result = _parse_response(message.content[0].text)
    print(f"  Analysis [{platform}/{period_label}]: {len(result.get('clusters', []))} clusters")
    return result


def _prioritize_reviews(reviews: list[Review]) -> list[Review]:
    if len(reviews) <= config.CLAUDE_MAX_REVIEWS:
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
        remaining = config.CLAUDE_MAX_REVIEWS - len(selected)
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
