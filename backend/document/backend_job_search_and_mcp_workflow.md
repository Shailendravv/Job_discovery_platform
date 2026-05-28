# Backend Job Search + MCP Workflow Implementation

This document combines the backend job search workflow and MCP search integration into a single, standalone implementation guide.
A developer or AI agent with no prior context should be able to reproduce the architecture from scratch.

## Overview

The backend service exposes a single REST endpoint for job search.
It performs a multi-step pipeline:
1. Search SearXNG for job listings
2. Auto-browse each result URL with camofox
3. Extract structured fields from the page using Ollama
4. Return enriched job results with skills and job type metadata

Additionally, the implementation includes an MCP abstraction layer for search.
The workflow uses a local in-process search provider today, but the design is ready to swap to a full MCP subprocess later.

## Required External Services

| Service | Default URL | Purpose |
| --- | --- | --- |
| SearXNG | `http://localhost:8080` | Local search engine for job queries |
| camofox | `http://localhost:3000` | Headless browser that returns accessibility snapshots |
| Ollama | `http://localhost:11434` | Local LLM used for structured extraction |

All three services must be running locally before starting the backend.

## Project Structure

Relevant backend files:

```
backend/
├── app/
│   ├── api/
│   │   └── v1/
│   │       └── jobs.py
│   ├── agents/
│   │   ├── __init__.py
│   │   ├── job_workflow.py
│   │   ├── search_provider.py
│   │   ├── nodes/
│   │   │   ├── job_mcp_server.py
│   │   │   ├── job_orchestrator.py
│   │   │   ├── extract_skills.py
│   │   │   └── search_jobs.py
│   │   └── tools/
│   │       ├── __init__.py
│   │       ├── browse_jobs.py
│   │       ├── skill_extraction.py
│   │       └── web_search.py
│   ├── core/
│   │   └── config.py
│   └── models/
│       └── job.py
└── document/
    └── backend_job_search_and_mcp_workflow.md
```

## Environment Variables

Add these values to `backend/.env`:

```env
MONGODB_URI=mongodb://localhost:27017
OPENAI_API_KEY=<your-key>
SEARXNG_URL=http://localhost:8080
CAMOFOX_URL=http://localhost:3000
SEARCH_NUM_RESULTS=6
```

`CAMOFOX_URL` defaults to `http://localhost:3000` if not set.
`SEARCH_NUM_RESULTS` defaults to `6` in code if the env var is absent.

## Logging

Logging is configured at startup in `backend/app/main.py`:

```python
import logging

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
```

This ensures module-level loggers emit debug and info output to the console.

## API Endpoint

### Search endpoint

- Path: `POST /api/v1/jobs/search`
- Request model: `JobSearchRequest`
- Response model: `List[JobResult]`

What it does:
1. Accepts a natural-language job query
2. Searches SearXNG for up to `num_results` results
3. For each result URL, automatically opens the page in camofox and extracts structured fields via Ollama
4. Falls back to SearXNG snippet + keyword skill extraction if extract fails
5. Returns enriched `JobResult` items including `job_type`

> The old `browse` endpoint has been removed. Browse tools still exist internally but are no longer exposed by the API.

## Request and Response Models

Defined in `backend/app/models/job.py`.

### Models

- `JobSearchRequest`
  - `user_input: str`
  - `num_results: int = 6`
- `JobResult`
  - `title: str`
  - `company: str`
  - `location: Optional[str]`
  - `description: str`
  - `url: Optional[str]`
  - `skills: Optional[List[str]]`
  - `job_type: Optional[str]`

> `JobBrowseRequest` may still exist in code for reference but is not used by any endpoint.

## Configuration

### File: `backend/app/core/config.py`

The settings class reads environment variables and provides defaults:

```python
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    MONGODB_URI: str
    OPENAI_API_KEY: str
    SEARXNG_URL: str
    CAMOFOX_URL: str = "http://localhost:3000"
    SEARCH_NUM_RESULTS: int = 6

    class Config:
        env_file = ".env"

settings = Settings()
```

## Unified Workflow Entrypoint

### File: `backend/app/agents/job_workflow.py`

This file contains the search workflow entrypoint used by the API.
It orchestrates the search → browse → extract pipeline for every result.

### JOB_EXTRACT_SCHEMA

A JSON schema passed to Ollama to extract structured fields from each job page:

```python
JOB_EXTRACT_SCHEMA = {
    "type": "object",
    "properties": {
        "title":       {"type": "string",  "description": "Job title"},
        "company":     {"type": "string",  "description": "Hiring company name"},
        "location":    {"type": "string",  "description": "Job location or remote status"},
        "description": {"type": "string",  "description": "Full job description or summary"},
        "salary":      {"type": "string",  "description": "Salary or compensation range"},
        "skills":      {"type": "array",   "items": {"type": "string"},
                         "description": "Required skills listed in the posting"},
        "job_type":    {"type": "string",
                         "description": "One of: full-time, part-time, contract, internship, freelance, remote, on-site, hybrid, unknown"},
    },
}
```

### Workflow behavior

`search_jobs_workflow(user_input, num_results=6)` performs:
1. `provider.search(user_input, num_results=num_results)` to obtain raw results
2. For each result:
   - Read `url`, `title`, and snippet description
   - If the URL is valid, call `browse_extract(url, JOB_EXTRACT_SCHEMA)`
   - Parse the returned JSON into `extracted`
   - On failure, log a warning and continue with fallback fields
   - Build a `JobResult`, using extracted data when available and falling back to SearXNG snippet values
   - Determine `job_type` with `_categorize_job_type(extracted, description)`
   - Print the full job JSON to stdout for debug visibility
3. Return the list of serialized `JobResult` dictionaries

### Job type categorization

A helper reads `job_type` from Ollama output and falls back to keyword scanning of the job description for:
- `internship`
- `contract`
- `freelance`
- `part-time`
- `remote`
- `hybrid`
- `full-time`

If no match is found, it returns `unknown`.

## Tools Layer

### Web search tool

File: `backend/app/agents/tools/web_search.py`

Function: `web_search(query: str, num_results: int = 10) -> list[dict]`

Behavior:
- Calls `GET {SEARXNG_URL}/search?q=...&format=json`
- Returns up to `num_results` raw result dictionaries
- Returns `[]` on any HTTP error

### Skill extraction tool

File: `backend/app/agents/tools/skill_extraction.py`

Function: `extract_skills_from_text(text: str) -> List[str]`

Behavior:
- Normalizes text to lowercase
- Matches against a hardcoded keyword list
- Returns unique matched skills
- Used as fallback when Ollama extraction does not produce skills

### Browse tool

File: `backend/app/agents/tools/browse_jobs.py`

Functions:

- `browse_fetch(url: str) -> str`
  - Opens the URL in camofox via `POST {CAMOFOX_URL}/tabs/open`
  - Waits for the page to settle
  - Retrieves the accessibility snapshot via `GET {CAMOFOX_URL}/tabs/{tabId}/snapshot`
  - Closes the tab and returns a truncated snapshot

- `browse_extract(url: str, schema: dict, model_name: str) -> str`
  - Fetches the page snapshot via `browse_fetch`
  - Sends the snapshot plus the schema to Ollama with `format="json"`
  - Returns a clean JSON string with extracted fields

### Tool package exports

File: `backend/app/agents/tools/__init__.py`

Exports all tools for use by the workflow:
- `web_search`
- `extract_skills_from_text`
- `browse_fetch`
- `browse_extract`

## MCP Search Integration

### Design Rationale

The workflow is abstracted from its search backend via two layers:
1. **Core search function** — pure, importable, returns raw data
2. **MCP layer** — formats output for LLM agents

This enables two deployment modes:
- **Option B (current)**: in-process calls, zero overhead, single log stream
- **Option A (future)**: MCP subprocess, separates concerns, enables multi-agent scaling

### Search Provider

File: `backend/app/agents/search_provider.py`

A singleton class that abstracts the search backend. Today it imports and calls `_do_search()` directly.
To switch to Option A later, only the body of the `search()` method needs to change — all callers stay the same.

```python
from app.agents.nodes.job_mcp_server import _do_search

class SearchProvider:
    def search(self, query: str, num_results: int | None = None) -> list[dict]:
        n = num_results if num_results is not None else settings.SEARCH_NUM_RESULTS
        results = _do_search(query, max_results=n)
        return results

provider = SearchProvider()
```

### MCP Server

File: `backend/app/agents/nodes/job_mcp_server.py`

This file exports two layers:

**`_do_search(query: str, max_results: int | None = None) -> list[dict]`**
- Pure function that calls SearXNG directly
- Returns raw result dictionaries
- Importable by other modules (used by `SearchProvider`)
- Resolves `max_results=None` to `settings.SEARCH_NUM_RESULTS`

**`@mcp.tool() search(query: str, max_results: int | None = None) -> str`**
- MCP protocol wrapper around `_do_search()`
- Formats results as a readable string for LLM agents
- Designed for the Ollama orchestrator (see below)

Full implementation stub:

```python
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
    log.info("[mcp:search] returning %d results", len(results))
    return results

@mcp.tool()
def search(query: str, max_results: int | None = None) -> str:
    """
    Search the web via a local SearXNG instance. Use this tool for any
    question that requires current or specific information such as job listings.
    Returns the top results with title, URL, and snippet.
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

Run standalone: `python -m app.agents.nodes.job_mcp_server`

## Agent Nodes

### Search jobs node

File: `backend/app/agents/nodes/search_jobs.py`

Calls `web_search()` and stores results in `state["raw_jobs"]`.
Kept for reference — not used by the current API workflow.

### Extract skills node

File: `backend/app/agents/nodes/extract_skills.py`

Reads `state["raw_jobs"]` and adds `skills` using `extract_skills_from_text()`.
Stored in `state["jobs_with_skills"]`.
Kept for reference — not used by the current unified workflow.

### Job orchestrator agent

File: `backend/app/agents/nodes/job_orchestrator.py`

An interactive CLI agent that connects to `job_mcp_server` and uses Ollama to answer questions by chaining tool calls.

Behavior:
1. User enters a question
2. Ollama calls the `search` tool
3. Ollama then calls `fetch` or `extract` on the best result
4. Final answer is printed with the source URL

Run: `python -m app.agents.nodes.job_orchestrator`

Configuration via environment:
- `OLLAMA_MODEL` (default: `llama3`)
- `OLLAMA_TEMPERATURE` (default: `0.0`)
- `AGENT_HISTORY_DIR` (default: `agent_history`)
- `MAX_TOOL_RESULT_CHARS` (default: `8000`)

## Data Flow

### Current workflow (Option B — in-process)

```
POST /api/v1/jobs/search  { user_input, num_results }
  ↓
jobs.py: search_jobs_workflow(user_input, num_results)
  ↓
search_provider.py: provider.search(user_input, num_results)
  ↓
job_mcp_server.py: _do_search(query, max_results)
  ↓
GET {SEARXNG_URL}/search?q=...&format=json  →  list[dict]
  ↓
For each result:
  └─ browse_extract(url, JOB_EXTRACT_SCHEMA)
      ├─ camofox: open → snapshot → close
      └─ Ollama: snapshot + schema → JSON
  └─ Fallback to SearXNG snippet + keyword skills
  └─ Build JobResult + categorize job_type
  └─ Print to stdout
  ↓
Return List[JobResult]
```

### Future workflow (Option A — MCP subprocess)

Option A is not yet implemented but the design supports it.
The only change would be to `SearchProvider.search()`:

```python
# Option A — future
async with mcp_client.connect(
    "job-server",
    "python",
    ["-m", "app.agents.nodes.job_mcp_server"]
) as session:
    result = await session.call_tool("search", {"query": query, "max_results": n})
    return parse_results(result)
```

`job_workflow.py`, `jobs.py`, and all callers remain unchanged.

### MCP orchestrator flow (CLI agent)

```
User: "Find a remote React job"
  ↓
job_orchestrator.py connects to job_mcp_server via MCP stdio
  ↓
Ollama calls: search(query="React developer remote")
  ↓
job_mcp_server: search tool returns formatted results
  ↓
Ollama calls: fetch(url=best_result_url)  or  extract(url=..., schema=...)
  ↓
job_mcp_server: returns snapshot or extracted JSON
  ↓
Ollama produces answer with source URL
```

## API Example

### Search request

```json
POST /api/v1/jobs/search
Content-Type: application/json

{
  "user_input": "React developer Python 4 years experience remote",
  "num_results": 6
}
```

### Search response

```json
[
  {
    "title": "Senior React Developer",
    "company": "Acme Corp",
    "location": "Remote",
    "description": "We are looking for a React developer with 4+ years...",
    "url": "https://example.com/jobs/123",
    "skills": ["react", "javascript", "typescript", "python"],
    "job_type": "remote"
  },
  ...
]
```

## Logging Output

When a search is executed, you will see logs like:

```
[INFO]  app.api.v1.jobs                  [search] user_input='react developer' num_results=6
[DEBUG] app.agents.job_workflow          [workflow] starting search: 'react developer' (num_results=6)
[DEBUG] app.agents.search_provider       [provider] search query='react developer' num_results=6
[INFO]  app.agents.nodes.job_mcp_server  [mcp:search] query='react developer' max_results=6
[DEBUG] app.agents.nodes.job_mcp_server  [mcp:search] SearXNG returned 6 raw results
[DEBUG] app.agents.job_workflow          [workflow] [1/6] processing url='https://...' title='React Developer'
[DEBUG] app.agents.job_workflow          [workflow] [1] fetching page via camofox: 'https://...'
[DEBUG] app.agents.job_workflow          [workflow] [1] extract succeeded, keys=['title', 'company', ...]
[INFO]  app.agents.job_workflow          [workflow] [1] job_type='remote'  title='React Developer'  url='https://...'
```

## Starting the Backend

Activate the virtual environment:
```powershell
cd "d:\AI Projects\job_project\project\backend"
.\.venv\Scripts\Activate.ps1
```

Install dependencies:
```powershell
pip install -r requirements.txt
```

Start the FastAPI server:
```powershell
uvicorn app.main:app --reload
```

Send requests to:
```
POST http://127.0.0.1:8000/api/v1/jobs/search
```

## num_results Priority

When a search is triggered, `num_results` is resolved in this order:
1. Value in the API request body `{ "num_results": N }`
2. `settings.SEARCH_NUM_RESULTS` from `.env`
3. Hardcoded default `6` in `config.py` (only if `.env` key is missing)

## Future Enhancements

### Browse MCP Tool

The next planned addition is to expose `browse` functionality as MCP tools:

```python
@mcp.tool()
def fetch(url: str) -> str:
    """Open a job page in camofox and return its snapshot."""
    return browse_fetch(url)

@mcp.tool()
def extract(url: str, schema: dict) -> str:
    """Open a job page in camofox and extract structured fields via Ollama."""
    return browse_extract(url, schema)
```

This will allow the Ollama orchestrator to call `browse` directly via MCP.

### MongoDB Persistence

The workflow currently prints jobs to stdout. The next phase is to persist them to MongoDB:

Planned collection:
```json
{
  "_id": "<ObjectId>",
  "title": "Senior React Developer",
  "company": "Acme Corp",
  "location": "Remote",
  "description": "...",
  "url": "https://example.com/jobs/123",
  "skills": ["react", "javascript"],
  "job_type": "remote",
  "created_at": "2024-01-01T12:00:00Z"
}
```

## Summary

This architecture provides:
- **Single REST endpoint** for job search with enriched results
- **Modular tools** that can be composed or replaced independently
- **Abstracted search backend** ready to scale from in-process to MCP subprocess
- **Debug logging** at every step for traceability
- **Fallback behavior** when Ollama or camofox is unavailable
- **Extensible design** for future MCP tools and MongoDB persistence