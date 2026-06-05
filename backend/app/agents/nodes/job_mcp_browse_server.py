"""
MCP server — exposes `fetch` and `extract` tools backed by Camofox browser.
Run standalone:  python -m app.agents.nodes.job_mcp_browse_server

Importable directly (Option B, zero subprocess overhead):
    from app.agents.nodes.job_mcp_browse_server import _do_fetch, _do_extract
"""

import json
import logging
import time
import uuid
import re

import httpx
from mcp.server.fastmcp import FastMCP

from app.core.config import settings
from app.core.llm import call_llm

log = logging.getLogger(__name__)

mcp = FastMCP("browser-server")

_SETTLE_SECONDS = settings.SETTLE_SECONDS
_MAX_SNAPSHOT_CHARS = settings.MAX_SNAPSHOT_CHARS

# How many chars of the snapshot to send to the LLM — keep low for small models.
_EXTRACT_SNAPSHOT_CHARS = getattr(settings, "EXTRACT_SNAPSHOT_CHARS", 3000)
_OLLAMA_TIMEOUT = getattr(settings, "OLLAMA_TIMEOUT", 120)

log.info(
    "[mcp:browse] module loaded — camofox=%s llm_provider=%s extract_chars=%d",
    settings.CAMOFOX_URL,
    getattr(settings, "LLM_PROVIDER", "ollama"),
    _EXTRACT_SNAPSHOT_CHARS,
)


# ── helpers ───────────────────────────────────────────────────────────────────


def _open_tab(client: httpx.Client, user_id: str, url: str) -> str:
    log.debug("[mcp:browse] opening tab user_id=%r url=%r", user_id, url)
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
    log.debug("[mcp:browse] tab opened tab_id=%r", tab_id)
    return tab_id


def _get_snapshot(client: httpx.Client, user_id: str, tab_id: str) -> str:
    log.debug("[mcp:browse] fetching snapshot tab_id=%r", tab_id)
    r = client.get(
        f"{settings.CAMOFOX_URL}/tabs/{tab_id}/snapshot",
        params={"userId": user_id},
        timeout=30.0,
    )
    r.raise_for_status()
    if "application/json" in r.headers.get("content-type", ""):
        data = r.json()
        snapshot = (
            data.get("snapshot") or data.get("aria") or data.get("text") or str(data)
        )
    else:
        snapshot = r.text
    log.debug("[mcp:browse] snapshot received %d chars", len(snapshot))
    return snapshot


def _close_tab(client: httpx.Client, user_id: str, tab_id: str) -> None:
    try:
        client.delete(
            f"{settings.CAMOFOX_URL}/tabs/{tab_id}",
            params={"userId": user_id},
            timeout=10.0,
        )
        log.debug("[mcp:browse] tab closed tab_id=%r", tab_id)
    except Exception as e:
        log.warning("[mcp:browse] failed to close tab tab_id=%r: %s", tab_id, e)


def _truncate(snapshot: str, max_chars: int | None = None) -> str:
    limit = max_chars if max_chars is not None else _MAX_SNAPSHOT_CHARS
    if len(snapshot) <= limit:
        return snapshot
    half = limit // 2 - 100
    head, tail = snapshot[:half], snapshot[-half:]
    dropped = len(snapshot) - len(head) - len(tail)
    log.debug(
        "[mcp:browse] snapshot truncated: kept %d+%d, dropped %d chars",
        len(head),
        len(tail),
        dropped,
    )
    return head + f"\n\n...[TRUNCATED {dropped} chars]...\n\n" + tail


def _parse_llm_json(raw: str) -> dict:
    """
    Robustly parse LLM output that may have:
    - Leading <think>...</think> blocks
    - Markdown code fences
    - Trailing garbage after the closing brace
    """
    raw = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL).strip()
    raw = re.sub(r"^```(?:json)?\s*", "", raw).strip()
    raw = re.sub(r"\s*```$", "", raw).strip()

    start = raw.find("{")
    if start == -1:
        raise ValueError(f"No JSON object found in LLM output: {raw[:200]!r}")

    depth = 0
    end = start
    for i, ch in enumerate(raw[start:], start):
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                end = i
                break

    return json.loads(raw[start : end + 1])


# ── core logic (importable directly — Option B) ───────────────────────────────


def _do_fetch(url: str, user_id: str = "") -> str:
    """Fetch a page via camofox and return its snapshot. Importable directly."""
    one_shot = not user_id
    if one_shot:
        user_id = f"oneshot-{uuid.uuid4().hex[:8]}"

    log.info("[mcp:browse] ── _do_fetch START url=%r user_id=%r", url, user_id)
    with httpx.Client() as client:
        try:
            tab_id = _open_tab(client, user_id, url)
        except Exception as e:
            log.warning("[mcp:browse] open tab failed: %s", e)
            return f"Error opening tab: {e}"

        log.debug("[mcp:browse] settling %.1fs before snapshot", _SETTLE_SECONDS)
        time.sleep(_SETTLE_SECONDS)

        try:
            snapshot = _get_snapshot(client, user_id, tab_id)
        except Exception as e:
            _close_tab(client, user_id, tab_id)
            log.warning("[mcp:browse] snapshot failed: %s", e)
            return f"Error fetching snapshot: {e}"

        if one_shot:
            _close_tab(client, user_id, tab_id)

    # Basic DOM Sanitization: compress empty lines
    snapshot = re.sub(r"\n\s*\n", "\n", snapshot)
    result = _truncate(snapshot)
    log.info("[mcp:browse] ── _do_fetch END url=%r final_chars=%d", url, len(result))
    return result


def _do_extract(url: str, schema: dict, user_id: str = "") -> str:
    """Fetch a page and extract structured JSON using LLM approach."""
    log.info(
        "[mcp:browse] ── _do_extract START url=%r fields=%s",
        url,
        list(schema.get("properties", {}).keys()),
    )

    snapshot = _do_fetch(url, user_id)
    if snapshot.startswith("Error"):
        log.warning("[mcp:browse] _do_extract aborting — fetch failed: %s", snapshot)
        return snapshot

    trimmed_snapshot = _truncate(snapshot, _EXTRACT_SNAPSHOT_CHARS)

    # ── REMOVED: Stage 1 classifier ─────────────────────────────
    # LinkedIn and other job sites often block headless browsers,
    # resulting in login walls or minimal content that fools the classifier.
    # Since we already know these are job URLs, skip classification
    # and let the extraction LLM handle empty/missing content naturally.

    fields = schema.get("properties", {})
    field_lines = "\n".join(
        f'  "{k}": {v.get("description", "")}' for k, v in fields.items()
    )

    extract_prompt = (
        "Extract job data from the page snapshot below. "
        "If the page is a login wall, anti-bot challenge, or missing job content, "
        "return a JSON object with all fields set to null. "
        "Otherwise, return ONLY a JSON object with these exact fields (use null for missing values):\n"
        f"{field_lines}\n\n"
        f"URL: {url}\n\n"
        f"Page content:\n{trimmed_snapshot}"
    )

    try:
        raw = call_llm(extract_prompt, json_format=True, timeout=_OLLAMA_TIMEOUT)
        parsed = _parse_llm_json(raw)
        return json.dumps(parsed, indent=2)
    except Exception as e:
        log.warning("[mcp:browse] Extraction failed: %s", e)
        return json.dumps({k: None for k in fields})


# ── MCP tools ─────────────────────────────────────────────────────────────────


@mcp.tool()
def fetch(url: str, user_id: str = "") -> str:
    """
    Fetch a webpage and return its accessibility-tree snapshot.
    """
    if not url.startswith(("http://", "https://")):
        return f"Error: URL must start with http:// or https://; got {url!r}"
    return _do_fetch(url, user_id)


@mcp.tool()
def extract(url: str, schema: dict, user_id: str = "") -> str:
    """
    Fetch a webpage and extract structured data matching a JSON Schema via LLM.
    """
    if not url.startswith(("http://", "https://")):
        return f"Error: URL must start with http:// or https://; got {url!r}"
    return _do_extract(url, schema, user_id)


if __name__ == "__main__":
    mcp.run()
