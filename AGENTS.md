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
| `pip install -e .` | backend/ | Installs the `jobctl` CLI (ATS ingestion — see `backend/docs/ingest.md`) |
| `jobctl ingest [--source X] [--org X] [--dry-run]` | backend/ | Fetch, normalize, dedupe, upsert postings from `config/ats_companies.yml`; runs the prefilter automatically afterward |
| `jobctl sources doctor` | backend/ | Live-probe every registry entry; reports 0-job/errored/dead tokens |
| `jobctl prefilter run \| show <id>` | backend/ | Rule-based reject before judging (`config/prefilter.yml`) — see `backend/docs/prefilter.md` |
| `jobctl profile add <file> --as resume` | backend/ | Extract text (no LLM) into `profile/resume.md` |
| `jobctl profile show` | backend/ | Which `profile/*.md` files exist yet |
| `jobctl list \| show <id> \| next \| judge --apply` | backend/ | The judging loop — see "Judging pipeline" below |
| `jobctl shortlist [--min-score 7] [--since 7d]` | backend/ | Judged postings worth applying to, highest score first |
| `jobctl stats` | backend/ | Posting counts overall, per-provider, new in last 24h |
| `/nightly` | repo root | Runs the full loop unaided — `.claude/commands/nightly.md` |
| `/calibrate` | repo root | Review sampled verdicts, update `profile/calibration.md` — `.claude/commands/calibrate.md` |
| `python test/test_integration.py` | backend/ | Integration tests |
| `python scripts/run_migrations.py` | backend/ | MongoDB schema migrations |
| `python scripts/create_indexes.py` | backend/ | DB index creation |
| `playwright install` | backend/ | Required for browser scraping |

## Judging pipeline (jobctl)

PLAN.md is the source design doc — read it before touching any of this.
This section is the operational summary a fresh session needs to run the
loop without me explaining anything (PLAN.md §9 milestone 4).

### Profile store

`profile/` (under `backend/`, gitignored except `*.example` — see
`.gitignore` and PLAN.md §10) holds what the judging agent reads directly,
every run, in this order:

1. `profile/resume.md` — written by `jobctl profile add <file> --as resume`
   (plain text extraction, no LLM call, no summarizing)
2. `profile/preferences.md` — locations, work authorization, salary floor,
   company size/stage, domains wanted/refused (hand-edited)
3. `profile/hard_filters.md` — automatic disqualifiers, stated plainly (hand-edited)
4. `profile/calibration.md` — corrections from `/calibrate`, overrides the
   rubric below when the two conflict (hand-edited, grows over time)

Copy the matching `*.md.example` template to get started on any of these.
Do not summarize these files into a prompt template — read the source.

### Verdict schema (`verdicts.json`, written by `jobctl judge --apply`)

```json
[{
  "id": "a3f9c1",
  "verdict": "apply" | "maybe" | "skip",
  "score": 8,
  "reasons": ["...", "..."],
  "concerns": ["..."],
  "matched_requirements": ["..."],
  "missing_requirements": ["..."],
  "judged_by": "claude-code",
  "judged_at": "2026-09-06T02:11:00Z"
}]
```

`id` accepts the short id shown by `jobctl next`/`list`, a longer prefix,
or the full sha256 id. `judge --apply` rejects unknown ids and refuses to
overwrite an already-judged posting unless `--force` is passed — both as
per-verdict outcomes, so one bad id in a batch doesn't cost the rest.

### Rubric

Score 1-10 on: requirement overlap with actual experience, seniority fit,
location/visa feasibility, domain interest, and company-stage fit. Then:

- **apply** — meets the core requirements, would take the interview
- **maybe** — one real gap, but worth a look
- **skip** — hard filter hit, or the gap is disqualifying

Be honest, not encouraging. A posting demanding 5 years for someone with 1
is a `skip`, not a `maybe`. State the specific missing requirement rather
than a generic "may not be a fit." Never invent experience that isn't
there in `matched_requirements`.

### The nightly loop

`/nightly` (`.claude/commands/nightly.md`) runs: `jobctl ingest --json` →
read the profile files above → loop `jobctl next --limit 25 --format md` →
judge each batch → `jobctl judge --apply` → until `next` returns empty →
`jobctl shortlist --min-score 7 --since 24h` → summarize counts.

**`.claude/commands/*.md` are not committed to this repo** — `.claude/` is
entirely gitignored here (settings.json, skills/ are local-only too). This
section is the durable, committed source of truth for the sequence; a
fresh clone can reconstruct `nightly.md`/`calibrate.md` from it even
without the slash-command shortcut.

### Calibration

`/calibrate` (`.claude/commands/calibrate.md`), roughly every ~200
judgments: sample ~20 recent verdicts across apply/maybe/skip, get each
marked right or wrong, and append concrete rules ("SDET roles are skip
even when the stack matches") to `profile/calibration.md` under a dated
heading — never rewrite prior entries.

### Full design

`backend/docs/judging.md` (query/verdicts/shortlist/profile_store),
`backend/docs/prefilter.md` (the rule-based reject stage before any of
this), `backend/docs/ingest.md` (ATS connectors, source registry).

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

<!-- code-review-graph MCP tools -->
## MCP Tools: code-review-graph

**This project has a knowledge graph. Start with the code-review-graph
MCP tools to narrow scope, then read the source.** The graph is cheaper than scanning files and
gives you structural context (callers, dependents, test coverage) that file search cannot.

### When to use graph tools FIRST

- **Exploring code**: `semantic_search_nodes_tool` or `query_graph_tool` instead of Grep
- **Understanding impact**: `get_impact_radius_tool` instead of manually tracing imports
- **Code review**: `detect_changes_tool` + `get_review_context_tool` instead of reading entire files
- **Finding relationships**: `query_graph_tool` with callers_of/callees_of/imports_of/tests_for
- **Architecture questions**: `get_architecture_overview_tool` + `list_communities_tool`

### Verify in the source

- Narrow scope with the graph, then read the source. Do not change code from graph output alone.
- For any non-trivial change, read the implementation and the relevant tests before concluding.
- Verify the exact source when touching behavior, database logic, migrations, retries, fallbacks,
  recovery, or compatibility code.
- When the graph and the source disagree, the source wins. The graph may be stale or may not
  model that relationship.
- An empty graph result can mean "not indexed" or "not statically visible", not "does not exist".

### Key Tools

| Tool | Use when |
| ------ | ---------- |
| `detect_changes_tool` | Reviewing code changes — gives risk-scored analysis |
| `get_review_context_tool` | Need source snippets for review — token-efficient |
| `get_impact_radius_tool` | Understanding blast radius of a change |
| `get_affected_flows_tool` | Finding which execution paths are impacted |
| `query_graph_tool` | Tracing callers, callees, imports, tests, dependencies |
| `semantic_search_nodes_tool` | Finding functions/classes by name or keyword |
| `get_architecture_overview_tool` | Understanding high-level codebase structure |
| `refactor_tool` | Planning renames, finding dead code |

### Workflow

1. The graph auto-updates on file changes (via hooks).
2. Use `detect_changes_tool` for code review.
3. Use `get_affected_flows_tool` to understand impact.
4. Use `query_graph_tool` pattern="tests_for" to check coverage.
<!-- /code-review-graph MCP tools -->
