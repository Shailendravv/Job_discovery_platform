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

### Ollama (LLM)
Ensure Ollama is running with the required model:
```bash
ollama run qwen2.5-coder:1.5b
```
Ollama listens on `http://localhost:11434` by default.

---

## Environment Setup

Copy `.env` and fill in your values:
```
MONGODB_URI=<your-mongodb-uri>
SEARXNG_URL=http://localhost:8888
CAMOFOX_URL=http://localhost:9500
Ollama=http://localhost:11434
MCP_SEARCH_URL=http://localhost:8001
MCP_BROWSE_URL=http://localhost:8002
LLM_PROVIDER=ollama
SEARCH_MAX_RESULTS=10
BROWSE_TOP_N=15
SEARCH_SITES=naukri.com,linkedin.com/jobs,apna.co,indeed.com,instahyre.com,shine.com,foundit.in
SEARCH_FRESH=true
SEARCH_CAREERS=false

# LinkedIn Guest API Configuration (optional)
LINKEDIN_GUEST_API_ENABLED=true
LINKEDIN_GUEST_API_LOCATION=India
LINKEDIN_GUEST_API_TIME_RANGE=r86400

# JSearch API (OpenWebNinja) Configuration (optional - requires API key)
JSEARCH_API_KEY=your_jsearch_api_key_here
JSEARCH_API_HOST=jsearch.p.rapidapi.com
JSEARCH_API_LOCATION=India
JSEARCH_API_DATE_POSTED=today
```

Install dependencies:
```bash
pip install -r requirements.txt
```

---

## Database Migrations

The project uses a migration system to manage MongoDB schema evolution. Migrations are stored in the `migrations/` directory and tracked in the `_migrations` collection.

### Available Migrations

- **Migration 001**: Initial schema setup - creates all collections with JSON schema validation
- **Migration 006**: Cleanup unused collections - removes collections not needed by current app

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

3. **Run migration 006** (cleans up unused collections - **destructive**):
   ```bash
   python -m migrations.006_cleanup_unused_collections --uri "mongodb://localhost:27017" --db jobapp
   ```
   
   This will prompt for confirmation before dropping collections.

### Migration Order

Always run migrations in order (the runner handles this automatically):

```bash
# Fresh setup: run 001 then 006
# Or simply: python scripts/run_migrations.py --uri ...

# If you already ran 001, you can just run 006
```

### What Gets Created

After completing the migrations, the following collections are active:
- `jobs` - job listings
- `resumes` - resume data (for future matching)
- `_migrations` - migration tracking

See `document/PROJECT_CONTEXT.md` for the complete schema.

---

## Starting the App

Run all commands from the **backend directory**.

### Start MCP first

1. `python -m app.agents.nodes.job_mcp_server`

2. `python -m app.agents.nodes.job_mcp_browse_server`

| MCP Server   | Port  | Purpose                        |
|--------------|-------|--------------------------------|
| job_mcp_server        | 8001  | Web search via SearXNG |
| job_mcp_browse_server | 8002  | Page extraction via Camofox |

### Now run your main App
```bash
uvicorn app.main:app --reload
```

API available at `http://localhost:8000`

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
│   │   ├── jobs.py                      # POST /api/v1/jobs/search
│   │   └── resumes.py
│   ├── core/
│   │   ├── config.py                    # Settings from .env
│   │   └── llm.py                       # LLM provider (Ollama / Groq / Gemini)
│   └── main.py
├── services/
│   └── docker-compose.yml               # SearXNG + Camofox
├── requirements.txt
└── .env
```
python scripts/run_migrations.py --uri "mongodb://localhost:27017" --db jobapp