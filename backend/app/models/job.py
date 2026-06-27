'''Job domain models.'''

from typing import List, Optional
from bson import ObjectId
from pydantic import BaseModel, Field


class JobSearchRequest(BaseModel):
    '''Frontend sends the job search query and optional location filter.'''
    user_input: str = Field(
        ...,
        description='Job search query in plain text',
        examples=['React developer Python 4 years experience remote'],
    )
    location: Optional[str] = Field(
        default=None,
        description='Location filter, e.g. "Remote", "India", "San Francisco"',
        examples=['Remote', 'India'],
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


# ── Resume & Tailoring Lifecycle Models ──


class ActiveResumeInfo(BaseModel):
    """Information about the currently active base resume."""
    resume_id: str
    cloudinary_url: str
    filename: str = ""
    name: Optional[str] = None
    skills: List[str] = Field(default_factory=list)
    processing_status: str = "completed"


class TailoringDownloadUrls(BaseModel):
    """Download URLs for tailored files from the last tailor session."""
    pdf: Optional[str] = None
    docx: Optional[str] = None
    cover_letter_pdf: Optional[str] = None


class TailoringStatus(BaseModel):
    """Tailoring lifecycle status for this job."""
    tailored: bool = False
    resume_id: Optional[str] = None
    job_id: Optional[str] = None
    download_urls: Optional[TailoringDownloadUrls] = None


class JobDetailResponse(BaseModel):
    """Detailed job response used for the Job Details page.

    Includes resume lifecycle state: the active base resume and
    whether a tailored version exists for this job.
    """
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

    # Resume lifecycle fields
    active_resume: Optional[ActiveResumeInfo] = None
    tailoring_status: Optional[TailoringStatus] = None

    class Config:
        populate_by_name = True
        extra = "ignore"
        json_encoders = {
            ObjectId: str,
        }