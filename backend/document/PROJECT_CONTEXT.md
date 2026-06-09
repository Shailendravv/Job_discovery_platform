# Job Search Backend - Complete Project Context

**Purpose:** This document provides a comprehensive, self-contained reference for understanding, maintaining, and recreating the job search backend from scratch. It covers project goals, architecture, data flow, APIs, configuration, and implementation details.

---

## Table of Contents

1. [Project Overview](#1-project-overview)
2. [Project Goals](#2-project-goals)
3. [Architecture](#3-architecture)
4. [Folder Structure](#4-folder-structure)
5. [Dependencies](#5-dependencies)
6. [Configuration](#6-configuration)
7. [Data Flow](#7-data-flow)
8. [APIs](#8-apis)
9. [Business Logic](#9-business-logic)
10. [Workflows](#10-workflows)
11. [Setup Steps](#11-setup-steps)
12. [Deployment Process](#12-deployment-process)
13. [Implementation Details](#13-implementation-details)
14. [Troubleshooting](#14-troubleshooting)
15. [Future Improvements](#15-future-improvements)
16. [Assumptions & Inferred Context](#16-assumptions--inferred-context)

---

## 1. Project Overview

This is a **Job Search Backend API** that aggregates job listings from multiple sources (SearXNG search, LinkedIn Guest API), fetches full job descriptions using a headless browser, and extracts structured fields using a Local LLM (Ollama). The system combines traditional web scraping with modern AI-powered data extraction to provide enriched job results.

**Key Characteristics:**
- **Multi-source aggregation**: SearXNG (proxied Google/Bing/etc.) + LinkedIn Guest API
- **Automated browsing**: Uses camofox (headless browser) to fetch full job pages
- **LLM extraction**: Uses Ollama to extract structured data (title, company, salary, skills, etc.)
- **MCP integration**: Exposes tools via Model Context Protocol for agent orchestration
- **Async-first**: Built with FastAPI and async/await patterns throughout

---

## 2. Project Goals

1. **Aggregate job listings** from multiple job boards and career sites without requiring API keys for most sources
2. **Extract structured data** from unstructured job postings using local LLMs (no data sent to third parties)
3. **Provide a simple API** where frontends send only a natural language query, and the backend handles all targeting logic
4. **Support extensibility** through modular design (easy to add new search sources, extractors, or LLM providers)
5. **Enable AI agent orchestration** via MCP tools for interactive job search assistants

---

## 3. Architecture

### High-Level System Diagram

```
┌─────────────┐     ┌─────────────────┐     ┌──────────────┐
│   Client    │────▶│  FastAPI Backend│────▶│   MongoDB    │
│ (Frontend)  │     │                 │     │  (optional)  │
└─────────────┘     └─────────────────┘     └──────────────┘
                           │
                    ┌──────┴──────┐
                    ▼             ▼
           ┌──────────────────────────┐
           │   SearchProvider         │
           │  (Aggregation Layer)     │
           └─────────┬────────────────┘
                     │
         ┌───────────┼───────────┐
         ▼           ▼           ▼
    ┌────────┐ ┌─────────┐ ┌──────────┐
    │SearXNG │ │LinkedIn │ │  (Future)│
    │via MCP │ │Guest API│ │ Sources  │
    └────┬───┘ └────┬────┘ └────┬─────┘
         │          │           │
         └──────────┼───────────┘
                    ▼
         ┌─────────────────────┐
         │  Candidate Pool     │
         │  (URL deduplicated) │
         └─────────┬───────────┘
                   │
         ┌─────────▼────────────┐
         │  Browse & Extract    │
         │  (camofox + Ollama)  │
         └─────────┬────────────┘
                   │
         ┌─────────▼──────────┐
         │   JobResult List   │
         └────────────────────┘
```

### Component Overview

| Component | File(s) | Purpose |
|-----------|---------|---------|
| **API Router** | `app/api/v1/jobs.py` | Exposes `/search` endpoint, calls workflow |
| **Workflow** | `app/agents/job_workflow.py` | Orchestrates search → browse → extract pipeline |
| **SearchProvider** | `app/agents/search_provider.py` | Aggregates results from multiple search sources |
| **MCP Server** | `app/agents/nodes/job_mcp_server.py` | Exposes `search` and `search_json` tools via MCP |
| **Tools Layer** | `app/agents/tools/` | Individual tools: `web_search`, `browse_extract`, `extract_skills` |
| **MCP Client** | `app/agents/mcp_client.py` | Connects to MCP servers over Streamable HTTP |
| **Config** | `app/core/config.py` | Settings loaded from `.env` |
| **LLM** | `app/core/llm.py` | Wrapper for Ollama/Groq/Gemini providers |
| **Database** | `app/core/database.py` | MongoDB async connection (Motor) |

---

## 4. Folder Structure

```
backend/
├── app/
│   ├── __init__.py
│   ├── main.py                          # FastAPI app entry point
│   ├── api/
│   │   ├── __init__.py
│   │   ├── deps.py                      # DB dependency injector
│   │   └── v1/
│   │       ├── __init__.py
│   │       ├── jobs.py                  # POST /api/v1/jobs/search
│   │       └── resumes.py               # Resume-related endpoints (TBD)
│   ├── agents/
│   │   ├── __init__.py
│   │   ├── job_workflow.py              # Main search+browse workflow
│   │   ├── mcp_client.py                # MCP client wrapper
│   │   ├── search_provider.py           # Search backend aggregator
│   │   ├── nodes/
│   │   │   ├── __init__.py
│   │   │   ├── job_mcp_server.py        # MCP server (search tools)
│   │   │   ├── job_orchestrator.py      # CLI agent (interactive)
│   │   │   └── search_jobs.py           # Original node (deprecated)
│   │   └── tools/
│   │       ├── __init__.py
│   │       ├── web_search.py            # Direct SearXNG call
│   │       ├── browse_jobs.py           # camofox fetch/extract
│   │       └── skill_extraction.py      # Keyword skill matcher
│   ├── core/
│   │   ├── config.py                    # Settings (BaseSettings)
│   │   ├── database.py                  # MongoDB connection
│   │   └── llm.py                       # LLM provider wrapper
│   └── models/
│       ├── __init__.py
│       └── job.py                       # Pydantic models (JobSearchRequest, JobResult)
├── services/
│   └── docker-compose.yml               # camofox + searxng containers
├── document/                            # Project documentation
│   ├── backend_job_search_workflow.md
│   ├── mcp_search_integration.md
│   ├── backend_job_search_and_mcp_workflow.md
│   ├── backend_job_search_and_mcp_workflow_04_06_26.md
│   ├── backend_job_search_and_mcp_workflow_06_06_26.md
│   ├── backend_job_search_and_mcp_workflow_07_06_26.md
│   └── backend_job_search_mcp_workflow_09_06_26.md
├── .env                                # Environment variables (create from template)
├── .gitignore
├── README.md
├── requirements.txt
└── PROJECT_CONTEXT.md                  # This file
```

---

## 5. Dependencies

### Python Packages (requirements.txt)

```
fastapi                    # Web framework
uvicorn[standard]         # ASGI server
python-dotenv             # .env loading (note: pydantic-settings also loads .env)
motor                     # Async MongoDB driver
pydantic-settings         # Settings management with env var support
python-multipart          # Form data parsing
langchain                 # (unused? reserved for future)
langchain-openai          # (unused? reserved for future)
langgraph                 # (unused? reserved for future)
httpx                     # Async HTTP client
pypdf                     # PDF processing (reserved)
reportlab                 # PDF generation (reserved)
ollama                    # Ollama Python client
mcp                       # Model Context Protocol Python SDK
```

### External Services

| Service | Default URL | Purpose | Status Required |
|---------|-------------|---------|-----------------|
| **SearXNG** | `http://localhost:8888` | Privacy-respecting meta-search engine (returns JSON API) | Required if `SEARXNG_ENABLED=true` |
| **camofox** | `http://localhost:9500` | Headless browser wrapper exposing accessibility tree snapshots | Required (always called) |
| **Ollama** | `http://localhost:11434` | Local LLM for data extraction and query generation | Required |
| **MongoDB** | Configured via `MONGODB_URI` | Optional persistence layer | Optional |

### Docker Images

- `camofox-browser:latest` - Custom headless Chrome container
- `searxng/searxng:latest` - Official SearXNG image with JSON API enabled

---

## 6. Configuration

### Environment Variables (.env)

All configuration is managed through environment variables loaded via Pydantic's `BaseSettings`.

#### Required Variables

```env
MONGODB_URI=mongodb://localhost:27017
SEARXNG_URL=http://localhost:8888
CAMOFOX_URL=http://localhost:9500
```

#### Optional Variables (with defaults)

```env
# MCP Server URLs
MCP_SEARCH_URL=http://localhost:8001
MCP_BROWSE_URL=http://localhost:8002

# LLM Configuration
Ollama=http://localhost:11434
LLM_PROVIDER=ollama                # Options: ollama, groq, gemini
MODEL_NAME=qwen2.5-coder:1.5b
MODEL_TEMPERATURE=0.1
GROQ_API_KEY=                     # Required if LLM_PROVIDER=groq
GEMINI_API_KEY=                   # Required if LLM_PROVIDER=gemini

# Search Configuration
SEARCH_MAX_RESULTS=15             # Max results per source before ranking
BROWSE_TOP_N=30                   # Max candidates to browse (per source)
SEARCH_SITES=greenhouse.io,lever.co,myworkdayjobs.com
SEARCH_FRESH=true                 # Filter recent jobs
SEARCH_CAREERS=false              # Target company career pages
SETTLE_SECONDS=1.5               # Camofox page settle time
MAX_SNAPSHOT_CHARS=12000          # Max chars from accessibility tree

# Feature Toggles
SEARXNG_ENABLED=false             # Set to true to enable SearXNG search
LINKEDIN_GUEST_API_ENABLED=true  # Set to true to enable LinkedIn
LINKEDIN_GUEST_API_LOCATION=India
LINKEDIN_GUEST_API_TIME_RANGE=r86400  # Past 24 hours (r86400, r604800, etc.)
LINKEDIN_GUEST_API_MAX_RESULTS=15
LINKEDIN_MAX_RESULTS=15           # Alias for above (see note*)

# Operations
LOG_LEVEL=INFO                    # DEBUG, INFO, WARNING, ERROR
```

***Note:** There is inconsistency in the codebase: `LINKEDIN_GUEST_API_MAX_RESULTS` is defined in config.py but `LINKEDIN_MAX_RESULTS` is referenced in `job_workflow.py`. The actual used value is `settings.LINKEDIN_GUEST_API_MAX_RESULTS` after the latest fixes.

### Settings Summary (config.py)

```python
class Settings(BaseSettings):
    # Database
    MONGODB_URI: str

    # External Services
    SEARXNG_URL: str
    CAMOFOX_URL: str
    MCP_SEARCH_URL: str = "http://localhost:8001"
    MCP_BROWSE_URL: str = "http://localhost:8002"
    Ollama: str = "http://localhost:11434"

    # LLM Provider
    LLM_PROVIDER: str = "ollama"
    GROQ_API_KEY: str | None = None
    GEMINI_API_KEY: str | None = None
    MODEL_NAME: str = "qwen2.5-coder:1.5b"
    MODEL_TEMPERATURE: float = 0.1

    # Search Configuration
    SEARCH_MAX_RESULTS: int = 15
    BROWSE_TOP_N: int = 30
    SEARCH_SITES: str = "greenhouse.io,lever.co,myworkdayjobs.com"
    SEARCH_FRESH: bool = True
    SEARCH_CAREERS: bool = False
    SETTLE_SECONDS: float = 1.5
    MAX_SNAPSHOT_CHARS: int = 12000

    # Search Source Toggles
    SEARXNG_ENABLED: bool = False
    LINKEDIN_GUEST_API_ENABLED: bool  # No default - must be explicitly set
    LINKEDIN_GUEST_API_LOCATION: str = "India"
    LINKEDIN_GUEST_API_TIME_RANGE: str = "r86400"
    LINKEDIN_GUEST_API_MAX_RESULTS: int = 15

    # Operations
    LOG_LEVEL: str = "INFO"
```

---

## 7. Data Flow

### Search Request Flow (Current - 2026-06-09)

```
POST /api/v1/jobs/search
{
  "user_input": "React developer Python 4 years experience remote"
}

Response: [
  {
    "title": "Senior React Developer",
    "company": "Acme Corp",
    "location": "Remote",
    "description": "Full job description...",
    "url": "https://example.com/jobs/123",
    "apply_url": "https://example.com/apply/123",
    "skills": ["react", "javascript", "python"],
    "job_type": "remote",
    "posted_date": "2 days ago",
    "salary": "$120k-$150k",
    "source": "searxng"
  },
  ...
]
```

### Detailed Internal Flow

1. **API Layer** (`jobs.py:search_jobs`)
   - Receives `JobSearchRequest` with `user_input`
   - Logs request details
   - Calls `search_jobs_workflow(user_input)`

2. **Query Generation** (`job_workflow.py:_build_queries_dynamic`)
   - Attempts LLM-based query generation using `call_llm()`
   - LLM returns JSON array of up to 3 queries targeting configured `SEARCH_SITES`
   - On failure, falls back to `_parse_user_input()` + `_build_queries()`
   - Each query uses `site:` operator (e.g., `"React developer site:greenhouse.io"`)

3. **Concurrent Search** (`job_workflow.py:search_jobs_workflow`)
   ```
   For each query:
     ├─ SearXNG (if SEARXNG_ENABLED=true)
     │   └─ provider._search_mcp_async() → job_mcp_server.search_json()
     │       └─ GET {SEARXNG_URL}/search?q={query}&format=json
     │
     └─ LinkedIn (if LINKEDIN_GUEST_API_ENABLED=true)
         └─ provider._search_linkedin_async()
             └─ GET https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search
             └─ For each job: GET {job_url} to fetch full description
   ```

4. **Source-Specific Deduplication**
   - Each source maintains independent `seen_urls` set
   - `_collect_unique_urls_only()` filters duplicates within that source
   - This fixes the bug where LinkedIn results were being filtered by SearXNG URLs

5. **LLM Ranking** (`job_workflow.py:_rank_and_trim_dynamic`)
   - Creates snippets with title + URL + content/description for all candidates
   - Calls LLM to score each candidate 0-10 against the original user query
   - Returns top `SEARCH_MAX_RESULTS * 2` candidates per source for browsing

6. **Browse & Extract Phase** (`job_workflow.py:_browse_and_build`)
   ```
   For each candidate:
     ├─ browse_extract(url, JOB_EXTRACT_SCHEMA)
     │   └─ call_mcp_tool(MCP_BROWSE_URL, "extract", ...)
     │       └─ browse_fetch(url) via camofox:
     │           ├─ POST {CAMOFOX_URL}/tabs/open → {tabId}
     │           ├─ GET {CAMOFOX_URL}/tabs/{tabId}/snapshot
     │           ├─ DELETE {CAMOFOX_URL}/tabs/{tabId}
     │           └─ Returns accessibility tree (40k char limit)
     │       └─ Send snapshot to Ollama with JSON Schema format
     │           Returns extracted fields as JSON string
     │
     ├─ Fallback if browse fails:
     │   └─ Use SearXNG snippet + extract_skills_from_text()
     │
     └─ Build JobResult with:
         - title (extracted or raw)
         - company (extracted or raw)
         - location (extracted or raw)
         - description (extracted or snippet)
         - skills (extracted or keyword-matched)
         - job_type (from extraction or keyword categorization)
         - url, apply_url, posted_date, source
   ```

7. **Title Deduplication (Final)**
   - `_is_duplicate()` uses difflib.SequenceMatcher with 0.95 threshold
   - Shared `final_seen_titles` list across both sources
   - Near-identical titles (>95% similarity) are dropped

8. **Response**
   - List of `JobResult` dicts returned to API
   - Total count includes both sources up to their individual quotas
   - Max possible: `SEARXNG_MAX_RESULTS + LINKEDIN_MAX_RESULTS`

---

## 8. APIs

### REST Endpoints

#### POST /api/v1/jobs/search

Search for jobs using natural language query.

**Request:**
```json
{
  "user_input": "React developer remote 4 years experience"
}
```

**Response:**
```json
[
  {
    "title": "Senior React Developer",
    "company": "Tech Corp",
    "location": "Remote",
    "description": "Full job posting text...",
    "url": "https://...",
    "apply_url": "https://...",
    "skills": ["react", "typescript"],
    "job_type": "remote",
    "posted_date": "2 days ago",
    "salary": "$120k-$150k",
    "source": "searxng"
  }
]
```

**Notes:**
- Frontend sends ONLY `user_input`. All search configuration is in backend `.env`.
- The endpoint accepts a `db` dependency but does not currently store results to MongoDB.

### MCP Tools (Model Context Protocol)

The MCP server (`job_mcp_server.py`) exposes tools that can be called by an LLM agent.

#### Tool: `search(query, max_results)`

Returns formatted string of search results. Used by interactive agents.

**Example return:**
```
[1] Senior React Developer
    https://example.com/job/123
    We are looking for an experienced React developer...

[2] React Engineer
    https://example.com/job/456
    Join our team as a React engineer...
```

#### Tool: `search_json(query, max_results, time_range)`

Returns raw JSON array of search results.

**Return format:**
```json
[
  {
    "title": "Senior React Developer",
    "url": "https://example.com/job/123",
    "content": "Snippet or description..."
  }
]
```

---

## 9. Business Logic

### Query Generation

The system uses an LLM to dynamically generate targeted queries. The prompt instructs the LLM to:

1. Consider the user's intent
2. Generate up to 3 distinct queries
3. Target specific job platforms from `SEARCH_SITES`
4. Use the `site:` operator
5. Return strictly as a JSON array

**Fallback behavior:** If LLM fails (timeout, invalid response), falls back to regex-based parser that:
- Extracts `site:` operators from the user query
- Detects career page searches (e.g., "careers at company.com")
- Builds queries for each configured site

### Search Sources

#### SearXNG
- Configurable via `SEARXNG_ENABLED`
- Searches local SearXNG instance (which proxies external search engines)
- Returns JSON with `results[]` containing `title`, `url`, `content` (snippet)
- Uses `_search_mcp_async()` which calls `search_json` MCP tool

#### LinkedIn Guest API
- Configurable via `LINKEDIN_GUEST_API_ENABLED`
- Scrapes LinkedIn's public guest job search page
- Parses HTML to extract: job ID, title, company, location
- Visits each job URL to fetch full description (multiple HTML patterns)
- Returns results with `source="linkedin"`

### Deduplication Strategy

**Two-level dedup:**

1. **Per-source URL dedup** (`_collect_unique_urls_only`)
   - Uses `url` as primary key, falls back to `apply_url`
   - Each source maintains its own `seen_urls` set
   - Prevents cross-source interference (fixed in 2026-06-09)

2. **Cross-source title dedup** (`_is_duplicate`)
   - Shared `final_seen_titles` during browse phase
   - Uses `difflib.SequenceMatcher` with >0.95 similarity threshold
   - Normalizes by removing non-word chars and lowercasing
   - Prevents near-identical listings from appearing twice

### Job Type Categorization

`_categorize_job_type()` determines job type:

1. Try extracted `job_type` from Ollama
2. If missing or "unknown", scan description for keywords:
   - `internship`, `contract`, `freelance`, `part-time`, `remote`, `hybrid`, `full-time`
3. Replace spaces with hyphens
4. Return "unknown" if no match

### Skill Extraction Fallback

If `browse_extract` doesn't return skills:
- Falls back to `extract_skills_from_text(description)`
- Matches against hardcoded `SKILL_KEYWORDS` list (35 common tech/business skills)
- Case-insensitive substring matching (not whole word)

---

## 10. Workflows

### Main Search Workflow (search_jobs_workflow)

```
Input: user_input (str)
Output: List[dict] - JobResult objects

Step 1: Generate search queries
  → _build_queries_dynamic(user_input)

Step 2: Execute SearXNG searches (optional)
  → For each query: provider._search_mcp_async()
  → Apply per-source URL dedup to searxng_seen_urls
  → Rank with _rank_and_trim_dynamic()
  → Store in searxng_candidates

Step 3: Execute LinkedIn search (optional)
  → provider._search_linkedin_async(user_input, linkedin_quota * 2)
  → Apply per-source URL dedup to linkedin_seen_urls
  → Rank with _rank_and_trim_dynamic()
  → Store in linkedin_candidates

Step 4: Browse and extract (per source)
  → _browse_and_build(searxng_candidates, searxng_quota, "searxng", final_seen_titles)
  → _browse_and_build(linkedin_candidates, linkedin_quota, "linkedin", final_seen_titles)

Step 5: Combine and return
  → searxng_jobs + linkedin_jobs
```

### Browse & Extract (`_browse_and_build`)

```
For each candidate in candidates (up to quota):
  1. Validate URL starts with http:// or https://
  2. Call browse_extract(url, JOB_EXTRACT_SCHEMA)
     └─ Returns JSON string (or raises exception)
  3. Parse JSON to `extracted` dict
  4. Apply title deduplication against final_seen_titles
  5. Build JobResult via _build_job()
     - Merges extracted fields with raw result data
     - Adds skills fallback if missing
     - Categorizes job_type
  6. Print JSON to stdout (debug visibility)
  7. Append to jobs list

Return list of job dicts
```

### LLM Query Generation Flow

```
call_llm(prompt, json_format=True)
  → LLM_PROVIDER determines which backend
  → ollama Client.chat() with format="json" if json_format
  → Wait in separate thread (timeout default 120s)
  → Return response["message"]["content"]
```

---

## 11. Setup Steps

### From Scratch Setup

1. **Clone repository and navigate to backend**
   ```bash
   cd backend
   ```

2. **Create Python virtual environment**
   ```bash
   python -m venv .venv
   # Windows
   .venv\Scripts\Activate.ps1
   # Unix/Mac
   source .venv/bin/activate
   ```

3. **Install dependencies**
   ```bash
   pip install -r requirements.txt
   ```

4. **Start external services via Docker**
   ```bash
   cd services
   docker-compose up -d
   ```
   - SearXNG will be available at `http://localhost:8888`
   - camofox will be available at `http://localhost:9500`

5. **Install and start Ollama**
   ```bash
   # Download from https://ollama.ai and install
   ollama pull qwen2.5-coder:1.5b
   ollama serve
   ```
   *(Run in separate terminal)*

6. **Configure environment variables**
   Create `.env` file in `backend/`:
   ```env
   MONGODB_URI=mongodb://localhost:27017
   SEARXNG_URL=http://localhost:8888
   CAMOFOX_URL=http://localhost:9500
   
   # Enable search sources
   SEARXNG_ENABLED=true
   LINKEDIN_GUEST_API_ENABLED=true
   
   # Optional: adjust quotas
   SEARCH_MAX_RESULTS=15
   LINKEDIN_GUEST_API_MAX_RESULTS=15
   
   # Logging
   LOG_LEVEL=INFO
   ```

7. **Start the FastAPI server**
   ```bash
   uvicorn app.main:app --reload
   ```

8. **Test the API**
   ```bash
   curl -X POST "http://127.0.0.1:8000/api/v1/jobs/search" \
     -H "Content-Type: application/json" \
     -d '{"user_input": "React developer remote"}'
   ```

---

## 12. Deployment Process

### Local Development

1. Ensure all services are running (SearXNG, camofox, Ollama)
2. Start Uvicorn with reload for hot reload
3. Check logs at `LOG_LEVEL` (set to DEBUG for detailed tracing)

### Production (Inferred)

**Recommended architecture:**

```
Production Load Balancer
       │
       ▼
┌─────────────────────┐
│   FastAPI App       │
│   (multiple workers)│
└─────────┬───────────┘
          │
          ├─► Redis Queue (optional, for async processing)
          │
          ▼
┌─────────────────────┐
│   Worker(s)         │
│   (run workflows)   │
└─────────┬───────────┘
          │
          ├─► MongoDB (persistence)
          ├─► SearXNG (self-hosted or remote)
          ├─► camofox (self-hosted cluster)
          └─► Ollama (GPU-optimized cluster)
```

**Considerations:**
- The browse+extract step is slow (multiple HTTP calls per job)
- Consider background task queue (Celery/Redis) for production
- Ollama should run on GPU servers for acceptable performance
- camofox scales horizontally; add more containers for higher throughput
- MongoDB connection pooling configured via Motor defaults

---

## 13. Implementation Details

### Key Files Reference

| File | Lines | Responsibility |
|------|-------|-----------------|
| `app/agents/job_workflow.py` | 367 | Main workflow - query gen, search orchestration, browse+extract, final assembly |
| `app/agents/search_provider.py` | 199 | Search backend abstraction, concurrent source execution |
| `app/agents/mcp_client.py` | 46 | MCP protocol client over Streamable HTTP |
| `app/agents/nodes/job_mcp_server.py` | 80 | MCP server exposing search_json tool |
| `app/agents/tools/browse_jobs.py` | 33 | Browser tool wrapper (calls MCP browse server) |
| `app/core/llm.py` | 72 | LLM provider abstraction with threading timeout |
| `app/core/config.py` | 50 | Settings management |
| `app/api/v1/jobs.py` | 22 | REST endpoint |

### Critical Code Patterns

#### Async Search with Exception Handling
```python
tasks = []
if settings.SEARXNG_ENABLED:
    task = asyncio.create_task(self._search_mcp_async(...), name="searxng_search")
    tasks.append(("searxng", task))
# ...
settled = await asyncio.gather(*task_list, return_exceptions=True)
for source_name, result in zip(source_names, settled):
    if isinstance(result, Exception):
        log.error(...)
    else:
        all_results.extend(result)
```

#### Fallback Chain
```python
try:
    raw_json = browse_extract(url, JOB_EXTRACT_SCHEMA)
    extracted = json.loads(raw_json)
    if not extracted or all(v is None for v in extracted.values()):
        extracted = {}
except Exception:
    extracted = {}  # Fallback to snippet + keyword skills
```

#### LLM JSON Parsing with Strip
```python
raw = call_llm(prompt, json_format=True)
raw = re.sub(r"^```(?:json)?\s*", "", raw).strip()
raw = re.sub(r"\s*```$", "", raw).strip()
start = raw.find("[")
end = raw.rfind("]")
queries = json.loads(raw[start:end+1])
```

### Known Issues from Code

1. **Browsing bottleneck**: Each job URL is browsed sequentially within a source. Consider `asyncio.gather` for parallel browsing (with rate limiting).
2. **LinkedIn rate limiting**: No retry/backoff logic. LinkedIn may block after rapid requests.
3. **MongoDB unused**: Connection established but no writes implemented.
4. **CAMOFOX_URL not used directly**: Only used through MCP client; config possibly redundant.
5. **Inconsistent variable naming**: `LINKEDIN_MAX_RESULTS` vs `LINKEDIN_GUEST_API_MAX_RESULTS`.

---

## 14. Troubleshooting

### "LinkedIn returns 0 results"
- **Cause (fixed 2026-06-09):** Shared dedup context filtered LinkedIn results before they could be collected.
- **After fix:** `linkedin unique after dedup` should ≈ `linkedin raw results`.

### "Ollama timeout"
- **Cause:** Selected model too large or GPU insufficient.
- **Solution:** Use smaller model (e.g., `qwen2.5-coder:0.5b`) or increase timeout in `llm.py`.

### "browse_extract failed"
- **Cause:** camofox not running, or camofox returned error.
- **Solution:** Check `docker-compose logs camofox`. The workflow will continue with snippet fallback.

### "SearXNG unreachable"
- **Cause:** Docker container not running or wrong port.
- **Solution:** `docker-compose ps` to verify, check `services/docker-compose.yml` port mapping.

### "No results from any source"
- Check `SEARXNG_ENABLED` and `LINKEDIN_GUEST_API_ENABLED` are `true` in `.env`
- Verify external services are healthy:
  ```bash
  curl http://localhost:8888/health  # SearXNG
  curl http://localhost:9500/health  # camofox
  curl http://localhost:11434/api/tags  # Ollama
  ```
- Set `LOG_LEVEL=DEBUG` to see detailed logs

---

## 15. Future Improvements

### From Latest Documentation (09_06_26)

**Planned:**
1. Add `browse` MCP tool to complete the search → browse → extract chain entirely through MCP
2. MongoDB persistence with collection per job_type or single collection with filter
3. Support for more search sources (JSearch API already referenced but not integrated)

**Potential Enhancements:**
- Parallelize browsing within sources (currently sequential)
- Add caching layer (Redis) to avoid re-extracting same URLs
- Implement paywall bypass strategies for locked job descriptions
- Add resume parsing and matching (matching score)
- Webhooks for async result delivery
- Rate limiting and quota management
- Better error reporting to clients (currently swallowed on browse failures)

---

## 16. Assumptions & Inferred Context

### Assumptions Made During Documentation

1. **MongoDB is optional** - The `get_db` dependency is injected but not used. The codebase appears to be transitioning toward MongoDB persistence but it's not required for basic operation.

2. **camofox port changed** - Earlier docs mention `CAMOFOX_URL=http://localhost:3000` but current `docker-compose.yml` maps to `9500`. The code uses whatever is configured, so documentation reflects configurable nature.

3. **JSEARCH_API not integrated** - The `.env.template` includes JSearch API variables but there's no implementation in `SearchProvider`. This is planned but not yet done.

4. **MCP browse server exists** - The `browse_jobs.py` tool calls `MCP_BROWSE_URL` with `fetch`/`extract` tools. The server implementation (`job_mcp_browse_server.py`) is referenced in older docs but not in current tree. It may be needed or the tools may call camofox directly. *Assumption: The MCP browse server exists or will be created.*

5. **LLM thread model** - `llm.py` uses `threading.Thread` to call blocking Ollama client, preventing FastAPI event loop blocking. This is correct but unusual for async code; consider using `asyncio.to_thread` in future.

6. **Search sites list** - `SEARCH_SITES` default is corporate ATS platforms (Greenhouse, Lever, Workday), not job boards. This suggests targeting company career pages rather than aggregate job boards.

7. **LinkedIn Guest API stability** - The implementation scrapes HTML which can break if LinkedIn changes their page structure. No official API key required, but fragile.

### Clarifications for New Developers

- **Why two MCP servers?** The original design separated search and browse concerns. The `search_provider.py` currently calls `_do_search()` directly (Option B) instead of via MCP subprocess (Option A). See `mcp_search_integration.md` for rationale.
- **Where is the browse MCP server?** Referenced but not found in current file tree. It may need to be created following `job_mcp_server.py` pattern, or `browse_jobs.py` may call camofox directly through MCP client to a separate process.
- **What's the difference between `job_workflow.py` and `search_jobs.py` (in nodes)?** The former is the new unified workflow; the latter is a node for the older LangGraph-based agent system. The node is kept for reference but not used by the API.

---

## Appendix

### Quick Reference: Environment Variables

| Variable | Required | Default | Purpose |
|----------|----------|---------|---------|
| `MONGODB_URI` | Yes | - | MongoDB connection string |
| `SEARXNG_URL` | Yes | - | SearXNG instance URL |
| `CAMOFOX_URL` | Yes | - | camofox browser server URL |
| `SEARXNG_ENABLED` | No | `false` | Enable/disable SearXNG source |
| `LINKEDIN_GUEST_API_ENABLED` | No | (must set) | Enable/disable LinkedIn source |
| `SEARCH_MAX_RESULTS` | No | `15` | Final jobs per source |
| `LINKEDIN_GUEST_API_MAX_RESULTS` | No | `15` | Max LinkedIn results |
| `LOG_LEVEL` | No | `INFO` | Logging level |

### File Modification Tracker (Current as of 2026-06-09)

Based on `backend_job_search_mcp_workflow_09_06_26.md`:

| File | Status | Change Summary |
|------|--------|----------------|
| `app/agents/job_workflow.py` | Modified | Fixed dedup: per-source URL sets, title dedup deferred, added `_collect_unique_urls_only()` |
| `app/core/config.py` | Modified | Removed default `False` from `LINKEDIN_GUEST_API_ENABLED`, added `LOG_LEVEL` |
| `app/main.py` | Modified | Configurable log level via settings |

---

**Document Version:** 1.0  
**Last Updated:** 2026-06-09  
**Based on:** Backend codebase analysis + all `document/*.md` files
