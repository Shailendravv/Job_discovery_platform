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


class ParsedResumeData(BaseModel):
    name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    education: List[EducationEntry] = Field(default_factory=list)
    experience: List[ExperienceEntry] = Field(default_factory=list)
    skills: List[str] = Field(default_factory=list)
    languages: List[str] = Field(default_factory=list)
    certifications: List[str] = Field(default_factory=list)


class ResumeUploadResponse(BaseModel):
    resume_id: str
    cloudinary_url: str
    parsed_data: ParsedResumeData
    extracted_text_preview: str
    processing_status: str


# ── Tailor Models ──

class ResumeTailorRequest(BaseModel):
    resume_id: str = Field(..., description="MongoDB ObjectId of the resume")
    job_id: str = Field(..., description="MongoDB ObjectId of the job")


class DownloadUrls(BaseModel):
    pdf: str
    docx: str
    cover_letter_pdf: Optional[str] = None


class ResumeTailorResponse(BaseModel):
    resume_id: str
    job_id: str
    tailored_text: str
    cover_letter: str
    download_urls: DownloadUrls


class ResumeTailorErrorResponse(BaseModel):
    resume_id: Optional[str] = None
    job_id: Optional[str] = None
    error: str
    tailored_text: Optional[str] = None
    cover_letter: Optional[str] = None
