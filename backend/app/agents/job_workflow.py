"""
Unified job search workflow:
  1. Search SearXNG for jobs (default 6 results)
  2. Auto-browse each result URL via camofox (fetch tool)
  3. Extract structured fields + job_type via Ollama (extract tool)
  4. Print debug logs showing job_type and full JSON structure
"""

import json
import logging
from typing import List

from app.agents.tools.skill_extraction import extract_skills_from_text
from app.agents.tools.browse_jobs import browse_extract
from app.agents.search_provider import provider
from app.models.job import JobResult

log = logging.getLogger(__name__)

# Schema used to extract structured fields from each job page
JOB_EXTRACT_SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string", "description": "Job title"},
        "company": {"type": "string", "description": "Hiring company name"},
        "location": {"type": "string", "description": "Job location or remote status"},
        "description": {
            "type": "string",
            "description": "Full job description or summary",
        },
        "salary": {"type": "string", "description": "Salary or compensation range"},
        "skills": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Required skills listed in the posting",
        },
        "job_type": {
            "type": "string",
            "description": (
                "Job category. One of: full-time, part-time, contract, "
                "internship, freelance, remote, on-site, hybrid, unknown"
            ),
        },
    },
}


def _categorize_job_type(extracted: dict, description: str) -> str:
    """Derive job_type from extracted data or fall back to keyword scan."""
    jt = (extracted.get("job_type") or "").strip().lower()
    if jt and jt != "unknown":
        return jt
    # keyword fallback on description
    desc_lower = description.lower()
    for kw in (
        "internship",
        "contract",
        "freelance",
        "part-time",
        "part time",
        "remote",
        "hybrid",
        "full-time",
        "full time",
    ):
        if kw in desc_lower:
            return kw.replace(" ", "-")
    return "unknown"


async def search_jobs_workflow(user_input: str, num_results: int = 6) -> List[dict]:
    """
    Search → browse each URL → extract fields → return enriched JobResult list.
    Prints debug logs for job_type and full JSON structure of each job.
    """
    log.debug("[workflow] starting search: %r (num_results=%d)", user_input, num_results)
    raw_results = provider.search(user_input, num_results=num_results)
    log.debug("[workflow] SearXNG returned %d raw results", len(raw_results))

    jobs: List[dict] = []

    for idx, result in enumerate(raw_results):
        url = result.get("url") or ""
        snippet = (
            result.get("description")
            or result.get("snippet")
            or result.get("content")
            or ""
        ).strip()
        base_title = (result.get("title") or result.get("name") or "").strip()

        extracted: dict = {}

        log.debug(
            "[workflow] [%d/%d] processing url=%r title=%r",
            idx + 1, len(raw_results), url, base_title,
        )

        # ── Auto-browse: fetch + extract structured fields ──────────────────
        if url.startswith(("http://", "https://")):
            log.debug("[workflow] [%d] fetching page via camofox: %r", idx + 1, url)
            try:
                raw_json = browse_extract(url, JOB_EXTRACT_SCHEMA)
                extracted = (
                    json.loads(raw_json) if isinstance(raw_json, str) else raw_json
                )
                log.debug(
                    "[workflow] [%d] extract succeeded, keys=%s",
                    idx + 1, list(extracted.keys()),
                )
            except Exception as exc:
                log.warning(
                    "[workflow] [%d] browse_extract failed (%s), falling back to snippet",
                    idx + 1,
                    exc,
                )
        else:
            log.warning("[workflow] [%d] no valid URL, skipping browse", idx + 1)

        # ── Build final job record ───────────────────────────────────────────
        title = (extracted.get("title") or base_title).strip()
        company = (extracted.get("company") or result.get("company") or "").strip()
        location = extracted.get("location") or result.get("location") or None
        description = (extracted.get("description") or snippet).strip()
        skills = extracted.get("skills") or extract_skills_from_text(description)
        job_type = _categorize_job_type(extracted, description)

        job = JobResult(
            title=title,
            company=company,
            location=location,
            description=description,
            url=url or None,
            skills=skills,
            job_type=job_type,
        )
        job_dict = job.model_dump()

        # ── Debug print: job_type + full JSON ───────────────────────────────
        log.info(
            "[workflow] [%d] job_type=%r  title=%r  url=%r",
            idx + 1,
            job_type,
            title,
            url,
        )
        print(f"\n{'='*60}")
        print(f"[JOB {idx+1}/{len(raw_results)}]  job_type={job_type!r}")
        print(json.dumps(job_dict, indent=2, ensure_ascii=False))
        print("=" * 60)

        jobs.append(job_dict)

    log.info("[workflow] done — %d jobs extracted", len(jobs))
    return jobs
