# Job Search Backend

## Prerequisites

Make sure the following services are running before starting the backend.

### Docker Services
Start SearXNG (search engine) and Camofox (headless browser) via Docker:
```bash
cd services
docker-compose up -d
```

| Service  | URL                        |
|----------|----------------------------|
| SearXNG  | http://localhost:8888      |
| Camofox  | http://localhost:9500      |

#### SearXNG Configuration

The SearXNG container mounts custom configuration files from `services/searxng/`:

- **`settings.yml`** — Enables JSON API format, configures outgoing HTTP/2 support, realistic Accept-Language headers, and extended timeouts (15s/30s) for slow job boards. The rate limiter is disabled (`limiter: false`) since LLM workflows fire many rapid requests.
- **`limiter.toml`** — Whitelists Docker/localhost subnets (`10.0.0.0/8`, `172.16.0.0/12`, `192.168.0.0/16`) so bot-detection warnings don't surface for API traffic.

These files are bind-mounted as read-only into the container. If you need to customise, edit the files and restart the container:
```bash
docker restart searxng-mcp
```

### Ollama (LLM)
Ensure Ollama is running with the required model:
```bash
ollama run qwen2.5-coder:1.5b
```
Ollama listens on `http://localhost:11434` by default.

---

## Environment Setup

Copy `.env.example` to `.env` and fill in your values:
```env
MONGODB_URI=mongodb://localhost:27017/jobapp
SEARXNG_URL=http://localhost:8888
CAMOFOX_URL=http://localhost:9500
Ollama=http://localhost:11434

# MCP Server URLs
MCP_SEARCH_URL=http://localhost:8001
MCP_BROWSE_URL=http://localhost:8002

# LLM Provider (ollama, groq, gemini)
LLM_PROVIDER=ollama
MODEL_NAME=qwen2.5-coder:1.5b
MODEL_TEMPERATURE=0.1
GROQ_API_KEY=
GROQ_MODEL_NAME=llama-3.3-70b-versatile

# Cloudinary (for resume file storage)
CLOUDINARY_CLOUD_NAME=
CLOUDINARY_API_KEY=
CLOUDINARY_API_SECRET=

# Search Configuration
SEARCH_MAX_RESULTS=10
BROWSE_TOP_N=15
SEARCH_SITES=naukri.com,linkedin.com/jobs,apna.co,indeed.com,instahyre.com,shine.com,foundit.in
SEARCH_FRESH=true
SEARCH_CAREERS=false

# SearXNG
SEARXNG_ENABLED=false

# LinkedIn Guest API
LINKEDIN_GUEST_API_ENABLED=false
LINKEDIN_GUEST_API_LOCATION=India
LINKEDIN_GUEST_API_TIME_RANGE=r86400

# Operations
LOG_LEVEL=INFO
```

> A complete reference with all optional vars is available in `.env.example`.

Install dependencies:
```bash
pip install -r requirements.txt
```

---

## Database Migrations

The project uses a migration system to manage MongoDB schema evolution. Migrations are stored in the `migrations/` directory and tracked in the `_migrations` collection.

### Available Migrations

- **Migration 001**: Initial schema setup — creates all collections with JSON schema validation
- **Migration 006**: Cleanup unused collections — removes collections not needed by current app
- **Migration 007**: Create job search indexes — adds URL unique index and text index on `jobs` collection

> Note: Migrations 002-005 were removed as they created features not in use (user auth, application tracking, skills taxonomy, company summaries, change streams). See `document/PROJECT_CONTEXT.md` for details.

### Running Migrations

#### Recommended: Use the Migration Runner (Automated)

The `run_migrations.py` script automatically discovers and applies all pending migrations in order:

```bash
# Apply all pending migrations
python scripts/run_migrations.py --uri "mongodb://localhost:27017" --db jobapp

# Show migration status (what's applied vs pending)
python scripts/run_migrations.py --uri "mongodb://localhost:27017" --db jobapp --status

# List all available migrations
python scripts/run_migrations.py --uri "mongodb://localhost:27017" --db jobapp --list

# Rollback all migrations (destructive!)
python scripts/run_migrations.py --uri "mongodb://localhost:27017" --db jobapp --rollback
```

The runner will:
- Load all `.py` migration files from `migrations/` (sorted by filename)
- Check which migrations are already applied in `_migrations` collection
- Prompt for confirmation before applying pending ones
- Execute them sequentially and record each application

#### Manual: Run Individual Migrations

If you prefer to run migrations one at a time:

1. **Preview what will be changed** (optional but recommended):
   ```bash
   python scripts/list_unused_collections.py --uri "mongodb://localhost:27017" --db jobapp
   ```

2. **Run migration 001** (creates the full schema):
   ```bash
   python -m migrations.001_initial_schema --uri "mongodb://localhost:27017" --db jobapp
   ```

3. **Run migration 006** (cleans up unused collections — **destructive**):
   ```bash
   python -m migrations.006_cleanup_unused_collections --uri "mongodb://localhost:27017" --db jobapp
   ```

4. **Run migration 007** (creates job search indexes):
   ```bash
   python -m migrations.007_add_job_search_indexes --uri "mongodb://localhost:27017" --db jobapp
   ```

### Migration Order

Always run migrations in order (the runner handles this automatically):

```bash
# Fresh setup: run 001 → 006 → 007
# Or simply: python scripts/run_migrations.py --uri ...
```

### What Gets Created

After completing the migrations, the following collections are active:
- `jobs` — job listings (with URL unique index and text search index)
- `resumes` — resume data (for future matching)
- `_migrations` — migration tracking

See `document/PROJECT_CONTEXT.md` for the complete schema.

---

## Starting the App

Run all commands from the **backend directory**.

### Start MCP first

1. `python -m app.agents.nodes.job_mcp_server`

2. `python -m app.agents.nodes.job_mcp_browse_server`

| MCP Server              | Port  | Purpose                        |
|-------------------------|-------|--------------------------------|
| job_mcp_server          | 8001  | Web search via SearXNG (uses shared httpx client with browser headers) |
| job_mcp_browse_server   | 8002  | Page extraction via Camofox    |

### Now run your main App
```bash
uvicorn app.main:app --reload
```

API available at `http://localhost:8000`

---

## API Endpoints

### POST /api/v1/jobs/search

Search for jobs using a natural language query. Results are persisted to MongoDB and return a saved count.

**Request:**
```json
{
  "user_input": "React developer remote 4 years experience"
}
```

**Response:**
```json
{
  "jobs": [
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
  ],
  "saved": 10
}
```

**Notes:**
- Frontend sends ONLY `user_input`. All search targeting configuration lives in backend `.env`.
- Results are automatically persisted to MongoDB with `save_jobs()`.
- `saved` field indicates how many jobs were newly saved (duplicates by URL are skipped).

#### Query Parameters

| Parameter   | Type   | Description                           |
|-------------|--------|---------------------------------------|
| user_input  | string | Natural language job search query     |

### GET /api/v1/jobs

Retrieve stored jobs with filtering, full-text search, pagination, and sorting.

**Example requests:**
```bash
# Basic paginated listing
curl "http://localhost:8000/api/v1/jobs?page=1&limit=20"

# Filter by source
curl "http://localhost:8000/api/v1/jobs?source=linkedin"

# Filter by job type
curl "http://localhost:8000/api/v1/jobs?job_type=remote"

# Full-text search across title, company, and description
curl "http://localhost:8000/api/v1/jobs?q=react+developer"

# Filter by location
curl "http://localhost:8000/api/v1/jobs?location=remote"

# Combined filters with sorting
curl "http://localhost:8000/api/v1/jobs?source=searxng&job_type=full-time&q=python&sort_by=created_at&sort_order=desc&limit=10"
```

**Response:**
```json
{
  "jobs": [
    {
      "_id": "...",
      "title": "Senior React Developer",
      "company": "Tech Corp",
      "location": "Remote",
      "description": "...",
      "url": "https://...",
      "skills": ["react", "typescript"],
      "job_type": "remote",
      "source": "searxng",
      "search_query": "React developer",
      "created_at": "2026-06-11T..."
    }
  ],
  "pagination": {
    "page": 1,
    "limit": 20,
    "total": 45,
    "pages": 3
  }
}
```

#### Query Parameters

| Parameter  | Type   | Default     | Description                                                  |
|------------|--------|-------------|--------------------------------------------------------------|
| page       | int    | 1           | Page number (>= 1)                                           |
| limit      | int    | 20          | Results per page (1-100)                                     |
| source     | string | —           | Filter by source: `searxng`, `linkedin`, etc.                 |
| job_type   | string | —           | Filter by job type: `full-time`, `part-time`, `remote`, etc.  |
| location   | string | —           | Filter by location (partial match)                            |
| q          | string | —           | Full-text search across title, company, and description       |
| sort_by    | string | `created_at`| Sort field: `created_at`, `updated_at`, `title`, `company`, `score` |
| sort_order | string | `desc`      | Sort direction: `asc` or `desc`                               |

---

## Project Structure

```
backend/
├── app/
│   ├── agents/
│   │   ├── nodes/
│   │   │   ├── job_mcp_server.py        # MCP search server (port 8001)
│   │   │   └── job_mcp_browse_server.py # MCP browse server (port 8002)
│   │   ├── mcp_client.py                # MCP HTTP client (StreamableHTTP)
│   │   ├── search_provider.py           # SearchProvider wrapping MCP client
│   │   └── job_workflow.py              # Main search + extract workflow
│   ├── api/v1/
│   │   ├── jobs.py                      # POST /api/v1/jobs/search + GET /api/v1/jobs
│   │   └── resumes.py
│   ├── core/
│   │   ├── config.py                    # Settings from .env
│   │   └── llm.py                       # LLM provider (Ollama / Groq / Gemini)
│   └── main.py
├── services/
│   ├── docker-compose.yml               # SearXNG + Camofox
│   └── searxng/
│       ├── settings.yml                 # SearXNG outgoing config (HTTP/2, timeouts, headers)
│       └── limiter.toml                 # Rate limiter config (Docker subnet whitelist)
├── migrations/
│   ├── 001_initial_schema.py
│   ├── 006_cleanup_unused_collections.py
│   └── 007_add_job_search_indexes.py
├── scripts/
│   ├── run_migrations.py
│   ├── list_unused_collections.py
│   ├── generate_test_data.py
│   └── create_indexes.py
├── requirements.txt
└── .env
```

---

## Utilities

### Clear Data — `scripts/clear_data.py`

Deletes all documents from the `jobs` and `resumes` collections while preserving the collections and their indexes. Useful for resetting the database between test runs.

```bash
# Preview what would be deleted (safe)
python scripts/clear_data.py --uri "mongodb://localhost:27017" --db jobapp --dry-run

# Delete all data (with confirmation prompt)
python scripts/clear_data.py --uri "mongodb://localhost:27017" --db jobapp

# Delete without prompting
python scripts/clear_data.py --uri "mongodb://localhost:27017" --db jobapp --force
```

### List Unused Collections — `scripts/list_unused_collections.py`

Shows which MongoDB collections are referenced by the application vs. which are safe to drop. Helpful before running cleanup migrations.

```bash
python scripts/list_unused_collections.py --uri "mongodb://localhost:27017" --db jobapp
```

### Generate Test Data — `scripts/generate_test_data.py`

Populates the database with sample job listings for development and testing.

```bash
python scripts/generate_test_data.py --uri "mongodb://localhost:27017" --db jobapp
```
