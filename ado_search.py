"""Azure DevOps Work Item Search — freshness + area path filtering (v3).

Supports two auth modes:
  - Local: uses `az rest` (requires `az login`)
  - CI/CD: uses SYSTEM_ACCESSTOKEN env var with direct HTTP requests
"""

from __future__ import annotations

import base64
import json
import os
import re
import subprocess
from datetime import datetime, timedelta, timezone

import requests as http_requests

import config
from models import TopicCluster, ADOMatch


def correlate_clusters(
    clusters: list[TopicCluster],
    platform: str = "",
    max_age_days: int = 90,
) -> list[TopicCluster]:
    """Search ADO for bugs matching each topic cluster.

    Filters by: area path (platform), freshness (max_age_days).
    """
    auth_mode = _get_auth_mode()
    if auth_mode == "none":
        print("  [warn] ADO: no auth available (az login or SYSTEM_ACCESSTOKEN), skipping")
        return clusters
    print(f"  ADO auth: {auth_mode}")

    cutoff = datetime.now(timezone.utc) - timedelta(days=max_age_days)
    area_paths = config.ADO_AREA_PATHS.get(platform, [])

    for cluster in clusters:
        keywords = _extract_keywords(cluster.topic, platform)
        if not keywords:
            continue
        try:
            matches = _search_bugs(keywords, area_paths)
            # Filter to bugs updated within window
            fresh = [m for m in matches if m.changed_date is None or m.changed_date >= cutoff]
            cluster.ado_matches = fresh
            if fresh:
                print(f"  ADO: '{cluster.topic}' -> {len(fresh)} bugs ({len(matches)} total)")
            elif matches:
                print(f"  ADO: '{cluster.topic}' -> 0 fresh ({len(matches)} stale >{max_age_days}d)")
        except Exception as e:
            print(f"  [warn] ADO failed for '{cluster.topic}': {e}")

    return clusters


def _get_auth_mode() -> str:
    """Determine auth mode: 'pat' if SYSTEM_ACCESSTOKEN is set (CI), else 'az'."""
    if os.environ.get("SYSTEM_ACCESSTOKEN"):
        return "pat"
    try:
        r = subprocess.run(["az", "account", "show"], capture_output=True, text=True, timeout=10)
        if r.returncode == 0:
            return "az"
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass
    return "none"


def _extract_keywords(topic: str, platform: str = "") -> str:
    stop_words = {
        "the", "a", "an", "is", "are", "was", "were", "in", "on", "at",
        "to", "for", "of", "with", "not", "no", "and", "or", "but",
        "outlook", "app", "issue", "problem", "bug", "issues", "problems",
        "users", "report", "frequently", "constantly", "sometimes", "often",
        "very", "also", "some", "many", "after", "when", "while", "been",
        "being", "having", "have", "has", "does", "doesn", "don", "can",
        "cannot", "could", "would", "should", "may", "might", "will",
        "just", "like", "get", "gets", "getting", "got", "make", "made",
        "even", "still", "much", "more", "most", "every", "each", "all",
        "any", "both", "other", "new", "old", "since", "update", "updated",
        "become", "becomes", "becoming", "fails", "failed", "unable",
        "certain", "specific", "particular", "despite", "without",
        "however", "between", "through", "during", "before",
        "repeatedly", "extended", "periods", "properly", "correctly",
        "working", "work", "works", "use", "using", "used",
    }
    if platform == "ios":
        stop_words.update({"mac", "macos", "desktop", "android"})
    elif platform == "mac":
        stop_words.update({"ios", "iphone", "ipad", "mobile", "android"})
    elif platform == "android":
        stop_words.update({"ios", "iphone", "ipad", "mac", "macos"})

    words = re.findall(r'\b\w+\b', topic.lower())
    keywords = [w for w in words if w not in stop_words and len(w) > 2]

    # Add platform name to improve ADO search relevance
    platform_terms = {"ios": "ios", "mac": "macos", "android": "android"}
    prefix = platform_terms.get(platform, "")
    if prefix:
        keywords = [prefix] + keywords

    return " ".join(keywords[:6])


def _search_bugs(keywords: str, area_paths: list[str]) -> list[ADOMatch]:
    org = config.ADO_ORG_URL.rstrip("/").split("/")[-1].replace(".visualstudio.com", "")
    url = (
        f"{config.ADO_SEARCH_URL}/{org}"
        f"/{config.ADO_PROJECT}/_apis/search/workitemsearchresults"
        f"?api-version=7.1-preview.1"
    )
    filters = {"System.WorkItemType": ["Bug"]}
    if area_paths:
        filters["System.AreaPath"] = area_paths

    payload = {
        "searchText": keywords,
        "$top": config.ADO_MAX_RESULTS,
        "$skip": 0,
        "filters": filters,
        "sortOptions": [{"field": "System.ChangedDate", "sortOrder": "DESC"}],
    }

    auth_mode = _get_auth_mode()
    if auth_mode == "pat":
        return _search_via_http(url, payload)
    return _search_via_az_rest(url, payload)


def _search_via_http(url: str, payload: dict) -> list[ADOMatch]:
    """Direct HTTP request using SYSTEM_ACCESSTOKEN (for CI/CD)."""
    pat = os.environ["SYSTEM_ACCESSTOKEN"]
    b64 = base64.b64encode(f":{pat}".encode()).decode()
    headers = {
        "Authorization": f"Basic {b64}",
        "Content-Type": "application/json",
    }
    try:
        resp = http_requests.post(url, json=payload, headers=headers, timeout=30)
        if resp.status_code != 200:
            if resp.status_code in (401, 403):
                raise RuntimeError(f"ADO auth error: {resp.status_code}")
            return []
        return _parse_results(resp.json())
    except http_requests.RequestException:
        return []


def _search_via_az_rest(url: str, payload: dict) -> list[ADOMatch]:
    """Use az rest CLI (for local development)."""
    body = json.dumps(payload)
    try:
        r = subprocess.run(
            ["az", "rest", "--method", "post", "--url", url,
             "--resource", config.ADO_RESOURCE_ID, "--body", body,
             "--headers", "Content-Type=application/json"],
            capture_output=True, text=True, timeout=30,
        )
        if r.returncode != 0:
            if "401" in r.stderr or "403" in r.stderr:
                raise RuntimeError("ADO auth error")
            return []
        if not r.stdout.strip():
            return []
        return _parse_results(json.loads(r.stdout))
    except subprocess.TimeoutExpired:
        return []
    except json.JSONDecodeError:
        return []


def _parse_results(data: dict) -> list[ADOMatch]:
    matches = []
    for item in data.get("results", []):
        fields = item.get("fields", {})
        wid = 0; title = ""; state = ""; assigned = ""; changed = None

        if isinstance(fields, dict):
            try: wid = int(fields.get("system.id", 0))
            except: pass
            title = fields.get("system.title", "")
            state = fields.get("system.state", "")
            assigned = fields.get("system.assignedto", "")
            changed = _pd(fields.get("system.changeddate", ""))
        else:
            for f in fields:
                n, v = f.get("name", ""), f.get("value", "")
                if n == "system.id":
                    try: wid = int(v)
                    except: pass
                elif n == "system.title": title = v
                elif n == "system.state": state = v
                elif n == "system.assignedto": assigned = v
                elif n == "system.changeddate": changed = _pd(v)

        if wid and title:
            matches.append(ADOMatch(
                work_item_id=wid, title=title, state=state,
                assigned_to=assigned,
                url=f"{config.ADO_ORG_URL}/{config.ADO_PROJECT}/_workitems/edit/{wid}",
                changed_date=changed,
            ))
    return matches


def _pd(s: str) -> datetime | None:
    if not s: return None
    try: return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except: return None
