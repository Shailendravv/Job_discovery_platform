# MCP Search Integration — Implementation Guide

This document covers everything added on top of the base workflow described in
`backend_job_search_workflow.md`. A developer or AI agent should be able to reproduce
this integration from scratch using only this file.

---

## What Changed and Why

Before this integration the workflow called `web_search()` from `tools/web_search.py` directly.
That worked but had no abstraction — swapping the search backend meant editing the workflow itself.

Three things were introduced:

1. **`job_mcp_server.py`** — MCP server with a `search` tool backed by SearXNG. Its core logic
   lives in `_do_search()` which is a plain importable function (no subprocess needed).
2. **`search_provider.py`** — thin abstraction layer. Today it calls `_do_search()` directly
   (Option B). When ready, swap its internals to an MCP client call (Option A) — nothing else changes.
3. **`SEARCH_NUM_RESULTS` in `.env`** — single source of truth for result count across all paths.

---

## Files Added / Modified

| File | Status | What changed |
|---|---|---|
| `app/agents/nodes/job_mcp_server.py` | **New** | MCP server + `_do_search()` |
| `app/agents/search_provider.py` | **New** | Abstraction layer over search backend |
| `app/agents/job_workflow.py` | **Modified** | Replaced `web_search()` with `provider.search()`, added DEBUG logs |
| `app/core/config.py` | **Modified** | Added `SEARCH_NUM_RESULTS: int = 6` |
| `app/main.py` | **Modified** | Switched logging level to `DEBUG` |
| `backend/.env` | **Modified** | Added `SEARCH_NUM_RESULTS=6` |

---

## Environment Variable

Add to `backend/.env`:

```env
SEARCH_NUM_RESULTS=6
```

- Controls how many SearXNG results are fetched per search request
- Read by `_do_search()`, `@mcp.tool()`, and `SearchProvider` all via `settings.SEARCH_NUM_RESULTS`
- Change this value and restart — no code changes needed
- The API request body can still override it per-request via `"num_results": N`
- Defaults to `6` in `config.py` if the key is missing from `.env`

---

## Configuration

### File: `app/core/config.py`

```python
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    MONGODB_URI: str
    SEARXNG_URL: str
    CAMOFOX_URL: str
    Ollama: str
    SEARCH_NUM_RESULTS: int = 6   # ← new field

    class Config:
        env_file = ".env"

settings = Settings()
```

---

## MCP Server

### File: `app/agents/nodes/job_mcp_server.py`

### Design — two-layer structure

```
_do_search(query, max_results)     ← pure function, returns list[dict], importable directly
        ↑
@mcp.tool() search(query, ...)     ← MCP protocol wrapper, formats output as string for LLM
```

This split gives two consumers what they each need:
- The workflow gets raw `list[dict]` — easy to process in Python
- An Ollama agent gets a formatted string — easy to read as LLM context
- Both share the exact same SearXNG call

### `_do_search(query, max_results=None) -> list[dict]`

- `max_results=None` → resolved to `settings.SEARCH_NUM_RESULTS` inside the function
- Calls `GET {SEARXNG_URL}/search?q={query}&format=json`
- Slices results to `max_results` and returns raw dicts
- Returns `[]` on any `httpx.HTTPError` — never raises
- Log prefix: `[mcp:search]`

### `@mcp.tool() search(query, max_results=None) -> str`

- Calls `_do_search()` and formats results as:
  ```
  [1] Job Title
      https://example.com/job/123
      Snippet text from SearXNG
  ```
- Returns an error string if SearXNG is unreachable (does not raise)
- Used by Ollama agent / future MCP client (Option A)
- Run standalone: `python -m app.agents.nodes.job_mcp_server`
- Transport: stdio (standard MCP stdio transport)

### Full file

```python
"""
MCP server — exposes a `search` tool backed by SearXNG.
Run standalone:  python -m app.agents.nodes.job_mcp_server

The core logic lives in _do_search() so it can be imported directly
(Option B) without spinning up the MCP subprocess.
"""

import logging
import httpx
from mcp.server.fastmcp import FastMCP
from app.core.config import settings

log = logging.getLogger(__name__)
mcp = FastMCP("search-server")


def _do_search(query: str, max_results: int | None = None) -> list[dict]:
    """Core SearXNG call — returns raw result dicts. Importable directly."""
    max_results = max_results if max_results is not None else settings.SEARCH_NUM_RESULTS
    log.info("[mcp:search] query=%r max_results=%d", query, max_results)
    try:
        response = httpx.get(
            f"{settings.SEARXNG_URL}/search",
            params={"q": query, "format": "json"},
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


if __name__ == "__main__":
    mcp.run()
```

---

## Search Provider (Abstraction Layer)

### File: `app/agents/search_provider.py`

### Purpose

Single abstraction between the workflow and the search backend.

- **Today (Option B):** calls `_do_search()` directly — same process, zero subprocess overhead,
  single log stream, easy to debug
- **Future (Option A):** replace the body of `search()` with an MCP client call — all callers
  stay unchanged

### Full file

```python
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
    def search(self, query: str, num_results: int | None = None) -> list[dict]:
        n = num_results if num_results is not None else settings.SEARCH_NUM_RESULTS
        log.debug("[provider] search query=%r num_results=%d", query, n)
        results = _do_search(query, max_results=n)
        log.debug("[provider] got %d results", len(results))
        return results


# Module-level singleton — import and use directly
provider = SearchProvider()
```

### How to swap to Option A (MCP subprocess) later

Only change the body of `SearchProvider.search()`:

```python
# Option A — future replacement
async with mcp_client.connect("job-server", "python", ["-m", "app.agents.nodes.job_mcp_server"]) as session:
    result = await session.call_tool("search", {"query": query, "max_results": n})
    return parse_results(result)
```

`job_workflow.py` and `jobs.py` do not change at all.

---

## Workflow Changes

### File: `app/agents/job_workflow.py`

### What changed

- Removed `from app.agents.tools.web_search import web_search`
- Removed `from app.agents.tools.browse_jobs import browse_fetch` (unused)
- Added `from app.agents.search_provider import provider`
- Replaced `web_search(user_input, num_results=num_results)` with `provider.search(user_input, num_results=num_results)`
- Added DEBUG log lines throughout so the full call chain is visible in the terminal

### Updated imports

```python
from app.agents.tools.skill_extraction import extract_skills_from_text
from app.agents.tools.browse_jobs import browse_extract
from app.agents.search_provider import provider   # ← replaces web_search()
from app.models.job import JobResult
```

### Updated search call inside `search_jobs_workflow()`

```python
# Before
raw_results = web_search(user_input, num_results=num_results)

# After
raw_results = provider.search(user_input, num_results=num_results)
```

---

## Logging Setup

### File: `app/main.py`

Switched from `INFO` to `DEBUG`:

```python
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
```

### Full log trace for one API call

When you hit `POST /api/v1/jobs/search` you will see this exact sequence:

```
[INFO]  app.api.v1.jobs                  [search] user_input='react developer' num_results=6
[DEBUG] app.agents.job_workflow          [workflow] starting search: 'react developer' (num_results=6)
[DEBUG] app.agents.search_provider       [provider] search query='react developer' num_results=6
[INFO]  app.agents.nodes.job_mcp_server  [mcp:search] query='react developer' max_results=6
[DEBUG] app.agents.nodes.job_mcp_server  [mcp:search] SearXNG returned 6 raw results
[DEBUG] app.agents.nodes.job_mcp_server  [mcp:search] [1] title='React Developer' url=https://...
[DEBUG] app.agents.nodes.job_mcp_server  [mcp:search] [2] title='...' url=https://...
[INFO]  app.agents.nodes.job_mcp_server  [mcp:search] returning 6 results
[DEBUG] app.agents.search_provider       [provider] got 6 results
[DEBUG] app.agents.job_workflow          [workflow] SearXNG returned 6 raw results
[DEBUG] app.agents.job_workflow          [workflow] [1/6] processing url='https://...' title='React Developer'
[DEBUG] app.agents.job_workflow          [workflow] [1] fetching page via camofox: 'https://...'
[DEBUG] app.agents.job_workflow          [workflow] [1] extract succeeded, keys=['title', 'company', ...]
[INFO]  app.agents.job_workflow          [workflow] [1] job_type='remote'  title='React Developer'  url='https://...'
...
[INFO]  app.agents.job_workflow          [workflow] done — 6 jobs extracted
[INFO]  app.api.v1.jobs                  [search] returning 6 jobs
```

> If you do NOT see `[mcp:search]` lines, `SearchProvider` is not wired to `_do_search()` correctly.
> If you see `[mcp:search]` lines, the MCP server code is confirmed running during the API call.

---

## Updated Data Flow

```
POST /api/v1/jobs/search  { user_input, num_results }
  └─► jobs.py
        └─► search_jobs_workflow(user_input, num_results)
              └─► provider.search(user_input, num_results)        [search_provider.py]
                    └─► _do_search(query, max_results)            [job_mcp_server.py]
                          └─► GET {SEARXNG_URL}/search            [SearXNG → list[dict]]
              └─► for each result:
                    └─► browse_extract(url, JOB_EXTRACT_SCHEMA)   [camofox → Ollama → JSON]
                          └─► on failure: fallback to snippet + extract_skills_from_text()
                    └─► _categorize_job_type(extracted, description)
                    └─► JobResult(...)
              └─► returns List[JobResult]
```

---

## Option A vs Option B — Decision Guide

| | Option B (current) | Option A (future) |
|---|---|---|
| How search runs | `_do_search()` called in-process | MCP server runs as subprocess, client connects via stdio |
| Overhead | Zero — same process, same log stream | Subprocess startup per request (or keep-alive) |
| Debugging | Single log stream, easy to trace | Two processes, logs split across them |
| Swap effort | N/A | Change only `SearchProvider.search()` body |
| When to use | Development, single-server deploy | Multi-agent setups, Ollama orchestrator driving the search |

---

## num_results Priority Order

When a search is triggered, `num_results` is resolved in this order (highest priority first):

1. Value passed in the API request body `{ "num_results": N }`
2. `settings.SEARCH_NUM_RESULTS` from `.env`
3. Hardcoded default `6` in `config.py` (only if `.env` key is missing entirely)

---

## Planned: Browse MCP Tool

The next tool to add to `job_mcp_server.py` is `browse` — wrapping `browse_fetch()` and
`browse_extract()` from `tools/browse_jobs.py` as MCP tools. This will allow the Ollama
orchestrator to call browse directly via the MCP protocol, completing the
search → browse → extract chain entirely through MCP.

```python
# Planned addition to job_mcp_server.py
@mcp.tool()
def fetch(url: str) -> str:
    """Open a job page in camofox and return its accessibility-tree snapshot."""
    return browse_fetch(url)

@mcp.tool()
def extract(url: str, schema: dict) -> str:
    """Open a job page in camofox and extract structured fields via Ollama."""
    return browse_extract(url, schema)
```
