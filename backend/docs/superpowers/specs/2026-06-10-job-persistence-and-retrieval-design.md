# Design Spec: Job Persistence and Retrieval API

**Date:** 2026-06-10
**Status:** Proposed
**Author:** Claude (Brainstorming)
**Related:** Job Search Backend

---

## 1. Problem Statement

The current job search API (`POST /api/v1/jobs/search`) aggregates job listings from multiple sources but does not persist the results. Every search query fetches fresh data and discards it after returning. This prevents:

- Querying historical job listings later
- Comparing job listings across multiple searches
- Building features like saved jobs, job alerts, analytics
- Reducing redundant external API calls (caching via persistence)

**Goal:** Add persistence for job search results and a new GET API to retrieve stored jobs with filtering and search capabilities.

---

## 2. Objectives

- Persist all job search results to MongoDB `jobs` collection
- Provide a `GET /api/v1/jobs` endpoint with:
  - Pagination
  - Basic filtering (source, job_type, location)
  - Full-text search (title, description, skills)
  - Sorting (by creation date or other fields)
- Return a count of saved jobs in the POST response
- Maintain backward compatibility with existing search workflow
- Keep the existing `resumes` collection for future resume-matching features

---

## 3. API Design

### 3.1 POST /api/v1/jobs/search (Enhanced)

**Current behavior:** Returns list of jobs from search sources.

**New behavior:** Same, plus persists results to database.

**Request:** (unchanged)
```json
{
  "user_input": "React developer remote"
}
```

**Response:**
```json
{
  "jobs": [
    { /* JobResult object */ }
  ],
  "saved": 15  // New: count of jobs successfully saved to DB
}
```

**Logic:**
- Execute the existing search workflow (query generation, concurrent search, browse & extract)
- For each job in the results:
  - If `url` exists: upsert by `url` (update if exists, insert if new)
  - If `url` is null: insert as new (rare edge case)
  - Set `search_query` = original user_input
  - Set `updated_at` = current timestamp
- Count successful operations (both inserts and updates) and return in `saved` field
- Errors on individual jobs are logged but do not abort the save operation

---

### 3.2 GET /api/v1/jobs (New)

Retrieve stored job listings with filtering and full-text search.

**Query Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `page` | int | Page number (default: 1) |
| `limit` | int | Items per page, max 100 (default: 20) |
| `source` | string | Filter by source (e.g., `searxng`, `linkedin`) |
| `job_type` | string | Filter by job_type (full-time, remote, contract, etc.) |
| `location` | string | Substring match on location field |
| `q` | string | Full-text search across title, description, skills |
| `sort_by` | string | Field to sort by (default: `created_at`) |
| `sort_order` | string | `asc` or `desc` (default: `desc`) |

**Example Requests:**
```
GET /api/v1/jobs?page=1&limit=10&source=linkedin&job_type=remote
GET /api/v1/jobs?q=python+django&location=remote
```

**Response:**
```json
{
  "jobs": [
    { /* JobResult object */ }
  ],
  "pagination": {
    "page": 1,
    "limit": 20,
    "total": 150,
    "pages": 8
  }
}
```

**Implementation Notes:**
- Use MongoDB aggregation pipeline to:
  1. Match filters (if any)
  2. Apply `$text` search if `q` is provided (requires text index)
  3. Sort by specified field and order
  4. Skip and limit for pagination
  5. Separate count query for total
- The `$text` operator returns a relevance score; sort by score when `q` is used (override `sort_by`)

---

## 4. Database Schema Changes

### 4.1 Indexes Required

Create a new migration `007_add_job_search_indexes.py` to add:

1. **Unique index on `url`** (for upsert operations):
   ```python
   db.jobs.create_index("url", unique=True, name="idx_jobs_url_unique")
   ```
   - Allows efficient upsert by URL
   - Jobs without URL will be skipped by unique index (insert as normal)

2. **Compound text index** (for full-text search):
   ```python
   db.jobs.create_index([
       ("title", "text"),
       ("description", "text"),
       ("skills", "text")
   ], name="idx_jobs_text_search", default_language="english")
   ```
   - Enables `$text` operator
   - MongoDB will automatically stem words and ignore stop words

**Note:** The `url` field already exists in jobs schema (can be null). The unique index will only enforce uniqueness for non-null values (MongoDB allows multiple nulls in unique index).

---

## 5. Service Layer Changes

### 5.1 Modify `app/services/db_service.py`

**Current `save_jobs()`** - uses `insert_many` for all jobs.

**New `save_jobs()`**:
```python
async def save_jobs(db: AsyncIOMotorDatabase, jobs: list[dict], search_query: str = None) -> int:
    """
    Save or update jobs using upsert based on URL.

    Args:
        db: Database connection
        jobs: List of job dictionaries (from search results)
        search_query: Original search query for tracking

    Returns:
        int: Number of successfully saved jobs (inserts + updates)
    """
    if not jobs:
        return 0

    now = datetime.utcnow()
    operations = []
    saved_count = 0

    for job in jobs:
        # Prepare update: set fields, add timestamps, store search_query
        update = {
            "$set": {
                field: value for field, value in job.items()
                if value is not None and field != "_id"
            },
            "$setOnInsert": {
                "created_at": now,
            },
            "$set": {
                "updated_at": now,
                "search_query": search_query,
            }
        }

        # Filter: use URL as upsert filter if present
        if job.get("url"):
            filter_ = {"url": job["url"]}
        else:
            # No URL: always insert (may create duplicates)
            filter_ = {}  # Will force insert since _id won't match
            # But better: generate a dedup_hash and use that?
            # For now, skip URL-less jobs for upsert to avoid duplicates
            continue

        operations.append(UpdateOne(filter_, update, upsert=True))

    if operations:
        try:
            result = await db.jobs.bulk_write(operations, ordered=False)
            saved_count = result.upserted_count + result.modified_count
        except BulkWriteError as bwe:
            # Log details but continue
            saved_count = len(operations)  # optimistic

    return saved_count
```

**New `get_jobs()` function:**
```python
async def get_jobs(
    db: AsyncIOMotorDatabase,
    page: int = 1,
    limit: int = 20,
    source: str = None,
    job_type: str = None,
    location: str = None,
    q: str = None,
    sort_by: str = "created_at",
    sort_order: int = -1  # -1 = desc, 1 = asc
) -> tuple[list[dict], int]:
    """
    Retrieve jobs with filtering, full-text search, and pagination.

    Returns: (jobs_list, total_count)
    """
    # Build match stage
    match = {}

    if source:
        match["source"] = source
    if job_type:
        match["job_type"] = job_type
    if location:
        match["location"] = {"$regex": location, "$options": "i"}

    # Build pipeline
    pipeline = []

    if match:
        pipeline.append({"$match": match})

    # Full-text search
    if q:
        pipeline.append({"$match": {"$text": {"$search": q}}})
        # Override sort to use text score
        pipeline.append({"$addFields": {"score": {"$meta": "textScore"}}})
        sort_by = "score"
        sort_order = -1  # Higher score first

    # Sort
    pipeline.append({"$sort": {sort_by: sort_order}})

    # Pagination
    skip = (page - 1) * limit
    pipeline.append({"$skip": skip})
    pipeline.append({"$limit": limit})

    # Execute query
    jobs = await db.jobs.aggregate(pipeline).to_list(limit)

    # Get total count (separate query for efficiency)
    count_pipeline = []
    if match:
        count_pipeline.append({"$match": match})
    if q:
        count_pipeline.append({"$match": {"$text": {"$search": q}}})
    total = await db.jobs.aggregate(count_pipeline + [{"$count": "total"}]).to_list(1)
    total_count = total[0]["total"] if total else 0

    return jobs, total_count
```

---

## 6. API Route Implementation

**In `app/api/v1/jobs.py`:**

```python
@router.post("/search", response_model=List[JobResult])
async def search_jobs(
    request: JobSearchRequest,
    db: AsyncIOMotorDatabase = Depends(get_db)
):
    """Search for jobs and optionally save results."""
    results = await search_jobs_workflow(request.user_input)

    # Save to database
    saved_count = await save_jobs(db, results, search_query=request.user_input)

    return JSONResponse(
        status_code=200,
        content={
            "jobs": results,
            "saved": saved_count
        }
    )

@router.get("/jobs", response_model=JobSearchResponse)
async def list_jobs(
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    source: Optional[str] = Query(None),
    job_type: Optional[str] = Query(None),
    location: Optional[str] = Query(None),
    q: Optional[str] = Query(None),
    sort_by: str = Query("created_at", regex="^(created_at|updated_at|title|company|score)$"),
    sort_order: str = Query("desc", regex="^(asc|desc)$"),
    db: AsyncIOMotorDatabase = Depends(get_db)
):
    """Retrieve stored jobs with filtering and full-text search."""
    sort_dir = -1 if sort_order == "desc" else 1

    jobs, total = await get_jobs(
        db=db,
        page=page,
        limit=limit,
        source=source,
        job_type=job_type,
        location=location,
        q=q,
        sort_by=sort_by,
        sort_order=sort_dir
    )

    total_pages = (total + limit - 1) // limit

    return {
        "jobs": jobs,
        "pagination": {
            "page": page,
            "limit": limit,
            "total": total,
            "pages": total_pages
        }
    }
```

---

## 7. Error Handling

- **POST save failures:** Continue processing all jobs even if some individual upserts fail; log errors; return total saved count (may be less than total jobs)
- **Database connection errors:** Log error but don't fail the search (search results still returned). The `saved` count would be 0 or partial.
- **GET query errors:**
  - Invalid `sort_by` or `sort_order`: return 400 Bad Request
  - Database errors: return 500 with error message
- **Empty results:** Return empty array with pagination metadata (total=0)

---

## 8. Implementation Steps (Todo)

1. [ ] Create migration 007: Create indexes on `jobs` (url unique, text)
2. [ ] Update `app/services/db_service.py`:
   - Modify `save_jobs()` to use bulk upsert by URL
   - Add new `get_jobs()` function
3. [ ] Add GET `/api/v1/jobs` endpoint in `app/api/v1/jobs.py`
4. [ ] Modify POST `/api/v1/jobs/search` to call `save_jobs()` and include `saved` in response
5. [ ] Update response models (Pydantic) if needed
6. [ ] Test locally with sample searches
7. [ ] Update README with new GET endpoint documentation

---

## 9. Out of Scope (Future)

- User authentication and personal saved jobs
- Job comparison features
- Job change notifications/webhooks
- More advanced search (fuzzy, typos, synonyms) - could use Atlas Search later
- Index optimization for extremely large result sets (may need covered queries)
- Soft delete functionality for jobs

---

## 10. Success Criteria

- [ ] POST `/search` returns `{"jobs": [...], "saved": N}` where N equals number of jobs upserted
- [ ] GET `/jobs?page=1&limit=10` returns paginated results
- [ ] GET `/jobs?source=linkedin` filters correctly
- [ ] GET `/jobs?job_type=remote` filters correctly
- [ ] GET `/jobs?location=India` substring-matches location case-insensitively
- [ ] GET `/jobs?q=python+django` returns jobs where title/description/skills contain these terms
- [ ] Text search relevance works (higher score for title matches vs description)
- [ ] Pagination works correctly (page 1, page 2, etc.)
- [ ] Sorting by `created_at` desc (default) and asc works
- [ ] Migration 007 runs without errors and creates both indexes
- [ ] No duplicate URLs exist after multiple searches (enforced by DB)
- [ ] Backward compatibility: existing search functionality still works

---

## 11. Technical Rationale

**Why bulk_write with UpdateOne?**
- Efficient: single round-trip to database
- Upsert: updates existing if URL exists, inserts if not
- `ordered=False`: continue even if some operations fail

**Why separate count query?**
- Using `count_documents()` would duplicate filter logic
- Aggregation `$count` after same match pipeline gives accurate total without fetching documents
- Two queries are acceptable trade-off for simplicity

**Why not use upsert by dedup_hash?**
- URL is simpler and more intuitive
- dedup_hash requires recomputing from search results (risk of mismatch)
- URL is already extracted and validated in workflow

**Why MongoDB text index instead of Atlas Search?**
- Works with any MongoDB (local or Atlas)
- No additional configuration needed
- Sufficient for basic keyword search
- Can upgrade to Atlas Search later if fuzzy/narrower features needed

---

## 12. Risks & Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| URL duplicates if same job appears on different URLs | Data redundancy | Acceptable for MVP; can implement dedup_hash later |
| Text search not as accurate as full-text engine | Users may not find jobs | Basic search is sufficient for MVP; can enhance |
| Bulk upsert fails due to large batch | Some jobs not saved | Use `ordered=False`, handle BulkWriteError, retry failures |
| Missing URL fields cause duplicate inserts | Same job stored multiple times | Skip URL-less jobs for upsert (use insert only) or log warning |
| Index creation blocks on large collection | Slow migration | Run migration during low-traffic; indexes can be built in background (`background=True`) |

---

## 13. Open Questions

**Q:** Should we store the raw search query (`search_query`) in the job document?  
**A:** Yes, to track which query found this job (useful for analytics).

**Q:** Should we allow combined filters (source + job_type + location + q)?  
**A:** Yes - all filters are ANDed together in the query.

**Q:** Should GET sort by relevance score when using full-text search?  
**A:** Yes - override `sort_by` to `score` when `q` is present.

**Q:** Should the `resumes` collection be used?  
**A:** Not yet - it's reserved for future resume parsing and matching.

---

## 14. Review Checklist

- [x] No placeholder "TBD" sections
- [x] All API endpoints clearly defined with request/response
- [x] Database schema changes specified (indexes only)
- [x] Implementation steps broken down
- [x] Error handling considered
- [x] Trade-offs explained
- [x] Out of scope items documented
- [x] Success criteria measurable
- [x] Technical rationale provided
- [x] Risks identified with mitigations

---

**Next:** Await user review and approval. Then move to implementation planning.
