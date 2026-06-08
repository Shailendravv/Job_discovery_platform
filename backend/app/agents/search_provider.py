"""
SearchProvider — aggregates results from multiple sources:
1. MCP Search Server (SearXNG) - Only if SEARXNG_ENABLED is True
2. LinkedIn Guest API - Only if LINKEDIN_GUEST_API_ENABLED is True
"""

import asyncio
import json
import logging
import re
from typing import List, Dict, Any, Optional

import httpx

from app.agents.mcp_client import call_mcp_tool_async
from app.core.config import settings

log = logging.getLogger(__name__)


class SearchProvider:
    async def search(self, query: str, num_results: int | None = None, time_range: str | None = None) -> list[dict]:
        """Search across all configured sources and return merged results."""
        return await self._search_async(query, num_results, time_range)

    async def _search_async(self, query: str, num_results: int | None = None, time_range: str | None = None) -> list[dict]:
        """Async search across all configured sources and return merged results."""
        n = num_results if num_results is not None else settings.SEARCH_MAX_RESULTS
        all_results: List[Dict[str, Any]] = []

        # Create tasks for concurrent execution
        tasks = []

        # 1. Search via MCP server (SearXNG)
        if settings.SEARXNG_ENABLED:
            log.info("[provider] SEARXNG_ENABLED=%r", settings.SEARXNG_ENABLED)
            task = asyncio.create_task(
                self._search_mcp_async(query, n, time_range),
                name="searxng_search"
            )
            tasks.append(("searxng", task))

        # 2. LinkedIn Guest API
        if settings.LINKEDIN_GUEST_API_ENABLED:
            log.info("[provider] LINKEDIN_GUEST_API_ENABLED=%r", settings.LINKEDIN_GUEST_API_ENABLED)
            task = asyncio.create_task(
                self._search_linkedin_async(query, n),
                name="linkedin_search"
            )
            tasks.append(("linkedin", task))

        # Execute all searches concurrently and collect results
        if tasks:
            source_names = [name for name, _ in tasks]
            task_list = [task for _, task in tasks]
            settled = await asyncio.gather(*task_list, return_exceptions=True)
            for source_name, result in zip(source_names, settled):
                if isinstance(result, Exception):
                    log.error("[provider] %s search failed: %s", source_name.upper(), result, exc_info=True)
                else:
                    all_results.extend(result)
                    log.info("[provider] %s search returned %d results", source_name.upper(), len(result))

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

    async def _search_mcp_async(self, query: str, num_results: int, time_range: Optional[str]) -> List[Dict[str, Any]]:
        """Async search via existing MCP server (SearXNG)."""
        args: dict = {"query": query, "max_results": num_results}
        if time_range:
            args["time_range"] = time_range

        raw = await call_mcp_tool_async(settings.MCP_SEARCH_URL, "search_json", args)
        try:
            results = json.loads(raw)
            if isinstance(results, list):
                for result in results:
                    result["source"] = "searxng"
                return results
        except (json.JSONDecodeError, TypeError) as e:
            log.warning("[provider] failed to parse MCP search response: %s", e)
        return []

    async def _search_linkedin_async(self, query: str, num_results: int) -> List[Dict[str, Any]]:
        """Async search LinkedIn Guest API for job postings.
        Enhanced to fetch full job descriptions by visiting job URLs."""
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
            # Use httpx.AsyncClient for true async HTTP requests
            async with httpx.AsyncClient(timeout=15.0) as client:
                response = await client.get(api_url, params=params, headers=headers)
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

                    # Fetch full job description by visiting the job URL
                    description = ""
                    try:
                        job_response = await client.get(job_url, timeout=10.0, headers=headers)
                        if job_response.status_code == 200:
                            job_html = job_response.text
                            # Extract job description from LinkedIn job page
                            desc_match = None
                            patterns = [
                                r'<div[^>]*class="description__text[^>]*>([\s\S]*?)</div>',
                                r'<div[^>]*class="jobs-description[^>]*>([\s\S]*?)</div>',
                                r'<div[^>]*class="show-more-less-html__markup[^>]*>([\s\S]*?)</div>',
                                r'<div[^>]*id="job-details"[^>]*>([\s\S]*?)</div>',
                                r'<section[^>]*class="description"[^>]*>([\s\S]*?)</section>',
                            ]
                            for pattern in patterns:
                                desc_match = re.search(pattern, job_html, re.IGNORECASE)
                                if desc_match:
                                    break

                            if desc_match:
                                # Clean HTML tags and extra whitespace
                                desc_text = re.sub(r'<[^>]+>', ' ', desc_match.group(1))
                                desc_text = re.sub(r'\s+', ' ', desc_text).strip()
                                # Keep full description, do not truncate
                                description = desc_text
                            else:
                                # Fallback to snippet if description not found
                                snippet_parts = [p for p in [
                                    f"Title: {title}" if title else "",
                                    f"Company: {company}" if company else "",
                                    f"Location: {location}" if location else "",
                                ] if p]
                                description = " | ".join(snippet_parts)
                        else:
                            # Fallback to snippet if request failed
                            snippet_parts = [p for p in [
                                f"Title: {title}" if title else "",
                                f"Company: {company}" if company else "",
                                f"Location: {location}" if location else "",
                            ] if p]
                            description = " | ".join(snippet_parts)
                    except Exception as e:
                        log.warning("[linkedin] failed to fetch description for job %s: %s", job_id, e)
                        # Fallback to snippet
                        snippet_parts = [p for p in [
                            f"Title: {title}" if title else "",
                            f"Company: {company}" if company else "",
                            f"Location: {location}" if location else "",
                        ] if p]
                        description = " | ".join(snippet_parts)

                    results.append({
                        "title": title,
                        "url": job_url,
                        "content": description,
                        "source": "linkedin",
                    })

                log.info("[linkedin] parsed %d results from %d job_ids found", len(results), len(job_ids))
                return results
        except Exception as e:
            log.error("[linkedin] request failed: %s", e, exc_info=True)
            return []


# Module-level singleton
provider = SearchProvider()
