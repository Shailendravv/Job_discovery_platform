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

import httpx
import ollama
from mcp.server.fastmcp import FastMCP

from app.core.config import settings

log = logging.getLogger(__name__)

mcp = FastMCP("browser-server")

_SETTLE_SECONDS = settings.SETTLE_SECONDS
_MAX_SNAPSHOT_CHARS = settings.MAX_SNAPSHOT_CHARS
_OLLAMA_MODEL = settings.MODEL_NAME
_OLLAMA_TEMPERATURE = settings.MODEL_TEMPERATURE
_OLLAMA_CLIENT = ollama.Client(host=settings.Ollama)

log.info(
    "[mcp:browse] module loaded — camofox=%s  ollama=%s  model=%s",
    settings.CAMOFOX_URL,
    settings.Ollama,
    _OLLAMA_MODEL,
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


def _truncate(snapshot: str) -> str:
    if len(snapshot) <= _MAX_SNAPSHOT_CHARS:
        return snapshot
    half = _MAX_SNAPSHOT_CHARS // 2 - 100
    head, tail = snapshot[:half], snapshot[-half:]
    dropped = len(snapshot) - len(head) - len(tail)
    log.debug(
        "[mcp:browse] snapshot truncated: kept %d+%d, dropped %d chars",
        len(head),
        len(tail),
        dropped,
    )
    return head + f"\n\n...[TRUNCATED {dropped} chars]...\n\n" + tail


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

    result = _truncate(snapshot)
    log.info("[mcp:browse] ── _do_fetch END url=%r final_chars=%d", url, len(result))
    return result


def _do_extract(url: str, schema: dict, user_id: str = "") -> str:
    """Fetch a page and extract structured JSON via Ollama. Importable directly."""
    log.info(
        "[mcp:browse] ── _do_extract START url=%r fields=%s",
        url,
        list(schema.get("properties", {}).keys()),
    )

    snapshot = _do_fetch(url, user_id)
    if snapshot.startswith("Error"):
        log.warning("[mcp:browse] _do_extract aborting — fetch failed: %s", snapshot)
        return snapshot

    prompt = (
        "You are a precise data extraction tool. Read the page snapshot "
        "below and return a JSON object matching the schema. Use property "
        "descriptions to find the right values. Set missing fields to null. "
        "Do not invent values. Respond with ONLY the JSON object.\n\n"
        f"SCHEMA:\n{json.dumps(schema, indent=2)}\n\n"
        f"PAGE SNAPSHOT (from {url}):\n{snapshot}"
    )

    log.info(
        "[mcp:browse] calling Ollama model=%r host=%s", _OLLAMA_MODEL, settings.Ollama
    )
    try:
        resp = _OLLAMA_CLIENT.chat(
            model=_OLLAMA_MODEL,
            messages=[{"role": "user", "content": prompt}],
            options={"temperature": _OLLAMA_TEMPERATURE},
            format="json",
            think=False,
        )
        raw = resp["message"]["content"]
        log.debug("[mcp:browse] Ollama raw response length=%d", len(raw))
    except Exception as e:
        log.warning("[mcp:browse] Ollama call failed: %s", e)
        return f"Extraction failed: {type(e).__name__}: {e}"

    try:
        parsed = json.loads(raw)
        log.info(
            "[mcp:browse] ── _do_extract END url=%r extracted_keys=%s",
            url,
            list(parsed.keys()),
        )
        return json.dumps(parsed, indent=2)
    except json.JSONDecodeError:
        log.warning("[mcp:browse] Ollama response was not valid JSON, returning raw")
        return raw


# ── MCP tools ─────────────────────────────────────────────────────────────────


@mcp.tool()
def fetch(url: str, user_id: str = "") -> str:
    """
    Fetch a webpage and return its accessibility-tree snapshot.

    Args:
        url: Full URL (must start with http:// or https://).
        user_id: Optional session ID; reuses browser context across calls.
    """
    if not url.startswith(("http://", "https://")):
        return f"Error: URL must start with http:// or https://; got {url!r}"
    log.info("[mcp:browse] tool:fetch called url=%r", url)
    return _do_fetch(url, user_id)


@mcp.tool()
def extract(url: str, schema: dict, user_id: str = "") -> str:
    """
    Fetch a webpage and extract structured data matching a JSON Schema via Ollama.

    Args:
        url: Full URL to extract from.
        schema: JSON Schema with properties describing the fields to extract.
        user_id: Optional, same semantics as `fetch`.

    Returns:
        JSON string with extracted fields; missing fields are null.
    """
    if not url.startswith(("http://", "https://")):
        return f"Error: URL must start with http:// or https://; got {url!r}"
    log.info("[mcp:browse] tool:extract called url=%r", url)
    return _do_extract(url, schema, user_id)


if __name__ == "__main__":
    mcp.run()
