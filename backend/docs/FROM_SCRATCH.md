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
| **Groq (LLaMA 3.3 70B)** | LLM provider for resume parsing/tailoring |
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
│  │  call_llm() — Groq/Ollama LLM provider            │      │
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
5. Parses extracted text with Groq LLM (extracts name, skills, etc.)
6. Uploads original file to Cloudinary
7. Saves to MongoDB: { resume_id, extracted_text, resume_html, parsed_data, ... }
```

### Data Flow: Resume Tailoring

```
1. User sends { resume_id, job_id }
2. Server fetches resume + job from MongoDB
3. Loads resume_html from database (or generates from plain text for legacy resumes)
4. Calls Groq LLM with prompt: "Edit this HTML text to match the job, preserve all tags"
5. Sanitizes returned HTML with BeautifulSoup
6. Generates downloadable files:
   - DOCX: htmldocx (HTML → DOCX)
   - PDF: Playwright (HTML → PDF via Chromium)
   - Cover letter PDF: reportlab (plain text)
7. Uploads all files to Cloudinary
8. Returns download URLs to frontend
```

---

## 3. Quick Start (5 minutes)

### Prerequisites

- Python 3.13+
- MongoDB (Atlas or local) — get a free cluster at mongodb.com
- Groq API key — get one at console.groq.com
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
GROQ_API_KEY=gsk_your_key_here
SEARXNG_URL=http://localhost:4000
CAMOFOX_URL=http://localhost:4000
LINKEDIN_GUEST_API_ENABLED=False
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

| Variable | Required | Default | Description |
|---|---|---|---|
| `MONGODB_URI` | **Yes** | — | MongoDB connection string |
| `SEARXNG_URL` | **Yes** | — | SearXNG instance URL |
| `CAMOFOX_URL` | **Yes** | — | Camofox search URL |
| `LINKEDIN_GUEST_API_ENABLED` | **Yes** | — | Enable LinkedIn job search (`True`/`False`) |
| `GROQ_API_KEY` | No | — | Groq API key (needed for LLM features) |
| `GROQ_MODEL_NAME` | No | `llama-3.3-70b-versatile` | Groq model to use |
| `LLM_PROVIDER` | No | `ollama` | `groq`, `ollama`, or `gemini` |
| `CLOUDINARY_CLOUD_NAME` | No | — | Cloudinary cloud name |
| `CLOUDINARY_API_KEY` | No | — | Cloudinary API key |
| `CLOUDINARY_API_SECRET` | No | — | Cloudinary API secret |
| `MCP_SEARCH_URL` | No | `http://localhost:8001` | MCP search server |
| `MCP_BROWSE_URL` | No | `http://localhost:8002` | MCP browse server |
| `Ollama` | No | `http://localhost:11434` | Ollama server URL |
| `MODEL_NAME` | No | `qwen2.5-coder:1.5b` | Ollama model name |
| `MODEL_TEMPERATURE` | No | `0.1` | LLM temperature |
| `SEARCH_MAX_RESULTS` | No | `15` | Max jobs to return per search |
| `SEARXNG_ENABLED` | No | `False` | Enable SearXNG search |
| `LOG_LEVEL` | No | `INFO` | Logging level |

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

#### Tailor Resume

```
POST /api/v1/resumes/tailor
{
  "resume_id": "<MongoDB ObjectId string>",
  "job_id": "<MongoDB ObjectId string>"
}

→ {
    "resume_id": "...",
    "job_id": "...",
    "tailored_text": "Rewritten resume with job-matched keywords...",
    "cover_letter": "Dear Hiring Manager...",
    "download_urls": {
      "pdf": "https://res.cloudinary.com/...resume_pdf.pdf",
      "docx": "https://res.cloudinary.com/...resume_docx",
      "cover_letter_pdf": "https://res.cloudinary.com/...cover_letter.pdf"
    }
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
- `ResumeTailorRequest`: resume_id (string), job_id (string)
- `ResumeTailorResponse`: resume_id, job_id, tailored_text, cover_letter, download_urls
- `ResumeTailorErrorResponse`: resume_id, job_id, error, tailored_text (optional)
- `DownloadUrls`: pdf (str), docx (str), cover_letter_pdf (str, optional)

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
| `validate_html(html)` | HTML string | Sanitized HTML | BeautifulSoup |
| `extract_text_from_html(html)` | HTML string | Plain text | BeautifulSoup |
| `plain_text_to_html(text)` | Plain text | HTML string | Manual wrapping |

Key design:
- `html_to_docx` strips the `<html><head><body>` wrapper **before** passing to htmldocx (htmldocx expects body-level content only)
- `html_to_pdf_async` runs Playwright in a thread pool via `loop.run_in_executor` to avoid blocking the async event loop
- If Playwright is unavailable, falls back to reportlab text-based PDF generation

### `app/services/resume_tailor.py` — LLM Tailoring

Three tailoring strategies (all using `call_llm` from `app.core.llm`):

| Function | Use Case | Prompt |
|---|---|---|
| `tailor_resume_text(text, job)` | Legacy resumes (no HTML stored) | Tells LLM to return plain text |
| `tailor_resume_html(html, job)` | **Primary path** | Tells LLM to preserve all HTML tags, only edit text content |
| `tailor_resume_structured(elements, job)` | Deprecated (kept for reference) | JSON-in/JSON-out with schema constraints |

### `app/services/resume_parser.py` — LLM Parsing

Takes plain text resume → Groq LLM → structured JSON (name, skills, experience, education, etc.).

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

### `app/core/llm.py` — LLM Provider

`call_llm(prompt, json_format=False, timeout=120, provider=None)`

This is the **single entry point** for all LLM calls. It:
1. Checks `LLM_PROVIDER` setting (or explicit `provider` arg)
2. Routes to the appropriate provider implementation:
   - **Groq**: Uses `groq` Python SDK with `response_format={"type": "json_object"}` for JSON mode
   - **Ollama**: Uses `ollama` Python SDK with threading for timeout support
   - **Gemini**: Not fully implemented
3. Returns the raw response string

**Important**: `call_llm` is a **synchronous** function (not async). When called from
async endpoints, it blocks the event loop. This is acceptable for the current
workload but should be wrapped in `run_in_executor` if concurrency becomes an issue.

### `app/core/config.py` — Settings

Uses `pydantic_settings.BaseSettings`. Reads from `.env` file automatically.
The `Settings` class is instantiated once at module level as `settings`.

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

### 8.2 Tailoring: LLM Edits the HTML

The LLM prompt (`TAILOR_HTML_PROMPT` in `resume_tailor.py`) instructs:

> "Rewrite the resume text to best match the job. CRITICAL RULE: Preserve
> all HTML tags and structure EXACTLY as they are. Only change the TEXT
> content between tags. Do NOT add, remove, or modify any HTML tags."

After the LLM responds, `validate_html()` uses BeautifulSoup to:
- Parse the HTML into a valid DOM tree (fixes unclosed tags)
- Removes any `<script>` or `<style>` tags the LLM might have injected
- Returns well-formed HTML

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
HTML (since mammoth can't handle PDFs). It's also the data structure used by
the (now deprecated) structured elements pipeline.

### 8.5 Legacy Support

Resumes uploaded **before** the HTML round-trip was implemented won't have
`resume_html` in MongoDB. The system detects this and falls back to:
1. `tailor_resume_text()` → plain text tailoring via LLM
2. `plain_text_to_html()` → wraps result in basic HTML
3. Same DOCX/PDF generation from the basic HTML (formatting will be minimal)

Users should re-upload their resumes after the HTML update to get full
formatting preservation.

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
   curl -X POST http://localhost:8000/api/v1/resumes/tailor \
     -H "Content-Type: application/json" \
     -d '{"resume_id": "<resume_id>", "job_id": "<job_id>"}'
   ```
5. Download the files using the URLs in `download_urls`

### Testing the HTML round-trip directly

```python
from app.services.html_service import docx_to_html, html_to_docx, validate_html

# Read a DOCX file
with open("resume.docx", "rb") as f:
    docx_bytes = f.read()

# DOCX → HTML
html = docx_to_html(docx_bytes)
print(html[:500])

# Validate
html = validate_html(html)

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

### LLM returns malformed JSON or HTML

- For HTML tailoring: `validate_html()` uses BeautifulSoup to fix unclosed tags
- The per-element `try/except` in `tailor_resume_structured` skips bad elements
- If the entire response fails, the original resume is returned untailored

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
│   │   └── llm.py              # call_llm() — Groq + Ollama provider
│   │
│   ├── models/
│   │   ├── resume.py           # Pydantic models for API request/response
│   │   ├── resume_elements.py  # ResumeElement, ResumeLink (structured format)
│   │   └── job.py              # JobResult model
│   │
│   ├── services/
│   │   ├── html_service.py     # ⭐ HTML round-trip (mammoth, htmldocx, Playwright)
│   │   ├── resume_tailor.py    # LLM tailoring (text, HTML, structured)
│   │   ├── resume_parser.py    # LLM resume parsing (extract name/skills/etc)
│   │   ├── cover_letter.py     # LLM cover letter generation
│   │   ├── docx_service.py     # DOCX read/write (python-docx)
│   │   ├── PDF_service.py      # PDF read/write (pypdf, PyMuPDF, reportlab)
│   │   ├── cloudinary_service.py  # Cloudinary upload/download/stream
│   │   └── db_service.py       # MongoDB CRUD operations
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

### Resume Tailoring (HTML)

File: `app/services/resume_tailor.py` → `TAILOR_HTML_PROMPT`

```
You are a professional resume writer. You will receive a candidate's resume
as formatted HTML, and a job description. Rewrite the resume text to best
match the job requirements.

CRITICAL RULE: You must PRESERVE all HTML tags and structure EXACTLY as they are.
Only change the TEXT content between tags.
- DO NOT add, remove, or modify any HTML tags or attributes
- DO NOT change heading text (section names like "Experience" are fine as-is)
- You MAY rewrite bullet items and paragraph text
- Preserve ALL <a href="..."> tags and their href attributes

Candidate's Resume HTML:
{resume_html}

Job Title: {job_title}
Job Description:
{job_description}
Required Skills: {job_skills}

Instructions:
1. Rewrite paragraph and bullet text to use stronger action verbs and keywords.
2. Reorder bullet points within sections to put the most relevant ones first.
3. Keep all factual information accurate — do NOT fabricate experience.
4. Return ONLY the modified HTML — no commentary, no markdown formatting.
```

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

*End of documentation. Last updated: 2026-06-20.*
