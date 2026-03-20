"""Azure DevOps Work Item Search — v4: synonym-aware, multi-signal relevance.

Supports two auth modes:
  - Local: uses `az rest` (requires `az login`)
  - CI/CD: uses SYSTEM_ACCESSTOKEN env var with direct HTTP requests

Relevance scoring:
  - Synonym-expanded keyword overlap (topic 40%, summary 15%)
  - Fuzzy string similarity (15%)
  - State boost: Active/New +0.1, Resolved 0, Closed -0.05 (20%)
  - Recency boost: updated within 30d +0.1, 60d +0.05 (10%)
  - Results capped at top 5 per cluster, min_score 0.25
"""

from __future__ import annotations

import base64
import json
import math
import os
import re
import subprocess
from collections import Counter
from difflib import SequenceMatcher
from datetime import datetime, timedelta, timezone

import requests as http_requests

import config
from models import TopicCluster, ADOMatch


# ── Synonym groups: any word in a group matches any other ──────────────
# Related concepts that should match each other in bug linking
_SYNONYM_GROUPS = [
    {"crash", "crashes", "crashing", "crashed", "freeze", "freezes", "frozen",
     "hang", "hangs", "hanging", "unresponsive", "stuck"},
    {"sync", "syncing", "synchronize", "synchronization", "synced",
     "refresh", "refreshing", "reload", "reloading"},
    {"login", "signin", "sign-in", "authentication", "auth"},
    {"notification", "notifications", "alert", "alerts", "notify",
     "reminder", "reminders"},
    {"calendar", "cal", "event", "events", "meeting", "meetings",
     "invite", "invites", "invitation", "appointment", "appointments"},
    {"email", "emails", "mail", "mails", "message", "messages", "inbox", "mailbox"},
    {"search", "searching", "find", "finding", "lookup",
     "filter", "filtering", "filters"},
    {"attachment", "attachments", "attach", "attaching"},
    {"compose", "composing", "draft", "drafts",
     "reply", "replying", "respond", "responding"},
    {"send", "sending", "sent", "deliver", "delivery"},
    {"load", "loading", "render", "rendering", "display", "displaying",
     "open", "opening", "launch", "launching", "startup"},
    {"slow", "sluggish", "lag", "laggy", "latency",
     "performance", "speed", "delay", "delayed", "delays"},
    {"layout", "alignment", "ui", "interface"},
    {"spam", "junk", "phishing", "block", "blocking", "blocked"},
    {"contact", "contacts", "directory", "people"},
    {"battery", "power", "drain", "draining"},
    {"delete", "deleting", "remove", "removing",
     "disappear", "disappearing", "missing", "lost", "gone", "vanish"},
    {"signature", "signatures"},
    {"swipe", "gesture", "gestures"},
    {"font", "fonts"},
    {"dark mode", "dark theme"},
]

# Build lookup: word -> set of all synonyms
_SYNONYM_MAP: dict[str, set[str]] = {}
for _group in _SYNONYM_GROUPS:
    for _word in _group:
        _SYNONYM_MAP[_word] = _group

# State priority for boosting
_STATE_BOOST = {
    "new": 0.10, "active": 0.10, "committed": 0.08,
    "in progress": 0.08, "resolved": 0.0,
    "closed": -0.05, "removed": -0.10,
}

MAX_RESULTS_PER_CLUSTER = 5
_MANUAL_LINKS_FILE = os.path.join(os.path.dirname(__file__), "manual_links.json")


def _load_manual_links() -> list[dict]:
    """Load manual links and prune expired entries (>retention_days old)."""
    if not os.path.exists(_MANUAL_LINKS_FILE):
        return []
    try:
        with open(_MANUAL_LINKS_FILE) as f:
            data = json.load(f)
    except (json.JSONDecodeError, IOError):
        return []

    retention = data.get("retention_days", 90)
    cutoff = datetime.now(timezone.utc) - timedelta(days=retention)
    original_count = len(data.get("links", []))

    # Prune expired entries
    active = []
    for link in data.get("links", []):
        try:
            linked_at = datetime.fromisoformat(link["linked_at"].replace("Z", "+00:00"))
            if linked_at >= cutoff:
                active.append(link)
        except (KeyError, ValueError):
            active.append(link)  # keep entries without valid dates

    # Write back if anything was pruned
    if len(active) < original_count:
        data["links"] = active
        try:
            with open(_MANUAL_LINKS_FILE, "w") as f:
                json.dump(data, f, indent=2)
                f.write("\n")
            print(f"  Manual links: pruned {original_count - len(active)} expired entries")
        except IOError:
            pass

    return active


def _get_manual_matches(
    cluster_topic: str, platform: str, links: list[dict],
) -> list[ADOMatch]:
    """Find manual links matching this cluster topic (fuzzy match)."""
    matches = []
    topic_lower = cluster_topic.lower()
    for link in links:
        if link.get("platform", "") != platform:
            continue
        link_topic = link.get("cluster_topic", "").lower()
        # Exact or high fuzzy match (topics may differ slightly between runs)
        ratio = SequenceMatcher(None, topic_lower, link_topic).ratio()
        if ratio >= 0.6:
            ado_id = link.get("ado_id", 0)
            if ado_id:
                matches.append(ADOMatch(
                    work_item_id=ado_id,
                    title=f"[Manual link by {link.get('linked_by', 'user')}]",
                    state="Linked",
                    url=f"{config.ADO_ORG_URL}/{config.ADO_PROJECT}/_workitems/edit/{ado_id}",
                    changed_date=None,
                ))
    return matches


def correlate_clusters(
    clusters: list[TopicCluster],
    platform: str = "",
    max_age_days: int = 90,
) -> list[TopicCluster]:
    """Search ADO for bugs matching each topic cluster.

    Merges manual links (from manual_links.json) with search results.
    Filters by: area path (platform), freshness (max_age_days).
    """
    # Load user-provided manual links (also prunes expired entries)
    manual_links = _load_manual_links()
    if manual_links:
        print(f"  Manual links: {len(manual_links)} active entries loaded")

    auth_mode = _get_auth_mode()
    if auth_mode == "none" and not manual_links:
        print("  [warn] ADO: no auth available (az login or SYSTEM_ACCESSTOKEN), skipping")
        return clusters
    if auth_mode != "none":
        print(f"  ADO auth: {auth_mode}")

    cutoff = datetime.now(timezone.utc) - timedelta(days=max_age_days)
    area_paths = config.ADO_AREA_PATHS.get(platform, [])

    for cluster in clusters:
        # Inject manual links first (pinned by user)
        pinned = _get_manual_matches(cluster.topic, platform, manual_links)
        pinned_ids = {m.work_item_id for m in pinned}

        keywords = _extract_keywords(cluster.topic, platform)
        if not keywords and not pinned:
            continue
        try:
            if auth_mode != "none" and keywords:
                matches = _search_bugs(keywords, area_paths)
                fresh = [m for m in matches if m.changed_date is None or m.changed_date >= cutoff]
                relevant = _rank_by_relevance(fresh, cluster.topic, cluster.summary)
                # Remove duplicates (don't repeat manually-linked bugs)
                relevant = [m for m in relevant if m.work_item_id not in pinned_ids]
            else:
                relevant = []

            # Manual links come first, then algorithm-found matches
            cluster.ado_matches = pinned + relevant
            total = len(cluster.ado_matches)
            manual_count = len(pinned)

            if total:
                parts = []
                if manual_count:
                    parts.append(f"{manual_count} pinned")
                if relevant:
                    parts.append(f"{len(relevant)} found")
                print(f"  ADO: '{cluster.topic}' -> {total} bugs ({', '.join(parts)})")
            elif matches if auth_mode != "none" else False:
                print(f"  ADO: '{cluster.topic}' -> 0 relevant")
        except Exception as e:
            # Still attach manual links even if search fails
            if pinned:
                cluster.ado_matches = pinned
                print(f"  ADO: '{cluster.topic}' -> {len(pinned)} pinned (search failed: {e})")
            else:
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
    """Extract meaningful keywords with synonym expansion for better ADO search."""
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

    platform_terms = {"ios": "ios", "mac": "macos", "android": "android"}
    prefix = platform_terms.get(platform, "")
    if prefix:
        keywords = [prefix] + keywords

    return " ".join(keywords[:6])


def _expand_with_synonyms(words: set[str]) -> set[str]:
    """Expand a set of words with their synonyms."""
    expanded = set(words)
    for w in words:
        if w in _SYNONYM_MAP:
            expanded |= {s for s in _SYNONYM_MAP[w] if " " not in s}
    return expanded


def _idf_weight(word: str, all_bug_titles: list[str]) -> float:
    """Inverse document frequency: rare words across bug titles score higher."""
    if not all_bug_titles:
        return 1.0
    doc_count = sum(1 for t in all_bug_titles if word in t.lower())
    if doc_count == 0:
        return 1.0
    return math.log(len(all_bug_titles) / doc_count) + 1.0


def _rank_by_relevance(
    matches: list[ADOMatch], topic: str, summary: str = "",
    min_score: float = 0.25,
) -> list[ADOMatch]:
    """Score ADO bugs using multi-signal relevance.

    Signals:
      1. Synonym-aware keyword overlap with topic (40%)
      2. Synonym-aware keyword overlap with summary (15%)
      3. Fuzzy string similarity (15%)
      4. State boost: Active/New > Resolved > Closed (20%)
      5. Recency boost: recently updated bugs score higher (10%)
    """
    stop = {
        "the", "a", "an", "is", "are", "was", "were", "in", "on", "at",
        "to", "for", "of", "with", "not", "and", "or", "but", "this", "that",
        "outlook", "app", "issue", "problem", "bug", "issues", "problems",
        "ios", "mac", "macos", "android", "mobile", "desktop", "re",
    }

    def _keywords(text: str) -> set[str]:
        return {w for w in re.findall(r'\b[a-z]{3,}\b', text.lower())} - stop

    topic_kw = _keywords(topic)
    summary_kw = _keywords(summary) if summary else set()

    # Expand with synonyms for matching
    topic_expanded = _expand_with_synonyms(topic_kw)
    summary_expanded = _expand_with_synonyms(summary_kw) if summary_kw else set()

    if not (topic_kw | summary_kw):
        return matches

    # Collect all bug titles for IDF calculation
    all_titles = [m.title for m in matches]
    now = datetime.now(timezone.utc)

    scored: list[tuple[float, ADOMatch]] = []
    for m in matches:
        title_kw = _keywords(m.title)
        if not title_kw:
            continue

        title_expanded = _expand_with_synonyms(title_kw)

        # Signal 1: Topic keyword overlap with synonym expansion (40%)
        direct_overlap = len(topic_kw & title_kw)
        synonym_overlap = len(topic_expanded & title_expanded) - direct_overlap
        # Synonym bonus only applies if there's at least 1 direct match
        if direct_overlap > 0:
            weighted_overlap = direct_overlap + (synonym_overlap * 0.4)
        else:
            weighted_overlap = synonym_overlap * 0.2  # weak signal without direct match
        topic_score = min(weighted_overlap / max(len(topic_kw), 1), 1.0)

        # Signal 2: Summary keyword overlap with synonyms (15%)
        if summary_kw:
            s_direct = len(summary_kw & title_kw)
            s_synonym = len(summary_expanded & title_expanded) - s_direct
            if s_direct > 0:
                s_weighted = s_direct + (s_synonym * 0.4)
            else:
                s_weighted = s_synonym * 0.2
            summary_score = min(s_weighted / max(len(summary_kw), 1), 1.0)
        else:
            summary_score = 0.0

        # Signal 3: Fuzzy string similarity (15%)
        fuzzy = SequenceMatcher(None, topic.lower(), m.title.lower()).ratio()

        # Signal 4: State boost (20%) — normalize to 0-1 range
        state_val = _STATE_BOOST.get(m.state.lower(), 0.0)
        state_score = (state_val + 0.10) / 0.20  # maps -0.10..+0.10 to 0..1

        # Signal 5: Recency boost (10%)
        if m.changed_date:
            age_days = (now - m.changed_date).days
            if age_days <= 14:
                recency_score = 1.0
            elif age_days <= 30:
                recency_score = 0.8
            elif age_days <= 60:
                recency_score = 0.5
            else:
                recency_score = 0.2
        else:
            recency_score = 0.3

        score = (
            topic_score * 0.40
            + summary_score * 0.15
            + fuzzy * 0.15
            + state_score * 0.20
            + recency_score * 0.10
        )

        # Content gate: require meaningful topic or summary relevance
        content_score = topic_score * 0.40 + summary_score * 0.15
        if content_score < 0.08:
            continue  # Skip bugs with no meaningful content match

        scored.append((score, m))

    scored.sort(key=lambda x: x[0], reverse=True)
    # Cap at top N and filter by min_score
    return [m for score, m in scored[:MAX_RESULTS_PER_CLUSTER] if score >= min_score]


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
