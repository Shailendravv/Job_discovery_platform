import logging
from fastapi import APIRouter, Depends
from typing import List

from app.models.job import JobSearchRequest, JobResult
from app.api.deps import get_db
from app.agents.job_workflow import search_jobs_workflow

log = logging.getLogger(__name__)
router = APIRouter()


@router.post("/search", response_model=List[JobResult])
async def search_jobs(request: JobSearchRequest, db=Depends(get_db)):
    """Search jobs. Frontend sends only user_input — all targeting config lives in backend."""
    log.info("[search] user_input=%r", request.user_input)
    results = await search_jobs_workflow(user_input=request.user_input)
    linkedin_count = sum(1 for r in results if r.get("source") == "linkedin")
    searxng_count = sum(1 for r in results if r.get("source") == "searxng")
    log.info("[search] returning %d jobs (searxng=%d, linkedin=%d)", len(results), searxng_count, linkedin_count)
    return results
