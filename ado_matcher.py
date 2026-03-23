"""Semantic ADO ↔ Review Cluster matching — hybrid embeddings + LLM re-rank.

Pipeline:
  1. WIQL pre-filter: fetch ADO work items by platform area path + recency
  2. Embeddings: cosine similarity between cluster text and ADO item text
  3. LLM re-rank: GPT 5.4 re-ranks top candidates for nuanced matching

Uses the GitHub Copilot API (same auth as CopilotAnalyzer).

Auth modes (same as ado_search):
  - CI/CD: SYSTEM_ACCESSTOKEN env var → HTTP Basic
  - Local: `az rest` CLI (requires `az login`)
"""

from __future__ import annotations

import base64
import json
import math
import os
import subprocess
from datetime import datetime, timedelta, timezone

import requests as http_requests

import config
from models import TopicCluster, ADOMatch


# ── ADO Work Item fetch via WIQL ─────────────────────────────────────

def _get_auth_mode() -> str:
    if os.environ.get("SYSTEM_ACCESSTOKEN"):
        return "pat"
    try:
        r = subprocess.run(
            ["az", "account", "show"],
            capture_output=True, text=True, timeout=10,
        )
        if r.returncode == 0:
            return "az"
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass
    return "none"


def _ado_headers_pat() -> dict:
    pat = os.environ["SYSTEM_ACCESSTOKEN"]
    b64 = base64.b64encode(f":{pat}".encode()).decode()
    return {"Authorization": f"Basic {b64}", "Content-Type": "application/json"}


def _run_wiql(query: str, auth_mode: str) -> list[int]:
    """Execute a WIQL query and return work item IDs."""
    url = (
        f"{config.ADO_ORG_URL}/{config.ADO_PROJECT}"
        f"/_apis/wit/wiql?api-version=7.0&$top={config.MATCHER_WIQL_MAX_ITEMS}"
    )
    payload = {"query": query}

    if auth_mode == "pat":
        resp = http_requests.post(
            url, json=payload, headers=_ado_headers_pat(), timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
    else:
        body = json.dumps(payload)
        r = subprocess.run(
            ["az", "rest", "--method", "post", "--url", url,
             "--resource", config.ADO_RESOURCE_ID, "--body", body,
             "--headers", "Content-Type=application/json"],
            capture_output=True, text=True, timeout=30,
        )
        if r.returncode != 0:
            raise RuntimeError(f"WIQL query failed: {r.stderr[:200]}")
        data = json.loads(r.stdout)

    return [wi["id"] for wi in data.get("workItems", [])]


def _fetch_work_items(ids: list[int], auth_mode: str) -> list[dict]:
    """Batch-fetch work item details (title, description, state, etc.)."""
    if not ids:
        return []

    items = []
    # ADO batch API supports up to 200 IDs per request
    for i in range(0, len(ids), 200):
        batch_ids = ids[i:i + 200]
        ids_param = ",".join(str(x) for x in batch_ids)
        fields = (
            "System.Id,System.Title,System.Description,"
            "System.State,System.AssignedTo,System.ChangedDate,"
            "System.CreatedDate,System.WorkItemType,System.Tags"
        )
        url = (
            f"{config.ADO_ORG_URL}/{config.ADO_PROJECT}"
            f"/_apis/wit/workitems?ids={ids_param}&fields={fields}"
            f"&api-version=7.0"
        )

        if auth_mode == "pat":
            resp = http_requests.get(
                url, headers=_ado_headers_pat(), timeout=30,
            )
            resp.raise_for_status()
            data = resp.json()
        else:
            r = subprocess.run(
                ["az", "rest", "--method", "get", "--url", url,
                 "--resource", config.ADO_RESOURCE_ID],
                capture_output=True, text=True, timeout=30,
            )
            if r.returncode != 0:
                continue
            data = json.loads(r.stdout)

        for wi in data.get("value", []):
            f = wi.get("fields", {})
            assigned = f.get("System.AssignedTo", "")
            if isinstance(assigned, dict):
                assigned = assigned.get("displayName", "")
            items.append({
                "id": wi.get("id", 0),
                "title": f.get("System.Title", ""),
                "description": _strip_html(f.get("System.Description", "") or ""),
                "state": f.get("System.State", ""),
                "assigned_to": assigned,
                "changed_date": f.get("System.ChangedDate", ""),
                "tags": f.get("System.Tags", ""),
                "work_item_type": f.get("System.WorkItemType", ""),
            })
    return items


def _strip_html(text: str) -> str:
    """Remove HTML tags from ADO description fields."""
    import re
    clean = re.sub(r'<[^>]+>', ' ', text)
    return re.sub(r'\s+', ' ', clean).strip()


def _build_wiql(platform: str, days: int) -> str:
    """Build WIQL query filtered by platform area path and recency."""
    area_paths = config.ADO_AREA_PATHS.get(platform, [])
    area_clause = ""
    if area_paths:
        # Use the first area path with UNDER for hierarchy matching
        area_clause = f"AND [System.AreaPath] UNDER '{area_paths[0]}'"

    return f"""
    SELECT [System.Id]
    FROM WorkItems
    WHERE [System.WorkItemType] IN ('Bug', 'Task', 'User Story')
      {area_clause}
      AND [System.ChangedDate] >= @today - {days}
    ORDER BY [System.ChangedDate] DESC
    """


# ── Embeddings via GitHub Copilot / OpenAI API ───────────────────────

def _get_embeddings(texts: list[str]) -> list[list[float]]:
    """Get embeddings for a list of texts via the GitHub Models API."""
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_MODELS_TOKEN")
    if not token:
        raise RuntimeError("GITHUB_TOKEN or GH_MODELS_TOKEN required for embeddings")

    url = f"{config.COPILOT_BASE_URL}/embeddings"
    embeddings = []

    # Batch in groups of 100 (API limit)
    for i in range(0, len(texts), 100):
        batch = texts[i:i + 100]
        resp = http_requests.post(
            url,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
            json={
                "model": config.MATCHER_EMBEDDING_MODEL,
                "input": batch,
            },
            timeout=60,
        )
        resp.raise_for_status()
        data = resp.json()
        # Sort by index to maintain order
        sorted_data = sorted(data.get("data", []), key=lambda x: x.get("index", 0))
        embeddings.extend([item["embedding"] for item in sorted_data])

    return embeddings


def _cosine_similarity(vec_a: list[float], vec_b: list[float]) -> float:
    """Compute cosine similarity between two vectors."""
    dot = sum(a * b for a, b in zip(vec_a, vec_b))
    norm_a = math.sqrt(sum(a * a for a in vec_a))
    norm_b = math.sqrt(sum(b * b for b in vec_b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def _cosine_similarity_matrix(
    cluster_embeddings: list[list[float]],
    ado_embeddings: list[list[float]],
) -> list[list[float]]:
    """Compute cosine similarity matrix: (num_clusters, num_ado_items)."""
    matrix = []
    for c_emb in cluster_embeddings:
        row = [_cosine_similarity(c_emb, a_emb) for a_emb in ado_embeddings]
        matrix.append(row)
    return matrix


# ── Text representations for embedding ────────────────────────────────

def _ado_item_to_text(item: dict) -> str:
    """Build a text representation of an ADO work item for embedding."""
    parts = [item["title"]]
    desc = item.get("description", "")
    if desc:
        # Truncate long descriptions to keep embedding input manageable
        parts.append(desc[:500])
    tags = item.get("tags", "")
    if tags:
        parts.append(f"Tags: {tags}")
    return ". ".join(parts)


def _cluster_to_text(cluster: TopicCluster) -> str:
    """Build a text representation of a review cluster for embedding."""
    parts = [cluster.topic]
    if cluster.summary:
        parts.append(cluster.summary)
    # Include a few representative quotes for richer semantic signal
    for quote in cluster.quotes[:3]:
        parts.append(quote)
    return ". ".join(parts)


# ── LLM Re-ranking via GPT 5.4 ───────────────────────────────────────

def _llm_rerank(
    cluster: TopicCluster,
    candidates: list[dict],
    platform: str,
) -> list[dict]:
    """Use GPT 5.4 to re-rank the top embedding candidates for a cluster.

    Returns candidates sorted by LLM confidence with match rationale.
    """
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_MODELS_TOKEN")
    if not token:
        return candidates  # fall back to embedding order

    # Build compact candidate summaries for the LLM
    candidate_summaries = []
    for c in candidates:
        candidate_summaries.append({
            "id": c["id"],
            "title": c["title"],
            "description": (c.get("description", "") or "")[:300],
            "state": c["state"],
            "type": c.get("work_item_type", "Bug"),
        })

    system_prompt = f"""You are an expert at matching customer feedback issues to Azure DevOps work items for Microsoft Outlook on {platform}.

Given a review cluster (an issue pattern from user feedback) and a list of ADO work item candidates, determine which work items are genuinely addressing the same problem described in the cluster.

Return a JSON array of matches, ordered by confidence (best match first). Only include items that are a genuine match. For each match, include:
- "id": the work item ID
- "confidence": "high", "medium", or "low"
- "rationale": one sentence explaining why this matches

Return ONLY valid JSON array, no markdown fences."""

    cluster_info = {
        "topic": cluster.topic,
        "summary": cluster.summary,
        "severity": cluster.severity,
        "sample_quotes": cluster.quotes[:3],
        "review_count": cluster.count,
    }

    user_prompt = f"""## Review Cluster
{json.dumps(cluster_info, indent=2)}

## ADO Work Item Candidates
{json.dumps(candidate_summaries, indent=2)}

Return the matching work items as a JSON array, best match first. Only include genuine matches."""

    url = f"{config.COPILOT_BASE_URL}/responses"
    try:
        resp = http_requests.post(
            url,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
            json={
                "model": config.MATCHER_MODEL,
                "input": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                "max_output_tokens": config.MATCHER_MAX_TOKENS,
            },
            timeout=60,
        )
        resp.raise_for_status()
        data = resp.json()

        # Extract text from Responses API format
        text = ""
        for item in data.get("output", []):
            if item.get("type") == "message":
                for content in item.get("content", []):
                    if content.get("type") == "output_text":
                        text = content.get("text", "")
                        break

        if not text:
            return candidates

        # Parse the LLM response
        # Strip markdown fences if present
        text = text.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[1] if "\n" in text else text[3:]
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()

        matches = json.loads(text)
        if not isinstance(matches, list):
            return candidates

        # Rebuild candidate list in LLM-ranked order
        id_to_candidate = {c["id"]: c for c in candidates}
        reranked = []
        for match in matches:
            mid = match.get("id")
            if mid in id_to_candidate:
                candidate = id_to_candidate[mid]
                candidate["llm_confidence"] = match.get("confidence", "medium")
                candidate["llm_rationale"] = match.get("rationale", "")
                reranked.append(candidate)

        return reranked if reranked else candidates

    except Exception as e:
        print(f"    [warn] LLM re-rank failed: {e}, using embedding order")
        return candidates


# ── Main entry point ──────────────────────────────────────────────────

def match_clusters_semantic(
    clusters: list[TopicCluster],
    platform: str = "",
    max_age_days: int | None = None,
) -> list[TopicCluster]:
    """Semantic matching: Review Clusters → ADO Work Items.

    Pipeline:
      1. WIQL query to fetch ADO items (filtered by platform + recency)
      2. Embed clusters + ADO items, compute cosine similarity
      3. LLM re-ranks top-K candidates per cluster
      4. Attach final ADOMatch objects to clusters

    Args:
        clusters: TopicCluster objects from the analysis phase
        platform: "ios", "mac", or "android"
        max_age_days: recency filter for WIQL (default: MATCHER_WIQL_DAYS)

    Returns:
        Same clusters with ado_matches populated
    """
    if not clusters:
        return clusters

    days = max_age_days or config.MATCHER_WIQL_DAYS
    auth_mode = _get_auth_mode()

    if auth_mode == "none":
        print("  [warn] Semantic matcher: no ADO auth available, skipping")
        return clusters

    print(f"  Semantic matcher: auth={auth_mode}, platform={platform}, lookback={days}d")

    # ── Phase 1: WIQL pre-filter ──────────────────────────────────
    print("  Phase 1: Fetching ADO work items via WIQL...")
    wiql = _build_wiql(platform, days)
    try:
        item_ids = _run_wiql(wiql, auth_mode)
    except Exception as e:
        print(f"  [error] WIQL query failed: {e}")
        return clusters

    if not item_ids:
        print("  No ADO items found for this platform/period")
        return clusters

    print(f"  WIQL returned {len(item_ids)} work item IDs")

    try:
        ado_items = _fetch_work_items(item_ids, auth_mode)
    except Exception as e:
        print(f"  [error] Work item fetch failed: {e}")
        return clusters

    print(f"  Fetched {len(ado_items)} work items with details")

    if not ado_items:
        return clusters

    # ── Phase 2: Embedding + cosine similarity ────────────────────
    print("  Phase 2: Computing semantic embeddings...")
    try:
        ado_texts = [_ado_item_to_text(item) for item in ado_items]
        cluster_texts = [_cluster_to_text(c) for c in clusters]

        # Batch embed everything in one call
        all_texts = cluster_texts + ado_texts
        all_embeddings = _get_embeddings(all_texts)

        num_clusters = len(clusters)
        cluster_embeddings = all_embeddings[:num_clusters]
        ado_embeddings = all_embeddings[num_clusters:]

        print(f"  Embedded {num_clusters} clusters + {len(ado_items)} ADO items")

        # Compute similarity matrix
        sim_matrix = _cosine_similarity_matrix(cluster_embeddings, ado_embeddings)

    except Exception as e:
        print(f"  [error] Embedding failed: {e}")
        return clusters

    # ── Phase 3: LLM re-rank top candidates ───────────────────────
    threshold = config.MATCHER_SIMILARITY_THRESHOLD
    top_k_embed = config.MATCHER_TOP_K_CANDIDATES
    top_k_final = config.MATCHER_TOP_K_FINAL

    print(f"  Phase 3: LLM re-ranking (threshold={threshold}, top_k={top_k_embed})...")

    for i, cluster in enumerate(clusters):
        scores = sim_matrix[i]

        # Get top-K candidates above threshold
        scored = sorted(enumerate(scores), key=lambda x: x[1], reverse=True)
        candidates = []
        for j, score in scored[:top_k_embed]:
            if score >= threshold:
                candidate = dict(ado_items[j])
                candidate["embedding_score"] = score
                candidates.append(candidate)

        if not candidates:
            print(f"    '{cluster.topic}' -> 0 candidates above threshold")
            continue

        print(f"    '{cluster.topic}' -> {len(candidates)} candidates "
              f"(best={scored[0][1]:.3f})")

        # LLM re-rank the candidates
        reranked = _llm_rerank(cluster, candidates, platform)

        # Convert to ADOMatch objects (cap at top_k_final)
        matches = []
        for item in reranked[:top_k_final]:
            changed = None
            if item.get("changed_date"):
                try:
                    changed = datetime.fromisoformat(
                        item["changed_date"].replace("Z", "+00:00")
                    )
                except (ValueError, TypeError):
                    pass

            matches.append(ADOMatch(
                work_item_id=item["id"],
                title=item["title"],
                state=item["state"],
                assigned_to=item.get("assigned_to", ""),
                url=f"{config.ADO_ORG_URL}/{config.ADO_PROJECT}/_workitems/edit/{item['id']}",
                changed_date=changed,
            ))

        cluster.ado_matches = matches
        confidence = reranked[0].get("llm_confidence", "n/a") if reranked else "n/a"
        print(f"    -> {len(matches)} matched (top confidence: {confidence})")

    total = sum(len(c.ado_matches) for c in clusters)
    print(f"  Semantic matching complete: {total} total matches across {len(clusters)} clusters")
    return clusters
