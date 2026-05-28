# Backend Job Search & Browse Workflow Implementation

This document describes the complete job workflow implementation added to the `backend` service.
It is written so that a developer or AI agent can reproduce the same architecture from scratch
without any prior knowledge of the project.

The system supports two modes:
- **Search mode** — query SearXNG (local search engine), auto-browse each result URL via camofox,
  extract structured fields + job type via Ollama, return enriched job results.
- **Browse mode** *(kept for reference, endpoint removed — see note below)* — open a specific job
  page URL in a real browser (camofox), return either a free-form snapshot or structured extracted fields.

> **Current state:** The `/browse` endpoint has been removed. Only `/search` exists.
> The browse *tools* (`browse_fetch`, `browse_extract`) are still present and are now called
> automatically inside the search workflow for every result URL.

---

## External Services Required

| Service | Default URL | Purpose |
|---|---|---|
| SearXNG | `http://localhost:8080` | Local web search engine used for job queries |
| camofox | `http://localhost:3000` | Headless browser that returns accessibility-tree snapshots |
| Ollama | `http://localhost:11434` | Local LLM used for structured field extraction (called for every search result) |

All three services must be running locally before starting the backend.

> Previously Ollama was only required for `browse_extract` or the MCP orchestrator.
> Now it is called for **every** search result URL during the auto-browse step.

---

## Project Folder Structure (relevant files only)

```
backend/
├── app/
│   ├── api/
│   │   └── v1/
│   │       └── jobs.py                        ← API endpoint (search only — browse removed)
│   ├── models/
│   │   └── job.py                             ← Request/response Pydantic models
│   ├── core/
│   │   └── config.py                          ← Settings (SEARXNG_URL, CAMOFOX_URL, etc.)
│   └── agents/
│       ├── job_workflow.py                    ← Unified workflow entrypoint (search + auto-browse)
│       ├── search_jobs.py                     ← Original search-only workflow (kept for reference)
│       ├── tools/
│       │   ├── __init__.py                    ← Exports all tools
│       │   ├── web_search.py                  ← SearXNG search tool
│       │   ├── skill_extraction.py            ← Keyword-based skill extractor
│       │   └── browse_jobs.py                 ← camofox fetch + extract tool
│       └── nodes/
│           ├── search_jobs.py                 ← Node: calls web_search, stores raw_jobs
│           ├── extract_skills.py              ← Node: adds skills to raw_jobs
│           ├── job_mcp_server.py              ← Unified MCP server (search+fetch+extract)
│           └── job_orchestrator.py            ← MCP agent orchestrator
└── document/
    └── backend_job_search_workflow.md         ← This file
```

---

## Environment Variables

Add these to `backend/.env`:

```env
MONGODB_URI=mongodb://localhost:27017
OPENAI_API_KEY=<your-key>
SEARXNG_URL=http://localhost:8080
CAMOFOX_URL=http://localhost:3000
```

`CAMOFOX_URL` defaults to `http://localhost:3000` if not set.

---

## Logging / Debug Setup

### File

- `backend/app/main.py`

### What was added

```python
import logging

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
```

This is configured at application startup so every module that calls `logging.getLogger(__name__)`
will emit logs to the console at DEBUG level and above.

### What you will see in the terminal

Every search request produces a stream of logs like:

```
2024-01-01 12:00:00 [INFO]  app.api.v1.jobs: [search] user_input='react developer' num_results=6
2024-01-01 12:00:00 [DEBUG] app.agents.job_workflow: [workflow] starting search: 'react developer' (num_results=6)
2024-01-01 12:00:01 [DEBUG] app.agents.job_workflow: [workflow] SearXNG returned 6 raw results
2024-01-01 12:00:01 [DEBUG] app.agents.job_workflow: [workflow] [1/6] processing url='https://...' title='React Developer'
2024-01-01 12:00:01 [DEBUG] app.agents.job_workflow: [workflow] [1] fetching page via camofox: 'https://...'
2024-01-01 12:00:04 [DEBUG] app.agents.job_workflow: [workflow] [1] extract succeeded, keys=['title', 'company', ...]
2024-01-01 12:00:04 [INFO]  app.agents.job_workflow: [workflow] [1] job_type='remote'  title='React Developer'  url='https://...'
```

In addition, a `print` block is emitted to stdout for each job showing the full JSON structure:

```
============================================================
[JOB 1/6]  job_type='remote'
{
  "title": "React Developer",
  "company": "Acme Corp",
  "location": "Remote",
  "description": "...",
  "url": "https://...",
  "skills": ["react", "javascript"],
  "job_type": "remote"
}
============================================================
```

---

## API Endpoints

All endpoints live in `backend/app/api/v1/jobs.py`.

### Search endpoint (only endpoint — browse removed)

- **Path:** `POST /api/v1/jobs/search`
- **Request model:** `JobSearchRequest`
- **Response model:** `List[JobResult]`
- **What it does:**
  1. Accepts a natural-language job query
  2. Searches SearXNG for up to `num_results` (default **6**) results
  3. For each result URL, automatically opens the page in camofox and extracts structured fields via Ollama
  4. Falls back to SearXNG snippet + keyword skill extraction if browse/extract fails
  5. Returns enriched `JobResult` list including `job_type`

### Browse endpoint *(removed)*

- **Path:** `POST /api/v1/jobs/browse` — **no longer exists**
- The browse *tools* (`browse_fetch`, `browse_extract`) still exist in `tools/browse_jobs.py`
  and are called internally by the search workflow. They are not exposed as a separate endpoint.

---

## Request and Response Models

### File

- `backend/app/models/job.py`

### Models

- `JobSearchRequest`
  - `user_input: str` — natural language job search query
  - `num_results: int = 6` — how many results to fetch from SearXNG *(default changed from 10 → 6)*

- `JobBrowseRequest` *(kept in codebase for reference but no longer used by any endpoint)*
  - `url: str` — full URL of the job page to open
  - `schema_fields: Optional[dict] = None` — JSON Schema for extraction; omit for free-form fetch

- `JobResult`
  - `title: str`
  - `company: str`
  - `location: Optional[str]`
  - `description: str`
  - `url: Optional[str]`
  - `skills: Optional[List[str]]`
  - `job_type: Optional[str]` *(new)* — categorized job type, e.g. `full-time`, `remote`, `contract`

---

## Configuration

### File

- `backend/app/core/config.py`

### Settings class

```python
class Settings(BaseSettings):
    MONGODB_URI: str
    OPENAI_API_KEY: str
    SEARXNG_URL: str
    CAMOFOX_URL: str = "http://localhost:3000"

    class Config:
        env_file = ".env"
```

---

## Unified Workflow Entrypoint

### File

- `backend/app/agents/job_workflow.py`

### Purpose

Single file containing the search workflow called by the API layer.
It now performs a full search → browse → extract pipeline for every result.

### JOB_EXTRACT_SCHEMA (defined at module level)

This JSON Schema is passed to `browse_extract` for every job URL.
It tells Ollama exactly which fields to pull from the page:

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

### Functions

**`_categorize_job_type(extracted, description) -> str`** *(private helper)*
- Reads `job_type` from the Ollama-extracted dict
- If missing or `"unknown"`, scans the description text for keywords:
  `internship`, `contract`, `freelance`, `part-time`, `remote`, `hybrid`, `full-time`
- Returns the matched keyword (spaces replaced with `-`) or `"unknown"`

**`search_jobs_workflow(user_input, num_results=6) -> List[dict]`**

Step-by-step:
1. Calls `web_search(user_input, num_results)` → raw SearXNG results
2. For each result:
   - Reads `url`, `title`, `description/snippet` from the raw result
   - If URL is valid (`http://` or `https://`):
     - Calls `browse_extract(url, JOB_EXTRACT_SCHEMA)` → JSON string from Ollama
     - Parses JSON into `extracted` dict
     - On failure: logs a warning, `extracted` stays `{}`
   - Builds a `JobResult` using extracted fields, falling back to SearXNG snippet values
   - Calls `_categorize_job_type(extracted, description)` to set `job_type`
   - Prints full JSON + job_type to stdout (debug visibility)
   - Appends serialized `JobResult` dict to results list
3. Returns the list

> The original `browse_jobs_workflow` function has been removed from this file.
> The original `backend/app/agents/search_jobs.py` is kept unchanged for reference.

---

## Tools Layer

### Web search tool (original, unchanged)

- **File:** `backend/app/agents/tools/web_search.py`
- **Function:** `web_search(query: str, num_results: int = 10) -> list[dict]`
- **Behavior:**
  - Calls `GET {SEARXNG_URL}/search?q=...&format=json`
  - Returns up to `num_results` raw result dicts from SearXNG
  - Returns `[]` on any error

### Skill extraction tool (original, unchanged)

- **File:** `backend/app/agents/tools/skill_extraction.py`
- **Function:** `extract_skills_from_text(text: str) -> List[str]`
- **Behavior:**
  - Normalizes text to lowercase
  - Matches against a hardcoded `SKILL_KEYWORDS` list (python, react, docker, aws, etc.)
  - Returns unique matched keywords
  - Used as fallback when `browse_extract` does not return skills

### Browse tool (original, unchanged — now called automatically)

- **File:** `backend/app/agents/tools/browse_jobs.py`
- **Functions:**
  - `browse_fetch(url: str) -> str`
    - Opens `url` in camofox via `POST {CAMOFOX_URL}/tabs/open`
    - Waits 2 seconds for the page to settle
    - Calls `GET {CAMOFOX_URL}/tabs/{tabId}/snapshot` to get the accessibility tree
    - Closes the tab, truncates snapshot to 40,000 chars, returns it
  - `browse_extract(url: str, schema: dict, model_name: str) -> str`
    - Runs `browse_fetch` to get the snapshot
    - Sends snapshot + JSON Schema to a local Ollama model with `format="json"`
    - Returns a clean JSON string with extracted fields (missing fields set to `null`)

#### How camofox tab lifecycle works

```
POST /tabs/open  { userId, url }  →  { tabId }
GET  /tabs/{tabId}/snapshot       →  accessibility-tree text
DELETE /tabs/{tabId}              →  closes the tab
```

Each call uses a one-shot `userId` (`oneshot-<random>`) so tabs don't persist between calls.

### Tool package exports

- **File:** `backend/app/agents/tools/__init__.py`
- **Exports:**
  - `web_search`
  - `extract_skills_from_text`
  - `browse_fetch`
  - `browse_extract`

---

## Agent Node Files

### Search jobs node (original, unchanged)

- **File:** `backend/app/agents/nodes/search_jobs.py`
- **Behavior:**
  - Calls `web_search(...)`
  - Stores the result in `state["raw_jobs"]`

### Extract skills node (original, unchanged)

- **File:** `backend/app/agents/nodes/extract_skills.py`
- **Behavior:**
  - Reads `state["raw_jobs"]`
  - Adds `skills` to each job entry using `extract_skills_from_text(...)`
  - Stores transformed jobs in `state["jobs_with_skills"]`

### Unified MCP server (original, unchanged)

- **File:** `backend/app/agents/nodes/job_mcp_server.py`
- **Purpose:** A single MCP server that exposes all three tools to an LLM agent via the MCP protocol.
- **Tools exposed:**
  - `search(query, max_results)` — calls SearXNG, appends detected skills to each result
  - `fetch(url)` — opens URL in camofox, returns snapshot
  - `extract(url, schema)` — opens URL in camofox, runs Ollama extraction, returns JSON
- **Run with:** `python -m app.agents.nodes.job_mcp_server`
- **Transport:** stdio (standard MCP stdio transport)

### Job orchestrator agent (original, unchanged)

- **File:** `backend/app/agents/nodes/job_orchestrator.py`
- **Purpose:** An interactive CLI agent that connects to `job_mcp_server` and uses an Ollama LLM to answer job search questions by chaining tool calls.
- **Agent loop:**
  1. User types a question
  2. Ollama decides which tool to call (always starts with `search`)
  3. After search results arrive, Ollama calls `fetch` or `extract` on the best URL
  4. Final answer is printed with the source URL cited
- **Tool chaining:** If Ollama returns another tool call after a tool result, the agent recurses (`handle_tools` calls itself). This allows unlimited search → fetch → extract chains.
- **Empty response guard:** If Ollama returns an empty response after a tool result, the agent sends a nudge message and retries once.
- **Run with:** `python -m app.agents.nodes.job_orchestrator`
- **Config via env vars:**
  - `OLLAMA_MODEL` (default: `llama3`)
  - `OLLAMA_TEMPERATURE` (default: `0.0`)
  - `AGENT_HISTORY_DIR` (default: `agent_history`)
  - `MAX_TOOL_RESULT_CHARS` (default: `8000`)

#### MCP connection pattern used in orchestrator

```python
# Each MCP server is connected by name. Tools are prefixed: "{server-name}_{tool-name}"
await agent.connect("job-server", "python", ["-m", "app.agents.nodes.job_mcp_server"])

# Tool dispatch: strip prefix to get real tool name, call via MCP session
real_name = prefixed_name[len(server_name) + 1:]
result = await session.call_tool(real_name, args)
```

---

## Data Flow

### Search flow (current — includes auto-browse)

```
Client
  └─► POST /api/v1/jobs/search  { user_input, num_results=6 }
        └─► jobs.py  →  search_jobs_workflow(user_input, num_results)
              └─► web_search(user_input)                    [calls SearXNG → 6 raw results]
              └─► for each result:
                    └─► browse_extract(url, JOB_EXTRACT_SCHEMA)  [camofox → Ollama → JSON]
                          └─► on failure: fallback to SearXNG snippet + extract_skills_from_text()
                    └─► _categorize_job_type(extracted, description)
                    └─► JobResult(title, company, location, description, url, skills, job_type)
                    └─► print JSON + job_type to stdout
              └─► returns List[JobResult]
```

### Browse flow *(reference only — endpoint removed)*

```
Client
  └─► POST /api/v1/jobs/browse  { url, schema_fields? }   ← ENDPOINT NO LONGER EXISTS
        └─► jobs.py  →  browse_jobs_workflow(url, schema_fields)
              ├─► [no schema]  browse_fetch(url)
              │     └─► camofox: open tab → snapshot → close tab
              │     └─► returns { mode: "fetch", snapshot: "..." }
              └─► [with schema]  browse_extract(url, schema)
                    └─► camofox: open tab → snapshot → close tab
                    └─► Ollama: snapshot + schema → JSON
                    └─► returns { mode: "extract", data: {...} }
```

### MCP agent flow (orchestrator — unchanged, CLI only)

```
User input
  └─► Ollama decides: call search(query)
        └─► job_mcp_server.search()  →  SearXNG results + skills
  └─► Ollama decides: call fetch(url) or extract(url, schema)
        └─► job_mcp_server.fetch/extract()  →  camofox snapshot / JSON
  └─► Ollama produces final answer citing the URL
```

---

## Running the Backend

1. Activate the virtual environment:
   ```powershell
   cd "d:\AI Projects\job_project\project\backend"
   .\.venv\Scripts\Activate.ps1
   ```
2. Install dependencies if needed:
   ```powershell
   pip install -r requirements.txt
   ```
3. Start the FastAPI server:
   ```powershell
   uvicorn app.main:app --reload
   ```
4. Send request to:
   ```http
   POST http://127.0.0.1:8000/api/v1/jobs/search
   ```

---

## Example Requests

### Search (only endpoint)

```json
POST /api/v1/jobs/search
{
  "user_input": "React developer FastAPI Python 4 years experience 16 LPA gen AI",
  "num_results": 6
}
```

**Example response item:**

```json
{
  "title": "Senior React Developer",
  "company": "Acme Corp",
  "location": "Remote",
  "description": "We are looking for a React developer with 4+ years experience...",
  "url": "https://example.com/jobs/123",
  "skills": ["react", "javascript", "python"],
  "job_type": "remote"
}
```

### Browse — fetch mode *(reference only — endpoint removed)*

```json
POST /api/v1/jobs/browse
{
  "url": "https://www.linkedin.com/jobs/view/123456789"
}
```

### Browse — extract mode *(reference only — endpoint removed)*

```json
POST /api/v1/jobs/browse
{
  "url": "https://www.linkedin.com/jobs/view/123456789",
  "schema_fields": {
    "type": "object",
    "properties": {
      "title":    { "type": "string", "description": "Job title" },
      "company":  { "type": "string", "description": "Hiring company name" },
      "salary":   { "type": "string", "description": "Salary or compensation range" },
      "location": { "type": "string", "description": "Job location or remote status" },
      "skills":   { "type": "array", "items": { "type": "string" },
                    "description": "Required skills listed in the posting" }
    }
  }
}
```

---

## Planned: Store Jobs to MongoDB

The search workflow currently prints extracted jobs to stdout for inspection.
The next step is to persist them to MongoDB, categorized by `job_type`.

Planned collection structure:

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

Jobs will be stored in a collection named after their `job_type` (e.g. `jobs_remote`, `jobs_contract`)
or in a single `jobs` collection with `job_type` as a filter field — TBD.

---

## Notes

- The endpoint accepts a `db` dependency but the database is not used yet — jobs are only printed to stdout.
- The implementation uses a local SearXNG endpoint and does not require Tavily or any paid search API.
- The code is intentionally modular: search logic, browse logic, and skill extraction are all separate tools that can be replaced or extended independently.
- The original `search_jobs.py` workflow and node files are preserved. The new `job_workflow.py` is the unified entrypoint going forward.
- The MCP server (`job_mcp_server.py`) and orchestrator (`job_orchestrator.py`) are optional — they are used for the interactive CLI agent mode, not required for the REST API to work.
- Ollama is now called for **every** search result URL (via `browse_extract`). If Ollama is not running, the workflow falls back gracefully to SearXNG snippet data and keyword-based skill extraction.
- If camofox is not running, `browse_extract` will raise an exception which is caught and logged; the job is still returned using SearXNG snippet data.
