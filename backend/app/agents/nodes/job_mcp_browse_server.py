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
import threading
from mcp.server.fastmcp import FastMCP

from app.core.config import settings

log = logging.getLogger(__name__)

mcp = FastMCP("browser-server")

_SETTLE_SECONDS = settings.SETTLE_SECONDS
_MAX_SNAPSHOT_CHARS = settings.MAX_SNAPSHOT_CHARS
_OLLAMA_MODEL = settings.MODEL_NAME
_OLLAMA_TEMPERATURE = settings.MODEL_TEMPERATURE
_OLLAMA_CLIENT = ollama.Client(host=settings.Ollama)

# How many chars of the snapshot to send to Ollama — keep low for small models.
# qwen3:2b context window is ~32k tokens; 3000 chars ≈ 750 tokens, safe budget.
_EXTRACT_SNAPSHOT_CHARS = getattr(settings, "EXTRACT_SNAPSHOT_CHARS", 3000)

# Seconds to wait for Ollama to respond before giving up.
_OLLAMA_TIMEOUT = getattr(settings, "OLLAMA_TIMEOUT", 120)

log.info(
    "[mcp:browse] module loaded — camofox=%s  ollama=%s  model=%s  extract_chars=%d  timeout=%ds",
    settings.CAMOFOX_URL,
    settings.Ollama,
    _OLLAMA_MODEL,
    _EXTRACT_SNAPSHOT_CHARS,
    _OLLAMA_TIMEOUT,
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


def _call_ollama(prompt: str, timeout: int = _OLLAMA_TIMEOUT) -> str:
    """
    Call Ollama with a hard wall-clock timeout.
    Raises RuntimeError if the model doesn't respond in time.
    """
    result: dict = {}
    exc_box: list = []

    def _worker():
        try:
            resp = _OLLAMA_CLIENT.chat(
                model=_OLLAMA_MODEL,
                messages=[{"role": "user", "content": prompt}],
                options={
                    "temperature": _OLLAMA_TEMPERATURE,
                    "num_predict": 512,  # cap output tokens — prevents infinite generation
                },
                format="json",
                think=False,
            )
            result["content"] = resp["message"]["content"]
        except Exception as e:
            exc_box.append(e)

    t = threading.Thread(target=_worker, daemon=True)
    t.start()
    t.join(timeout)

    if t.is_alive():
        raise RuntimeError(
            f"Ollama did not respond within {timeout}s — "
            "model may be too slow or context too large. "
            "Try a faster model or reduce EXTRACT_SNAPSHOT_CHARS."
        )
    if exc_box:
        raise exc_box[0]
    return result.get("content", "")


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


def _build_extract_prompt(schema: dict, url: str, snapshot: str) -> str:
    """
    Build a tight extraction prompt.

    Key changes vs the original:
    - Schema is inlined as a flat field list (not full JSON Schema) — saves tokens.
    - Snapshot is trimmed to _EXTRACT_SNAPSHOT_CHARS — prevents context overflow.
    - Instruction is much shorter — small models do better with concise instructions.
    """
    # Convert schema properties into a compact one-line-per-field description.
    fields = schema.get("properties", {})
    field_lines = "\n".join(
        f'  "{k}": {v.get("description", "")}' for k, v in fields.items()
    )

    trimmed_snapshot = _truncate(snapshot, _EXTRACT_SNAPSHOT_CHARS)

    return (
        "Extract job data from the page snapshot below. "
        "Return ONLY a JSON object with these fields (use null for missing values):\n"
        f"{field_lines}\n\n"
        f"Page ({url}):\n{trimmed_snapshot}"
    )


def _parse_ollama_json(raw: str) -> dict:
    """
    Robustly parse Ollama output that may have:
    - Leading <think>...</think> blocks (even with think=False on some models)
    - Markdown code fences
    - Trailing garbage after the closing brace
    """
    # Strip <think> blocks
    import re

    raw = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL).strip()

    # Strip markdown fences
    raw = re.sub(r"^```(?:json)?\s*", "", raw).strip()
    raw = re.sub(r"\s*```$", "", raw).strip()

    # Find the first complete JSON object
    start = raw.find("{")
    if start == -1:
        raise ValueError(f"No JSON object found in Ollama output: {raw[:200]!r}")

    # Walk to find the matching closing brace
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

    prompt = _build_extract_prompt(schema, url, snapshot)
    log.info(
        "[mcp:browse] calling Ollama model=%r host=%s prompt_chars=%d timeout=%ds",
        _OLLAMA_MODEL,
        settings.Ollama,
        len(prompt),
        _OLLAMA_TIMEOUT,
    )

    try:
        raw = _call_ollama(prompt, timeout=_OLLAMA_TIMEOUT)
        log.debug("[mcp:browse] Ollama raw response length=%d", len(raw))
    except RuntimeError as e:
        # Timeout — return empty result so the workflow falls back to snippet
        log.warning("[mcp:browse] Ollama timeout: %s", e)
        return json.dumps({k: None for k in schema.get("properties", {})})
    except Exception as e:
        log.warning("[mcp:browse] Ollama call failed: %s", e)
        return f"Extraction failed: {type(e).__name__}: {e}"

    try:
        parsed = _parse_ollama_json(raw)
        log.info(
            "[mcp:browse] ── _do_extract END url=%r extracted_keys=%s",
            url,
            list(parsed.keys()),
        )
        return json.dumps(parsed, indent=2)
    except (ValueError, json.JSONDecodeError) as e:
        log.warning(
            "[mcp:browse] JSON parse failed (%s), returning empty result. raw=%r",
            e,
            raw[:300],
        )
        # Return null-filled result so the workflow can continue with snippet fallback
        return json.dumps({k: None for k in schema.get("properties", {})})


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
