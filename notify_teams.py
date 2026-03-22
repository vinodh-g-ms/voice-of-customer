#!/usr/bin/env python3
"""Send Teams notification after VoC pipeline completes.

Posts a rich Adaptive Card to a Teams channel via Incoming Webhook.
Shows per-platform top issues + health warnings for expired tokens.

Required env vars:
    TEAMS_WEBHOOK_URL         — Teams Incoming Webhook URL
    SHAREPOINT_DASHBOARD_URL  — URL to the hosted dashboard (optional)
"""

import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import requests

OUTPUT_DIR = Path(__file__).parent / "output_v3"
GITHUB_REPO = "vinodh-g-ms/voice-of-customer"
DASHBOARD_URL_DEFAULT = f"https://{GITHUB_REPO.split('/')[0]}.github.io/{GITHUB_REPO.split('/')[1]}/"

SEVERITY_EMOJI = {"critical": "🔴", "high": "🟠", "medium": "🟡", "low": "🟢"}
PLAT_EMOJI = {"iOS": "📱", "MacOS": "💻", "macOS": "💻", "Android": "🤖"}


def build_summary() -> dict:
    """Read the latest markdown report to extract per-platform top issues."""
    md_files = sorted(OUTPUT_DIR.glob("pulse_report_v3_*.md"), reverse=True)
    summary = {
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "platforms": [],
        "total_reviews": 0,
        "platform_issues": {},  # { "iOS": [{"title": ..., "severity": ..., "count": ...}, ...] }
    }

    if not md_files:
        return summary

    content = md_files[0].read_text()
    lines = content.split("\n")

    current_platform = None
    current_section = None  # "90d" or "15d"

    for i, line in enumerate(lines):
        # Detect platform headers: "## iOS", "## MacOS", "## Android"
        if line.startswith("## ") and not line.startswith("### "):
            plat = line.strip("# ").strip()
            if plat and plat not in summary["platforms"]:
                summary["platforms"].append(plat)
                current_platform = plat

        # Detect period section: "### iOS — 15d"
        if line.startswith("### ") and "—" in line:
            if "15d" in line:
                current_section = "15d"
            else:
                current_section = "90d"

        # Extract review counts from the 15d section (most recent)
        if "**reviews:**" in line.lower() and current_section == "15d":
            try:
                segment = line.split("|")[0]
                digits = "".join(c for c in segment.split(":**")[1] if c.isdigit())
                if digits:
                    summary["total_reviews"] += int(digits)
            except (IndexError, ValueError):
                pass

        # Extract cluster titles from 15d sections: "#### 1. 🔴 App crashes"
        if (line.startswith("#### ") and current_platform and current_section == "15d"):
            title = re.sub(r'^#+\s*\d+\.\s*', '', line).strip()
            # Extract emoji severity
            severity = "medium"
            if "🔴" in title:
                severity = "critical"
            elif "🟠" in title:
                severity = "high"
            elif "🟡" in title:
                severity = "medium"
            # Clean title
            title = re.sub(r'^[🔴🟠🟡🟢\s]+', '', title).strip()

            # Get count from next line if it has mentions
            count = ""
            if i + 1 < len(lines):
                next_line = lines[i + 1]
                m = re.search(r'(\d+)\s+mention', next_line)
                if m:
                    count = m.group(1)

            if current_platform not in summary["platform_issues"]:
                summary["platform_issues"][current_platform] = []

            summary["platform_issues"][current_platform].append({
                "title": title,
                "severity": severity,
                "count": count,
            })

    # Also sum 90d reviews if we didn't find 15d
    if summary["total_reviews"] == 0:
        for line in lines:
            if "**reviews:**" in line.lower():
                try:
                    segment = line.split("|")[0]
                    digits = "".join(c for c in segment.split(":**")[1] if c.isdigit())
                    if digits:
                        summary["total_reviews"] += int(digits)
                except (IndexError, ValueError):
                    pass

    return summary


def _detect_warnings() -> list[dict]:
    """Detect token/config issues to surface in the notification."""
    warnings = []
    provider = os.environ.get("ANALYSIS_PROVIDER", "copilot").lower()

    # ADO PAT
    if not os.environ.get("SYSTEM_ACCESSTOKEN"):
        warnings.append({
            "text": "⚠️ **ADO token missing** — bug linking is disabled.",
            "fix_url": f"https://github.com/{GITHUB_REPO}/settings/secrets/actions",
            "fix_label": "Update ADO_PAT secret",
        })

    # AI provider token (only warn if we detect it may be broken)
    if provider == "copilot" and not (os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_MODELS_TOKEN")):
        warnings.append({
            "text": "⛔ **GitHub token missing** — AI analysis will fail.",
            "fix_url": f"https://github.com/{GITHUB_REPO}/settings/secrets/actions",
            "fix_label": "Add GH_MODELS_TOKEN secret",
        })
    elif provider == "claude" and not os.environ.get("ANTHROPIC_API_KEY"):
        warnings.append({
            "text": "⛔ **Anthropic API key missing** — AI analysis will fail.",
            "fix_url": f"https://github.com/{GITHUB_REPO}/settings/secrets/actions",
            "fix_label": "Add ANTHROPIC_API_KEY secret",
        })

    return warnings


def _get_pipeline_status() -> dict:
    """Read pipeline status from environment (set by GitHub Actions workflow)."""
    status = os.environ.get("PIPELINE_STATUS", "")
    first_error_time = os.environ.get("PIPELINE_FIRST_ERROR_TIME", "")

    if status == "failed":
        return {
            "icon": "❌",
            "text": "Pipeline failed after retry",
            "detail": f"First failure at {first_error_time}. Retried after 5 min — still failed. Error dashboard deployed instead." if first_error_time else "Pipeline failed. Error dashboard deployed instead.",
            "color": "Attention",
            "failed": True,
        }
    elif status == "success_after_retry":
        return {
            "icon": "⚠️",
            "text": "Pipeline succeeded after retry",
            "detail": f"First attempt failed at {first_error_time}. Retried after 5 min — succeeded." if first_error_time else "First attempt failed. Retried after 5 min — succeeded.",
            "color": "Warning",
            "failed": False,
        }
    else:
        return {
            "icon": "✅",
            "text": "Pipeline completed successfully",
            "detail": "",
            "color": "Good",
            "failed": False,
        }


def build_adaptive_card(summary: dict, dashboard_url: str) -> dict:
    """Build a rich Teams Adaptive Card with per-platform issues."""
    platforms_str = ", ".join(summary["platforms"]) if summary["platforms"] else "See dashboard"
    warnings = _detect_warnings()
    pipeline = _get_pipeline_status()

    # Determine status line
    if pipeline["failed"]:
        status_value = f"{pipeline['icon']} {pipeline['text']}"
    elif warnings:
        status_value = "⚠️ Completed with warnings"
    else:
        status_value = f"{pipeline['icon']} {pipeline['text']}"

    body = [
        # Header
        {
            "type": "ColumnSet",
            "columns": [
                {
                    "type": "Column", "width": "auto",
                    "items": [{"type": "TextBlock", "text": "📊", "size": "Large"}],
                },
                {
                    "type": "Column", "width": "stretch",
                    "items": [
                        {"type": "TextBlock", "text": f"[Voice of Customer]({dashboard_url})" if dashboard_url else "Voice of Customer",
                         "size": "Large", "weight": "Bolder", "wrap": True, "spacing": "None"},
                        {"type": "TextBlock", "text": "Outlook Customer Intelligence — Daily Report",
                         "size": "Small", "isSubtle": True, "spacing": "None"},
                    ],
                },
            ],
        },
        # Status bar
        {
            "type": "FactSet",
            "facts": [
                {"title": "Generated", "value": summary["timestamp"]},
                {"title": "Platforms", "value": platforms_str},
                {"title": "Reviews Analyzed", "value": f"{summary['total_reviews']:,}" if summary["total_reviews"] else "—"},
                {"title": "Status", "value": status_value},
            ],
            "separator": True,
        },
    ]

    # Pipeline failure/retry detail
    if pipeline["detail"]:
        body.append({
            "type": "TextBlock",
            "text": f"**{pipeline['icon']} {pipeline['detail']}**",
            "wrap": True, "spacing": "Medium",
            "color": pipeline["color"],
        })

    # Per-platform top 3 issues
    for plat in summary["platforms"]:
        issues = summary["platform_issues"].get(plat, [])[:3]
        if not issues:
            continue

        emoji = PLAT_EMOJI.get(plat, "📋")
        body.append({
            "type": "TextBlock",
            "text": f"{emoji} **{plat} — Top Issues (Last 15 Days)**",
            "wrap": True, "spacing": "Medium", "weight": "Bolder",
            "separator": True,
        })

        for issue in issues:
            sev_dot = SEVERITY_EMOJI.get(issue["severity"], "⚪")
            count_str = f" ({issue['count']} mentions)" if issue["count"] else ""
            body.append({
                "type": "TextBlock",
                "text": f"{sev_dot} {issue['title']}{count_str}",
                "wrap": True, "spacing": "Small",
            })

    # Warnings section
    if warnings:
        body.append({
            "type": "TextBlock",
            "text": "**Action Required**",
            "wrap": True, "spacing": "Large", "weight": "Bolder",
            "color": "Attention", "separator": True,
        })
        for w in warnings:
            body.append({
                "type": "TextBlock",
                "text": f"{w['text']} → [{w['fix_label']}]({w['fix_url']})",
                "wrap": True, "spacing": "Small",
            })

    # Actions
    actions = []
    if dashboard_url:
        actions.append({"type": "Action.OpenUrl", "title": "📊 Open Dashboard", "url": dashboard_url})
    actions.append({
        "type": "Action.OpenUrl", "title": "⚙️ Pipeline Logs",
        "url": f"https://github.com/{GITHUB_REPO}/actions",
    })
    if pipeline["failed"]:
        actions.insert(0, {
            "type": "Action.OpenUrl", "title": "🔄 Re-run Pipeline",
            "url": f"https://github.com/{GITHUB_REPO}/actions/workflows/daily-voc.yml",
        })
    if warnings:
        actions.append({
            "type": "Action.OpenUrl", "title": "🔑 Manage Secrets",
            "url": f"https://github.com/{GITHUB_REPO}/settings/secrets/actions",
        })

    return {
        "type": "message",
        "attachments": [{
            "contentType": "application/vnd.microsoft.card.adaptive",
            "contentUrl": None,
            "content": {
                "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
                "type": "AdaptiveCard",
                "version": "1.4",
                "body": body,
                "actions": actions,
                "selectAction": {
                    "type": "Action.OpenUrl",
                    "url": dashboard_url,
                } if dashboard_url else None,
            },
        }],
    }


def main():
    webhook_url = os.environ.get("TEAMS_WEBHOOK_URL")
    dashboard_url = os.environ.get("SHAREPOINT_DASHBOARD_URL") or DASHBOARD_URL_DEFAULT

    if not webhook_url:
        print("ERROR: TEAMS_WEBHOOK_URL not set")
        sys.exit(1)

    print("\n  Teams Notification")
    print("  " + "=" * 40)

    summary = build_summary()
    card = build_adaptive_card(summary, dashboard_url)

    # Print preview
    for plat in summary["platforms"]:
        issues = summary["platform_issues"].get(plat, [])[:3]
        if issues:
            print(f"  {plat}: {', '.join(i['title'][:40] for i in issues)}")

    resp = requests.post(
        webhook_url,
        json=card,
        headers={"Content-Type": "application/json"},
        timeout=30,
    )

    if resp.status_code in (200, 202):
        print("  ✅ Notification sent successfully")
    else:
        print(f"  FAILED: {resp.status_code} {resp.text[:200]}")
        sys.exit(1)


if __name__ == "__main__":
    main()
