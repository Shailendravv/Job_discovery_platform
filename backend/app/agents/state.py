from typing import TypedDict, List, Optional

class AgentState(TypedDict):
    query: str
    location: Optional[str]
    raw_jobs: List[dict]
    jobs_with_skills: List[dict]
    resume_text: Optional[str]
    tailored_resume: Optional[str]
