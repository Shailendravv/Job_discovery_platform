---
covers: [backend/app/api/v1/jobs.py, backend/app/agents/job_workflow.py, backend/app/services/db_service.py, backend/app/models/job.py]
status: active
last_verified: 2026-06-28
---

# Jobs API

## Purpose
Lets users search for jobs (via LinkedIn and SearXNG aggregation), browse stored results with filtering/pagination, and view full job details including resume tailoring lifecycle state.

## Behavior Specification
- **Inputs:** plain-text search query + optional location (`POST /search`), query parameters for filtering/pagination/sorting (`GET /jobs`), or a job ObjectId (`GET /jobs/{job_id}`)
- **Process:**
   1. `POST /search` — receives `{user_input: string, location?: string}`, delegates to `search_jobs_workflow` which collects results from LinkedIn, SearXNG, and ATS scrapers (greenhouse, lever, ashby, workday). After location filtering, Phase 4 browses ATS job URLs via Camofox to enrich missing fields (description, skills, job_type) — uses `browse_extract` with Ollama if available (free), otherwise `browse_fetch` (no LLM). Then persists every result to MongoDB via `save_jobs` (upserts by URL with `search_query` and `search_location`, drops jobs without a URL). Returns the result list and a count of saved records.
  2. `GET /jobs` — queries stored jobs with optional filters (`source`, `job_type`, `location` regex, full-text `q`), paginates (`page`, `limit`), sorts (`sort_by` in `created_at|updated_at|title|company|score`, `sort_order` `asc|desc`). On full-text search, sort is forced to descending text score regardless of `sort_by`/`sort_order`.
  3. `GET /jobs/{job_id}` — fetches the single job document, converts `_id` to string, serializes `datetime` fields to ISO strings, then enriches the response with the latest uploaded resume (`active_resume`) and the latest tailor session for this job (`tailoring_status`).
- **Outputs:**
  - `POST /search` → `JobSearchResponse` `{jobs: JobResult[], saved: int}`
  - `GET /jobs` → `JobListResponse` `{jobs: JobResult[], pagination: PaginationMeta}`
  - `GET /jobs/{job_id}` → `JobDetailResponse` (all `JobResult` fields plus `created_at`, `updated_at`, `active_resume`, `tailoring_status`)
  - Invalid ObjectId → `400 {"detail": "Invalid job ID format: <value>"}`
  - Missing job → `404 {"detail": "Job not found: <job_id>"}`
- **Validation rules:**
  - `page` ≥ 1, `limit` 1–100
  - `sort_by` must match regex `^(created_at|updated_at|title|company|score)$`
  - `sort_order` must match regex `^(asc|desc)$`
  - `job_id` path param must be a valid 24-character hex ObjectId
- **Error handling:** `save_jobs` swallows bulk-write exceptions and returns 0; the endpoint still returns the job list to the caller.

1. Search query comes in as `user_input` string → workflow runs agents → results collected.
2. Results are upserted into MongoDB keyed by `url`; jobs without a `url` field are silently dropped.
3. Persisted jobs are retrieved with optional filters, text-search scoring, and pagination via aggregation pipeline.
4. Single-job detail enriches the stored document with the latest resume and tailor session from separate collections.

## Data & Interface Contract
### API signatures

**`POST /api/v1/search`**
- Request body: `{user_input: string, location?: string}`
- Response 200: `{jobs: JobResult[], saved: number}`

**`GET /api/v1/jobs`**
- Query params: `page` (int, default 1), `limit` (int, default 20, max 100), `source` (optional string), `job_type` (optional string), `location` (optional string, regex-matched), `q` (optional string, MongoDB text search), `sort_by` (enum), `sort_order` (enum)
- Response 200: `{jobs: JobResult[], pagination: {page, limit, total, pages}}`

**`GET /api/v1/jobs/{job_id}`**
- Response 200: `JobDetailResponse` (all JobResult fields + `created_at`, `updated_at`, `active_resume`, `tailoring_status`)
- Response 400: `{detail: "Invalid job ID format: ..."}`
- Response 404: `{detail: "Job not found: ..."}`

### Data model

**`JobResult` / stored document fields:**
`id` (aliased from `_id`), `title`, `company`, `location`, `description`, `url`, `apply_url`, `skills` (list), `job_type`, `posted_date`, `salary`, `source`, `experience`, `requirements` (list), `ref_id`
Plus timestamps: `created_at`, `updated_at`, and `search_query` / `search_location` set on upsert.

**`ActiveResumeInfo`:** `resume_id`, `cloudinary_url`, `filename`, `name`, `skills`, `processing_status`

**`TailoringStatus`:** `tailored` (bool), `resume_id`, `job_id`, `download_urls` (with `pdf`, `docx`, `cover_letter_pdf`)

## Example
Using the test at `backend/tests/test_db_service.py::test_save_jobs_sets_timestamps_and_search_query` as the basis:

**Input** — a search returns two job dicts that reach `save_jobs`:
```python
[
    {"title": "Job 1", "url": "http://example.com/1"},
    {"title": "Job 2", "url": "http://example.com/2"},
]
```
Called with `search_query="test"`.

**Process** — `save_jobs` builds one `UpdateOne` per URL (upsert). Each operation sets `updated_at` and `search_query` via `$set`, and `created_at` via `$setOnInsert` (only set on first insert, not on subsequent upserts).

**Output** — `return result.upserted_count + result.modified_count`, which is `2 + 0 = 2` in this test (both were new inserts).

## Dependencies & Integration Points
- **MongoDB** via `motor` — collections used: `jobs`, `resumes`, `tailor_sessions`
- **`search_jobs_workflow`** from `app.agents.job_workflow` — the agent orchestration that calls LinkedIn and SearXNG scrapers
- **`get_db`** dependency from `app.api.deps` — provides the `AsyncIOMotorDatabase` handle, injected per-request

## Edge Cases & Known Gotchas
- Jobs without a `url` field are silently dropped during save — they produce no `UpdateOne` operation and are never persisted. This is intentional: `url` is the deduplication key.
- `save_jobs` sanitises empty required strings — if `title` is falsy it becomes `"No Title"`, `company` becomes `"Unknown"`, `description` becomes `"No description"`. Empty strings in `skills` are filtered out.
- Full-text search (`q`) overrides sort: when `q` is present, sorting is always by descending MongoDB text score (`score` field), ignoring `sort_by` and `sort_order` params.
- `save_jobs` swallows bulk-write exceptions and returns `0`. The caller still returns whatever the workflow produced.
- `JobDetailResponse` includes `active_resume` (the latest uploaded resume across all jobs, not one specific to this job) and `tailoring_status` (the tailor session keyed to this specific `job_id`).

## Key Files
- `backend/app/api/v1/jobs.py` — router definition, three endpoints
- `backend/app/agents/job_workflow.py` — search orchestration (LinkedIn, SearXNG, ATS), Phase 4 ATS browsing
- `backend/app/services/db_service.py` — `save_jobs`, `get_jobs`, `get_job_by_id`, `get_latest_resume`, `get_tailor_session_for_job`
- `backend/app/models/job.py` — Pydantic request/response models
- `backend/tests/test_db_service.py` — tests for `save_jobs`

## Why (Design Rationale)
- **User sends only a plain-text query** — all agent configuration (scraper selection, region, sources) lives in backend `.env` so the frontend never needs to know about scraping infrastructure. This also makes it trivial to add new job sources without a frontend change.
- **Upsert by URL** — the same job can appear across multiple search runs; upserting on URL prevents duplicates while preserving the first `created_at`.
- **Separate `resumes` and `tailor_sessions` collections** — resume and tailoring state is not embedded in the job document because a single resume applies to many jobs and a tailor session is a separate lifecycle with its own processing pipeline.
- **Full-text search forces score sort** — MongoDB `$text` scoring is the most relevant ranking when the user searches; allowing arbitrary sort columns would produce confusing results (e.g. alphabetical).

## Open Issues
- No integration tests for the `location` filter on `POST /search` — existing `test_integration.py` covers job search without a location parameter.
- Phase 4 ATS browsing runs after location filter; no timeout/retry config specific to ATS browsing (reuses `SETTLE_SECONDS` and `MAX_SNAPSHOT_CHARS` from settings).
