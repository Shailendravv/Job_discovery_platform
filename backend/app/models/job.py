from pydantic import BaseModel
from typing import Optional, List, Literal


class JobSearchRequest(BaseModel):
    user_input: str
    num_results: int = 6


class JobResult(BaseModel):
    title: str
    company: str
    location: Optional[str] = None
    description: str
    url: Optional[str] = None
    skills: Optional[List[str]] = []
    job_type: Optional[str] = None  # categorized job type extracted from page
