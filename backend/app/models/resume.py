from pydantic import BaseModel
from typing import Optional

class ResumeUploadResponse(BaseModel):
    resume_id: str
    extracted_text: str

class ResumeTailorRequest(BaseModel):
    resume_id: str
    job_description: str

class ResumeTailorResponse(BaseModel):
    resume_id: str
    tailored_text: str
    download_url: Optional[str] = None
