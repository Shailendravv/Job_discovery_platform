"""
MCP server — exposes a `search` tool backed by SearXNG.
Run standalone:  python -m app.agents.nodes.job_mcp_server

The core logic lives in _do_search() so it can be imported directly
(Option B) without spinning up the MCP subprocess.
"""

import json
import logging

import httpx
from mcp.server.fastmcp import FastMCP

from app.core.config import settings

log = logging.getLogger(__name__)

mcp = FastMCP("search-server")


def _do_search(query: str, max_results: int | None = None, time_range: str | None = None) -> list[dict]:
    """Core SearXNG call — returns raw result dicts. Importable directly."""
    max_results = max_results if max_results is not None else settings.SEARCH_MAX_RESULTS
    log.info("[mcp:search] query=%r max_results=%d time_range=%r", query, max_results, time_range)
    try:
        params = {"q": query, "format": "json"}
        if time_range:
            params["time_range"] = time_range
            
        response = httpx.get(
            f"{settings.SEARXNG_URL}/search",
            params=params,
            timeout=10.0,
        )
        response.raise_for_status()
    except httpx.HTTPError as e:
        log.warning("[mcp:search] SearXNG request failed: %s", e)
        return []

    results = response.json().get("results", [])[:max_results]
    log.debug("[mcp:search] SearXNG returned %d raw results", len(results))
    for i, r in enumerate(results, 1):
        log.debug("[mcp:search] [%d] title=%r url=%s", i, r.get("title"), r.get("url"))
    log.info("[mcp:search] returning %d results", len(results))
    return results


@mcp.tool()
def search(query: str, max_results: int | None = None) -> str:
    """
    Search the web via a local SearXNG instance. Use this tool for any
    question that requires up-to-date or specific information such as
    job listings, company announcements, or current events.

    Returns the top results, each with a title, URL, and snippet.
    """
    results = _do_search(query, max_results)
    if not results:
        return f"No results found or SearXNG unreachable at {settings.SEARXNG_URL}."

    lines = [
        f"[{i}] {r.get('title', '(no title)')}\n    {r.get('url', '')}\n    {r.get('content', '')}"
        for i, r in enumerate(results, 1)
    ]
    return "\n\n".join(lines)


@mcp.tool()
def search_json(query: str, max_results: int | None = None, time_range: str | None = None) -> str:
    """
    Same as `search` but returns raw results as a JSON array string.
    Each item has: title, url, content.
    """
    results = _do_search(query, max_results, time_range)
    return json.dumps(results)


if __name__ == "__main__":
    mcp.run(transport="streamable-http", host="0.0.0.0", port=8001)
