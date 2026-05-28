from typing import List

from app.agents.tools.skill_extraction import extract_skills_from_text
from app.agents.tools.web_search import web_search
from app.models.job import JobResult


async def search_jobs_workflow(user_input: str, num_results: int = 10) -> List[dict]:
    raw_results = web_search(user_input, num_results=num_results)
    jobs: List[dict] = []

    for result in raw_results:
        title = (result.get("title") or result.get("name") or "").strip()
        description = (
            result.get("description")
            or result.get("snippet")
            or result.get("content")
            or ""
        )
        skills = extract_skills_from_text(description)

        job = JobResult(
            title=title,
            company=(result.get("company") or result.get("organization") or "").strip(),
            location=result.get("location") or None,
            description=description.strip(),
            url=result.get("url"),
            skills=skills,
        )
        jobs.append(job.dict())

    return jobs
