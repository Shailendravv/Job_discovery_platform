import logging
from fastapi import APIRouter, Depends, Query
from typing import List, Optional

from app.models.job import JobSearchRequest, JobResult, JobSearchResponse, JobListResponse, PaginationMeta
from app.api.deps import get_db
from app.services.db_service import get_jobs, save_jobs
from app.agents.job_workflow import search_jobs_workflow

log = logging.getLogger(__name__)
router = APIRouter()


@router.post("/search", response_model=JobSearchResponse)
async def search_jobs(request: JobSearchRequest, db=Depends(get_db)):
    """Search jobs. Frontend sends only user_input — all targeting config lives in backend."""
    log.info("[search] user_input=%r", request.user_input)
    results = await search_jobs_workflow(user_input=request.user_input)
    linkedin_count = sum(1 for r in results if r.get("source") == "linkedin")
    searxng_count = sum(1 for r in results if r.get("source") == "searxng")
    log.info("[search] returning %d jobs (searxng=%d, linkedin=%d)", len(results), searxng_count, linkedin_count)
    # Persist results to database
    saved_count = await save_jobs(db, results, search_query=request.user_input)
    return JobSearchResponse(jobs=results, saved=saved_count)


@router.get("/jobs", response_model=JobListResponse)
async def list_jobs(
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    source: Optional[str] = Query(None),
    job_type: Optional[str] = Query(None),
    location: Optional[str] = Query(None),
    q: Optional[str] = Query(None),
    sort_by: str = Query("created_at", pattern="^(created_at|updated_at|title|company|score)$"),
    sort_order: str = Query("desc", pattern="^(asc|desc)$"),
    db=Depends(get_db)
):
    """Retrieve stored jobs with filtering, full-text search, pagination, and sorting."""
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

    pagination = PaginationMeta(
        page=page,
        limit=limit,
        total=total,
        pages=total_pages
    )

    return JobListResponse(jobs=jobs, pagination=pagination)
