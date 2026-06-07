"""
SearchProvider — aggregates results from multiple sources:
1. MCP Search Server (SearXNG) - Only if SEARXNG_ENABLED is True
2. LinkedIn Guest API - Only if LINKEDIN_GUEST_API_ENABLED is True
"""

import json
import logging
import re
from typing import List, Dict, Any, Optional

import httpx

from app.agents.mcp_client import call_mcp_tool
from app.core.config import settings

log = logging.getLogger(__name__)


class SearchProvider:
    def search(self, query: str, num_results: int | None = None, time_range: str | None = None) -> list[dict]:
        """Search across all configured sources and return merged results."""
        n = num_results if num_results is not None else settings.SEARCH_MAX_RESULTS
        all_results: List[Dict[str, Any]] = []

        # 1. Search via MCP server (SearXNG)
        log.info("[provider] SEARXNG_ENABLED=%r", settings.SEARXNG_ENABLED)
        if settings.SEARXNG_ENABLED:
            try:
                mcp_results = self._search_mcp(query, n, time_range)
                all_results.extend(mcp_results)
                log.info("[provider] MCP search returned %d results", len(mcp_results))
            except Exception as e:
                log.error("[provider] MCP search failed: %s", e, exc_info=True)

        # 2. LinkedIn Guest API
        log.info("[provider] LINKEDIN_GUEST_API_ENABLED=%r", settings.LINKEDIN_GUEST_API_ENABLED)
        if settings.LINKEDIN_GUEST_API_ENABLED:
            try:
                linkedin_results = self._search_linkedin(query, n)
                all_results.extend(linkedin_results)
                log.info("[provider] LinkedIn search returned %d results", len(linkedin_results))
            except Exception as e:
                log.error("[provider] LinkedIn search failed: %s", e, exc_info=True)

        # Deduplicate by URL
        seen_urls = set()
        deduped_results = []
        for result in all_results:
            url = result.get("url", "")
            if url and url not in seen_urls:
                seen_urls.add(url)
                deduped_results.append(result)

        log.info("[provider] Total unique results after dedup: %d", len(deduped_results))
        return deduped_results

    def _search_mcp(self, query: str, num_results: int, time_range: Optional[str]) -> List[Dict[str, Any]]:
        """Search via existing MCP server (SearXNG)."""
        args: dict = {"query": query, "max_results": num_results}
        if time_range:
            args["time_range"] = time_range

        raw = call_mcp_tool(settings.MCP_SEARCH_URL, "search_json", args)
        try:
            results = json.loads(raw)
            if isinstance(results, list):
                for result in results:
                    result["source"] = "searxng"
                return results
        except (json.JSONDecodeError, TypeError) as e:
            log.warning("[provider] failed to parse MCP search response: %s", e)
        return []

    def _search_linkedin(self, query: str, num_results: int) -> List[Dict[str, Any]]:
        """Search LinkedIn Guest API for job postings.
        The endpoint returns HTML job cards — parsed with regex."""
        api_url = "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"
        # Strip site: operators from query
        clean_query = re.sub(r'site:\S+', '', query).strip()
        params = {
            "keywords": clean_query,
            "location": settings.LINKEDIN_GUEST_API_LOCATION,
            "f_TPR": settings.LINKEDIN_GUEST_API_TIME_RANGE,
            "start": "0",
            "count": str(num_results),
        }
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.5",
        }
        try:
            response = httpx.get(api_url, params=params, headers=headers, timeout=15.0)
            log.info("[linkedin] status_code=%d", response.status_code)
            response.raise_for_status()
            html = response.text

            job_ids = re.findall(r'data-entity-urn="urn:li:jobPosting:(\d+)"', html)
            titles = re.findall(r'class="base-search-card__title"[^>]*>\s*([^<]+?)\s*</h3>', html)
            companies = re.findall(r'class="base-search-card__subtitle"[^>]*>.*?<a[^>]*>\s*([^<]+?)\s*</a>', html, re.DOTALL)
            locations = re.findall(r'class="job-search-card__location"[^>]*>\s*([^<]+?)\s*</span>', html)

            results = []
            for i, job_id in enumerate(job_ids[:num_results]):
                title = titles[i].strip() if i < len(titles) else ""
                company = companies[i].strip() if i < len(companies) else ""
                location = locations[i].strip() if i < len(locations) else ""
                job_url = f"https://www.linkedin.com/jobs/view/{job_id}/"
                snippet_parts = [p for p in [
                    f"Title: {title}" if title else "",
                    f"Company: {company}" if company else "",
                    f"Location: {location}" if location else "",
                ] if p]
                results.append({
                    "title": title,
                    "url": job_url,
                    "content": " | ".join(snippet_parts),
                    "source": "linkedin",
                })

            log.info("[linkedin] parsed %d results from %d job_ids found", len(results), len(job_ids))
            return results
        except Exception as e:
            log.error("[linkedin] request failed: %s", e, exc_info=True)
            return []


# Module-level singleton
provider = SearchProvider()
