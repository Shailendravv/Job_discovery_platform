# Job App Backend — From-Scratch Build Guide

> If you have zero context about this project, this document contains everything
> you need to understand, set up, extend, and deploy it. It is written for both
> humans and AI assistants.

---

## Table of Contents

1.  [Project Overview](#1-project-overview)
2.  [System Architecture](#2-system-architecture)
3.  [Quick Start (5 minutes)](#3-quick-start-5-minutes)
4.  [Environment Variables](#4-environment-variables)
5.  [Database Schemas](#5-database-schemas)
6.  [API Endpoints](#6-api-endpoints)
7.  [Services Layer](#7-services-layer)
8.  [Resume Formatting Pipeline (The Core)](#8-resume-formatting-pipeline-the-core)
9.  [Agent Workflows](#9-agent-workflows)
10. [Migrations](#10-migrations)
11. [Testing](#11-testing)
12. [Deployment](#12-deployment)
13. [Troubleshooting](#13-troubleshooting)
14. [File Map](#14-file-map)

---

## 1. Project Overview

### What it does

This is a **job search assistant** backend. It lets users:
- **Search for jobs** across multiple platforms (LinkedIn, company career pages, ATS platforms like Greenhouse/Lever) using SearXNG or MCP-based search tools.
- **Upload resumes** (PDF or DOCX) and have them parsed by an LLM into structured data (name, skills, experience, education).
- **Tailor resumes** to specific job descriptions — the LLM rewrites bullet points and summaries to match the job, preserving formatting.
- **Download tailored resumes** as both DOCX and PDF, with preserved formatting (bold, headings, hyperlinks).
- **Generate cover letters** tailored to each job application.

### Key Technologies

| Technology | Purpose |
|---|---|
| **Python 3.13+** | Runtime |
| **FastAPI** | HTTP API framework |
| **MongoDB + Motor** | Database (async driver) |
| **Multi-Provider LLM** (Groq, Cerebras, SambaNova, NVIDIA, OpenRouter) | Provider-level fallback chain for LLM calls |
| **Cloudinary** | File storage for uploaded and generated documents |
| **Mammoth** | DOCX → HTML conversion (preserves formatting) |
| **htmldocx** | HTML → DOCX conversion |
| **Playwright** | HTML → PDF conversion (headless Chromium) |
| **PyMuPDF (fitz)** | PDF text extraction with font metadata |
| **python-docx** | DOCX reading/writing |
| **pypdf** | PDF text extraction (fallback) |
| **reportlab** | PDF generation (fallback for cover letters) |
| **BeautifulSoup4** | HTML sanitization after LLM editing |

### The Core Design Decision: HTML Round-Trip

The resume formatting pipeline does **NOT** manipulate DOCX or PDF files directly.
Instead it uses a round-trip through HTML:

```
DOCX ──mammoth──▶ HTML ──LLM edits text──▶ modified HTML ──htmldocx──▶ DOCX
                                                            └──playwright──▶ PDF
```

**Why HTML?**
- HTML is a format the LLM understands natively (`<b>`, `<a href>`, `<h2>`, `<ul>`).
- No need for custom JSON schemas or fragile heuristics.
- `mammoth` extracts bold, links, headings, and lists as real HTML tags.
- `Playwright` renders HTML via Chromium → pixel-perfect PDFs.
- `htmldocx` converts HTML back to Word format.

For **PDF uploads** (which can't be converted to HTML directly), PyMuPDF extracts
text with font metadata, then we generate HTML from the extracted elements.

---

## 2. System Architecture

```
┌──────────────────────────────────────────────────────────────┐
│                    Frontend (React/Vite)                      │
│  http://localhost:5173                                        │
└──────────────────────────┬───────────────────────────────────┘
                           │ HTTP (REST API)
                           ▼
┌──────────────────────────────────────────────────────────────┐
│                    FastAPI Backend (:8000)                    │
│                                                              │
│  main.py ──▶ routers (jobs.py, resumes.py)                   │
│                  │                                            │
│                  ▼                                            │
│           Services Layer                                     │
│  ┌─────────┬──────────┬──────────┬──────────┬──────────┐    │
│  │resume_  │  docx_   │  PDF_    │  html_   │  cover_  │    │
│  │tailor   │  service │  service │  service │  letter  │    │
│  └────┬────┴────┬─────┴────┬─────┴────┬─────┴────┬─────┘    │
│       │         │          │          │          │           │
│       ▼         ▼          ▼          ▼          ▼           │
│  ┌───────────────────────────────────────────────────┐      │
│  │  call_llm() — Multi-Provider LLM Layer            │      │
│  │                                                     │      │
│  │  ┌─────────┐ ┌─────────┐ ┌─────────┐ ┌────────┐   │      │
│  │  │  Groq   │ │Cerebras │ │SambaNova│ │ NVIDIA │   │      │
│  │  └────┬────┘ └────┬────┘ └────┬────┘ └───┬────┘   │      │
│  │       │           │           │           │         │      │
│  │       └───────────┴───────────┴───────────┘         │      │
│  │                        ▼  (falls through on failure) │      │
│  │  ┌─────────────────────────────────────────────┐   │      │
│  │  │ OpenRouter (model-level fallback, 8 models) │   │      │
│  │  └─────────────────────────────────────────────┘   │      │
│  └───────────────────────────────────────────────────┘      │
│       │                                                     │
│       ▼                                                     │
│  ┌───────────────────────────────────────────────────┐      │
│  │  MongoDB (jobs, resumes, tailor_sessions)          │      │
│  └───────────────────────────────────────────────────┘      │
│       │                                                     │
│       ▼                                                     │
│  ┌───────────────────────────────────────────────────┐      │
│  │  Cloudinary (file storage for resumes/docs)       │      │
│  └───────────────────────────────────────────────────┘      │
└──────────────────────────────────────────────────────────────┘
```

### Data Flow: Resume Upload

```
1. User uploads PDF/DOCX
2. Server reads file bytes, validates type/size
3. Extracts plain text (pypdf for PDF, python-docx for DOCX) ← for LLM parsing
4. Converts to HTML:
   - DOCX: mammoth → HTML (preserves bold, links, headings)
   - PDF: PyMuPDF extracts text + font metadata → generates HTML
5. Parses extracted text with LLM (extracts name, skills, etc.)
6. Uploads original file to Cloudinary
7. Saves to MongoDB: { resume_id, extracted_text, resume_html, parsed_data, ... }
```

### Data Flow: Resume Tailoring

```
1. User sends { resume_id, job_id }
2. Server fetches resume + job from MongoDB
3. Strips PII (name, email, phone) from parsed resume data
4. If resume data is large: splits into 2-3 chunks for parallel LLM processing
5. Each chunk is tailored independently (rewritten to match job keywords)
6. Reassembles chunks into final JSON, reinjects PII
7. Generates HTML from tailored JSON → DOCX (htmldocx) → PDF (Playwright)
8. Generates cover letter via LLM → PDF (reportlab)
9. Uploads all files to Cloudinary
10. Returns download URLs + tailored JSON + ATS keyword analysis
```

---

## 3. Quick Start (5 minutes)

### Prerequisites

- Python 3.13+
- MongoDB (Atlas or local) — get a free cluster at mongodb.com
- At least one LLM provider API key:
  - **Groq**: console.groq.com
  - **Cerebras**: console.cerebras.ai/api-keys
  - **SambaNova**: cloud.sambanova.ai/apis
  - **NVIDIA**: build.nvidia.com
  - **OpenRouter**: openrouter.ai/keys
- Cloudinary account (optional, for file storage) — cloudinary.com

### Step 1: Clone and enter backend

```bash
cd backend
```

### Step 2: Create virtual environment

```bash
python -m venv .venv
.venv\Scripts\activate   # Windows
source .venv/bin/activate  # macOS/Linux
```

### Step 3: Install dependencies

```bash
pip install -r requirements.txt
python -m playwright install chromium  # for PDF generation
```

### Step 4: Create .env file

```bash
copy .env.example .env   # Windows
cp .env.example .env     # macOS/Linux
```

Fill in these **required** values:

```env
MONGODB_URI=mongodb+srv://user:pass@cluster.mongodb.net/jobapp
SEARXNG_URL=http://localhost:4000
CAMOFOX_URL=http://localhost:4000
LINKEDIN_GUEST_API_ENABLED=False
```

Set `LLM_PROVIDER` to your preferred mode:

```env
# Single provider (choose one):
LLM_PROVIDER=groq
GROQ_API_KEY=gsk_your_key_here

# Or multi-provider fallback chain:
LLM_PROVIDER=multi
LLM_PROVIDER_CHAIN=groq,cerebras,sambanova,nvidia,openrouter
GROQ_API_KEY=gsk_your_key_here
CEREBRAS_API_KEY=your_cerebras_key
SAMBANOVA_API_KEY=your_sambanova_key
NVIDIA_API_KEY=nvapi-your_nvidia_key
OPENROUTER_API_KEY=sk-or-your_openrouter_key
```

Optional but recommended:

```env
CLOUDINARY_CLOUD_NAME=your_cloud
CLOUDINARY_API_KEY=123456
CLOUDINARY_API_SECRET=abcdef
LOG_LEVEL=INFO
```

### Step 5: Run database migrations

```bash
python -m migrations.001_initial_schema --uri "%MONGODB_URI%" --db jobapp
```

Replace `%MONGODB_URI%` with your actual MongoDB URI. Repeat for any later
migrations (002, 006, 008, 009) — or use the migration runner:

```bash
python scripts/run_migrations.py
```

### Step 6: Start the server

```bash
uvicorn app.main:app --reload --port 8000
```

### Step 7: Verify

```bash
curl http://localhost:8000/health
# {"status": "ok"}
```

---

## 4. Environment Variables

All configuration lives in `.env` at `backend/.env` (gitignored). A full list:

### Required

| Variable | Description |
|---|---|
| `MONGODB_URI` | MongoDB connection string |
| `SEARXNG_URL` | SearXNG instance URL |
| `CAMOFOX_URL` | Camofox search URL |
| `LINKEDIN_GUEST_API_ENABLED` | Enable LinkedIn job search (`True`/`False`) |

### LLM Provider — Selection

| Variable | Default | Description |
|---|---|---|
| `LLM_PROVIDER` | `ollama` | `"multi"` for fallback chain, or `"ollama"`, `"openrouter"`, `"groq"`, `"cerebras"`, `"sambanova"`, `"nvidia"` |
| `LLM_PROVIDER_CHAIN` | `groq,cerebras,sambanova,nvidia,openrouter` | Comma-separated provider chain (only used when `LLM_PROVIDER=multi`) |
| `MODEL_TEMPERATURE` | `0.1` | LLM temperature (applied across all providers) |

### Ollama

| Variable | Default | Description |
|---|---|---|
| `OLLAMA_BASE_URL` | `http://localhost:11434` | Ollama server URL |
| `OLLAMA_MODEL` | `qwen2.5-coder:1.5b` | Model name |

### OpenRouter

| Variable | Default | Description |
|---|---|---|
| `OPENROUTER_API_KEY` | — | OpenRouter API key |
| `OPENROUTER_BASE_URL` | `https://openrouter.ai/api/v1` | API base URL |
| `OPENROUTER_MODEL` | `qwen/qwen3-coder:free` | Preferred model (falls back through 8 free-tier models on failure) |

### Groq

| Variable | Default | Description |
|---|---|---|
| `GROQ_API_KEY` | — | Groq API key (console.groq.com) |
| `GROQ_BASE_URL` | `https://api.groq.com/openai/v1` | API base URL |
| `GROQ_MODEL` | `llama-3.3-70b-versatile` | Model name |

### Cerebras

| Variable | Default | Description |
|---|---|---|
| `CEREBRAS_API_KEY` | — | Cerebras API key (console.cerebras.ai/api-keys) |
| `CEREBRAS_BASE_URL` | `https://api.cerebras.ai/v1` | API base URL |
| `CEREBRAS_MODEL` | `gpt-oss-120b` | Model name |

### SambaNova

| Variable | Default | Description |
|---|---|---|
| `SAMBANOVA_API_KEY` | — | SambaNova API key (cloud.sambanova.ai/apis) |
| `SAMBANOVA_BASE_URL` | `https://api.sambanova.ai/v1` | API base URL |
| `SAMBANOVA_MODEL` | `gpt-oss-120b` | Model name |

### NVIDIA NIM

| Variable | Default | Description |
|---|---|---|
| `NVIDIA_API_KEY` | — | NVIDIA API key (build.nvidia.com) |
| `NVIDIA_BASE_URL` | `https://integrate.api.nvidia.com/v1` | API base URL |
| `NVIDIA_MODEL` | `nvidia/nemotron-3-super-120b-a12b` | Model name |

### Storage

| Variable | Default | Description |
|---|---|---|
| `CLOUDINARY_CLOUD_NAME` | — | Cloudinary cloud name |
| `CLOUDINARY_API_KEY` | — | Cloudinary API key |
| `CLOUDINARY_API_SECRET` | — | Cloudinary API secret |

### Search

| Variable | Default | Description |
|---|---|---|
| `SEARCH_MAX_RESULTS` | `15` | Max jobs to return per search |
| `BROWSE_TOP_N` | `30` | Max job pages to browse for full details |
| `SEARCH_SITES` | (list of ATS domains) | Comma-separated career site domains |
| `SEARCH_FRESH` | `True` | Only search for recent jobs |
| `SEARCH_CAREERS` | `False` | Include career page search |
| `SETTLE_SECONDS` | `1.5` | Delay between search requests |
| `MAX_SNAPSHOT_CHARS` | `12000` | Max chars to snapshot from job pages |
| `SEARXNG_ENABLED` | `False` | Enable SearXNG search |

### Other

| Variable | Default | Description |
|---|---|---|
| `MCP_SEARCH_URL` | `http://localhost:8001` | MCP search server |
| `MCP_BROWSE_URL` | `http://localhost:8002` | MCP browse server |
| `LINKEDIN_GUEST_API_LOCATION` | `India` | Location filter for LinkedIn |
| `LINKEDIN_GUEST_API_TIME_RANGE` | `r86400` | Time range for LinkedIn search |
| `LINKEDIN_GUEST_API_MAX_RESULTS` | `15` | Max LinkedIn results |
| `LOG_LEVEL` | `INFO` | Logging level |

### For AI assistants

The Settings class is defined in `app/core/config.py`. It uses
`pydantic_settings.BaseSettings` and reads from `.env` file automatically.
Any env var set in the OS/terminal overrides the `.env` file value.

---

## 5. Database Schemas

### Collection: `resumes`

```json
{
  "_id": "ObjectId",
  "resume_id": "string (UUID hex, unique)",
  "cloudinary_url": "string",
  "cloudinary_public_id": "string",
  "cloudinary_resource_type": "string ('image' | 'raw')",
  "filename": "string",
  "content_type": "string (MIME type)",
  "file_size": "int (bytes)",
  "extracted_text": "string (plain text extracted from file)",
  "extracted_text_length": "int",
  "resume_html": "string (HTML representation, used for tailoring)",
  "parsed_data": {
    "name": "string",
    "email": "string (optional)",
    "phone": "string (optional)",
    "education": [{"institution": "string", "degree": "string", "year": "int"}],
    "experience": [{"company": "string", "title": "string", "duration": "string", "description": "string"}],
    "skills": ["string"],
    "languages": ["string"],
    "certifications": ["string"]
  },
  "processing_status": "string ('pending' | 'processing' | 'completed' | 'failed')",
  "schema_version": "int",
  "created_at": "ISODate",
  "updated_at": "ISODate"
}
```

### Collection: `jobs`

```json
{
  "_id": "ObjectId",
  "title": "string (required)",
  "company": "string (required)",
  "description": "string (required)",
  "location": "string (optional)",
  "url": "string (URL)",
  "apply_url": "string (URL, optional)",
  "skills": ["string"],
  "job_type": "string (enum)",
  "salary": "string (optional)",
  "source": "string ('searxng' | 'linkedin' | etc.)",
  "posted_date": "string (optional)",
  "created_at": "ISODate",
  "updated_at": "ISODate"
}
```

### Collection: `tailor_sessions`

```json
{
  "_id": "ObjectId",
  "resume_id": "string",
  "job_id": "string",
  "original_text_preview": "string (first 500 chars)",
  "tailored_text": "string",
  "cover_letter": "string",
  "cloudinary_pdf_url": "string",
  "cloudinary_docx_url": "string",
  "cloudinary_cover_letter_url": "string",
  "created_at": "ISODate",
  "updated_at": "ISODate"
}
```

### Indexes

- `resumes`: unique index on `resume_id`
- `jobs`: unique index on `url`; text index on `title, description, company`
- `tailor_sessions`: unique compound index on `(resume_id, job_id)`; compound index on `(resume_id, created_at)`

---

## 6. API Endpoints

Base URL: `http://localhost:8000/api/v1`

### Health Check

```
GET /health
→ {"status": "ok"}
```

### Jobs

#### Search Jobs

```
POST /api/v1/jobs/search
{
  "query": "software engineer react",
  "location": "remote"         # optional
}

→ [{
    "title": "Senior React Engineer",
    "company": "Acme Corp",
    "location": "Remote",
    "description": "...",
    "url": "https://...",
    "skills": ["React", "TypeScript"],
    "job_type": "full-time",
    "source": "linkedin"
  }]
```

#### Get Jobs (stored)

```
GET /api/v1/jobs?page=1&limit=20&q=react&source=linkedin
→ {
    "jobs": [...],
    "total": 42,
    "page": 1,
    "limit": 20
  }
```

### Resumes

#### Upload Resume

```
POST /api/v1/resumes/upload
Content-Type: multipart/form-data
file: <PDF or DOCX file>

→ {
    "resume_id": "abc123",
    "cloudinary_url": "https://res.cloudinary.com/...",
    "parsed_data": {
      "name": "John Doe",
      "email": "john@example.com",
      "skills": ["Python", "React"],
      ...
    },
    "extracted_text_preview": "John Doe\nPython Developer\n...",
    "processing_status": "completed"
  }
```

Supports: PDF, DOC, DOCX (max 10 MB).

#### Tailor Resume (Structured JSON Pipeline)

```
POST /api/v1/resumes/tailor-structured
{
  "resume_id": "<MongoDB ObjectId string>",
  "job_id": "<MongoDB ObjectId string>"
}

→ {
    "resume_id": "...",
    "job_id": "...",
    "tailored_data": {
      "summary": "Experienced engineer with 5 years in React...",
      "skills": ["React", "TypeScript", "Python"],
      "experience": [...],
      "projects": [...],
      "education": [...],
      "certifications": []
    },
    "tailored_text": "Plain text version of the tailored resume...",
    "cover_letter": "Dear Hiring Manager...",
    "download_urls": {
      "pdf": "https://res.cloudinary.com/...resume_pdf.pdf",
      "docx": "https://res.cloudinary.com/...resume_docx",
      "cover_letter_pdf": "https://res.cloudinary.com/...cover_letter.pdf"
    },
    "ats_keywords_matched": ["React", "TypeScript"],
    "ats_keywords_missing": ["GraphQL"],
    "optimization_notes": ["Consider adding GraphQL experience"],
    "llm_model": "qwen/qwen3-coder:free"
  }
```

#### Download via Proxy

```
POST /api/v1/resumes/download-from-url
{
  "url": "https://res.cloudinary.com/.../resume_pdf.pdf"
}

→ Streams the file bytes as a download (bypasses Cloudinary delivery restrictions)
```

### Response Models (defined in `app/models/resume.py`)

- `ResumeUploadResponse`: resume_id, cloudinary_url, parsed_data, extracted_text_preview, processing_status
- `StructuredTailorRequest`: resume_id (string), job_id (string)
- `StructuredTailorResponse`: resume_id, job_id, tailored_data (TailoredResumeData), tailored_text, cover_letter, download_urls (StructuredTailorDownloadUrls), ats_keywords_matched, ats_keywords_missing, optimization_notes, llm_model
- `StructuredTailorErrorResponse`: resume_id, job_id, error, tailored_text (optional)
- `StructuredTailorDownloadUrls`: pdf (str), docx (str), cover_letter_pdf (str, optional)
- `TailoredResumeData`: summary, skills, experience, projects, education, certifications

---

## 7. Services Layer

### `app/services/html_service.py` — The Core Formatter

This is the most important service. It implements the HTML round-trip:

| Function | Input | Output | Library |
|---|---|---|---|
| `docx_to_html(docx_bytes)` | DOCX bytes | HTML string | mammoth |
| `elements_to_html(elements)` | `list[ResumeElement]` | HTML string | Manual generation |
| `html_to_docx(html)` | HTML string | DOCX bytes | htmldocx |
| `html_to_pdf_async(html)` | HTML string | PDF bytes | Playwright |
| `extract_text_from_html(html)` | HTML string | Plain text | BeautifulSoup |
| `plain_text_to_html(text)` | Plain text | HTML string | Manual wrapping |

Key design:
- `html_to_docx` strips the `<html><head><body>` wrapper **before** passing to htmldocx (htmldocx expects body-level content only)
- `html_to_pdf_async` runs Playwright in a thread pool via `loop.run_in_executor` to avoid blocking the async event loop
- If Playwright is unavailable, falls back to reportlab text-based PDF generation

### `app/services/structured_tailor.py` — LLM Tailoring (Structured JSON Pipeline)

The **active** tailoring pipeline. Uses JSON-in/JSON-out with PII-safe chunking:

```
1. Take parsed_data (JSON) + job description (JSON)
2. Strip PII, education, certifications via pii_service.py (factual data preserved)
3. If data is large: split into 2-3 chunks, call LLM per chunk (parallel)
4. Reassemble chunks → final JSON → HTML → DOCX → PDF
5. Analyze ATS keyword match rates + generate optimization notes
```

Key functions:

| Function | Purpose |
|---|---|
| `tailor_resume_structured(resume_text, parsed_data, job)` | Main entry point — full pipeline |
| `_chunk_experience(experience, n_chunks)` | Split experience into balanced chunks |
| `_reassemble_chunks(chunks, base_data)` | Merge LLM outputs back together |
| `_generate_html_from_data(data, pii)` | Build HTML from structured JSON |
| `_analyze_ats_keywords(data, job)` | Compute match/missing keyword lists |

### `app/services/pii_service.py` — PII Stripping & Reinjection

Ensures personally identifiable information (name, email, phone) is **removed before LLM processing** and reinjected after:

| Function | Purpose |
|---|---|
| `strip_pii(data)` | Parses parsed_data → removes name/email/phone → returns safe copy + extracted PII |
| `reinject_pii(data, pii)` | Puts name/email/phone back into the final output |

### `app/services/resume_parser.py` — LLM Parsing

Takes plain text resume → configured LLM → structured JSON (name, skills, experience, education, etc.).

### `app/services/cover_letter.py` — LLM Cover Letter

Generates a 3-4 paragraph cover letter using candidate info + job description.

### `app/services/PDF_service.py` — PDF Handling

| Function | Purpose |
|---|---|
| `extract_text_from_pdf(bytes)` | Plain text extraction (pypdf) |
| `extract_structured_from_pdf(bytes)` | Structured extraction (PyMuPDF/fitz) with font metadata |
| `generate_pdf(text)` | PDF from plain text (reportlab) — used for cover letters |
| `generate_pdf_from_elements(elements)` | PDF from structured elements (reportlab) |
| `generate_pdf_from_docx(bytes)` | Legacy fallback |

### `app/services/docx_service.py` — DOCX Handling

| Function | Purpose |
|---|---|
| `extract_text_from_docx(bytes)` | Plain text extraction (python-docx) |
| `extract_structured_from_docx(bytes)` | Structured extraction with bold/link detection |
| `generate_docx(text)` | DOCX from plain text with heuristic headings (legacy) |
| `generate_docx_from_elements(elements)` | DOCX from structured elements with heading styles |
| `add_hyperlink_run(paragraph, url, text, ...)` | Low-level OOXML hyperlink insertion |
| `_render_text_with_hyperlinks(paragraph, element)` | Renders element text with inline links |

### `app/services/cloudinary_service.py` — File Storage

| Function | Purpose |
|---|---|
| `configure_cloudinary()` | Initialize Cloudinary SDK from settings |
| `upload_file(bytes, public_id, resource_type)` | Upload file → Cloudinary |
| `get_download_url(public_id, resource_type, file_format)` | Generate delivery URL |
| `stream_file(public_id, resource_type, file_format)` | Async generator for downloading through backend |
| `parse_cloudinary_url(url)` | Parse Cloudinary URL → components for re-download |

Key rules for Cloudinary:
- PDFs must use `resource_type="image"` (Cloudinary treats PDFs as images)
- `public_id` must NOT include file extensions
- Free accounts block PDF/ZIP delivery by default → uncheck in Settings > Security

### `app/services/db_service.py` — Database Operations

| Function | Purpose |
|---|---|
| `save_resume(db, resume_dict)` | Insert resume → returns ObjectId string |
| `get_resume_by_id(db, resume_id)` | Fetch resume by ObjectId |
| `save_tailor_session(db, session_dict)` | Save tailor session |
| `save_jobs(db, jobs_list)` | Bulk upsert jobs (by URL) |
| `get_jobs(db, filters)` | Query jobs with pagination, sorting, text search |
| `get_job_by_id(db, job_id)` | Fetch job by ObjectId |

### `app/core/llm.py` — LLM Entry Point

`call_llm(prompt, json_format=False, timeout=120, provider=None, max_tokens=4096, system_prompt=None)`

This is the **single entry point** for all LLM calls. It:
1. Delegates to `get_llm_provider(provider)` from `app/services/llm/factory.py`
2. Calls `provider.generate()` (sync) or `provider.generate_async()` (async)
3. Returns the raw response string (or empty string on failure)

The `provider` parameter accepts:
- **`None`** — uses the `LLM_PROVIDER` env var (or `LLM_PROVIDER_CHAIN` if `LLM_PROVIDER=multi`)
- **`"ollama"`, `"groq"`, `"cerebras"`, `"sambanova"`, `"nvidia"`, `"openrouter"`** — uses that single provider
- **`"multi"`** — uses the fallback chain from `LLM_PROVIDER_CHAIN`

**Important**: `call_llm` is a **synchronous** function that wraps the async call. When called from async endpoints, use `call_llm_async` instead to avoid blocking the event loop.

### `app/services/llm/` — Provider Architecture

The LLM provider system lives in `app/services/llm/` and follows an abstract base class pattern:

| File | Class | Provider |
|---|---|---|
| `base.py` | `LLMProvider` (ABC), `LLMResult` | Abstract interface |
| `ollama_provider.py` | `OllamaProvider` | Local Ollama instance |
| `openrouter_provider.py` | `OpenRouterProvider` | OpenRouter API (with model-level fallback) |
| `groq_provider.py` | `GroqProvider` | Groq API |
| `cerebras_provider.py` | `CerebrasProvider` | Cerebras API |
| `sambanova_provider.py` | `SambaNovaProvider` | SambaNova API |
| `nvidia_provider.py` | `NvidiaProvider` | NVIDIA NIM API |
| `multi_provider.py` | `MultiProvider` | Orchestrator (chains multiple providers) |
| `fallback_manager.py` | `FallbackManager` | Model-level fallback (used by OpenRouter) |
| `factory.py` | `get_llm_provider()` | Provider factory / singleton cache |

#### Multi-Provider Fallback

When `LLM_PROVIDER=multi`, `MultiProvider` chains providers in the order specified by `LLM_PROVIDER_CHAIN` (default: `groq,cerebras,sambanova,nvidia,openrouter`). On **any** error from a provider (429 rate limit, timeout, 5xx, empty response), it falls through to the next provider.

```
Groq ──failure──▶ Cerebras ──failure──▶ SambaNova ──failure──▶ NVIDIA ──failure──▶ OpenRouter
                                                                                     │
                                                                                     ▼
                                                                            8 free-tier models
                                                                           (model-level fallback)
```

The `OpenRouterProvider` itself wraps `FallbackManager` which internally tries 8 free-tier models with jittered exponential backoff. So if the chain reaches OpenRouter, it exhausts its own model fallback before returning failure.

#### Logging

Every provider logs structured messages so you can trace which provider+model handled each request:

```
[llm:multi] attempting provider=groq (1/5)
[llm:groq] failed — model=llama-3.3-70b-versatile error=rate limit exceeded
[llm:multi] provider=groq failed — falling through to next provider
[llm:multi] attempting provider=cerebras (2/5)
[llm:cerebras] success — model=gpt-oss-120b response_time=1234ms
[llm:multi] success — provider=cerebras model=gpt-oss-120b response_time=1234ms attempts=2
```

### `app/core/config.py` — Settings

Uses `pydantic_settings.BaseSettings`. Reads from `.env` file automatically.
The `Settings` class is instantiated once at module level as `settings`.

Key LLM-related settings:
- `LLM_PROVIDER` — selects provider mode (`"multi"`, `"ollama"`, `"openrouter"`, `"groq"`, etc.)
- `LLM_PROVIDER_CHAIN` — comma-separated chain for multi-provider fallback
- Per-provider `*_API_KEY`, `*_BASE_URL`, `*_MODEL` vars for each supported provider

### `app/core/database.py` — MongoDB Connection

- `connect_db()`: Creates `AsyncIOMotorClient`, pings to verify
- `close_db()`: Closes client on shutdown
- `get_database()`: Returns the database handle (used by dependency injection)

---

## 8. Resume Formatting Pipeline (The Core)

This is the most complex part of the system. Here's the complete flow.

### 8.1 Upload: Converting to HTML

```
                 ┌──────────────────────┐
                 │   Uploaded file       │
                 │   (PDF or DOCX)       │
                 └──────────┬───────────┘
                            │
                    ┌───────┴───────┐
                    │               │
                 PDF (is_pdf)    DOCX
                    │               │
                    ▼               ▼
            ┌────────────┐   ┌──────────┐
            │ PyMuPDF    │   │ mammoth  │
            │ (fitz)     │   │ (native) │
            └─────┬──────┘   └────┬─────┘
                  │               │
                  ▼               ▼
          ┌──────────────┐  ┌──────────┐
          │ elements_    │  │ docx_    │
          │ to_html()    │  │ to_html()│
          └──────┬───────┘  └────┬─────┘
                 │               │
                 └───────┬───────┘
                         ▼
                 ┌──────────────┐
                 │  resume_html │
                 │  (stored in  │
                 │   MongoDB)   │
                 └──────────────┘
```

**For DOCX**: `mammoth.convert_to_html()` extracts the document preserving:
- Heading 1/2/3 → `<h1>`, `<h2>`, `<h3>`
- Bold → `<strong>` or `<b>`
- Italic → `<em>` or `<i>`
- Links → `<a href="...">`
- Lists → `<ul>`, `<ol>`, `<li>`

The raw mammoth output is wrapped in a full HTML document with CSS:
```html
<!DOCTYPE html>
<html lang="en">
<head>
<style>
  body { font-family: Calibri, sans-serif; font-size: 11pt; }
  h2 { font-size: 13pt; color: #1A1A2E; border-bottom: 1px solid #ddd; }
  a { color: #0563C1; text-decoration: underline; }
</style>
</head>
<body>
<h1>John Doe</h1>
<h2>Experience</h2>
<p><strong>Senior Developer at Acme Corp</strong></p>
<ul>
  <li>Led a team of 5 engineers...</li>
  <li>Visit our <a href="https://example.com">website</a></li>
</ul>
</body>
</html>
```

**For PDF**: PyMuPDF extracts text blocks with font metadata. A heuristic
detects bold by checking font names containing "Bold" or "Black", and detects
headings by comparing font sizes to the page's most common body size. Then
`elements_to_html()` generates equivalent HTML from the extracted elements.

**Fallback**: If any step in the HTML conversion fails, `plain_text_to_html()`
wraps the extracted plain text in basic `<p>` tags.

### 8.2 Tailoring: Structured JSON Pipeline

The active tailoring pipeline uses **structured JSON** (not HTML editing). The flow:

```
parsed_data (JSON)                                                 
      │                                                            
      ▼                                                            
┌─────────────────┐                                                
│  strip_pii()    │  → removes name/email/phone, stores as PII     
└────────┬────────┘                                                
         ▼                                                        
┌─────────────────┐                                                
│  chunk if large │  → splits experience into 2-3 balanced chunks  
└────────┬────────┘                                                
         ▼                                                        
┌─────────────────┐                                                
│  LLM per chunk  │  → each chunk: "rewrite bullet points to match 
│  (parallel)     │     JD, use stronger action verbs, keep facts" 
└────────┬────────┘                                                
         ▼                                                        
┌─────────────────┐                                                
│  reassemble     │  → merges LLM outputs + base data              
└────────┬────────┘                                                
         ▼                                                        
┌─────────────────┐                                                
│  reinject_pii() │  → puts name/email/phone back                  
└────────┬────────┘                                                
         ▼                                                        
┌─────────────────┐                                                
│  JSON → HTML    │  → _generate_html_from_data()                  
└────────┬────────┘                                                
         ▼                                                        
┌─────────────────┐                                                
│  HTML → DOCX    │  → html_to_docx()                              
│  HTML → PDF     │  → html_to_pdf_async()                        
└─────────────────┘                                                
```

**Why JSON instead of HTML?**
- JSON has a fixed schema → no risk of the LLM breaking HTML tags
- Chunking is natural (split experience array) vs. splitting HTML mid-tag
- PII stripping is trivial (just remove fields) vs. scanning HTML text
- ATS keyword analysis is straightforward (compare JSON fields to JD)
- LLM can focus on content quality instead of tag preservation

The LLM prompt (`tailor_chunk_system_prompt` / `tailor_chunk_user_prompt` in `structured_tailor.py`) instructs the model to:
- Rewrite bullet points to match job description keywords
- Use stronger action verbs (led, designed, implemented, optimized)
- Keep all factual information accurate
- Return strictly valid JSON matching the output schema

### 8.3 Download: Converting Back to DOCX and PDF

**DOCX**: `html_to_docx()` → `htmldocx.HtmlToDocx.add_html_to_document()`
- The HTML body is extracted from the wrapper (strips `<html>`, `<head>`, `<style>`)
- htmldocx converts `<h2>`, `<p>`, `<strong>`, `<a>`, `<ul>`/`<li>` to native DOCX styles
- Bold text becomes real `w:b` OOXML runs
- Links become real `w:hyperlink` relationships
- Headings become real Heading 2/Heading 3 styles

**PDF**: `html_to_pdf_async()` → Playwright (headless Chromium)
- Writes HTML to a temp file
- Opens it in headless Chromium via Playwright
- Calls `page.pdf()` with letter format and proper margins
- Returns the raw PDF bytes
- Falls back to reportlab text extraction if Playwright fails

### 8.4 The ResumeElement Model

Defined in `app/models/resume_elements.py`:

```python
class ResumeLink(BaseModel):
    text: str          # Display text of the link
    url: str           # Target URL

class ResumeElement(BaseModel):
    text: str          # The displayed text
    type: str          # "heading" | "subheading" | "bullet" | "normal"
    bold: bool         # Whether text should be bold
    links: list[ResumeLink]  # Hyperlinks in this element
    font_size_pt: float | None  # Optional font size override
```

This model is used as an intermediate representation when converting PDFs to
HTML (since mammoth can't handle PDFs).

---



## 9. Agent Workflows

### LangGraph-based Job Search

Defined in `app/agents/graph.py` and `app/agents/job_workflow.py`.

The job search uses separate LangGraph agents for different search sources:

```
┌────────────────────────────────────────────────────────────────┐
│                    search_jobs_workflow(query)                  │
│                                                                 │
│  1. Parse user input (LLM generates targeted search queries)   │
│  2. SearXNG search (if enabled)                                │
│  3. LinkedIn Guest API search (if enabled)                     │
│  4. LLM ranks + deduplicates results                           │
│  5. Browse top results (extract full job details via MCP)      │
│  6. Return structured job objects                              │
└────────────────────────────────────────────────────────────────┘
```

The agent state (`app/agents/state.py`):
```python
class AgentState(TypedDict):
    query: str
    location: Optional[str]
    raw_jobs: List[dict]
    jobs_with_skills: List[dict]
    resume_text: Optional[str]
    tailored_resume: Optional[str]
```

### MCP Server Nodes

The `/app/agents/nodes/` directory contains:
- `job_mcp_server.py` — MCP server for job search tools
- `job_mcp_browse_server.py` — MCP server for browsing job pages
- `search_jobs.py` — Job search node
- `extract_skills.py` — Skill extraction node
- `tailor_resume.py` — Resume tailoring node (minimal implementation)

---

## 10. Migrations

Migrations live in `backend/migrations/` and are numbered sequentially:

| File | Purpose |
|---|---|
| `001_initial_schema.py` | Creates all MongoDB collections with JSON schema validation |
| `006_cleanup_unused_collections.py` | Drops unused collections (users, applications, etc.) |
| `007_add_job_search_indexes.py` | Creates search indexes on jobs collection |
| `008_add_tailor_sessions.py` | Creates tailor_sessions collection with validation |
| `009_add_structured_elements.py` | Adds `structured_elements` field to resumes schema |
| `ROLLBACK.py` | Destructive rollback of all migrations |

### Running Migrations

**Option 1: Migration runner (recommended)**

```bash
cd backend
python scripts/run_migrations.py --uri "mongodb+srv://..." --db jobapp
```

This runs all pending migrations in order. You'll be prompted to confirm.

**Option 2: Individual migration**

```bash
cd backend
python -m migrations.009_add_structured_elements --uri "mongodb+srv://..." --db jobapp
```

### After adding a new field

When you add a new field to a MongoDB document, you may need to update the
collection's JSON schema validator. The schema validators use
`validationLevel: "moderate"` which allows extra fields not defined in the
schema. So new fields are generally accepted without schema changes.

However, if the schema uses `additionalProperties: false` or the field has
a specific type requirement, you'll need a new migration.

---

## 11. Testing

### Running existing tests

```bash
cd backend
python -m pytest tests/ -v
```

### Test structure

- `tests/test_db_service.py` — Database service tests
- `tests/__init__.py` — Test package init
- `test/test_integration.py` — Integration tests

### Manual testing workflow

1. Start the server: `uvicorn app.main:app --reload --port 8000`
2. Upload a test DOCX resume:
   ```bash
   curl -X POST http://localhost:8000/api/v1/resumes/upload \
     -F "file=@resume.docx"
   ```
3. Note the `resume_id` from the response
4. Get a job ObjectId from the database, then tailor:
   ```bash
   curl -X POST http://localhost:8000/api/v1/resumes/tailor-structured \
     -H "Content-Type: application/json" \
     -d '{"resume_id": "<resume_id>", "job_id": "<job_id>"}'
   ```
5. Download the files using the URLs in `download_urls`

### Testing the HTML round-trip directly

```python
from app.services.html_service import docx_to_html, html_to_docx

# Read a DOCX file
with open("resume.docx", "rb") as f:
    docx_bytes = f.read()

# DOCX → HTML
html = docx_to_html(docx_bytes)
print(html[:500])

# HTML → DOCX
output_bytes = html_to_docx(html)

# Save
with open("output.docx", "wb") as f:
    f.write(output_bytes)
```

---

## 12. Deployment

### Server

```bash
cd backend
pip install -r requirements.txt
python -m playwright install chromium
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

For production:
```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 4
```

### Docker

A `services/docker-compose.yml` file exists for SearXNG and other services.
The backend itself doesn't have a Dockerfile yet — create one with:

```dockerfile
FROM python:3.13-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt && python -m playwright install chromium
COPY . .
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

### Dependencies with system requirements

| Library | System Dependencies |
|---|---|
| **Playwright** | Downloads Chromium browser (~150MB) via `playwright install chromium` |
| **PyMuPDF** | None (pure Python wheel on Windows, may need build tools on Linux) |
| **pypdf** | None (pure Python) |
| **reportlab** | None (pure Python) |
| **weasyprint** | NOT USED — requires GTK/Pango/Cairo system libraries, not installed |

### Cloudinary

If using Cloudinary for file storage:
1. Create a free account at cloudinary.com
2. Get your cloud name, API key, and API secret
3. In Cloudinary Dashboard → Settings → Security:
   - **Uncheck** "Restrict media delivery and block PDF and ZIP files"
   - PDF delivery is blocked by default on free accounts

---

## 13. Troubleshooting

### "Structured extraction failed" warning

This means the PyMuPDF-based structured extraction failed for a PDF upload.
The system falls back gracefully to plain text. This can happen with:
- Scanned/image-based PDFs (no selectable text)
- Corrupted PDFs
- PDFs with unusual encoding

### "HTML conversion failed" warning

Mammoth failed to convert a DOCX to HTML. Falls back to plain text wrapped in
basic `<p>` tags. Try:
- Saving the DOCX in a newer/older Word format
- Checking if the file is actually a DOCX (rename .doc files)

### LLM returns malformed JSON

- Each chunk's LLM call is wrapped in `try/except` — bad chunks are skipped
- JSON parsing uses `json.loads()` with cleanup (strip markdown fences)
- If the entire response fails, the original resume data is returned untailored

### Playwright PDF generation fails

- If `playwright` is not installed: falls back to reportlab text-based PDF
- If Chromium fails to launch: check that `playwright install chromium` was run
- Run `playwright install --with-deps chromium` to install system dependencies

### Cloudinary blocks PDF download

Free Cloudinary accounts block PDF delivery by default. Fix:
1. Go to Cloudinary Dashboard → Settings → Security
2. Uncheck "Restrict media delivery and block PDF and ZIP files delivery"
3. Save changes

### MongoDB validation errors

If you get a `Document failed validation` error:
1. The collection has a JSON schema validator
2. Check if a field has a type requirement your data doesn't match
3. Run `db.getCollectionInfos()` in mongosh to see the current validator
4. Either update the validator (create a migration) or fix the data

### .env not found

If you see `Field required` errors for settings like `MONGODB_URI`:
1. Create a `.env` file in `backend/`
2. Copy variables from `.env.example` if it exists
3. Or set them as OS environment variables

---

## 14. File Map

```
backend/
├── .env                        # Environment variables (gitignored)
├── .gitignore
├── README.md
├── requirements.txt            # Python dependencies
│
├── app/
│   ├── main.py                 # FastAPI app, CORS, routes, startup/shutdown
│   │
│   ├── api/
│   │   ├── deps.py             # Dependency injection (get_db)
│   │   └── v1/
│   │       ├── jobs.py         # /api/v1/jobs/* endpoints
│   │       └── resumes.py      # /api/v1/resumes/* endpoints
│   │
│   ├── core/
│   │   ├── config.py           # Settings class (reads .env)
│   │   ├── database.py         # MongoDB connection (async)
│   │   └── llm.py              # call_llm() — Multi-provider entry point
│   │
│   ├── models/
│   │   ├── resume.py           # Pydantic models for API request/response
│   │   ├── resume_elements.py  # ResumeElement, ResumeLink (structured format)
│   │   └── job.py              # JobResult model
│   │
│   ├── services/
│   │   ├── html_service.py     # ⭐ HTML round-trip (mammoth, htmldocx, Playwright)
│   │   ├── structured_tailor.py # ⭐ Structured JSON tailoring (PII-safe, chunked)
│   │   ├── pii_service.py      # PII stripping & reinjection
│   │   ├── resume_parser.py    # LLM resume parsing (extract name/skills/etc)
│   │   ├── cover_letter.py     # LLM cover letter generation
│   │   ├── docx_service.py     # DOCX read/write (python-docx)
│   │   ├── PDF_service.py      # PDF read/write (pypdf, PyMuPDF, reportlab)
│   │   ├── cloudinary_service.py  # Cloudinary upload/download/stream
│   │   ├── db_service.py       # MongoDB CRUD operations
│   │   │
│   │   └── llm/                # ⭐ Multi-provider LLM architecture
│   │       ├── __init__.py         # Re-exports all providers
│   │       ├── base.py            # LLMProvider ABC + LLMResult
│   │       ├── factory.py         # get_llm_provider() factory
│   │       ├── fallback_manager.py  # Model-level fallback (OpenRouter)
│   │       ├── multi_provider.py  # Provider-level orchestration
│   │       ├── ollama_provider.py # Ollama provider
│   │       ├── openrouter_provider.py # OpenRouter provider
│   │       ├── groq_provider.py   # Groq provider
│   │       ├── cerebras_provider.py  # Cerebras provider
│   │       ├── sambanova_provider.py # SambaNova provider
│   │       └── nvidia_provider.py # NVIDIA NIM provider
│   │
│   └── agents/
│       ├── state.py            # AgentState TypedDict
│       ├── graph.py            # LangGraph state machine
│       ├── job_workflow.py     # Main job search orchestration
│       ├── search_provider.py  # Search source provider
│       ├── tools/
│       │   ├── web_search.py   # Web search tool
│       │   ├── skill_extraction.py  # Skill extraction tool
│       │   └── browse_jobs.py  # Job browsing tool
│       └── nodes/
│           ├── search_jobs.py       # Job search agent node
│           ├── extract_skills.py    # Skill extraction node
│           ├── tailor_resume.py     # Resume tailoring node
│           ├── job_mcp_server.py    # MCP server for job search
│           └── job_mcp_browse_server.py  # MCP server for browsing
│
├── migrations/
│   ├── 001_initial_schema.py       # Create collections + validation
│   ├── 006_cleanup_unused_collections.py
│   ├── 007_add_job_search_indexes.py
│   ├── 008_add_tailor_sessions.py
│   ├── 009_add_structured_elements.py
│   └── ROLLBACK.py
│
├── scripts/
│   ├── run_migrations.py           # Migration runner
│   ├── create_indexes.py
│   ├── clear_data.py
│   ├── generate_test_data.py
│   └── list_unused_collections.py
│
├── tests/
│   ├── test_db_service.py
│   └── __init__.py
├── test/
│   └── test_integration.py
│
├── services/
│   └── docker-compose.yml          # SearXNG + other services
│
└── docs/
    ├── FROM_SCRATCH.md              ← You are here
    ├── Frontend Planning.md
    ├── MONGODB_SCHEMAS_ATLAS.md
    ├── QUICK_REFERENCE.md
    └── ...
```

---

## Appendix: LLM Prompts Reference

### Resume Tailoring (Structured JSON)

File: `app/services/structured_tailor.py` → `tailor_chunk_system_prompt` / `tailor_chunk_user_prompt`

The system prompt instructs the LLM to:
- Rewrite experience bullet points to match job description keywords
- Use stronger action verbs (led, designed, implemented, optimized)
- Keep factual information accurate
- Return strictly valid JSON matching the output schema

The user prompt provides:
- The chunk of experience entries (as JSON array)
- The job description, title, and required skills
- Instructions on ATS keyword optimization

### Cover Letter

File: `app/services/cover_letter.py` → `COVER_LETTER_PROMPT`

```
You are a professional cover letter writer. Write a compelling cover letter
for a job application.

Candidate Name: {candidate_name}
Candidate Skills:
{candidate_skills}
...
```

### Resume Parsing

File: `app/services/resume_parser.py` → `PARSE_PROMPT_TEMPLATE`

```
You are a resume parser. Extract structured information from the following
resume text. Return ONLY valid JSON with this exact structure:
{
  "name": "...",
  "email": "...",
  "phone": "...",
  ...
}
```

---

*End of documentation. Last updated: 2026-06-23.*
