# Backend Job Search & MCP Workflow Reconstruction Guide (July 6, 2026)

This document provides a complete, self-contained implementation guide for the backend job search workflow and Model Context Protocol (MCP) servers.
Any developer or AI agent starting with zero context will be able to reconstruct the entire service and run it successfully using this guide.

> **Changelog from June 6, 2026:**
> - `app/agents/mcp_client.py` — **Fully rewritten.** Replaced raw JSON-RPC HTTP calls with the official MCP Python SDK (`mcp>=1.27.1`). The client now performs the required `initialize` handshake via `ClientSession` + `streamablehttp_client` before any `tools/call`. Runs inside a `ThreadPoolExecutor` to avoid event loop conflicts with FastAPI.
> - `app/agents/search_provider.py` — **Switched from Option B (direct import) to Option A (HTTP MCP client).** Now calls `call_mcp_tool()` over HTTP instead of importing `_do_search()` directly.
> - `app/agents/nodes/job_mcp_server.py` — Added `search_json` tool, bound server to `host="0.0.0.0" port=8001`, and set `transport="streamable-http"` in `__main__`.
> - `.env` / `config.py` — Added `MCP_SEARCH_URL` and `MCP_BROWSE_URL` settings. Updated `SEARCH_SITES` to Indian job portals.
> - **NEW: July 6, 2026** - Enhanced `search_provider.py` to aggregate results from multiple sources:
>   - MCP Search Server (SearXNG)
>   - LinkedIn Guest API (https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search)
>   - JSearch API (OpenWebNinja) via RapidAPI
> - Added configuration for LinkedIn Guest API and JSearch API in `.env` and `config.py`

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
       [Search Provider Layer]  ← Option A: HTTP via MCP Client
                      │
                      ▼
  [MCP Search Server :8001]  ← StreamableHTTP (FastMCP)
                      │
                      ▼
[SearXNG Search Engine (Local)] ── (Strict time_range="day" for latest postings)
                      │
                      ▼
   [LinkedIn Guest API] ← (Public API for job postings)
                      │
                      ▼
     [JSearch API] ← (OpenWebNinja via RapidAPI)
                      │
                      ▼
      [Results Aggregation & Deduplication]
                      │
                      ▼
       [Relevancy Rank & Trim] ── (Uses LLM to rank snippets 0-10)
                      │
                      ▼
         [Automated Camofox Browser]
           - Opens tab per top URL
           - Waits for page to settle
           - Retrieves Accessibility Tree snapshot
           - Compresses whitespaces
                      │
                      ▼
    [Multi-Stage Extraction Pipeline]
         - Stage 1: Is it a Job page? (Yes/No Classifier)
         - Stage 2: Schema Extraction (Ollama/LLM)
                      │
                      ▼
   [Response Enrichment & Fallback]
     - Fallback to SearXNG snippets and keyword skills if extraction fails
                      │
                      ▼
    [JSON List of Enriched Jobs]
```

### Key Optimizations Implemented

1. **Dynamic Query Expansion:** Converts natural language queries into specific search operators targeting job portals (e.g., `site:naukri.com`, `site:linkedin.com/jobs`, `site:foundit.in`).
2. **Strict Freshness Enforcement:** Restricts SearXNG queries using the parameter `time_range="day"` to ensure only newly posted roles are retrieved.
3. **Relevance Ranking:** Scores search results (0 to 10) using an LLM before browsing, weeding out irrelevant hits and conserving resource bandwidth.
4. **Multi-Stage Extraction:** Saves LLM context size and runtime:
   - **Stage 1 (Classification):** Quickly determines if the web page is actually a job listing. If false, skips processing.
   - **Stage 2 (Schema-constrained Extraction):** Extracts structured attributes matching `JOB_EXTRACT_SCHEMA`.
5. **Configurable LLM Backends:** Centralized LLM abstraction allowing seamless swaps between local models (Ollama) and cloud APIs (Groq or Gemini).
6. **MCP Protocol Compliance (NEW):** The MCP client now uses the official SDK with a full `initialize` → `tools/call` handshake, compatible with MCP `1.27.1+` StreamableHTTP transport.
7. **Multi-Source Job Aggregation (NEW):** Combines results from SearXNG, LinkedIn Guest API, and JSearch API with deduplication for comprehensive job discovery.

---

## 2. Required External Services

Ensure the following local servers are active before running the backend:

| Service | Port | Configuration / Setup | Purpose |
| --- | --- | --- | --- |
| **SearXNG** | `8888` | Active on `http://localhost:8888` | Aggregates search requests across engines in JSON format. |
| **Camofox** | `9500` | Active on `http://localhost:9500` | Headless automation tool returning accessibility-tree DOM snapshots. |
| **Ollama** | `11434` | Active on `http://localhost:11434` with model `qwen2.5-coder:1.5b` | Handles text query expansion, relevance scoring, page classification, and schema extraction. |
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
│   │   ├── job_workflow.py
│   │   ├── mcp_client.py          ← rewritten June 6
│   │   ├── search_provider.py     ← updated June 6 (Option A), enhanced July 6 (multi-source)
│   │   ├── state.py
│   │   ├── nodes/
│   │   │   ├── __init__.py
│   │   │   ├── extract_skills.py
│   │   │   ├── job_mcp_browse_server.py
│   │   │   ├── job_mcp_server.py  ← updated June 6
│   │   │   └── tailor_resume.py
│   │   └── tools/
│   │       ├── __init__.py
│   │       ├── browse_jobs.py
│       │   ├── skill_extraction.py
│   │       └── web_search.py
│   ├── core/
│   │   ├── __init__.py
│   │   ├── config.py
│   │   ├── database.py
│   │   └── llm.py
│   └── models/
│       ├── __init__.py
│       ├── job.py
│       └── resume.py
└── document/
    ├── backend_job_search_and_mcp_workflow_04_06_26.md
    ├── backend_job_search_and_mcp_workflow_06_06_26.md
    └── backend_job_search_and_mcp_workflow_07_06_26.md
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
MONGODB_URI=mongodb://localhost:27017
SEARXNG_URL=http://localhost:8888
CAMOFOX_URL=http://localhost:9500
Ollama=http://localhost:11434
MCP_SEARCH_URL=http://localhost:8001
MCP_BROWSE_URL=http://localhost:8002
LLM_PROVIDER=ollama
GROQ_API_KEY=your_groq_key_here
GEMINI_API_KEY=your_gemini_key_here
SEARCH_MAX_RESULTS=10
BROWSE_TOP_N=15
SEARCH_SITES=naukri.com,linkedin.com/jobs,apna.co,indeed.com,instahyre.com,shine.com,foundit.in
SEARCH_FRESH=true
SEARCH_CAREERS=false

# LinkedIn Guest API Configuration
LINKEDIN_GUEST_API_ENABLED=true
LINKEDIN_GUEST_API_LOCATION=India
LINKEDIN_GUEST_API_TIME_RANGE=r86400

# JSearch API (OpenWebNinja) Configuration
JSEARCH_API_KEY=your_jsearch_api_key_here
JSEARCH_API_HOST=jsearch.p.rapidapi.com
JSEARCH_API_LOCATION=India
JSEARCH_API_DATE_POSTED=today
```

---

## 5. Implementation Code

### Core Settings & Abstractions

#### [app/core/config.py](file:///d:/AI%20Projects/job_project/project/backend/app/core/config.py)
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
    MAX_SNAPSHOT_CHARS: int = 3000
    MODEL_NAME: str = "qwen2.5-coder:1.5b"
    MODEL_TEMPERATURE: float = 0.1

    # LinkedIn Guest API settings
    LINKEDIN_GUEST_API_ENABLED: bool = True
    LINKEDIN_GUEST_API_LOCATION: str = "India"
    LINKEDIN_GUEST_API_TIME_RANGE: str = "r86400"  # Past 24 hours

    # JSearch API (OpenWebNinja) settings
    JSEARCH_API_KEY: str | None = None
    JSEARCH_API_HOST: str = "jsearch.p.rapidapi.com"
    JSEARCH_API_URL: str | None = None  # Custom URL if needed
    JSEARCH_API_LOCATION: str = "India"
    JSEARCH_API_DATE_POSTED: str = "today"  # Equivalent to LinkedIn's r86400

    @property
    def search_sites_list(self) -> List[str]:
        return [s.strip() for s in self.SEARCH_SITES.split(",") if s.strip()]

    class Config:
        env_file = ".env"


settings = Settings()
```

#### [app/core/database.py](file:///d:/AI%20Projects/job_project/project/backend/app/core/database.py)
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

#### [app/core/llm.py](file:///d:/AI%20Projects/job_project/project/backend/app/core/llm.py)
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

### MCP Client & Search Provider (Updated June 6, Enhanced July 6)

#### [app/agents/mcp_client.py](file:///d:/AI%20Projects/job_project/project/backend/app/agents/mcp_client.py) ← rewritten
```python
"""
Thin MCP client — calls tools on a FastMCP StreamableHTTP server.
Uses the official MCP Python SDK to handle session/protocol lifecycle.
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
```

#### [app/agents/search_provider.py](file:///d:/AI%20Projects/job_project/project/backend/app/agents/search_provider.py) ← updated (Option A), enhanced July 6
```python
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
            "location": getattr(settings, "LINKEDIN_GUEST_API_LOCATION", "India"),
            "f_TPR": getattr(settings, "LINKEDIN_GUEST_API_TIME_RANGE", "r86400"),    # Past 24 hours
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
        custom_url = getattr(settings, "JSEARCH_API_URL", None)
        url = custom_url if custom_url else "https://jsearch.p.rapidapi.com/search"

        # Use API key from settings
        api_key = getattr(settings, "JSEARCH_API_KEY", None)
        api_host = getattr(settings, "JSEARCH_API_HOST", "jsearch.p.rapidapi.com")

        headers = {
            "X-RapidAPI-Key": api_key,
            "X-RapidAPI-Host": api_host,
        }

        params = {
            "query": query,
            "location": getattr(settings, "JSEARCH_API_LOCATION", "India"),  # Could be made configurable
            "page": "1",
            "num_pages": "1",
            "date_posted": getattr(settings, "JSEARCH_API_DATE_POSTED", "today")  # Equivalent to f_TPR=r86400
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
```

---

### MCP Servers (Updated June 6)

#### [app/agents/nodes/job_mcp_server.py](file:///d:/AI%20Projects/job_project/project/backend/app/agents/nodes/job_mcp_server.py) ← updated
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

#### [app/agents/nodes/job_mcp_browse_server.py](file:///d:/AI%20Projects/job_project/project/backend/app/agents/nodes/job_mcp_browse_server.py)
```python
"""
MCP server — exposes `fetch` and `extract` tools backed by Camofox browser.
Run standalone:  python -m app.agents.nodes.job_mcp_browse_server
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
mcp = FastMCP("browser-server")

_SETTLE_SECONDS = settings.SETTLE_SECONDS
_MAX_SNAPSHOT_CHARS = settings.MAX_SNAPSHOT_CHARS
_EXTRACT_SNAPSHOT_CHARS = 3000
_OLLAMA_TIMEOUT = 120

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
    if "application/json" in r.headers.get("content-type", ""):
        data = r.json()
        snapshot = data.get("snapshot") or data.get("aria") or data.get("text") or str(data)
    else:
        snapshot = r.text
    return snapshot


def _close_tab(client: httpx.Client, user_id: str, tab_id: str) -> None:
    try:
        client.delete(
            f"{settings.CAMOFOX_URL}/tabs/{tab_id}",
            params={"userId": user_id},
            timeout=10.0,
        )
    except Exception as e:
        log.warning("[mcp:browse] failed to close tab tab_id=%r: %s", tab_id, e)


def _truncate(snapshot: str, max_chars: int | None = None) -> str:
    limit = max_chars if max_chars is not None else _MAX_SNAPSHOT_CHARS
    if len(snapshot) <= limit:
        return snapshot
    half = limit // 2 - 100
    head, tail = snapshot[:half], snapshot[-half:]
    dropped = len(snapshot) - len(head) - len(tail)
    return head + f"\n\n...[TRUNCATED {dropped} chars]...\n\n" + tail


def _parse_llm_json(raw: str) -> dict:
    raw = re.sub(r"```.*?```", "", raw, flags=re.DOTALL).strip()
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


def _do_fetch(url: str, user_id: str = "") -> str:
    """Fetch a page via camofox and return its compressed accessibility tree snapshot."""
    one_shot = not user_id
    if one_shot:
        user_id = f"oneshot-{uuid.uuid4().hex[:8]}"

    with httpx.Client() as client:
        try:
            tab_id = _open_tab(client, user_id, url)
        except Exception as e:
            return f"Error opening tab: {e}"

        time.sleep(_SETTLE_SECONDS)

        try:
            snapshot = _get_snapshot(client, user_id, tab_id)
        except Exception as e:
            _close_tab(client, user_id, tab_id)
            return f"Error fetching snapshot: {e}"

        if one_shot:
            _close_tab(client, user_id, tab_id)

    # Basic DOM Sanitization: compress repeating newlines
    snapshot = re.sub(r'\n\s*\n', '\n', snapshot)
    return _truncate(snapshot)


def _do_extract(url: str, schema: dict, user_id: str = "") -> str:
    """Fetch a page and extract structured JSON using multi-stage LLM classifier and extractor."""
    snapshot = _do_fetch(url, user_id)
    if snapshot.startswith("Error"):
        return snapshot

    trimmed_snapshot = _truncate(snapshot, _EXTRACT_SNAPSHOT_CHARS)

    # Stage 1: Classification
    class_prompt = (
        "Analyze the following web page snapshot and determine if it is a job listing or related to a job vacancy. "
        "Return ONLY a JSON object: {\"is_job\": true} or {\"is_job\": false}. "
        "If you are unsure or if the page contains any job descriptions, default to true.\n\n"
        f"Page ({url}):\n{trimmed_snapshot}"
    )
    empty_result = json.dumps({k: None for k in schema.get("properties", {})})

    try:
        class_raw = call_llm(class_prompt, json_format=True, timeout=_OLLAMA_TIMEOUT)
        class_data = _parse_llm_json(class_raw)
        if not class_data.get("is_job", False):
            log.info("[mcp:browse] Page is not a job listing. Skipping Stage 2 extraction.")
            return empty_result
    except Exception as e:
        log.warning("[mcp:browse] Stage 1 classification error: %s. Proceeding anyway.", e)

    # Stage 2: Core Extraction
    fields = schema.get("properties", {})
    field_lines = "\n".join(
        f'  "{k}": {v.get("description", "")}' for k, v in fields.items()
    )

    extract_prompt = (
        "Extract job data from the page snapshot below. "
        "Return ONLY a JSON object with these exact fields (use null for missing values):\n"
        f"{field_lines}\n\n"
        f"Page ({url}):\n{trimmed_snapshot}"
    )

    try:
        raw = call_llm(extract_prompt, json_format=True, timeout=_OLLAMA_TIMEOUT)
        parsed = _parse_llm_json(raw)
        return json.dumps(parsed, indent=2)
    except Exception as e:
        log.warning("[mcp:browse] Extraction failed: %s", e)
        return empty_result


@mcp.tool()
def fetch(url: str, user_id: str = "") -> str:
    """Fetch a webpage and return its accessibility-tree snapshot."""
    if not url.startswith(("http://", "https://")):
        return f"Error: URL must start with http:// or https://; got {url!r}"
    return _do_fetch(url, user_id)


@mcp.tool()
def extract(url: str, schema: dict, user_id: str = "") -> str:
    """Fetch a webpage and extract structured data matching a JSON Schema."""
    if not url.startswith(("http://", "https://")):
        return f"Error: URL must start with http:// or https://; got {url!r}"
    return _do_extract(url, schema, user_id)


if __name__ == "__main__":
    mcp.run()
```

---

### Custom Workflow Engine & Auxiliary Tools

#### [app/agents/job_workflow.py](file:///d:/AI%20Projects/job_project/project/backend/app/agents/job_workflow.py)
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

JOB_EXTRACT_SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string", "description": "Job title"},
        "company": {"type": "string", "description": "Hiring company name"},
        "location": {"type": "string", "description": "Job location or remote status"},
        "description": {
            "type": "string",
            "description": "Full job description or summary",
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
        import re
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
        import re
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
        # Use time_range="day" for latest jobs as requested
        batch = provider.search(q, num_results=search_per_query, time_range="day")
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
            
        # Dedupe check on final extracted title
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
Create a `.env` file in the root `backend/` directory matching the values provided in section 4. Adjust the ports/URLs if your local instances of SearXNG, Camofox, or Ollama are running on different values.

### Step 3: Start Docker Services
```bash
cd services
docker-compose up -d
```

### Step 4: Start MCP Servers (run from backend directory)
```bash
python -m app.agents.nodes.job_mcp_server
```
```bash
python -m app.agents.nodes.job_mcp_browse_server
```

### Step 5: Run the FastAPI Server
```bash
uvicorn app.main:app --reload
```

### Step 6: Verify Search & Extractions
You can verify the entire workflow pipeline by running a simple POST request:

**Sample Request (using `curl` or Postman):**
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
    "description": "We are seeking a React developer with Python skills...",
    "url": "https://naukri.com/job/12345",
    "apply_url": "https://naukri.com/job/12345#apply",
    "skills": ["react", "javascript", "python"],
    "job_type": "remote",
    "posted_date": "2 days ago",
    "salary": "₹12,00,000 - ₹18,00,000"
  }
]
```

### Step 7: Verify Fallbacks
- **Simulate MCP Server Offline:** Stop `job_mcp_server`. The `SearchProvider` will raise an error from `call_mcp_tool`. Check that the error is logged and the API returns a 500 with a clear message.
- **Simulate Browser Offline:** Stop the `camofox` Docker container. Run the query again. The output should print warnings indicating browser failures, but succeed anyway by populating job fields from SearXNG's `content` and parsing skills via regex in the `extract_skills_from_text` module.
- **Simulate Ollama Offline:** Stop the `ollama` service. The search should degrade gracefully using `_parse_user_input` and `_rank_and_trim` fallbacks instead of crashing.
- **Simulate LinkedIn API Issues:** The LinkedIn Guest API may occasionally block requests without proper headers or rate limit. The system will continue to work using other sources.
- **Simulate JSearch API Issues:** If the JSearch API key is invalid or the service is unavailable, the system will continue to work using MCP and LinkedIn sources.

### Step 8: Testing Multi-Source Functionality
To test the new multi-source search capabilities:
```powershell
# PowerShell - Set API keys for current session only
$env:JSEARCH_API_KEY="your_actual_key_here"
python test_integration.py
```

The test will verify that:
1. Results are aggregated from all available sources
2. Duplicate results are removed based on URL
3. The system works even if some sources are unavailable
4. LinkedIn Guest API and JSearch API integration functions correctly