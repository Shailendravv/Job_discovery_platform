# AGENTS.md — JobSphere

## Quick start
```bash
bash start.sh                      # one-command: Docker → Ollama → MCP → backend → frontend
```
Or individually:
```bash
cd backend && python -m venv .venv && .venv\Scripts\activate && pip install -r requirements.txt
cd backend && python scripts/run_migrations.py
cd backend && uvicorn app.main:app --reload --port 8000    # API on :8000
cd frontend && npm install && npm run dev                   # UI on :5173
```

## Architecture
- **Backend:** FastAPI + Motor (async MongoDB) + LangGraph agents. Entry: `backend/app/main.py:15`
- **Frontend:** React 19 + TypeScript + Vite 8 + Tailwind CSS v4. Entry: `frontend/src/main.tsx`
- **MCP servers:** Two standalone Python processes for job search (:8001) and browsing (:8002)
- **Infra (Docker):** SearXNG (:8888), Camofox browser (:9500) via `backend/services/docker-compose.yml`
- **LLM:** Pluggable via `LLM_PROVIDER` env var — ollama, groq, openrouter, cerebras, sambanova, nvidia, multi (fallback chain)
- **Config:** `backend/app/core/config.py` — Pydantic Settings from `.env` or OS env vars

## Key commands
| Command | Location | Notes |
|---|---|---|
| `python -m app.agents.nodes.job_mcp_server` | backend/ | MCP Search server (port 8001) |
| `python -m app.agents.nodes.job_mcp_browse_server` | backend/ | MCP Browse server (port 8002) |
| `uvicorn app.main:app --reload --port 8000` | backend/ | Backend API |
| `npm run dev` | frontend/ | Vite dev server |
| `npm run build` | frontend/ | `tsc -b && vite build` |
| `npm run lint` | frontend/ | ESLint |
| `pytest tests/` | backend/ | Unit tests |
| `python test/test_integration.py` | backend/ | Integration tests |
| `python scripts/run_migrations.py` | backend/ | MongoDB schema migrations |
| `python scripts/create_indexes.py` | backend/ | DB index creation |
| `playwright install` | backend/ | Required for browser scraping |

## Documentation workflow

**Before writing any doc:** read `backend/docs/INDEX.md` — it lists every doc file and the source paths it covers. Use the index, don't guess filenames.

**Naming:** one file per module, named after the module path (e.g. `jobs.py` → `jobs.md`). No scratch files (`NOTES.md`, `TODO.md`, etc.) in `backend/docs/`.

**Format:** every doc starts with YAML frontmatter (`covers`, `last_verified`, `status`). Use `backend/docs/DOC_TEMPLATE.md` as the structure. Update `last_verified` on every edit — even if text didn't change.

**Doc is secondary to code.** The codebase is the source of truth. If docs and code disagree, trust the code, then fix the docs.

**Location:** all docs live in `backend/docs/`. `backend/documentation/` is deprecated — do not create or edit there.

**Maintenance:**
- Modifying a feature → find its doc via `INDEX.md`, update it, rewrite stale sections (never append "Update:" notes)
- New feature → check `INDEX.md` first; extend existing doc if covered, otherwise create one file and add it to `INDEX.md`

**Recovery from stale docs:** read the actual implementation as ground truth, salvage only rationale/intent, rewrite behavior from code, replace old files. Use `git log -1 --format=%ai -- <path>` to compare source vs doc dates; if source is newer, treat all covering docs as stale. List files to delete and wait for confirmation before removing.

**Before finishing any task:**
- List every doc file created or edited
- Cross-check `INDEX.md` for duplicates
- Update `INDEX.md` if doc set changed

**Completion checklist:**
- [ ] Code updated
- [ ] Corresponding doc found via `INDEX.md` (not created blind)
- [ ] Doc content matches implementation, stale parts removed
- [ ] `last_verified` updated
- [ ] No scratch file left behind
- [ ] `INDEX.md` updated if doc set changed

## Testing quirks
- Only `tests/test_db_service.py` has unit tests (4 async tests mocking MongoDB)
- Integration tests in `backend/test/test_integration.py` (standalone script, not pytest)
- Resume endpoints have no dedicated tests

## Secrets & env vars
- `start.sh` exports non-secret defaults (URLs, toggles, model names) — no API keys are hardcoded
- Secrets are loaded dynamically, never stored in workspace files:
  1. Already-set terminal env vars (highest priority)
  2. `~/.jobsphere/secrets.env` (outside workspace — invisible to assistants)
  3. Interactive `read -s` prompt at startup if still missing
- To pre-configure secrets without prompts: `mkdir -p ~/.jobsphere` and create `secrets.env` with `export KEY=value` lines
- Backend `.env` file holds only non-secret defaults, consumed by Pydantic `Settings` at import time
- Frontend needs `VITE_API_URL=http://localhost:8000` in `frontend/.env`
- `.gitignore` now blocks `.env`, `.env.*`, and `secrets*` patterns (but allows `.env.example`)
- MCP servers must be running before backend starts (backend depends on them)
