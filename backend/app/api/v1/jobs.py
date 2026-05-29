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
    """
    Search jobs via SearXNG, auto-browse each result URL, return enriched jobs.

    Accepts flexible input — see JobSearchRequest docstring for all formats.
    """
    log.info(
        "[search] user_input=%r sites=%r company_careers=%r num_results=%d",
        request.user_input,
        request.sites,
        request.company_careers,
        request.num_results,
    )
    results = await search_jobs_workflow(
        user_input=request.to_workflow_input(),
        num_results=request.num_results,
    )
    log.info("[search] returning %d jobs", len(results))
    return results
