'''Job domain models.'''

from typing import List, Optional
from pydantic import BaseModel, Field


class JobSearchRequest(BaseModel):
    '''Frontend sends only the job search query. All other config lives in backend .env.'''
    user_input: str = Field(
        ...,
        description='Job search query in plain text',
        examples=['React developer Python 4 years experience remote'],
    )


class JobResult(BaseModel):
    title: str = ''
    company: str = ''
    location: Optional[str] = None
    description: str = ''
    url: Optional[str] = None
    apply_url: Optional[str] = None
    skills: List[str] = Field(default_factory=list)
    job_type: str = 'unknown'
    posted_date: Optional[str] = None
    salary: Optional[str] = None
    source: Optional[str] = None


# New response models for job persistence and retrieval


class PaginationMeta(BaseModel):
    page: int
    limit: int
    total: int
    pages: int


class JobSearchResponse(BaseModel):
    jobs: List[JobResult]
    saved: int


class JobListResponse(BaseModel):
    jobs: List[JobResult]
    pagination: PaginationMeta