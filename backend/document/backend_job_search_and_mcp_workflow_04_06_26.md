# Backend Job Search & MCP Workflow Reconstruction Guide (June 4, 2026)

This document provides a complete, self-contained implementation guide for the backend job search workflow and Model Context Protocol (MCP) servers. 
Any developer or AI agent starting with zero context will be able to reconstruct the entire service and run it successfully using this guide.

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
           [Search Provider Layer]
                      │
                      ▼
      [SearXNG Search Engine (Local)] ── (Strict time_range="day" for latest postings)
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
1. **Dynamic Query Expansion:** Converts natural language queries into specific search operators targeting applicant tracking systems (e.g., `site:greenhouse.io`, `site:lever.co`, `site:myworkdayjobs.com`).
2. **Strict Freshness Enforcement:** Restricts SearXNG queries using the parameter `time_range="day"` to ensure only newly posted roles are retrieved.
3. **Relevance Ranking:** Scores search results (0 to 10) using an LLM before browsing, weeding out irrelevant hits and conserving resource bandwidth.
4. **Multi-Stage Extraction:** Saves LLM context size and runtime:
   - **Stage 1 (Classification):** Quickly determines if the web page is actually a job listing. If false, skips processing.
   - **Stage 2 (Schema-constrained Extraction):** Extracts structured attributes matching `JOB_EXTRACT_SCHEMA`.
5. **Configurable LLM Backends:** Centralized LLM abstraction allowing seamless swaps between local models (Ollama) and cloud APIs (Groq or Gemini).

---

## 2. Required External Services

Ensure the following local servers are active before running the backend:

| Service | Port | Configuration / Setup | Purpose |
| --- | --- | --- | --- |
| **SearXNG** | `8888` | Active on `http://localhost:8888` | Aggregates search requests across engines in JSON format. |
| **Camofox** | `9500` | Active on `http://localhost:9500` | Headless automation tool returning accessibility-tree DOM snapshots. |
| **Ollama** | `11434` | Active on `http://localhost:11434` with model `qwen2.5-coder:1.5b` | Handles text query expansion, relevance scoring, page classification, and schema extraction. |
| **MongoDB** | `27017` | Local or Remote URI | Stores job entries, user settings, and uploaded resumes. |

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
│   │   ├── search_provider.py
│   │   ├── state.py
│   │   ├── nodes/
│   │   │   ├── __init__.py
│   │   │   ├── extract_skills.py
│   │   │   ├── job_mcp_browse_server.py
│   │   │   ├── job_mcp_server.py
│   │   │   └── tailor_resume.py
│   │   └── tools/
│   │       ├── __init__.py
│   │       ├── browse_jobs.py
│   │       ├── skill_extraction.py
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
    └── backend_job_search_and_mcp_workflow_04_06_26.md
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
LLM_PROVIDER=ollama
GROQ_API_KEY=your_groq_key_here
GEMINI_API_KEY=your_gemini_key_here
SEARCH_MAX_RESULTS=10
BROWSE_TOP_N=15
SEARCH_SITES=greenhouse.io,lever.co,myworkdayjobs.com
SEARCH_FRESH=true
SEARCH_CAREERS=false
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

### Data Models & API Layout

#### [app/models/job.py](file:///d:/AI%20Projects/job_project/project/backend/app/models/job.py)
```python
from typing import List, Optional
from pydantic import BaseModel, Field


class JobSearchRequest(BaseModel):
    user_input: str = Field(
        ...,
        description="Job search query in plain text",
        examples=["React developer Python 4 years experience remote"],
    )


class JobResult(BaseModel):
    title: str = ""
    company: str = ""
    location: Optional[str] = None
    description: str = ""
    url: Optional[str] = None
    apply_url: Optional[str] = None
    skills: List[str] = Field(default_factory=list)
    job_type: str = "unknown"
    posted_date: Optional[str] = None
    salary: Optional[str] = None
```

#### [app/models/resume.py](file:///d:/AI%20Projects/job_project/project/backend/app/models/resume.py)
```python
from pydantic import BaseModel
from typing import Optional

class ResumeUploadResponse(BaseModel):
    resume_id: str
    extracted_text: str

class ResumeTailorRequest(BaseModel):
    resume_id: str
    job_description: str

class ResumeTailorResponse(BaseModel):
    resume_id: str
    tailored_text: str
    download_url: Optional[str] = None
```

#### [app/api/deps.py](file:///d:/AI%20Projects/job_project/project/backend/app/api/deps.py)
```python
from app.core.database import get_database

def get_db():
    return get_database()
```

#### [app/api/v1/jobs.py](file:///d:/AI%20Projects/job_project/project/backend/app/api/v1/jobs.py)
```python
import logging
from fastapi import APIRouter, Depends
from typing import List

from app.models.job import JobSearchRequest, JobResult
from app.api.deps import get_db
from app.agents.job_workflow import search_jobs_workflow

log = logging.getLogger(__name__)
router = APIRouter()


@router.post("/search", response_model=List[JobResult])
async def search_jobs(request: JobSearchRequest, db=Depends(get_db)):
    """Search jobs using dynamic pre-search, relevance scoring, and browser automation."""
    log.info("[search] user_input=%r", request.user_input)
    results = await search_jobs_workflow(user_input=request.user_input)
    log.info("[search] returning %d jobs", len(results))
    return results
```

#### [app/api/v1/resumes.py](file:///d:/AI%20Projects/job_project/project/backend/app/api/v1/resumes.py)
```python
from fastapi import APIRouter, Depends, UploadFile, File
from app.models.resume import ResumeUploadResponse, ResumeTailorRequest, ResumeTailorResponse
from app.api.deps import get_db

router = APIRouter()

@router.post("/upload", response_model=ResumeUploadResponse)
async def upload_resume(file: UploadFile = File(...), db=Depends(get_db)):
    # Placeholder implementation
    return ResumeUploadResponse(resume_id="placeholder", extracted_text="")

@router.post("/tailor", response_model=ResumeTailorResponse)
async def tailor_resume(request: ResumeTailorRequest, db=Depends(get_db)):
    # Placeholder implementation
    return ResumeTailorResponse(resume_id=request.resume_id, tailored_text="")
```

#### [app/main.py](file:///d:/AI%20Projects/job_project/project/backend/app/main.py)
```python
import logging
from fastapi import FastAPI
from app.core.database import connect_db, close_db
from app.api.v1 import jobs, resumes

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

app = FastAPI(title="Job App API")

app.include_router(jobs.router, prefix="/api/v1/jobs", tags=["jobs"])
app.include_router(resumes.router, prefix="/api/v1/resumes", tags=["resumes"])


@app.on_event("startup")
async def startup():
    await connect_db()


@app.on_event("shutdown")
async def shutdown():
    await close_db()


@app.get("/health")
async def health():
    return {"status": "ok"}
```

---

### In-Process Search & MCP Servers

#### [app/agents/search_provider.py](file:///d:/AI%20Projects/job_project/project/backend/app/agents/search_provider.py)
```python
"""
SearchProvider — abstraction over the search backend.
Option B (Current): Calls _do_search() directly in the same process to eliminate overhead.
Option A (Future): Scalable via standard MCP Client stdio connection without affecting workflows.
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


provider = SearchProvider()
```

#### [app/agents/nodes/job_mcp_server.py](file:///d:/AI%20Projects/job_project/project/backend/app/agents/nodes/job_mcp_server.py)
```python
"""
MCP server — exposes a `search` tool backed by SearXNG.
Run standalone:  python -m app.agents.nodes.job_mcp_server
"""
import logging
import httpx
from mcp.server.fastmcp import FastMCP
from app.core.config import settings

log = logging.getLogger(__name__)
mcp = FastMCP("search-server")


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
    job listings.
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
    raw = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL).strip()
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
`python
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

# ── Backend targeting config — all values read from settings (.env) ──────────

# ── Schema used to extract structured fields from each job page ───────────────
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
        # try to parse just the array
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
        # Increased to 0.95 to be much more lenient (only near-identical strings are discarded)
        if difflib.SequenceMatcher(None, new_norm, et_norm).ratio() > 0.95:
            return True
    return False


async def search_jobs_workflow(user_input: str) -> List[dict]:
    """Entry point called by the API. Accepts plain-text user query only."""
    log.info("[workflow] starting dynamic search for: %s", user_input)

    queries = _build_queries_dynamic(user_input)
    log.debug("[workflow] will run %d queries: %s", len(queries), queries)

    # ── Phase 1: Search — fetch SEARCH_MAX_RESULTS per query, de-dupe by URL ──
    # Fetch 2N results so we have enough to rank/score
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

    # ── Phase 2: Rank — score by relevance using LLM, keep larger pool to allow skipping bad ones
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

        # ── Auto-browse: fetch + extract structured fields ───────────────────
        if url.startswith(("http://", "https://")):
            log.debug("[workflow] [%d] fetching page via camofox: %r", idx + 1, url)
            try:
                raw_json = browse_extract(url, JOB_EXTRACT_SCHEMA)
                extracted = (
                    json.loads(raw_json) if isinstance(raw_json, str) else raw_json
                )
                
                if not extracted or all(v is None for v in extracted.values()):
                    log.warning("[workflow] [%d] Stage 1 classified as not a job or empty extraction. Skipping.", idx + 1)
                    continue
                    
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

        # ── Build final job record ───────────────────────────────────────────
        title = (extracted.get("title") or base_title).strip()
        company = (extracted.get("company") or result.get("company") or "").strip()
        location = extracted.get("location") or result.get("location") or None
        description = (extracted.get("description") or snippet).strip()
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

`

#### [app/agents/tools/web_search.py](file:///d:/AI%20Projects/job_project/project/backend/app/agents/tools/web_search.py)
```python
import httpx
from app.core.config import settings

def web_search(query: str, num_results: int = 10) -> list[dict]:
    if not query:
        return []
    try:
        response = httpx.get(
            f"{settings.SEARXNG_URL}/search",
            params={"q": query.strip(), "format": "json", "count": num_results},
            timeout=10.0,
        )
        response.raise_for_status()
        return response.json().get("results", [])[:num_results]
    except Exception:
        return []
```

#### [app/agents/tools/browse_jobs.py](file:///d:/AI%20Projects/job_project/project/backend/app/agents/tools/browse_jobs.py)
```python
"""
Browse tool — delegates to the browse MCP server (Option B).
"""
import logging
from app.agents.nodes.job_mcp_browse_server import _do_fetch, _do_extract

log = logging.getLogger(__name__)


def browse_fetch(url: str) -> str:
    log.info("[browse_tool] browse_fetch url=%r", url)
    return _do_fetch(url)


def browse_extract(url: str, schema: dict, model_name: str = "") -> str:
    log.info("[browse_tool] browse_extract url=%r", url)
    return _do_extract(url, schema)
```

#### [app/agents/tools/skill_extraction.py](file:///d:/AI%20Projects/job_project/project/backend/app/agents/tools/skill_extraction.py)
```python
from typing import List

SKILL_KEYWORDS = [
    "python", "sql", "excel", "javascript", "react", "node", "docker", 
    "kubernetes", "aws", "azure", "gcp", "machine learning", "data analysis", 
    "data science", "project management", "communication", "teamwork", 
    "leadership", "presentation", "sales", "marketing", "crm", "analytics", 
    "design", "testing", "automation", "cloud", "devops", "security", 
    "networks", "documentation",
]

def extract_skills_from_text(text: str) -> List[str]:
    if not text:
        return []
    normalized = text.lower()
    return [kw for kw in SKILL_KEYWORDS if kw in normalized]
```

#### [app/agents/tools/\_\_init\_\_.py](file:///d:/AI%20Projects/job_project/project/backend/app/agents/tools/__init__.py)
```python
from .web_search import web_search
from .browse_jobs import browse_fetch, browse_extract
from .skill_extraction import extract_skills_from_text
```

#### [app/agents/state.py](file:///d:/AI%20Projects/job_project/project/backend/app/agents/state.py)
```python
from typing import TypedDict, List, Optional

class AgentState(TypedDict):
    query: str
    location: Optional[str]
    raw_jobs: List[dict]
    jobs_with_skills: List[dict]
    resume_text: Optional[str]
    tailored_resume: Optional[str]
```

#### [app/agents/graph.py](file:///d:/AI%20Projects/job_project/project/backend/app/agents/graph.py)
```python
"""
LangGraph topology configuration.
Kept as an extensible layer for multi-agent workflows.
"""
from langgraph.graph import StateGraph, END
from app.agents.state import AgentState
from app.agents.nodes.extract_skills import extract_skills_node
from app.agents.nodes.tailor_resume import tailor_resume_node

def build_job_search_graph():
    # Extensible skeleton graph topology
    graph = StateGraph(AgentState)
    graph.add_node("extract_skills", extract_skills_node)
    graph.set_entry_point("extract_skills")
    graph.add_edge("extract_skills", END)
    return graph.compile()

def build_resume_tailor_graph():
    graph = StateGraph(AgentState)
    graph.add_node("tailor_resume", tailor_resume_node)
    graph.set_entry_point("tailor_resume")
    graph.add_edge("tailor_resume", END)
    return graph.compile()

job_search_graph = build_job_search_graph()
resume_tailor_graph = build_resume_tailor_graph()
```

#### [app/agents/nodes/extract_skills.py](file:///d:/AI%20Projects/job_project/project/backend/app/agents/nodes/extract_skills.py)
```python
from app.agents.state import AgentState
from app.agents.tools.skill_extraction import extract_skills_from_text

async def extract_skills_node(state: AgentState) -> AgentState:
    jobs_with_skills = []
    for job in state.get("raw_jobs", []):
        description = job.get("description") or job.get("snippet") or job.get("content") or ""
        job["skills"] = extract_skills_from_text(description)
        jobs_with_skills.append(job)
    state["jobs_with_skills"] = jobs_with_skills
    return state
```

#### [app/agents/nodes/tailor_resume.py](file:///d:/AI%20Projects/job_project/project/backend/app/agents/nodes/tailor_resume.py)
```python
from app.agents.state import AgentState

async def tailor_resume_node(state: AgentState) -> AgentState:
    state["tailored_resume"] = state.get("resume_text", "")
    return state
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

### Step 3: Run the FastAPI Server
Launch the server via uvicorn:
```bash
uvicorn app.main:app --reload --port 8000
```

### Step 4: Verify Search & Extractions
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
    "location": "Remote, USA",
    "description": "We are seeking a React developer with Python skills...",
    "url": "https://greenhouse.io/techcorp/jobs/12345",
    "apply_url": "https://greenhouse.io/techcorp/jobs/12345#apply",
    "skills": ["react", "javascript", "python"],
    "job_type": "remote",
    "posted_date": "2 days ago",
    "salary": "$120,000 - $140,000"
  }
]
```

### Step 5: Verify Fallbacks
- **Simulate Browser Offline:** Stop the `camofox` server. Run the query again. The output should print warnings indicating browser failures, but succeed anyway by populating job fields from SearXNG's `content` and parsing skills via regex in the `extract_skills_from_text` module.
- **Simulate Ollama Offline:** Stop the `ollama` service. The search should degrade gracefully using `_parse_user_input` and `_rank_and_trim` fallbacks instead of crashing.
