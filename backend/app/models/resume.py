from pydantic import BaseModel, Field
from typing import Optional, List


# ── Upload Models ──

class EducationEntry(BaseModel):
    institution: Optional[str] = None
    degree: Optional[str] = None
    year: Optional[int] = None


class ExperienceEntry(BaseModel):
    company: Optional[str] = None
    title: Optional[str] = None
    duration: Optional[str] = None
    description: Optional[str] = None


class ProjectEntry(BaseModel):
    """A project entry for the structured resume."""
    name: Optional[str] = None
    description: Optional[str] = None


class ParsedResumeData(BaseModel):
    name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    summary: Optional[str] = None
    education: List[EducationEntry] = Field(default_factory=list)
    experience: List[ExperienceEntry] = Field(default_factory=list)
    skills: List[str] = Field(default_factory=list)
    projects: List[ProjectEntry] = Field(default_factory=list)
    languages: List[str] = Field(default_factory=list)
    certifications: List[str] = Field(default_factory=list)


class ResumeUploadResponse(BaseModel):
    resume_id: str
    cloudinary_url: str
    parsed_data: ParsedResumeData
    extracted_text_preview: str
    processing_status: str


# ── Structured Tailor Models (PII-safe, chunked JSON pipeline) ──

class TailoredResumeData(BaseModel):
    """The tailored resume output schema matching the ATS system prompt."""
    summary: str = ""
    skills: List[str] = Field(default_factory=list)
    experience: List[ExperienceEntry] = Field(default_factory=list)
    projects: List[ProjectEntry] = Field(default_factory=list)
    education: List[EducationEntry] = Field(default_factory=list)
    certifications: List[str] = Field(default_factory=list)


class StructuredTailorRequest(BaseModel):
    resume_id: str = Field(..., description="MongoDB ObjectId of the resume")
    job_id: str = Field(..., description="Posting _id (sha256 hex) from the postings collection")


class StructuredTailorDownloadUrls(BaseModel):
    pdf: str = ""
    docx: str = ""
    cover_letter_pdf: Optional[str] = None


class StructuredTailorResponse(BaseModel):
    resume_id: str
    job_id: str
    tailored_data: TailoredResumeData
    tailored_text: str
    cover_letter: str
    download_urls: StructuredTailorDownloadUrls
    ats_keywords_matched: List[str] = Field(default_factory=list)
    ats_keywords_missing: List[str] = Field(default_factory=list)
    optimization_notes: List[str] = Field(default_factory=list)
    llm_model: str = ""
    # ATS optimisation metadata
    keyword_coverage_pct: float = 0.0
    paper_format: str = "letter"
    jd_keywords: List[str] = Field(default_factory=list)
    competency_keywords: List[str] = Field(default_factory=list)
    selected_project_count: int = 0
    keyword_distribution: dict = Field(default_factory=dict)


class StructuredTailorErrorResponse(BaseModel):
    resume_id: Optional[str] = None
    job_id: Optional[str] = None
    error: str
    tailored_text: Optional[str] = None
    cover_letter: Optional[str] = None
    ats_keywords_matched: List[str] = Field(default_factory=list)
    ats_keywords_missing: List[str] = Field(default_factory=list)
    optimization_notes: List[str] = Field(default_factory=list)


# ── Download from URL Models ──

class DownloadFromUrlRequest(BaseModel):
    url: str = Field(..., description="Cloudinary delivery URL to download and proxy through backend")
