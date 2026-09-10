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
    # Set only when the exact role query matched nothing and a broader one
    # did — e.g. "AI full stack developer" -> "fullstack developer". The UI
    # must say so rather than passing the wider results off as an exact
    # match; silently widening a search is its own kind of wrong answer.
    role_relaxed_to: Optional[str] = None


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


class IngestTriggerRequest(BaseModel):
    """POST /api/v1/postings/ingest — how a Job Discovery session is scoped.

    Every field is optional and the body itself is optional, so the
    unparameterised `POST /ingest` that predates the Discovery search still
    starts a full, unscoped run.
    """

    role: Optional[str] = Field(
        None,
        description=(
            "Free-text role, e.g. 'backend engineer'. Recorded on the run and "
            "used to filter the results read; no ATS API in the registry "
            "supports a server-side keyword filter, so it cannot narrow the "
            "fetch itself."
        ),
    )
    window: Optional[str] = Field(
        None,
        description=(
            "Freshness window, e.g. '24h', '48h', '7d'. Defaults to "
            "settings.DISCOVERY_WINDOW. Providers that pay a per-job "
            "description fetch use it to skip stale postings before spending "
            "that call."
        ),
    )
    source: Optional[str] = Field(None, description="Only this provider id, e.g. 'greenhouse'.")
    org: Optional[str] = Field(None, description="Only this company (org slug or name).")


class IngestTriggerResponse(BaseModel):
    """POST /api/v1/ingest — the run has been started in the background."""
    run_id: str
    status: str = "started"


class IngestStage(BaseModel):
    """One timed stage of a run — how long it took and how much it handled."""
    name: str
    duration_ms: float
    count: int = 0


class IngestRunStatus(BaseModel):
    """GET /api/v1/postings/ingest/{run_id} — live progress for the Discovery
    page. The run document is written when the run *starts* and updated as
    each stage lands, so this is meaningful while the run is still going."""

    run_id: str
    status: str  # "running" | "completed" | "failed"
    started_at: Optional[str] = None
    finished_at: Optional[str] = None
    elapsed_ms: float = 0.0
    role: Optional[str] = None
    window: Optional[str] = None
    stages: List[IngestStage] = Field(default_factory=list)

    sources_total: int = 0
    sources_ok: int = 0
    sources_error: int = 0
    postings_fetched: int = 0
    postings_normalized: int = 0
    postings_fresh: int = 0
    inserted: int = 0
    updated: int = 0
    error: Optional[str] = None
