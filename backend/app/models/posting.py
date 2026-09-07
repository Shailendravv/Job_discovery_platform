"""API response models for postings.

Wraps app.ingest.models.Posting (the normalized ATS posting schema shared
with jobctl) with the resume/tailoring lifecycle fields the frontend Job
Details page needs. Posting itself is the source of truth for the job
data — these models add response shape only, no new fields.
"""

from typing import List, Optional

from pydantic import BaseModel, Field

from app.ingest.models import Posting


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
    """Tailoring lifecycle status for this posting."""
    tailored: bool = False
    resume_id: Optional[str] = None
    job_id: Optional[str] = None
    download_urls: Optional[TailoringDownloadUrls] = None


class PostingListResponse(BaseModel):
    """GET /api/v1/postings — up to `limit` latest postings."""
    postings: List[Posting]
    total: int


class PostingDetailResponse(Posting):
    """GET /api/v1/postings/{id} — a posting plus resume lifecycle state
    for the Job Details page."""
    active_resume: Optional[ActiveResumeInfo] = None
    tailoring_status: Optional[TailoringStatus] = None


class ShortlistEntry(BaseModel):
    """One row of GET /api/v1/shortlist — a verdict joined to its posting."""
    id: str
    verdict: str
    score: int
    reasons: List[str] = Field(default_factory=list)
    concerns: List[str] = Field(default_factory=list)
    judged_at: Optional[str] = None
    posting: Posting


class ShortlistResponse(BaseModel):
    entries: List[ShortlistEntry]


class IngestTriggerResponse(BaseModel):
    """POST /api/v1/ingest — the run has been started in the background."""
    run_id: str
    status: str = "started"
