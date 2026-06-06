"""
SearchProvider — calls the search MCP server over HTTP (Option A).
"""

import json
import logging

from app.agents.mcp_client import call_mcp_tool
from app.core.config import settings

log = logging.getLogger(__name__)


class SearchProvider:
    def search(self, query: str, num_results: int | None = None, time_range: str | None = None) -> list[dict]:
        n = num_results if num_results is not None else settings.SEARCH_MAX_RESULTS
        log.debug("[provider] MCP search query=%r num_results=%d", query, n)

        args: dict = {"query": query, "max_results": n}
        if time_range:
            args["time_range"] = time_range

        raw = call_mcp_tool(settings.MCP_SEARCH_URL, "search_json", args)
        try:
            results = json.loads(raw)
            if isinstance(results, list):
                log.debug("[provider] got %d results", len(results))
                return results
        except (json.JSONDecodeError, TypeError) as e:
            log.warning("[provider] failed to parse MCP search response: %s", e)
        return []


# Module-level singleton
provider = SearchProvider()
