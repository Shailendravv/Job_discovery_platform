# Backend Job Search & MCP Workflow Reconstruction Guide (June 8, 2026)

This document provides a complete, self-contained implementation guide for the backend job search workflow and Model Context Protocol (MCP) servers.
Any developer or AI agent starting with zero context will be able to reconstruct the entire service and run it successfully using this guide.

> **Changelog from June 6, 2026:**
> - `app/agents/search_provider.py` — **Fully async + LinkedIn scope bug fixed.** All methods converted to `async` with `asyncio.create_task` for true concurrent SearXNG + LinkedIn execution. Fixed critical client scoping bug: the `for` loop processing LinkedIn results was previously OUTSIDE the `async with httpx.AsyncClient()` block, so `client` was always closed when attempting to fetch individual job description pages. Now correctly placed inside the block. Added 5 regex patterns for fallback LinkedIn description extraction; removed 2000-char description truncation (full JDs preserved).
> - `app/agents/nodes/job_mcp_browse_server.py` — **Snapshot truncation fixed.** Increased `_EXTRACT_SNAPSHOT_CHARS` default from 3000 → 12000. Added `max_chars` parameter to `_do_fetch()` so `_do_extract()` can pass its extraction budget through without double-truncation. LLM extraction prompt now explicitly requests FULL and COMPLETE job descriptions — no summarization. Removed the deprecated Stage 1 classifier (login walls were causing false negatives).
> - `app/agents/job_workflow.py` — **Full description extraction enforced.** `JOB_EXTRACT_SCHEMA` `description` field updated to: *"Complete and un-truncated full job description. Do not summarize — include every detail from the original posting."* Workflow now `await`s `provider.search()` correctly (async). Added `source` field to `JobResult` to track which provider returned each result.
> - `app/core/config.py` — `MAX_SNAPSHOT_CHARS` increased from 3000 → 12000. Added `SEARXNG_ENABLED` toggle (`False` by default). Removed JSearch API settings (OpenWebNinja integration dropped). Added Pydantic `model_config` with `env_file_override=False`.
> - `app/agents/mcp_client.py` — Now exposes both `call_mcp_tool()` (sync) and `call_mcp_tool_async()` (async) so the search provider can use the async path natively.

---

## 1. High-Level System Architecture & Flow

The backend exposes a FastAPI REST API that orchestrates search query expansion, results retrieval, relevancy ranking, automated page browsing, and structured metadata extraction.

```
       [User Input (Natural Language)]
                      │
                      ▼
            [FastAPI Web Endpoint]
                      │
                      ▼
     [Pre-Search Query Expansion] ── (Uses LLM / Ollama)
                      │
                      ▼
       [Search Provider Layer]  ← Async concurrent via asyncio.create_task
                      │
         ┌────────────┼────────────┐
         ▼                         ▼
  [SearXNG via MCP :8001]   [LinkedIn Guest API]
         │                         │
         ▼                         ▼
  [Raw search results]     [Parsed HTML → per-job detail fetch]
         │                         │
         └────────────┬────────────┘
                      ▼
      [Results Aggregation & Deduplication]
                      │
                      ▼
       [Relevancy Rank & Trim] ── (Uses LLM to rank snippets 0-10)
                      │
                      ▼
         [Automated Camofox Browser :9500]
           - Opens tab per top URL
           - Waits for page to settle (SETTLE_SECONDS)
           - Retrieves Accessibility Tree snapshot (up to 12000 chars)
           - Compresses whitespaces
                      │
                      ▼
       [Single-Stage LLM Extraction Prompt]
         - Returns full JSON with all fields (description NOT truncated)
         - If page is login wall / empty, returns all nulls
                      │
                      ▼
   [Response Enrichment & Fallback]
     - Fallback to search snippet + keyword skills if extraction fails
                      │
                      ▼
    [JSON List of Enriched Jobs]
```

### Key Optimizations Implemented

1. **Dynamic Query Expansion:** Converts natural language queries into specific search operators targeting job portals (e.g., `site:naukri.com`, `site:linkedin.com/jobs`, `site:foundit.in`).
2. **Strict Freshness Enforcement:** Restricts SearXNG queries using the parameter `time_range="day"` to ensure only newly posted roles are retrieved.
3. **Concurrent Multi-Source Search (NEW June 8):** SearXNG and LinkedIn Guest API searches run in parallel via `asyncio.create_task`. Results are merged and deduplicated before ranking.
4. **LinkedIn Full Description Fetching (FIXED June 8):** Each LinkedIn job result now fetches the individual job detail page to extract the complete job description. Uses 5 fallback regex patterns. No truncation.
5. **Full Description Preservation (FIXED June 8):** Browser snapshots now captured at 12000 chars (up from 3000). LLM extraction prompt explicitly requests complete un-truncated descriptions.
6. **Relevance Ranking:** Scores search results (0 to 10) using an LLM before browsing, weeding out irrelevant hits and conserving resource bandwidth.
7. **Configurable LLM Backends:** Centralized LLM abstraction allowing seamless swaps between local models (Ollama) and cloud APIs (Groq or Gemini).
8. **MCP Protocol Compliance:** The MCP client uses the official MCP Python SDK with a full `initialize` → `tools/call` handshake via StreamableHTTP transport.

---

## 2. Required External Services

Ensure the following local servers are active before running the backend:

| Service | Port | Configuration / Setup | Purpose |
| --- | --- | --- | --- |
| **SearXNG** | `8080` | Active on `http://localhost:8080` | Aggregates search requests across engines in JSON format. |
| **Camofox** | `8050` | Active on `http://localhost:8050` | Headless automation tool returning accessibility-tree DOM snapshots. |
| **Ollama** | `11434` | Active on `http://localhost:11434` with model `qwen2.5-coder:1.5b` | Handles text query expansion, relevance scoring, and schema extraction. |
| **MongoDB** | `27017` | Local or Remote URI | Stores job entries, user settings, and uploaded resumes. |
| **MCP Search Server** | `8001` | `python -m app.agents.nodes.job_mcp_server` | StreamableHTTP MCP server exposing `search` and `search_json` tools. |
| **MCP Browse Server** | `8002` | `python -m app.agents.nodes.job_mcp_browse_server` | StreamableHTTP MCP server exposing `fetch` and `extract` tools via Camofox. |

### Docker Services (SearXNG + Camofox)
```bash
cd services
docker-compose up -d
```

---

## 3. Project Structure

Recreate the folder tree as follows:

```
backend/
├── .env
├── .gitignore
├── requirements.txt
├── app/
│   ├── __init__.py
│   ├── main.py
│   ├── api/
│   │   ├── __init__.py
│   │   ├── deps.py
│   │   └── v1/
│   │       ├── __init__.py
│   │       ├── jobs.py
│   │       └── resumes.py
│   ├── agents/
│   │   ├── __init__.py
│   │   ├── graph.py
│   │   ├── job_workflow.py          ← updated June 8 (full description schema)
│   │   ├── mcp_client.py            ← updated June 8 (async + sync wrappers)
│   │   ├── search_provider.py       ← FIXED June 8 (async concurrent + LinkedIn scope)
│   │   ├── state.py
│   │   ├── nodes/
│   │   │   ├── __init__.py
│   │   │   ├── extract_skills.py
│   │   │   ├── job_mcp_browse_server.py  ← FIXED June 8 (12000 char snapshots)
│   │   │   ├── job_mcp_server.py
│   │   │   └── tailor_resume.py
│   │   └── tools/
│   │       ├── __init__.py
│   │       ├── browse_jobs.py
│   │       ├── skill_extraction.py
│   │       └── web_search.py
│   ├── core/
│   │   ├── __init__.py
│   │   ├── config.py                ← updated June 8 (MAX_SNAPSHOT_CHARS=12000)
│   │   ├── database.py
│   │   └── llm.py
│   └── models/
│       ├── __init__.py
│       ├── job.py
│       └── resume.py
└── document/
    ├── backend_job_search_and_mcp_workflow_04_06_26.md
    ├── backend_job_search_and_mcp_workflow_06_06_26.md
    ├── backend_job_search_and_mcp_workflow_07_06_26.md
    └── backend_job_search_and_mcp_workflow_08_06_26.md
```

---

## 4. Dependencies & Environment Settings

### File: `requirements.txt`
```text
fastapi
uvicorn[standard]
python-dotenv
motor
pydantic-settings
python-multipart
langchain
langchain-openai
langgraph
httpx
pypdf
reportlab
ollama
mcp
```

### File: `.env`
```env
# Enable LinkedIn Guest API
LINKEDIN_GUEST_API_ENABLED=True
LINKEDIN_GUEST_API_LOCATION=India
LINKEDIN_GUEST_API_TIME_RANGE=r86400

# SearXNG settings
SEARXNG_ENABLED=True
SEARXNG_URL=http://localhost:8080
CAMOFOX_URL=http://localhost:8050
MCP_SEARCH_URL=http://localhost:8001
MCP_BROWSE_URL=http://localhost:8002

# LLM settings
LLM_PROVIDER=ollama
OLLAMA=http://localhost:11434
MODEL_NAME=qwen2.5-coder:1.5b

# Search config
SEARCH_MAX_RESULTS=10
BROWSE_TOP_N=15
SEARCH_SITES=naukri.com,linkedin.com/jobs,apna.co,indeed.com,instahyre.com,shine.com,foundit.in
SEARCH_FRESH=true
SEARCH_CAREERS=false

# Optional: Override snapshot limits (defaults: 12000)
# EXTRACT_SNAPSHOT_CHARS=12000
# MAX_SNAPSHOT_CHARS=12000

# Optional: MongoDB
# MONGODB_URI=mongodb://localhost:27017
```

---

## 5. Implementation Code

### Core Settings & Abstractions

#### app/core/config.py
```python
from typing import List
from pydantic import field_validator
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    MONGODB_URI: str
    SEARXNG_URL: str
    CAMOFOX_URL: str
    MCP_SEARCH_URL: str = "http://localhost:8001"
    MCP_BROWSE_URL: str = "http://localhost:8002"
    Ollama: str = "http://localhost:11434"
    LLM_PROVIDER: str = "ollama"  # e.g., 'ollama', 'groq', 'gemini'
    GROQ_API_KEY: str | None = None
    GEMINI_API_KEY: str | None = None
    SEARCH_MAX_RESULTS: int = 10
    BROWSE_TOP_N: int = 15
    SEARCH_SITES: str = "greenhouse.io,lever.co,myworkdayjobs.com"
    SEARCH_FRESH: bool = True
    SEARCH_CAREERS: bool = False
    SETTLE_SECONDS: float = 1.5
    MAX_SNAPSHOT_CHARS: int = 12000
    MODEL_NAME: str = "qwen2.5-coder:1.5b"
    MODEL_TEMPERATURE: float = 0.1

    # SearXNG toggle
    SEARXNG_ENABLED: bool = False  # Set to True to enable SearXNG search results

    # LinkedIn Guest API settings
    LINKEDIN_GUEST_API_ENABLED: bool = (
        False  # Set to True to enable LinkedIn Guest API search results
    )
    LINKEDIN_GUEST_API_LOCATION: str = "India"
    LINKEDIN_GUEST_API_TIME_RANGE: str = "r86400"  # Past 24 hours

    @property
    def search_sites_list(self) -> List[str]:
        return [s.strip() for s in self.SEARCH_SITES.split(",") if s.strip()]

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "extra": "ignore",
        # env vars from OS/terminal always override .env file values
        "env_file_override": False,
    }


settings = Settings()
```

#### app/core/database.py
```python
from motor.motor_asyncio import AsyncIOMotorClient
from app.core.config import settings

client: AsyncIOMotorClient = None


def get_database():
    return client["jobapp"]


async def connect_db():
    global client
    client = AsyncIOMotorClient(settings.MONGODB_URI)


async def close_db():
    global client
    if client:
        client.close()
```

#### app/core/llm.py
```python
import logging
import threading
from app.core.config import settings

log = logging.getLogger(__name__)


def call_llm(prompt: str, json_format: bool = False, timeout: int = 120) -> str:
    """
    Call the configured LLM provider.
    Currently defaults to Ollama, but designed to be easily extensible for Groq/Gemini.
    """
    provider = getattr(settings, "LLM_PROVIDER", "ollama").lower()

    if provider == "ollama":
        import ollama

        client = ollama.Client(host=settings.Ollama)
        result = {}
        exc_box = []

        def _worker():
            try:
                options = {
                    "temperature": settings.MODEL_TEMPERATURE,
                    "num_predict": 1024
                }
                kwargs = {
                    "model": settings.MODEL_NAME,
                    "messages": [{"role": "user", "content": prompt}],
                    "options": options,
                }
                if json_format:
                    kwargs["format"] = "json"

                try:
                    kwargs["think"] = False
                    resp = client.chat(**kwargs)
                except Exception:
                    kwargs.pop("think")
                    resp = client.chat(**kwargs)

                result["content"] = resp["message"]["content"]
            except Exception as e:
                exc_box.append(e)

        t = threading.Thread(target=_worker, daemon=True)
        t.start()
        t.join(timeout)

        if t.is_alive():
            raise RuntimeError(f"Ollama timeout after {timeout}s")
        if exc_box:
            raise exc_box[0]
        return result.get("content", "")

    elif provider == "groq":
        raise NotImplementedError("Groq provider not fully implemented yet")

    elif provider == "gemini":
        raise NotImplementedError("Gemini provider not fully implemented yet")

    else:
        raise ValueError(f"Unknown LLM provider: {provider}")
```

---

### MCP Client, Search Provider & Workflow

#### app/agents/mcp_client.py
```python
"""
Thin MCP client — calls tools on a FastMCP StreamableHTTP server.
Uses the official MCP Python SDK to handle session/protocol lifecycle.
Exposes both sync and async wrappers.
"""

import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor

from mcp.client.session import ClientSession
from mcp.client.streamable_http import streamablehttp_client

log = logging.getLogger(__name__)

_executor = ThreadPoolExecutor(max_workers=4)


async def _call_tool_async(base_url: str, tool_name: str, arguments: dict) -> str:
    async with streamablehttp_client(f"{base_url}/mcp") as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            log.debug("[mcp_client] → %s/mcp  tool=%r args=%r", base_url, tool_name, arguments)
            result = await session.call_tool(tool_name, arguments)
            if not result.content:
                return ""
            first = result.content[0]
            return first.text if hasattr(first, "text") else str(first)


def call_mcp_tool(base_url: str, tool_name: str, arguments: dict, timeout: float = 120.0) -> str:
    """
    Call a single MCP tool over StreamableHTTP (sync wrapper).
    Runs in a fresh thread to avoid conflicts with FastAPI's event loop.
    """
    def _run():
        return asyncio.run(_call_tool_async(base_url, tool_name, arguments))

    future = _executor.submit(_run)
    return future.result(timeout=timeout)


def call_mcp_tool_async(base_url: str, tool_name: str, arguments: dict):
    """
    Public async wrapper for MCP tool calls.
    Used by SearchProvider for native async execution.
    """
    return _call_tool_async(base_url, tool_name, arguments)
```

#### app/agents/search_provider.py ← FIXED (async concurrent + LinkedIn scoping)
```python
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

        # Execute all searches concurrently
        for source_name, task in tasks:
            try:
                results = await task
                all_results.extend(results)
                log.info("[provider] %s search returned %d results", source_name.upper(), len(results))
            except Exception as e:
                log.error("[provider] %s search failed: %s", source_name.upper(), e, exc_info=True)

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
            # CRITICAL: entire for-loop is inside async with block so client stays alive
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
```

---

### MCP Servers

#### app/agents/nodes/job_mcp_server.py (Search Server)
```python
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

mcp = FastMCP("search-server", host="0.0.0.0", port=8001)


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
    mcp.run(transport="streamable-http")
```

#### app/agents/nodes/job_mcp_browse_server.py ← FIXED (12000 char snapshots)
```python
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
import re

import httpx
from mcp.server.fastmcp import FastMCP

from app.core.config import settings
from app.core.llm import call_llm

log = logging.getLogger(__name__)

mcp = FastMCP("browser-server", host="0.0.0.0", port=8002)

_SETTLE_SECONDS = settings.SETTLE_SECONDS
_MAX_SNAPSHOT_CHARS = settings.MAX_SNAPSHOT_CHARS

# How many chars of the snapshot to send to the LLM — 12000 for full descriptions
_EXTRACT_SNAPSHOT_CHARS = getattr(settings, "EXTRACT_SNAPSHOT_CHARS", 12000)
_OLLAMA_TIMEOUT = getattr(settings, "OLLAMA_TIMEOUT", 120)

log.info(
    "[mcp:browse] module loaded — camofox=%s llm_provider=%s extract_chars=%d",
    settings.CAMOFOX_URL,
    getattr(settings, "LLM_PROVIDER", "ollama"),
    _EXTRACT_SNAPSHOT_CHARS,
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


def _parse_llm_json(raw: str) -> dict:
    """
    Robustly parse LLM output that may have:
    - Leading  thinking... response blocks
    - Markdown code fences
    - Trailing garbage after the closing brace
    """
    raw = re.sub(r" thinking.*? response", "", raw, flags=re.DOTALL).strip()
    raw = re.sub(r"^```(?:json)?\s*", "", raw).strip()
    raw = re.sub(r"\s*```$", "", raw).strip()

    start = raw.find("{")
    if start == -1:
        raise ValueError(f"No JSON object found in LLM output: {raw[:200]!r}")

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


# ── core logic (importable directly — Option B) ───────────────────────────────


def _do_fetch(url: str, user_id: str = "", max_chars: int | None = None) -> str:
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

    # Basic DOM Sanitization: compress empty lines
    snapshot = re.sub(r"\n\s*\n", "\n", snapshot)
    result = _truncate(snapshot, max_chars)
    log.info("[mcp:browse] ── _do_fetch END url=%r final_chars=%d", url, len(result))
    return result


def _do_extract(url: str, schema: dict, user_id: str = "") -> str:
    """Fetch a page and extract structured JSON using LLM approach."""
    log.info(
        "[mcp:browse] ── _do_extract START url=%r fields=%s",
        url,
        list(schema.get("properties", {}).keys()),
    )

    # Pass _EXTRACT_SNAPSHOT_CHARS to _do_fetch so the full LLM budget is available
    snapshot = _do_fetch(url, user_id, max_chars=_EXTRACT_SNAPSHOT_CHARS)
    if snapshot.startswith("Error"):
        log.warning("[mcp:browse] _do_extract aborting — fetch failed: %s", snapshot)
        return snapshot

    trimmed_snapshot = _truncate(snapshot, _EXTRACT_SNAPSHOT_CHARS)

    # ── REMOVED: Stage 1 classifier ─────────────────────────────
    # LinkedIn and other job sites often block headless browsers,
    # resulting in login walls or minimal content that fools the classifier.
    # Since we already know these are job URLs, skip classification
    # and let the extraction LLM handle empty/missing content naturally.

    fields = schema.get("properties", {})
    field_lines = "\n".join(
        f'  "{k}": {v.get("description", "")}' for k, v in fields.items()
    )

    extract_prompt = (
        "Extract job data from the page snapshot below. "
        "If the page is a login wall, anti-bot challenge, or missing job content, "
        "return a JSON object with all fields set to null. "
        "Otherwise, return ONLY a JSON object with these exact fields (use null for missing values).\n"
        "IMPORTANT: For the 'description' field, return the FULL and COMPLETE job description text. "
        "Do NOT summarize or truncate it. Include every detail from the original posting.\n"
        f"{field_lines}\n\n"
        f"URL: {url}\n\n"
        f"Page content:\n{trimmed_snapshot}"
    )

    try:
        raw = call_llm(extract_prompt, json_format=True, timeout=_OLLAMA_TIMEOUT)
        parsed = _parse_llm_json(raw)
        return json.dumps(parsed, indent=2)
    except Exception as e:
        log.warning("[mcp:browse] Extraction failed: %s", e)
        return json.dumps({k: None for k in fields})


# ── MCP tools ─────────────────────────────────────────────────────────────────


@mcp.tool()
def fetch(url: str, user_id: str = "") -> str:
    """
    Fetch a webpage and return its accessibility-tree snapshot.
    """
    if not url.startswith(("http://", "https://")):
        return f"Error: URL must start with http:// or https://; got {url!r}"
    return _do_fetch(url, user_id)


@mcp.tool()
def extract(url: str, schema: dict, user_id: str = "") -> str:
    """
    Fetch a webpage and extract structured data matching a JSON Schema via LLM.
    """
    if not url.startswith(("http://", "https://")):
        return f"Error: URL must start with http:// or https://; got {url!r}"
    return _do_extract(url, schema, user_id)


if __name__ == "__main__":
    mcp.run(transport="streamable-http")
```

---

### Custom Workflow Engine & Auxiliary Tools

#### app/agents/job_workflow.py ← UPDATED (full description schema + async)
```python
"""
Unified job search workflow.
All search targeting config (sites, freshness, result counts) lives in
backend config/settings — the frontend sends only user_input.
"""

import json
import logging
import re
import difflib
from typing import List

from app.agents.tools.skill_extraction import extract_skills_from_text
from app.agents.tools.browse_jobs import browse_extract
from app.agents.search_provider import provider
from app.core.config import settings
from app.core.llm import call_llm
from app.models.job import JobResult

log = logging.getLogger(__name__)

# ── Schema used to extract structured fields from each job page ───────────────
JOB_EXTRACT_SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string", "description": "Job title"},
        "company": {"type": "string", "description": "Hiring company name"},
        "location": {"type": "string", "description": "Job location or remote status"},
        "description": {
            "type": "string",
            "description": "Complete and un-truncated full job description. Do not summarize - include every detail from the original posting.",
        },
        "salary": {"type": "string", "description": "Salary or compensation range"},
        "posted_date": {
            "type": "string",
            "description": "When the job was posted, e.g. '2 days ago', '2024-06-01'",
        },
        "skills": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Required skills listed in the posting",
        },
        "job_type": {
            "type": "string",
            "description": (
                "Job category. One of: full-time, part-time, contract, "
                "internship, freelance, remote, on-site, hybrid, unknown"
            ),
        },
        "apply_url": {
            "type": "string",
            "description": "Direct URL to apply for the job, if different from the listing URL",
        },
    },
}


def _parse_user_input(user_input: str) -> dict:
    """Fallback plain-text parser if LLM fails."""
    text = str(user_input).strip()
    sites: List[str] = list(settings.search_sites_list)
    fresh = settings.SEARCH_FRESH
    company_careers = settings.SEARCH_CAREERS

    site_matches = re.findall(r"site:(\S+)", text, re.IGNORECASE)
    if site_matches:
        sites = site_matches
        text = re.sub(r"site:\S+", "", text, flags=re.IGNORECASE).strip()

    career_pattern = re.compile(
        r"\b(careers?|career\s*page|hiring\s*page|job\s*openings?)\s+(?:at\s+)?(\S+)",
        re.IGNORECASE,
    )
    m = career_pattern.search(text)
    if m:
        company_careers = True
        company_hint = m.group(2).strip(".,/")
        sites = [f"{company_hint.lower()}.com"] if "." not in company_hint else [company_hint]
        text = career_pattern.sub("", text).strip()

    text = re.sub(r"\b(latest|recent|new|today|this\s+week)\b", "", text, flags=re.IGNORECASE).strip()

    return {"query": text, "sites": sites, "fresh": fresh, "company_careers": company_careers}


def _build_queries(parsed: dict) -> List[str]:
    """Fallback query builder if LLM fails."""
    base = parsed["query"]
    sites = parsed["sites"]
    careers_mode = parsed["company_careers"]
    queries: List[str] = []
    if careers_mode and sites:
        for site in sites:
            domain = site.split("/")[0]
            queries.append(f"{base} site:{domain}/careers")
            queries.append(f"{base} site:{domain}/jobs")
        return queries
    if sites:
        for site in sites:
            queries.append(f"{base} site:{site}")
        return queries
    for site in settings.search_sites_list:
        queries.append(f"{base} site:{site}")
    return queries


def _build_queries_dynamic(user_input: str) -> List[str]:
    """Uses LLM to dynamically generate SearXNG queries targeting ATS platforms."""
    log.info("[workflow] Dynamically building search queries using LLM")
    sites_str = ", ".join(settings.search_sites_list)

    prompt = (
        f"You are a job search assistant. The user wants to find a job: '{user_input}'\n"
        "Generate up to 3 distinct search queries to find this job. "
        f"Target these specific job platforms: {sites_str}. "
        "Each query MUST use the 'site:' operator. "
        "Format the output strictly as a JSON array of strings, for example: "
        "[\"React developer site:greenhouse.io\", \"React engineer site:lever.co\"]"
    )

    try:
        raw = call_llm(prompt, json_format=True, timeout=30)
        raw = re.sub(r"^```(?:json)?\s*", "", raw).strip()
        raw = re.sub(r"\s*```$", "", raw).strip()

        start = raw.find("[")
        end = raw.rfind("]")
        if start != -1 and end != -1:
            queries = json.loads(raw[start:end+1])
            if isinstance(queries, list) and all(isinstance(q, str) for q in queries) and len(queries) > 0:
                log.info("[workflow] LLM generated %d queries: %s", len(queries), queries)
                return queries
    except Exception as e:
        log.warning("[workflow] LLM query generation failed: %s. Falling back to default logic.", e)

    parsed = _parse_user_input(user_input)
    return _build_queries(parsed)


def _rank_and_trim(results: List[dict], query: str, top_n: int) -> List[dict]:
    """Fallback ranking logic using simple keywords."""
    terms = [t.lower() for t in re.split(r"\W+", query) if len(t) > 2]

    def score(result):
        haystack = " ".join([
            (result.get("title") or ""),
            (result.get("content") or result.get("description") or result.get("snippet") or ""),
        ]).lower()
        return sum(1 for t in terms if t in haystack)

    scored = sorted(results, key=score, reverse=True)
    return scored[:top_n]


def _rank_and_trim_dynamic(results: List[dict], query: str, top_n: int) -> List[dict]:
    """Score every result against the base query using LLM, return top_n."""
    if not results:
        return []

    log.info("[workflow] LLM ranking %d candidates for query: %r", len(results), query)

    snippets = []
    for i, r in enumerate(results):
        title = r.get("title", "")
        url = r.get("url", "")
        snip = r.get("content") or r.get("description") or r.get("snippet") or ""
        snippets.append(f"[{i}] Title: {title}\nURL: {url}\nSnippet: {snip}")

    snippets_text = "\n\n".join(snippets)

    prompt = (
        f"You are a job search ranker. The user is looking for: '{query}'.\n"
        "Score each of the following search results from 0 to 10 based on how well it matches the user's intent. "
        "A score of 10 means a perfect match (recent, exact job, trusted site). "
        "A score of 0 means irrelevant.\n\n"
        f"{snippets_text}\n\n"
        "Return ONLY a JSON array of integers, where the index corresponds to the result index. "
        f"For example, if there are {len(results)} results, return: [8, 2, 9, ...]"
    )

    try:
        raw = call_llm(prompt, json_format=True, timeout=60)
        raw = re.sub(r"^```(?:json)?\s*", "", raw).strip()
        raw = re.sub(r"\s*```$", "", raw).strip()

        start = raw.find("[")
        end = raw.rfind("]")
        if start != -1 and end != -1:
            scores = json.loads(raw[start:end+1])
            if isinstance(scores, list):
                if len(scores) != len(results):
                    log.warning("[workflow] LLM returned invalid scores array (length mismatch): expected %d, got %d. Padding/truncating.", len(results), len(scores))
                    if len(scores) < len(results):
                        scores.extend([0] * (len(results) - len(scores)))
                    else:
                        scores = scores[:len(results)]

                scored = list(zip(results, scores))
                scored.sort(key=lambda x: x[1], reverse=True)
                kept = [r for r, s in scored[:top_n]]
                log.info("[workflow] LLM ranking successful. Top scores: %s", [s for r, s in scored[:top_n]])
                return kept
            else:
                log.warning("[workflow] LLM returned invalid scores array (not a list): %s", scores)
    except Exception as e:
        log.warning("[workflow] LLM ranking failed: %s", e)

    return _rank_and_trim(results, query, top_n)


def _categorize_job_type(extracted: dict, description: str) -> str:
    jt = (extracted.get("job_type") or "").strip().lower()
    if jt and jt != "unknown":
        return jt
    desc_lower = description.lower()
    for kw in (
        "internship", "contract", "freelance", "part-time", "part time",
        "remote", "hybrid", "full-time", "full time",
    ):
        if kw in desc_lower:
            return kw.replace(" ", "-")
    return "unknown"


def _is_duplicate(new_title: str, existing_titles: List[str]) -> bool:
    if not new_title: return False
    new_norm = re.sub(r'\W+', ' ', new_title.lower()).strip()
    for et in existing_titles:
        et_norm = re.sub(r'\W+', ' ', et.lower()).strip()
        if not et_norm: continue
        if difflib.SequenceMatcher(None, new_norm, et_norm).ratio() > 0.95:
            return True
    return False


async def search_jobs_workflow(user_input: str) -> List[dict]:
    """Entry point called by the API. Accepts plain-text user query only."""
    log.info("[workflow] starting dynamic search for: %s", user_input)

    queries = _build_queries_dynamic(user_input)
    log.debug("[workflow] will run %d queries: %s", len(queries), queries)

    search_per_query = settings.SEARCH_MAX_RESULTS * 2
    browse_top_n = settings.BROWSE_TOP_N

    seen_urls: set = set()
    raw_results: List[dict] = []
    seen_titles: List[str] = []

    for q in queries:
        batch = await provider.search(q, num_results=search_per_query, time_range="day")
        log.info(
            "[workflow] query=%r fetch_per_query=%d → got %d results",
            q, search_per_query, len(batch),
        )
        for r in batch:
            url = r.get("url", "")
            title = r.get("title", "")
            if url and url not in seen_urls:
                if _is_duplicate(title, seen_titles):
                    continue
                seen_titles.append(title)
                seen_urls.add(url)
                raw_results.append(r)

    log.info("[workflow] total unique candidates after search: %d", len(raw_results))

    pool_size = browse_top_n * 3
    raw_results = _rank_and_trim_dynamic(raw_results, user_input, pool_size)
    log.info("[workflow] browse phase will process up to %d candidates to find %d valid jobs", len(raw_results), browse_top_n)

    jobs: List[dict] = []
    final_seen_titles: List[str] = []

    for idx, result in enumerate(raw_results):
        if len(jobs) >= browse_top_n:
            break

        url = result.get("url") or ""
        snippet = (
            result.get("description")
            or result.get("snippet")
            or result.get("content")
            or ""
        ).strip()
        base_title = (result.get("title") or result.get("name") or "").strip()

        extracted: dict = {}

        log.debug(
            "[workflow] [%d/%d] processing url=%r title=%r",
            idx + 1,
            len(raw_results),
            url,
            base_title,
        )

        if url.startswith(("http://", "https://")):
            log.debug("[workflow] [%d] fetching page via camofox: %r", idx + 1, url)
            try:
                raw_json = browse_extract(url, JOB_EXTRACT_SCHEMA)
                extracted = (
                    json.loads(raw_json) if isinstance(raw_json, str) else raw_json
                )

                if not extracted or all(v is None for v in extracted.values()):
                    log.warning("[workflow] [%d] browse extraction empty, falling back to snippet.", idx + 1)
                    extracted = {}

                log.debug(
                    "[workflow] [%d] extract succeeded, keys=%s",
                    idx + 1,
                    list(extracted.keys()),
                )
            except Exception as exc:
                log.warning(
                    "[workflow] [%d] browse_extract failed (%s), falling back to snippet",
                    idx + 1,
                    exc,
                )
        else:
            log.warning("[workflow] [%d] no valid URL, skipping browse", idx + 1)
            continue

        final_title = (extracted.get("title") or base_title).strip()
        if _is_duplicate(final_title, final_seen_titles):
            log.info("[workflow] [%d] duplicate title detected after extraction: %r. Skipping.", idx + 1, final_title)
            continue
        final_seen_titles.append(final_title)

        title = (extracted.get("title") or base_title).strip()
        company = (extracted.get("company") or result.get("company") or "").strip()
        location = extracted.get("location") or result.get("location") or None
        description = (extracted.get("description") or snippet).strip()

        if not title and not description:
            log.warning("[workflow] [%d] no title or description, skipping.", idx + 1)
            continue
        skills = extracted.get("skills") or extract_skills_from_text(description)
        job_type = _categorize_job_type(extracted, description)
        posted_date = (
            extracted.get("posted_date") or result.get("publishedDate") or None
        )
        apply_url = extracted.get("apply_url") or url or None

        job = JobResult(
            title=title,
            company=company,
            location=location,
            description=description,
            url=url or None,
            skills=skills,
            job_type=job_type,
            posted_date=posted_date,
            apply_url=apply_url,
            source=result.get("source", "unknown"),
        )
        job_dict = job.model_dump()

        log.info(
            "[workflow] [%d] job_type=%r  title=%r  url=%r  posted=%r",
            idx + 1,
            job_type,
            title,
            url,
            posted_date,
        )
        print(f"\n{'='*60}")
        print(
            f"[JOB {idx+1}/{len(raw_results)}]  job_type={job_type!r}  posted={posted_date!r}"
        )
        print(json.dumps(job_dict, indent=2, ensure_ascii=False))
        print("=" * 60)

        jobs.append(job_dict)

    log.info("[workflow] done — %d jobs extracted", len(jobs))
    return jobs
```

#### app/agents/tools/browse_jobs.py
```python
"""
Browse tool — calls the browse MCP server over HTTP (Option A).
"""

import json
import logging

from app.agents.mcp_client import call_mcp_tool
from app.core.config import settings

log = logging.getLogger(__name__)


def browse_fetch(url: str) -> str:
    """Fetch a job page via the browse MCP server and return its snapshot."""
    log.info("[browse_tool] browse_fetch → MCP:fetch url=%r", url)
    result = call_mcp_tool(settings.MCP_BROWSE_URL, "fetch", {"url": url})
    log.info("[browse_tool] browse_fetch ← done chars=%d", len(result))
    return result


def browse_extract(url: str, schema: dict, model_name: str = "") -> str:
    """Fetch a job page and extract structured fields via the browse MCP server."""
    log.info("[browse_tool] browse_extract → MCP:extract url=%r", url)
    result = call_mcp_tool(
        settings.MCP_BROWSE_URL,
        "extract",
        {"url": url, "schema": schema},
        timeout=180.0,
    )
    log.info("[browse_tool] browse_extract ← done chars=%d", len(result))
    return result
```

---

## 6. How to Deploy, Start, and Verify

### Step 1: Environment Setup
1. Create a python virtual environment:
   ```bash
   python -m venv .venv
   ```
2. Activate it:
   - **Windows Powershell:**
     ```powershell
     .\.venv\Scripts\Activate.ps1
     ```
   - **macOS / Linux Bash:**
     ```bash
     source .venv/bin/activate
     ```
3. Install required packages:
   ```bash
   pip install -r requirements.txt
   ```

### Step 2: Configure Environment Variables
Create a `.env` file in the root `backend/` directory matching the values in Section 4. Key settings:
- `LINKEDIN_GUEST_API_ENABLED=True` — Enable LinkedIn job results
- `SEARXNG_ENABLED=True` — Enable SearXNG search
- `SEARXNG_URL` and `CAMOFOX_URL` — Point to your Docker services

### Step 3: Start Docker Services
```bash
cd services
docker-compose up -d
```
Verify:
- SearXNG → `http://localhost:8080`
- Camofox → `http://localhost:8050`

### Step 4: Start Ollama
```bash
ollama run qwen2.5-coder:1.5b
```
Ollama listens on `http://localhost:11434`.

### Step 5: Start MCP Servers (run from backend directory in separate terminals)
```bash
# Terminal 1: Search Server (port 8001)
python -m app.agents.nodes.job_mcp_server
```
```bash
# Terminal 2: Browse Server (port 8002)
python -m app.agents.nodes.job_mcp_browse_server
```

### Step 6: Run the FastAPI Server
```bash
uvicorn app.main:app --reload
```
API available at `http://localhost:8000`

### Step 7: Verify Search & Extractions
**Sample Request:**
```bash
curl -X POST http://127.0.0.1:8000/api/v1/jobs/search \
     -H "Content-Type: application/json" \
     -d '{"user_input": "React developer python remote"}'
```

**Expected Response format:**
```json
[
  {
    "title": "Frontend Software Engineer (React)",
    "company": "Tech Corp",
    "location": "Remote",
    "description": "We are seeking a React developer with Python skills to join our engineering team. You will be responsible for building modern web applications... [FULL DESCRIPTION, not truncated]",
    "url": "https://naukri.com/job/12345",
    "apply_url": "https://naukri.com/job/12345#apply",
    "skills": ["react", "javascript", "python"],
    "job_type": "remote",
    "posted_date": "2 days ago",
    "salary": "₹12,00,000 - ₹18,00,000",
    "source": "searxng"
  }
]
```

### Step 8: Verify Fallbacks
- **MCP Server Offline:** Stop `job_mcp_server`. SearXNG search will fail but LinkedIn results continue.
- **LinkedIn API Down:** Stop/disconnect from LinkedIn. SearXNG results continue.
- **Browser (Camofox) Offline:** Job extraction falls back to search snippet + regex keyword skills.
- **Ollama Offline:** Query expansion and ranking fall back to `_parse_user_input` / `_rank_and_trim` keyword matching.

### Step 9: Testing Multi-Source Functionality
```bash
python test/test_integration.py
```
The test verifies:
1. SearXNG and LinkedIn search results are aggregated concurrently
2. Duplicate results are removed by URL
3. Each result includes a `source` field (searxng/linkedin)
4. LinkedIn job descriptions are fetched from individual job pages
5. The system degrades gracefully when a source fails

---

## 7. Key Architecture Decisions (June 8, 2026)

### Concurrent Source Execution
SearXNG and LinkedIn searches run in parallel via `asyncio.create_task`. When both are enabled, the search phase takes the time of the slowest source, not the sum of both.

### Full Description Strategy
Two-pronged approach for getting complete job descriptions:
1. **SearXNG results:** Browse the actual job URL via Camofox → extract full text via LLM with 12000-char budget
2. **LinkedIn results:** Fetch individual job detail pages directly via HTTP → extract description HTML with 5 fallback patterns

### No Truncation Policy
- Snapshot size: 12000 chars (up from 3000)
- LinkedIn descriptions: No char limit (previously 2000)
- LLM prompt: Explicitly says "Do NOT summarize or truncate"
- Schema: "Complete and un-truncated full job description"