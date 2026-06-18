'''Job domain models.'''

from typing import List, Optional
from bson import ObjectId
from pydantic import BaseModel, Field


class JobSearchRequest(BaseModel):
    '''Frontend sends only the job search query. All other config lives in backend .env.'''
    user_input: str = Field(
        ...,
        description='Job search query in plain text',
        examples=['React developer Python 4 years experience remote'],
    )


class JobResult(BaseModel):
    id: Optional[str] = Field(default=None, alias="_id")
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
    experience: Optional[str] = None
    requirements: List[str] = Field(default_factory=list)
    ref_id: Optional[str] = None

    class Config:
        populate_by_name = True
        extra = "ignore"
        json_encoders = {
            ObjectId: str,
        }


# Response models for job persistence and retrieval


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


class JobDetailResponse(BaseModel):
    """Detailed job response used for the Job Details page."""
    id: str = Field(..., alias="_id")
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
    experience: Optional[str] = None
    requirements: List[str] = Field(default_factory=list)
    ref_id: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None

    class Config:
        populate_by_name = True
        extra = "ignore"
        json_encoders = {
            ObjectId: str,
        }