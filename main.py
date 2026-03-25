#!/usr/bin/env python3
"""Customer Pulse v3 — iOS + Mac + Android feedback analyzer.

Usage:
    python main.py [--platforms ios,mac,android] [--topic TOPIC] [--skip-ado] [--no-cache]
"""

import argparse
import sys
import time
from datetime import datetime, timedelta, timezone

import config
from models import Review, CompositePulseReport


def main():
    args = parse_args()

    print("\n  Customer Pulse v3 — Outlook Feedback Analyzer")
    print("  " + "=" * 50)

    start = time.time()
    platforms = [p.strip() for p in args.platforms.split(",") if p.strip()]
    sources = list(config.DEFAULT_SOURCES) if args.sources == "all" else [s.strip() for s in args.sources.split(",")]
    use_cache = not args.no_cache
    composite = CompositePulseReport(generated_at=datetime.now(timezone.utc))

    for platform in platforms:
        print(f"\n  {'=' * 50}")
        print(f"  PLATFORM: {platform.upper()}")
        print(f"  {'=' * 50}")

        max_days = max(w["days"] for w in config.TIME_WINDOWS)
        all_reviews = phase_fetch(platform, max_days, sources, use_cache, args.topic)
        if not all_reviews:
            print(f"\n  [warn] No reviews for {platform}")
            continue

        for window in config.TIME_WINDOWS:
            wname, wdays = window["name"], window["days"]
            cutoff = datetime.now(timezone.utc) - timedelta(days=wdays)
            window_reviews = [r for r in all_reviews if r.date is None or r.date >= cutoff]
            if not window_reviews:
                continue
            report = phase_analyze(window_reviews, args.topic, platform, wname, wdays)
            composite.put(platform, wname, report)

        phase_trends(composite, platform, all_reviews, args.topic)

        if not args.skip_ado:
            for window in config.TIME_WINDOWS:
                rpt = composite.get(platform, window["name"])
                if rpt:
                    if args.semantic_match:
                        phase_correlate_semantic(rpt, platform, window["days"])
                    else:
                        phase_correlate(rpt, platform, window["days"])
        else:
            for _, rpt in composite.reports.items():
                if not any("skipped" in n for n in rpt.data_quality_notes):
                    rpt.data_quality_notes.append("ADO correlation skipped (--skip-ado)")

    phase_report(composite, args)
    print(f"\n  Done in {time.time() - start:.1f}s")


def parse_args():
    p = argparse.ArgumentParser(description="Customer Pulse v3")
    p.add_argument("--platforms", default=",".join(config.DEFAULT_PLATFORMS))
    p.add_argument("--topic", default="")
    p.add_argument("--sources", default="all")
    p.add_argument("--skip-ado", action="store_true")
    p.add_argument("--semantic-match", action="store_true",
                   help="Use semantic (embedding + LLM) ADO matching instead of keyword search")
    p.add_argument("--no-cache", action="store_true")
    return p.parse_args()


def phase_fetch(platform, days, sources, use_cache, topic) -> list[Review]:
    print(f"\n  Phase 1: FETCH ({platform}, {days}d)")
    print("  " + "-" * 48)
    all_reviews: list[Review] = []

    # App Store (iOS + Mac)
    if "appstore" in sources and platform in ("ios", "mac"):
        try:
            from sources.appstore import fetch as f
            all_reviews.extend(f(days=days, platform=platform, use_cache=use_cache))
        except Exception as e:
            print(f"  [error] App Store ({platform}): {e}")

    # Google Play Store (Android)
    if "playstore" in sources and platform == "android":
        try:
            from sources.playstore import fetch as f
            all_reviews.extend(f(days=days, use_cache=use_cache))
        except Exception as e:
            print(f"  [error] Play Store: {e}")

    # Reddit (all platforms)
    if "reddit" in sources:
        try:
            from sources.reddit import fetch as f
            all_reviews.extend(f(days=days, topic=topic, platform=platform, use_cache=use_cache))
        except Exception as e:
            print(f"  [error] Reddit ({platform}): {e}")

    # MS Q&A (all platforms)
    if "msqa" in sources:
        try:
            from sources.msqa import fetch as f
            all_reviews.extend(f(days=days, topic=topic, platform=platform, use_cache=use_cache))
        except Exception as e:
            print(f"  [error] MS Q&A ({platform}): {e}")

    print(f"\n  Total ({platform}): {len(all_reviews)} reviews")
    return all_reviews


def phase_analyze(reviews, topic, platform, period_label, days):
    from analysis import analyze, build_report_from_analysis
    print(f"\n  Phase 2: ANALYZE ({platform}/{period_label}, {len(reviews)} reviews)")
    print("  " + "-" * 48)
    result = analyze(reviews, topic=topic, platform=platform, period_label=period_label)
    return build_report_from_analysis(result, reviews, days, platform=platform, period_label=period_label)


def phase_trends(composite, platform, all_reviews, topic):
    from analysis import analyze, build_report_from_analysis, compute_trends
    current = composite.get(platform, "15d")
    if not current:
        return
    print(f"\n  Phase 2b: TRENDS ({platform})")
    print("  " + "-" * 48)
    now = datetime.now(timezone.utc)
    prev = [r for r in all_reviews if r.date and (now - timedelta(days=30)) <= r.date < (now - timedelta(days=15))]
    if len(prev) < 5:
        print(f"  [warn] Only {len(prev)} reviews in prev 15d, skipping trends")
        current.data_quality_notes.append(f"Trends skipped: {len(prev)} reviews in prev 15d")
        return
    result = analyze(prev, topic=topic, platform=platform, period_label="prev-15d")
    prev_report = build_report_from_analysis(result, prev, 15, platform=platform, period_label="prev-15d")
    compute_trends(current, prev_report)
    print(f"  Trends: {sum(1 for c in current.clusters if c.trend)} clusters with trend data")


def phase_correlate(report, platform, max_age_days):
    from ado_search import correlate_clusters
    print(f"\n  Phase 3: CORRELATE ({platform}/{report.period_label}, max {max_age_days}d, area path filter)")
    print("  " + "-" * 48)
    try:
        correlate_clusters(report.clusters, platform=platform, max_age_days=max_age_days)
        total = sum(len(c.ado_matches) for c in report.clusters)
        print(f"  ADO matches ({platform}/{report.period_label}): {total}")
    except Exception as e:
        print(f"  [error] ADO: {e}")
        report.data_quality_notes.append(f"ADO failed: {e}")


def phase_correlate_semantic(report, platform, max_age_days):
    from ado_matcher import match_clusters_semantic
    print(f"\n  Phase 3: CORRELATE/SEMANTIC ({platform}/{report.period_label}, max {max_age_days}d)")
    print("  " + "-" * 48)
    try:
        match_clusters_semantic(report.clusters, platform=platform, max_age_days=max_age_days)
        total = sum(len(c.ado_matches) for c in report.clusters)
        print(f"  Semantic matches ({platform}/{report.period_label}): {total}")
        if total == 0:
            print("  [fallback] No semantic matches, trying keyword search...")
            phase_correlate(report, platform, max_age_days)
    except Exception as e:
        print(f"  [error] Semantic matcher: {e}")
        print("  [fallback] Falling back to keyword search...")
        phase_correlate(report, platform, max_age_days)


def phase_report(composite, args):
    from report import generate_composite
    print(f"\n  Phase 4: REPORT")
    print("  " + "-" * 48)
    generate_composite(composite, topic=args.topic)


if __name__ == "__main__":
    main()
