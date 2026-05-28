"""
Stage 5: Browser MCP server with `fetch` and `extract`
=======================================================
Adds a second tool, `extract`, that uses camofox's POST /tabs/{tabId}/extract
endpoint. The model passes a JSON Schema describing the fields it wants,
camofox runs the extraction server-side, and the model gets back
structured JSON instead of an unstructured snapshot.

This is faster, cheaper, and more reliable than asking the model to
extract fields from a raw snapshot — the work happens once on the
server, not in the model's head.

Prerequisites:
  - camofox-browser running locally (see ../stage1/)

Run with:
    mcp-browser-stage5

Probe with:
    python ../inspect_any.py mcp_browser_05.main
    python ../inspect_any.py mcp_browser_05.main fetch --kv url=https://example.com
"""

import json
import logging
import uuid
import time
import httpx
import ollama
from mcp.server.fastmcp import FastMCP

from mcp_browser_config import (
    CAMOFOX_URL,
    MAX_SNAPSHOT_CHARS,
    SETTLE_SECONDS,
    MODEL_NAME,
    MODEL_TEMPERATURE,
)

log = logging.getLogger(__name__)

mcp = FastMCP("browser-server")


def _open_tab(client: httpx.Client, user_id: str, url: str) -> str:
    r = client.post(
        f"{CAMOFOX_URL}/tabs/open",
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
        f"{CAMOFOX_URL}/tabs/{tab_id}/snapshot",
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
            f"{CAMOFOX_URL}/tabs/{tab_id}",
            params={"userId": user_id},
            timeout=10.0,
        )
    except Exception:
        pass


def _truncate(snapshot: str) -> str:
    if len(snapshot) <= MAX_SNAPSHOT_CHARS:
        return snapshot
    half = MAX_SNAPSHOT_CHARS // 2 - 100
    head = snapshot[:half]
    tail = snapshot[-half:]
    marker = f"\n\n...[TRUNCATED {len(snapshot) - len(head) - len(tail)} chars]...\n\n"
    return head + marker + tail


@mcp.tool()
def fetch(url: str, user_id: str = "") -> str:
    """
    Fetch a webpage and return its accessibility-tree snapshot.

    Use this tool to read or summarize the contents of a URL. The
    snapshot is an LLM-friendly representation of the page's structure
    (headings, paragraphs, links, forms) with element references like
    [e1], [e2].

    Args:
        url: The full URL to fetch (must include http:// or https://).
        user_id: Optional. If set, camofox reuses a browser context
            across calls (faster). Default opens a one-shot tab.

    Returns:
        The page's accessibility snapshot, possibly truncated.
    """
    if not url.startswith(("http://", "https://")):
        return f"Error: URL must start with http:// or https://; got {url!r}"

    log.info("fetch %s", url)

    one_shot = not user_id
    if one_shot:
        user_id = f"oneshot-{uuid.uuid4().hex[:8]}"

    with httpx.Client() as client:
        try:
            tab_id = _open_tab(client, user_id, url)
        except Exception as e:
            log.warning("opening tab failed: %s", e)
            return f"Error opening tab: {e}"

        time.sleep(SETTLE_SECONDS)

        try:
            snapshot = _get_snapshot(client, user_id, tab_id)
        except Exception as e:
            _close_tab(client, user_id, tab_id)
            log.warning("snapshot fetch failed: %s", e)
            return f"Error fetching snapshot: {e}"

        if one_shot:
            _close_tab(client, user_id, tab_id)

    log.debug("snapshot is %d chars (before truncation)", len(snapshot))
    return _truncate(snapshot)


@mcp.tool()
def extract(url: str, schema: dict, user_id: str = "") -> str:
    """
    Fetch a webpage and extract structured data from it according to a
    JSON Schema. The MCP server fetches the page, then asks a local
    Ollama model to populate the schema from the page contents. So the
    caller gets clean JSON back, without having to read or parse the
    snapshot itself.

    Use this tool when the user asks for specific fields that you can
    name in advance, especially on pages with structured content (WHOIS
    lookups, product pages, GitHub repos, recipes, tables of data).
    Arrays and nested objects are supported, since the work is done by
    an LLM and not by a constrained server-side extractor.

    Prefer `fetch` when the user asks an open-ended question or wants a
    free-form summary.

    Args:
        url: The full URL to extract from.
        schema: A JSON Schema describing the fields to extract. Property
            descriptions guide the extraction model in finding the right
            page content. Example:
                {
                    "type": "object",
                    "properties": {
                        "registrar": {"type": "string",
                                      "description": "Domain registrar name"},
                        "expiration_date": {"type": "string",
                                            "description": "Registrar Registration Expiration Date"},
                        "nameservers": {"type": "array",
                                        "items": {"type": "string"},
                                        "description": "Name Server entries"}
                    }
                }
        user_id: Optional, same semantics as for `fetch`.

    Returns:
        A JSON string with the extracted fields. If a field cannot be
        found, it is set to null.
    """
    if not url.startswith(("http://", "https://")):
        return f"Error: URL must start with http:// or https://; got {url!r}"

    one_shot = not user_id
    if one_shot:
        user_id = f"oneshot-{uuid.uuid4().hex[:8]}"

    # Step 1: fetch the page using the same path as the `fetch` tool.
    with httpx.Client() as client:
        try:
            tab_id = _open_tab(client, user_id, url)
        except Exception as e:
            return f"Error opening tab: {e}"

        time.sleep(SETTLE_SECONDS)

        try:
            snapshot = _get_snapshot(client, user_id, tab_id)
        except Exception as e:
            _close_tab(client, user_id, tab_id)
            return f"Error fetching snapshot: {e}"

        if one_shot:
            _close_tab(client, user_id, tab_id)

    snapshot = _truncate(snapshot)

    # Step 2: ask the model to populate the schema from the snapshot.
    # We use the same Ollama model the agent is using. The prompt is
    # strict: respond with JSON and only JSON, matching the schema.
    extraction_prompt = (
        "You are a precise data extraction tool. Read the page snapshot "
        "below and return a JSON object that matches the schema. Use the "
        "property descriptions to find the right values on the page. If a "
        "field is not present, set it to null. Do not invent values. Do "
        "not explain. Respond with ONLY the JSON object, no markdown, no "
        "preamble.\n\n"
        f"SCHEMA:\n{json.dumps(schema, indent=2)}\n\n"
        f"PAGE SNAPSHOT (from {url}):\n{snapshot}"
    )

    log.info(
        "extracting from %s with %d schema properties",
        url,
        len(schema.get("properties", {})),
    )
    try:
        resp = ollama.chat(
            model=MODEL_NAME,
            messages=[{"role": "user", "content": extraction_prompt}],
            options={"temperature": MODEL_TEMPERATURE},
            format="json",
            # think=False is hardcoded here, not pulled from config: even
            # when the user has thinking on for the agent's main loop, we
            # want it off for structured extraction, because thinking
            # interferes with format="json" output.
            think=False,
        )
        raw = resp["message"]["content"]
    except Exception as e:
        log.warning("extraction LLM call failed: %s", e)
        return f"Extraction failed: {type(e).__name__}: {e}"

    # The `format="json"` option asks Ollama to constrain output to
    # valid JSON. So in the happy path the response is already parseable.
    # We try to parse and re-serialize for clean formatting; if the model
    # produced something funky, return the raw text and let the caller
    # see it.
    try:
        parsed = json.loads(raw)
        return json.dumps(parsed, indent=2)
    except json.JSONDecodeError:
        return raw


def chat():
    mcp.run(transport="stdio")


if __name__ == "__main__":
    chat()
