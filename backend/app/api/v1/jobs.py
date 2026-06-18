import logging
from fastapi import APIRouter, Depends, HTTPException, Query
from typing import List, Optional
from bson import ObjectId

from app.models.job import JobSearchRequest, JobResult, JobSearchResponse, JobListResponse, PaginationMeta, JobDetailResponse
from app.api.deps import get_db
from app.services.db_service import get_jobs, save_jobs, get_job_by_id
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

    # Convert MongoDB _id (ObjectId) to string for each job
    for job in jobs:
        if "_id" in job and job["_id"] is not None:
            job["_id"] = str(job["_id"])

    total_pages = (total + limit - 1) // limit

    pagination = PaginationMeta(
        page=page,
        limit=limit,
        total=total,
        pages=total_pages
    )

    return JobListResponse(jobs=jobs, pagination=pagination)


@router.get("/jobs/{job_id}", response_model=JobDetailResponse)
async def get_job_detail(job_id: str, db=Depends(get_db)):
    """Retrieve a single job by its ObjectId with all detail fields."""
    try:
        oid = ObjectId(job_id)
    except Exception:
        raise HTTPException(status_code=400, detail=f"Invalid job ID format: {job_id}")

    job = await get_job_by_id(db, job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job not found: {job_id}")

    # Map MongoDB _id to the response id field
    job["_id"] = str(job["_id"])

    # Convert datetime fields to ISO strings for JSON serialization
    for date_field in ("created_at", "updated_at"):
        if date_field in job and job[date_field] is not None:
            job[date_field] = job[date_field].isoformat()

    return JobDetailResponse(**job)
