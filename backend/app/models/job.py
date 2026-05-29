"""
Job domain models.
"""

from typing import List, Optional
from pydantic import BaseModel, Field


class JobSearchRequest(BaseModel):
    """
    Flexible search request — accepts plain text OR structured targeting.

    Frontend can send any of:

    1. Simple plain text:
       { "user_input": "Python developer Delhi" }

    2. Site-targeted plain text (SearXNG site: operator):
       { "user_input": "React developer site:naukri.com site:linkedin.com" }

    3. Company career-page crawl:
       { "user_input": "careers at Google" }
       or with explicit flag:
       { "user_input": "Software Engineer", "sites": ["google.com"], "company_careers": true }

    4. Fully structured (richest control):
       {
         "user_input": "Data Engineer",
         "sites": ["naukri.com", "linkedin.com/jobs", "apna.co"],
         "fresh": true,
         "company_careers": false,
         "num_results": 10
       }
    """

    user_input: str = Field(
        ...,
        description="Job search query (plain text or site:-qualified)",
        examples=["Python developer Delhi", "React jobs site:naukri.com"],
    )
    num_results: int = Field(
        default=6,
        ge=1,
        le=30,
        description="Maximum number of job listings to return",
    )
    sites: List[str] = Field(
        default_factory=list,
        description=(
            "Explicit site targets, e.g. ['naukri.com', 'linkedin.com/jobs', 'apna.co']. "
            "Leave empty to search all default job portals."
        ),
        examples=[["naukri.com", "linkedin.com/jobs"]],
    )
    fresh: bool = Field(
        default=True,
        description="Restrict results to recent postings (adds after:2024-01-01 to queries)",
    )
    company_careers: bool = Field(
        default=False,
        description=(
            "Set true to crawl a company's own careers/jobs pages instead of portals. "
            "Requires at least one domain in `sites`."
        ),
    )

    def to_workflow_input(self) -> dict | str:
        """
        Convert to the format expected by search_jobs_workflow().
        If only user_input is set, pass it as plain text (backward-compatible).
        Otherwise pass a structured dict.
        """
        if not self.sites and not self.company_careers:
            return self.user_input  # plain-text path — workflow parses it
        return {
            "query": self.user_input,
            "sites": self.sites,
            "fresh": self.fresh,
            "company_careers": self.company_careers,
        }


class JobResult(BaseModel):
    title: str = ""
    company: str = ""
    location: Optional[str] = None
    description: str = ""
    url: Optional[str] = None
    apply_url: Optional[str] = None
    skills: List[str] = Field(default_factory=list)
    job_type: str = "unknown"
    posted_date: Optional[str] = None
    salary: Optional[str] = None
