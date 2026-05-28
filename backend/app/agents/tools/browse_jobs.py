"""
Browse tool: wraps camofox browser (fetch + extract) for job page browsing.
- fetch(url)   → accessibility-tree snapshot (free-form)
- extract(url, schema) → structured JSON via local Ollama model
"""

import json
import logging
import time
import uuid
from typing import Optional

import httpx
import ollama

from app.core.config import settings

log = logging.getLogger(__name__)

SETTLE_SECONDS = 2
MAX_SNAPSHOT_CHARS = 40_000


def _open_tab(client: httpx.Client, user_id: str, url: str) -> str:
    r = client.post(
        f"{settings.CAMOFOX_URL}/tabs/open",
        json={"userId": user_id, "url": url},
        timeout=60.0,
    )
    r.raise_for_status()
    body = r.json()
    tab_id = body.get("tabId") or body.get("id")
    if not tab_id:
        raise RuntimeError(f"camofox returned no tabId: {body}")
    return tab_id


def _get_snapshot(client: httpx.Client, user_id: str, tab_id: str) -> str:
    r = client.get(
        f"{settings.CAMOFOX_URL}/tabs/{tab_id}/snapshot",
        params={"userId": user_id},
        timeout=30.0,
    )
    r.raise_for_status()
    ct = r.headers.get("content-type", "")
    if "application/json" in ct:
        data = r.json()
        return data.get("snapshot") or data.get("aria") or data.get("text") or str(data)
    return r.text


def _close_tab(client: httpx.Client, user_id: str, tab_id: str) -> None:
    try:
        client.delete(
            f"{settings.CAMOFOX_URL}/tabs/{tab_id}",
            params={"userId": user_id},
            timeout=10.0,
        )
    except Exception:
        pass


def _truncate(snapshot: str) -> str:
    if len(snapshot) <= MAX_SNAPSHOT_CHARS:
        return snapshot
    half = MAX_SNAPSHOT_CHARS // 2 - 100
    return snapshot[:half] + f"\n...[TRUNCATED]...\n" + snapshot[-half:]


def _fetch_snapshot(url: str) -> str:
    """Open url in camofox, return truncated snapshot."""
    user_id = f"oneshot-{uuid.uuid4().hex[:8]}"
    with httpx.Client() as client:
        tab_id = _open_tab(client, user_id, url)
        time.sleep(SETTLE_SECONDS)
        try:
            snapshot = _get_snapshot(client, user_id, tab_id)
        finally:
            _close_tab(client, user_id, tab_id)
    return _truncate(snapshot)


def browse_fetch(url: str) -> str:
    """Fetch a job page and return its accessibility-tree snapshot."""
    if not url.startswith(("http://", "https://")):
        return f"Error: URL must start with http:// or https://; got {url!r}"
    log.info("browse_fetch %s", url)
    try:
        return _fetch_snapshot(url)
    except Exception as e:
        log.warning("browse_fetch failed: %s", e)
        return f"Error: {e}"


def browse_extract(url: str, schema: dict, model_name: str = "llama3") -> str:
    """
    Fetch a job page and extract structured fields defined by `schema` (JSON Schema).
    Returns a JSON string. Fields not found are set to null.
    """
    if not url.startswith(("http://", "https://")):
        return f"Error: URL must start with http:// or https://; got {url!r}"
    log.info("browse_extract %s", url)
    try:
        snapshot = _fetch_snapshot(url)
    except Exception as e:
        return f"Error fetching page: {e}"

    prompt = (
        "You are a precise data extraction tool. Read the page snapshot below and "
        "return a JSON object matching the schema. Set missing fields to null. "
        "Respond with ONLY the JSON object, no markdown, no preamble.\n\n"
        f"SCHEMA:\n{json.dumps(schema, indent=2)}\n\n"
        f"PAGE SNAPSHOT (from {url}):\n{snapshot}"
    )
    try:
        resp = ollama.chat(
            model=model_name,
            messages=[{"role": "user", "content": prompt}],
            options={"temperature": 0.0},
            format="json",
            think=False,
        )
        raw = resp["message"]["content"]
        return json.dumps(json.loads(raw), indent=2)
    except json.JSONDecodeError:
        return raw
    except Exception as e:
        return f"Extraction failed: {e}"
