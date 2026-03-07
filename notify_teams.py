#!/usr/bin/env python3
"""Send Teams notification after VoC pipeline completes.

Posts an Adaptive Card to a Teams channel via Incoming Webhook.
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


def build_summary() -> dict:
    """Read the latest markdown report to extract summary stats."""
    md_files = sorted(OUTPUT_DIR.glob("pulse_report_v3_*.md"), reverse=True)
    summary = {
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "platforms": [],
        "total_reviews": 0,
        "critical_issues": [],
    }

    if not md_files:
        return summary

    content = md_files[0].read_text()
    lines = content.split("\n")
    prev_line = ""

    for line in lines:
        # Detect platform headers: "## iOS", "## MacOS", "## Android"
        if line.startswith("## ") and not line.startswith("### "):
            plat = line.strip("# ").strip()
            if plat and plat not in summary["platforms"]:
                summary["platforms"].append(plat)

        # Extract review counts: "**Reviews:** 1351 | **Sentiment:** -0.72"
        if "**reviews:**" in line.lower():
            try:
                segment = line.split("|")[0]
                digits = "".join(c for c in segment.split(":**")[1] if c.isdigit())
                if digits:
                    summary["total_reviews"] += int(digits)
            except (IndexError, ValueError):
                pass

        # Extract critical issues: line with "**critical**" preceded by a cluster title
        if "**critical**" in line.lower():
            # The cluster title is the preceding "#### N. ..." line
            title = prev_line.strip()
            if title.startswith("####"):
                title = re.sub(r'^#+\s*\d+\.\s*', '', title).strip()
                # Remove emoji prefix
                title = re.sub(r'^[\U0001f300-\U0001fAFF]\s*', '', title).strip()
                if title:
                    summary["critical_issues"].append(title)

        prev_line = line

    return summary


def build_adaptive_card(summary: dict, dashboard_url: str) -> dict:
    """Build a Teams Adaptive Card payload."""
    platforms_str = ", ".join(summary["platforms"]) if summary["platforms"] else "See dashboard"
    facts = [
        {"title": "Generated", "value": summary["timestamp"]},
        {"title": "Platforms", "value": platforms_str},
        {"title": "Total Reviews", "value": str(summary["total_reviews"]) if summary["total_reviews"] else "See dashboard"},
        {"title": "Status", "value": "Pipeline completed successfully"},
    ]

    actions = []
    if dashboard_url:
        actions.append({
            "type": "Action.OpenUrl",
            "title": "Open Dashboard",
            "url": dashboard_url,
        })

    card = {
        "type": "message",
        "attachments": [{
            "contentType": "application/vnd.microsoft.card.adaptive",
            "contentUrl": None,
            "content": {
                "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
                "type": "AdaptiveCard",
                "version": "1.4",
                "body": [
                    {
                        "type": "TextBlock",
                        "size": "Large",
                        "weight": "Bolder",
                        "text": "Customer Pulse — Daily Report",
                        "wrap": True,
                    },
                    {
                        "type": "TextBlock",
                        "text": "Voice of Customer pipeline has completed. Fresh insights are ready.",
                        "wrap": True,
                        "spacing": "Small",
                    },
                    {
                        "type": "FactSet",
                        "facts": facts,
                    },
                ],
                "actions": actions,
            },
        }],
    }

    # Add critical issues if any
    if summary["critical_issues"]:
        card["attachments"][0]["content"]["body"].append({
            "type": "TextBlock",
            "text": "**Critical Issues:**",
            "wrap": True,
            "spacing": "Medium",
        })
        for issue in summary["critical_issues"][:5]:
            card["attachments"][0]["content"]["body"].append({
                "type": "TextBlock",
                "text": f"- {issue}",
                "wrap": True,
                "spacing": "None",
            })

    return card


def main():
    webhook_url = os.environ.get("TEAMS_WEBHOOK_URL")
    dashboard_url = os.environ.get("SHAREPOINT_DASHBOARD_URL", "")

    if not webhook_url:
        print("ERROR: TEAMS_WEBHOOK_URL not set")
        sys.exit(1)

    print("\n  Teams Notification")
    print("  " + "=" * 40)

    summary = build_summary()
    card = build_adaptive_card(summary, dashboard_url)

    resp = requests.post(
        webhook_url,
        json=card,
        headers={"Content-Type": "application/json"},
        timeout=30,
    )

    if resp.status_code in (200, 202):
        print("  Notification sent successfully")
    else:
        print(f"  FAILED: {resp.status_code} {resp.text[:200]}")
        sys.exit(1)


if __name__ == "__main__":
    main()
