# Job App Backend

A FastAPI + MongoDB backend for job search aggregation, resume parsing, and AI-powered resume tailoring. Orchestrates multi-source job scraping (LinkedIn, SearXNG), stores results with full-text search, parses uploaded resumes via LLM, and tailors them against job descriptions through a PII-safe structured pipeline.

**Key technologies:** FastAPI, Motor (async MongoDB), LangGraph, Ollama / Groq / OpenRouter / Cerebras / SambaNova / NVIDIA NIM, Cloudinary.

## Features

- **Multi-source job search** — aggregates results from LinkedIn Guest API, SearXNG meta-search engine, and configurable career sites via an MCP-based agent workflow.
- **Persistent job storage** — upserts results into MongoDB (keyed by URL), supports filtering, pagination, full-text search, and sorting.
- **Resume upload & LLM parsing** — accepts PDF and DOCX files, extracts text, converts to HTML, sends to an LLM for structured field extraction (name, skills, education, experience, etc.), and stores on Cloudinary.
- **PII-safe structured tailoring** — strips personally identifying information before sending resume + job description to an LLM, then re-injects PII into the tailored result. Generates downloadable PDF and DOCX files plus a cover letter.
- **Multi-provider LLM abstraction** — pluggable backend supporting Ollama (local), Groq, Cerebras, SambaNova, NVIDIA NIM, and OpenRouter with automatic fallback chaining.
- **Proxy file download** — serves Cloudinary-stored files through the backend to work around free-plan access restrictions.
- **Interactive API docs** — auto-generated Swagger UI and ReDoc.

## Project Structure

```
backend/
├── app/
│   ├── main.py                         # FastAPI application entry point, CORS, startup/shutdown
│   │
│   ├── api/
│   │   ├── deps.py                     # Dependency injection (MongoDB session)
│   │   └── v1/
│   │       ├── jobs.py                 # POST /search, GET /jobs, GET /jobs/{id}
│   │       └── resumes.py              # POST /upload, /tailor-structured, /download-from-url
│   │
│   ├── agents/                         # LangGraph job search agent system
│   │   ├── graph.py                    # Agent graph definition
│   │   ├── job_workflow.py             # Job search orchestration
│   │   ├── search_provider.py          # Search provider abstraction
│   │   ├── mcp_client.py               # MCP protocol client
│   │   ├── state.py                    # Agent state schemas
│   │   ├── nodes/                      # Pipeline steps (skill extraction, MCP servers, tailoring)
│   │   └── tools/                      # Callable utilities (browse jobs, web search)
│   │
│   ├── core/
│   │   ├── config.py                   # Pydantic Settings from .env
│   │   ├── database.py                 # Motor MongoDB client (connect, close, get_db)
│   │   └── llm.py                      # LLM routing helper
│   │
│   ├── models/
│   │   ├── job.py                      # JobResult, JobSearchResponse, JobListResponse, JobDetailResponse, etc.
│   │   ├── resume.py                   # ParsedResumeData, ResumeUploadResponse, StructuredTailorResponse, etc.
│   │   └── resume_elements.py          # Structured resume element models
│   │
│   └── services/
│       ├── db_service.py               # CRUD for jobs, resumes, tailor_sessions
│       ├── cloudinary_service.py       # Cloudinary upload, download URL generation, streaming
│       ├── cover_letter.py             # Cover letter generation via LLM
│       ├── docx_service.py             # DOCX text extraction (python-docx)
│       ├── html_service.py             # HTML conversion (docx↔html, html→pdf)
│       ├── PDF_service.py              # PDF text extraction (PyMuPDF) and generation (ReportLab)
│       ├── pii_service.py              # PII redaction utilities
│       ├── resume_parser.py            # Resume text → structured data via Groq LLM
│       ├── structured_tailor.py        # Structured resume tailoring pipeline
│       ├── llm/                        # LLM provider abstraction
│       │   ├── base.py                 # Abstract provider
│       │   ├── factory.py              # Provider factory
│       │   ├── fallback_manager.py     # Fallback chain manager
│       │   ├── groq_provider.py
│       │   ├── cerebras_provider.py
│       │   ├── sambanova_provider.py
│       │   ├── nvidia_provider.py
│       │   ├── ollama_provider.py
│       │   ├── openrouter_provider.py
│       │   └── multi_provider.py
│       └── resume_tailor_engine/       # Tailoring sub-engine
│           ├── llm_client.py
│           ├── parser.py
│           ├── reinjector.py           # Re-injects PII after LLM call
│           ├── validator.py
│           └── verifier.py
│
├── docs/                               # Developer documentation (per AGENTS.md workflow)
│   ├── AGENTS.md
│   ├── DOC_TEMPLATE.md
│   ├── INDEX.md
│   ├── jobs.md
│   └── resume.md
│
├── migrations/                         # MongoDB schema migrations (numbered 001–009)
│   ├── 001_initial_schema.py
│   ├── ...
│   └── ROLLBACK.py
│
├── scripts/                            # Operational utilities
│   ├── run_migrations.py
│   ├── create_indexes.py
│   ├── clear_data.py
│   ├── generate_test_data.py
│   └── list_unused_collections.py
│
├── services/                           # Infrastructure Docker configs
│   ├── docker-compose.yml              # SearXNG + Camofox browser service
│   └── searxng/                        # SearXNG settings and limiter config
│
├── tests/                              # Unit tests
│   ├── __init__.py
│   └── test_db_service.py
│
├── test/                               # Integration tests
│   └── test_integration.py
│
├── .env.example                        # Environment variable template
├── requirements.txt                    # Python dependencies
└── mcp_browse.py                       # Standalone MCP browse server
```

## Architecture Overview

```
┌──────────┐     ┌──────────────────────────────────────────────────────┐
│  Client  │────▶│                 FastAPI (uvicorn)                     │
└──────────┘     │                                                      │
                 │  /api/v1/jobs/*          /api/v1/resumes/*            │
                 │       │                         │                    │
                 │       ▼                         ▼                    │
                 │  ┌──────────┐          ┌──────────────┐              │
                 │  │  Agents  │          │   Services   │              │
                 │  │LangGraph │          │ ┌──────────┐ │              │
                 │  │ workflow │          │ │Resume    │ │              │
                 │  │ + MCP    │          │ │Parser    │ │              │
                 │  │ servers  │          │ ├──────────┤ │              │
                 │  └────┬─────┘          │ │Tailor    │ │              │
                 │       │                │ │Engine    │ │              │
                 │       ▼                │ ├──────────┤ │              │
                 │  ┌──────────┐          │ │LLMProv.  │ │              │
                 │  │ MongoDB  │◀─────────│ │Abstrac.  │ │              │
                 │  │ (Motor)  │─────────▶│ ├──────────┤ │              │
                 │  └──────────┘          │ │Cloudinary│ │              │
                 │                        │ │+ Docs    │ │              │
                 │                        │ └──────────┘ │              │
                 └──────────────────────────────────────────────────────┘
                                    │
                                    ▼
                          ┌─────────────────┐
                          │  External APIs   │
                          │  LinkedIn Guest  │
                          │  SearXNG         │
                          │  LLM Providers   │
                          │  Cloudinary      │
                          └─────────────────┘
```

The application follows a layered architecture:
1. **Routes** (`app/api/v1/`) — validate inputs, delegate to agents/services, shape responses.
2. **Agents** (`app/agents/`) — LangGraph-based orchestration for multi-step job search workflows.
3. **Services** (`app/services/`) — all business logic: database CRUD, document processing, LLM calls, file storage.
4. **LLM Abstraction** (`app/services/llm/`) — unified interface over 7 provider backends with automatic fallback.
5. **Models** (`app/models/`) — Pydantic schemas for request validation and response serialization.
6. **Core** (`app/core/`) — configuration, database connection lifecycle, shared utilities.

## Installation & Setup

### Prerequisites
- Python 3.11+
- MongoDB (local or Atlas)
- (Optional) Docker + Docker Compose for SearXNG and Camofox

### 1. Clone the repository
```bash
git clone <repo-url>
cd backend
```

### 2. Create and activate a virtual environment
```bash
python -m venv .venv

# Windows
.venv\Scripts\activate

# macOS / Linux
source .venv/bin/activate
```

### 3. Install dependencies
```bash
pip install -r requirements.txt
```

### 4. Configure environment variables
```bash
cp .env.example .env
# Edit .env with your MongoDB URI, API keys, and provider preferences
```

### 5. Install Playwright browsers (for browser-based scraping)
```bash
playwright install
```

### 6. (Optional) Start infrastructure services
```bash
cd services
docker-compose up -d
```

### 7. Run database migrations
```bash
python scripts/run_migrations.py
```

## Running the Application

Start the FastAPI server with uvicorn:

```bash
uvicorn app.main:app --reload --port 8000
```

The API will be available at `http://localhost:8000`.

## API Documentation

Once the server is running:

| Docs | URL |
|---|---|
| Swagger UI | `http://localhost:8000/docs` |
| ReDoc | `http://localhost:8000/redoc` |
| Health Check | `http://localhost:8000/health` |

### Available Endpoints

| Method | Path | Description |
|---|---|---|
| `POST` | `/api/v1/jobs/search` | Search jobs via agents (plain-text query) |
| `GET` | `/api/v1/jobs/jobs` | List stored jobs with filters/pagination |
| `GET` | `/api/v1/jobs/jobs/{job_id}` | Get job detail with resume/tailoring lifecycle |
| `POST` | `/api/v1/resumes/upload` | Upload and parse a resume (PDF/DOCX) |
| `POST` | `/api/v1/resumes/tailor-structured` | Tailor resume against a job (PII-safe) |
| `POST` | `/api/v1/resumes/download-from-url` | Proxy-download a Cloudinary file |
| `GET` | `/health` | Health check |

## Environment Variables

| Variable | Required | Default | Description |
|---|---|---|---|
| `MONGODB_URI` | **Yes** | `mongodb://localhost:27017/jobapp` | MongoDB connection string |
| `LLM_PROVIDER` | No | `ollama` | LLM backend: `ollama`, `openrouter`, `groq`, `cerebras`, `sambanova`, `nvidia`, `multi` |
| `OPENROUTER_API_KEY` | Conditional | — | Required if using OpenRouter provider |
| `GROQ_API_KEY` | Conditional | — | Required if using Groq provider |
| `CLOUDINARY_CLOUD_NAME` | Conditional | — | Required for resume file storage |
| `CLOUDINARY_API_KEY` | Conditional | — | Required for resume file storage |
| `CLOUDINARY_API_SECRET` | Conditional | — | Required for resume file storage |
| `SEARXNG_URL` | No | `http://localhost:8888` | SearXNG instance URL |
| `LINKEDIN_GUEST_API_ENABLED` | No | `false` | Enable LinkedIn Guest API search source |
| `SEARXNG_ENABLED` | No | `false` | Enable SearXNG search source |
| `LOG_LEVEL` | No | `INFO` | Logging level |

See `.env.example` for the full list of all configurable options and provider-specific variables.

## Testing

```bash
# Run unit tests
pytest tests/

# Run integration tests
python test/test_integration.py
```

Current test coverage: `test_db_service.py` covers `save_jobs` behavior (deduplication, timestamp injection, empty-list handling). Resume endpoints have no dedicated tests yet.

## Docker Setup

The `services/docker-compose.yml` starts supporting infrastructure:

```bash
cd services
docker-compose up -d
```

| Service | Port | Purpose |
|---|---|---|
| SearXNG | `8888` | Meta-search engine for job aggregation |
| Camofox | `9500` | Headless browser service for scraping |

## Tech Stack

| Layer | Technology |
|---|---|
| Framework | FastAPI |
| Runtime | Python 3.11+ / Uvicorn |
| Database | MongoDB (via Motor async driver) |
| Agent Orchestration | LangGraph |
| LLM Providers | Ollama, Groq, Cerebras, SambaNova, NVIDIA NIM, OpenRouter |
| File Storage | Cloudinary |
| Document Processing | PyMuPDF, ReportLab, python-docx, mammoth, htmldocx, weasyprint / pdfkit |
| PDF/HTML | BeautifulSoup4, htmldocx, Playwright |

## Contributing

1. Read `docs/AGENTS.md` for the documentation-first development workflow.
2. Check `docs/INDEX.md` before creating any new documentation.
3. Follow the existing code style (async/await, type hints, Pydantic models for all I/O).
4. Run existing tests before submitting changes.
5. Update the corresponding doc file when modifying a feature — a pre-commit hook enforces this.

## License

MIT
