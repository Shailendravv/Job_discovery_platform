"""
SearchProvider — abstraction over the search backend.

Today (Option B): calls _do_search() directly (same process, zero overhead).
Later (Option A): swap the body of search() to an MCP client call — callers unchanged.
"""

import logging
from app.agents.nodes.job_mcp_server import _do_search
from app.core.config import settings

log = logging.getLogger(__name__)


class SearchProvider:
    def search(self, query: str, num_results: int | None = None, time_range: str | None = None) -> list[dict]:
        n = num_results if num_results is not None else settings.SEARCH_MAX_RESULTS
        log.debug("[provider] search query=%r num_results=%d", query, n)
        results = _do_search(query, max_results=n, time_range=time_range)
        log.debug("[provider] got %d results", len(results))
        return results


# Module-level singleton — import and use directly
provider = SearchProvider()
