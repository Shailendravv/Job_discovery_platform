"""
Unified MCP server for job search and browsing.

Exposes three tools:
  - search(query, max_results)  → SearXNG web search
  - fetch(url)                  → camofox accessibility-tree snapshot
  - extract(url, schema)        → camofox + Ollama structured extraction

Run with:
    python -m app.agents.nodes.job_mcp_server

Or register as an MCP entry point in pyproject.toml.
"""

import json
import logging
import time
import uuid

import httpx
import ollama
from mcp.server.fastmcp import FastMCP

from app.core.config import settings
from app.agents.tools.skill_extraction import extract_skills_from_text

log = logging.getLogger(__name__)

SETTLE_SECONDS = 2
MAX_SNAPSHOT_CHARS = 40_000

mcp = FastMCP("job-server")


# ── helpers ──────────────────────────────────────────────────────────────────

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


def _truncate(text: str) -> str:
    if len(text) <= MAX_SNAPSHOT_CHARS:
        return text
    half = MAX_SNAPSHOT_CHARS // 2 - 100
    return text[:half] + "\n...[TRUNCATED]...\n" + text[-half:]


def _fetch_page(url: str) -> str:
    user_id = f"oneshot-{uuid.uuid4().hex[:8]}"
    with httpx.Client() as client:
        tab_id = _open_tab(client, user_id, url)
        time.sleep(SETTLE_SECONDS)
        try:
            snapshot = _get_snapshot(client, user_id, tab_id)
        finally:
            _close_tab(client, user_id, tab_id)
    return _truncate(snapshot)


# ── MCP tools ─────────────────────────────────────────────────────────────────

@mcp.tool()
def search(query: str, max_results: int = 5) -> str:
    """
    Search for jobs via local SearXNG. Returns top results with title, URL, snippet,
    and detected skill keywords.
    """
    log.info("search %r (max %d)", query, max_results)
    try:
        r = httpx.get(
            f"{settings.SEARXNG_URL}/search",
            params={"q": query, "format": "json"},
            timeout=10.0,
        )
        r.raise_for_status()
    except httpx.HTTPError as e:
        return f"Search failed: {e}"

    results = r.json().get("results", [])[:max_results]
    if not results:
        return "No results found."

    lines = []
    for i, res in enumerate(results, 1):
        snippet = res.get("content", "")
        skills = extract_skills_from_text(snippet)
        lines.append(
            f"[{i}] {res.get('title', '')}\n"
            f"    {res.get('url', '')}\n"
            f"    {snippet}\n"
            f"    Skills: {', '.join(skills) if skills else 'none detected'}"
        )
    return "\n\n".join(lines)


@mcp.tool()
def fetch(url: str) -> str:
    """
    Open a job page in camofox and return its accessibility-tree snapshot.
    Use for free-form reading or summarization of a URL.
    """
    if not url.startswith(("http://", "https://")):
        return f"Error: URL must start with http:// or https://; got {url!r}"
    log.info("fetch %s", url)
    try:
        return _fetch_page(url)
    except Exception as e:
        return f"Error: {e}"


@mcp.tool()
def extract(url: str, schema: dict) -> str:
    """
    Open a job page in camofox and extract structured fields defined by a JSON Schema.
    Use when you need specific named fields (title, company, salary, skills, etc.).
    Returns a JSON string; missing fields are null.

    Example schema:
        {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "Job title"},
                "company": {"type": "string", "description": "Hiring company"},
                "salary": {"type": "string", "description": "Salary or compensation range"},
                "skills": {"type": "array", "items": {"type": "string"},
                           "description": "Required skills listed in the job posting"}
            }
        }
    """
    if not url.startswith(("http://", "https://")):
        return f"Error: URL must start with http:// or https://; got {url!r}"
    log.info("extract %s", url)
    try:
        snapshot = _fetch_page(url)
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
            model="llama3",
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


def main():
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
