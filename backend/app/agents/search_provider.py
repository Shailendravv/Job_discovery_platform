"""
SearchProvider — aggregates results from multiple sources:
1. MCP Search Server (SearXNG)
2. LinkedIn Guest API
3. JSearch API (OpenWebNinja)
"""

import json
import logging
import time
from typing import List, Dict, Any, Optional

import httpx

from app.agents.mcp_client import call_mcp_tool
from app.core.config import settings

log = logging.getLogger(__name__)


class SearchProvider:
    def search(self, query: str, num_results: int | None = None, time_range: str | None = None) -> list[dict]:
        """Search across all configured sources and return merged results."""
        n = num_results if num_results is not None else settings.SEARCH_MAX_RESULTS
        log.debug("[provider] Starting multi-source search: query=%r num_results=%d", query, n)

        all_results: List[Dict[str, Any]] = []

        # 1. Search via MCP server (SearXNG)
        try:
            mcp_results = self._search_mcp(query, n, time_range)
            all_results.extend(mcp_results)
            log.debug("[provider] MCP search returned %d results", len(mcp_results))
        except Exception as e:
            log.warning("[provider] MCP search failed: %s", e)

        # 2. Search LinkedIn Guest API (if enabled)
        if getattr(settings, "LINKEDIN_GUEST_API_ENABLED", True):
            try:
                linkedin_results = self._search_linkedin(query, n)
                all_results.extend(linkedin_results)
                log.debug("[provider] LinkedIn search returned %d results", len(linkedin_results))
            except Exception as e:
                log.warning("[provider] LinkedIn search failed: %s", e)

        # 3. Search JSearch API (if API key configured)
        if getattr(settings, "JSEARCH_API_KEY", None):
            try:
                jsearch_results = self._search_jsearch(query, n)
                all_results.extend(jsearch_results)
                log.debug("[provider] JSearch returned %d results", len(jsearch_results))
            except Exception as e:
                log.warning("[provider] JSearch failed: %s", e)

        # Deduplicate by URL (keeping first occurrence)
        seen_urls = set()
        deduped_results = []
        for result in all_results:
            url = result.get("url", "")
            if url and url not in seen_urls:
                seen_urls.add(url)
                deduped_results.append(result)

        log.debug("[provider] Total unique results after dedup: %d", len(deduped_results))
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
                return results
        except (json.JSONDecodeError, TypeError) as e:
            log.warning("[provider] failed to parse MCP search response: %s", e)
        return []

    def _search_linkedin(self, query: str, num_results: int) -> List[Dict[str, Any]]:
        """Search LinkedIn Guest API for job postings."""
        # LinkedIn Guest API endpoint (public, no auth required but may need headers)
        url = "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"

        # Prepare parameters
        params = {
            "keywords": query,
            "location": "India",  # Default, could be made configurable
            "f_TPR": "r86400",    # Past 24 hours
            "start": "0"
        }

        # LinkedIn may block without proper headers
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
            "Accept": "application/json",
        }

        try:
            response = httpx.get(url, params=params, headers=headers, timeout=15.0)
            response.raise_for_status()
            data = response.json()

            results = []
            # LinkedIn Guest API returns jobs in "elements" array
            for item in data.get("elements", [])[:num_results]:
                # Normalize to our expected format: title, url, content
                title = item.get("jobTitle", "")
                company = item.get("companyName", "")
                location = item.get("location", "")
                # Construct LinkedIn job URL (approximate)
                job_id = item.get("jobId", "")
                url = f"https://www.linkedin.com/jobs/view/{job_id}/" if job_id else ""
                # Create snippet from available fields
                snippet_parts = []
                if title:
                    snippet_parts.append(f"Title: {title}")
                if company:
                    snippet_parts.append(f"Company: {company}")
                if location:
                    snippet_parts.append(f"Location: {location}")
                snippet = " | ".join(snippet_parts)

                results.append({
                    "title": title,
                    "url": url,
                    "content": snippet
                })

            return results
        except Exception as e:
            log.warning("[provider] LinkedIn API request failed: %s", e)
            return []

    def _search_jsearch(self, query: str, num_results: int) -> List[Dict[str, Any]]:
        """Search JSearch API (OpenWebNinja) for job postings."""
        # JSearch API endpoint (requires API key)
        # Based on OpenWebNinja docs, this is a common pattern
        url = "https://jsearch.p.rapidapi.com/search"  # Alternative: check settings for custom URL

        # Use API key from settings
        api_key = getattr(settings, "JSEARCH_API_KEY", None)
        api_host = getattr(settings, "JSEARCH_API_HOST", "jsearch.p.rapidapi.com")

        # If we have a custom URL from settings, use it
        custom_url = getattr(settings, "JSEARCH_API_URL", None)
        if custom_url:
            url = custom_url

        headers = {
            "X-RapidAPI-Key": api_key,
            "X-RapidAPI-Host": api_host,
        }

        params = {
            "query": query,
            "location": "India",  # Could be made configurable
            "page": "1",
            "num_pages": "1",
            "date_posted": "today"  # Equivalent to f_TPR=r86400
        }

        try:
            response = httpx.get(url, headers=headers, params=params, timeout=15.0)
            response.raise_for_status()
            data = response.json()

            results = []
            # JSearch API typically returns jobs in "data" array
            for item in data.get("data", [])[:num_results]:
                # Normalize to our expected format
                title = item.get("job_title", "")
                company = item.get("employer_name", "")
                location = item.get("job_city", "") or item.get("job_state", "") or item.get("job_country", "")
                url = item.get("job_apply_link", "") or item.get("job_link", "")
                # Use job description or highlights as snippet
                description = item.get("job_description", "")
                highlights = item.get("job_highlights", [])
                snippet_parts = []
                if title:
                    snippet_parts.append(f"Title: {title}")
                if company:
                    snippet_parts.append(f"Company: {company}")
                if location:
                    snippet_parts.append(f"Location: {location}")
                if description:
                    # Truncate description to reasonable length
                    desc_preview = description[:200] + "..." if len(description) > 200 else description
                    snippet_parts.append(f"Description: {desc_preview}")
                if highlights and isinstance(highlights, list):
                    # Take first few highlights
                    highlight_text = " | ".join(str(h) for h in highlights[:3] if h)
                    if highlight_text:
                        snippet_parts.append(f"Highlights: {highlight_text}")
                snippet = " | ".join(snippet_parts)

                results.append({
                    "title": title,
                    "url": url,
                    "content": snippet
                })

            return results
        except Exception as e:
            log.warning("[provider] JSearch API request failed: %s", e)
            return []


# Module-level singleton
provider = SearchProvider()
