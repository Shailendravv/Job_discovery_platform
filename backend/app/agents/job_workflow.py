"""
Unified job search workflow.
All search targeting config (sites, freshness, result counts) lives in
backend config/settings — the frontend sends only user_input.
"""

import json
import logging
import re
from typing import List

from app.agents.tools.skill_extraction import extract_skills_from_text
from app.agents.tools.browse_jobs import browse_extract
from app.agents.search_provider import provider
from app.core.config import settings
from app.models.job import JobResult

log = logging.getLogger(__name__)

# ── Backend targeting config — all values read from settings (.env) ──────────

# ── Schema used to extract structured fields from each job page ───────────────
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
        "posted_date": {
            "type": "string",
            "description": "When the job was posted, e.g. '2 days ago', '2024-06-01'",
        },
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
        "apply_url": {
            "type": "string",
            "description": "Direct URL to apply for the job, if different from the listing URL",
        },
    },
}


# ── Input parsing ─────────────────────────────────────────────────────────────


def _parse_user_input(user_input: str) -> dict:
    """
    Parse plain-text user query. Applies backend config defaults for
    sites, freshness, and career-page mode.
    Returns: { query, sites, fresh, company_careers }
    """
    text = str(user_input).strip()
    sites: List[str] = list(settings.search_sites_list)
    fresh = settings.SEARCH_FRESH
    company_careers = settings.SEARCH_CAREERS

    # Allow user to embed site: overrides inline e.g. "React jobs site:naukri.com"
    site_matches = re.findall(r"site:(\S+)", text, re.IGNORECASE)
    if site_matches:
        sites = site_matches
        text = re.sub(r"site:\S+", "", text, flags=re.IGNORECASE).strip()

    # Detect career-page intent e.g. "careers at Google"
    career_pattern = re.compile(
        r"\b(careers?|career\s*page|hiring\s*page|job\s*openings?)\s+(?:at\s+)?(\S+)",
        re.IGNORECASE,
    )
    m = career_pattern.search(text)
    if m:
        company_careers = True
        company_hint = m.group(2).strip(".,/")
        sites = [f"{company_hint.lower()}.com"] if "." not in company_hint else [company_hint]
        text = career_pattern.sub("", text).strip()

    # Strip freshness keywords (freshness is always on by backend default)
    text = re.sub(r"\b(latest|recent|new|today|this\s+week)\b", "", text, flags=re.IGNORECASE).strip()

    return {"query": text, "sites": sites, "fresh": fresh, "company_careers": company_careers}


# ── Query builder ─────────────────────────────────────────────────────────────


def _build_queries(parsed: dict) -> List[str]:
    """
    Return a list of SearXNG query strings.

    • If explicit sites given  → one query per site with site: operator
    • If company_careers       → target <company>/careers or jobs.<company>
    • Otherwise                → one query per default job portal
    """
    base = parsed["query"]
    sites = parsed["sites"]
    fresh_suffix = " after:2026-06-02" if parsed["fresh"] else ""
    careers_mode = parsed["company_careers"]

    queries: List[str] = []

    if careers_mode and sites:
        for site in sites:
            domain = site.split("/")[0]  # strip path if any
            queries.append(f"{base} site:{domain}/careers{fresh_suffix}")
            queries.append(f"{base} site:{domain}/jobs{fresh_suffix}")
        return queries

    if sites:
        for site in sites:
            queries.append(f"{base} site:{site}{fresh_suffix}")
        return queries

    # Default: rotate through known job portals
    for site in settings.search_sites_list:
        queries.append(f"{base} site:{site}{fresh_suffix}")

    return queries


# ── Relevance ranker ─────────────────────────────────────────────────────────


def _score_result(result: dict, query_terms: List[str]) -> int:
    """
    Simple keyword-overlap score between query terms and result title+snippet.
    Higher = more relevant. Used to pick the top-N results to browse.
    """
    haystack = " ".join([
        (result.get("title") or ""),
        (result.get("content") or result.get("description") or result.get("snippet") or ""),
    ]).lower()
    return sum(1 for t in query_terms if t in haystack)


def _rank_and_trim(results: List[dict], query: str, top_n: int) -> List[dict]:
    """Score every result against the base query, return top_n by score."""
    terms = [t.lower() for t in re.split(r"\W+", query) if len(t) > 2]
    scored = sorted(results, key=lambda r: _score_result(r, terms), reverse=True)
    kept = scored[:top_n]
    log.info(
        "[workflow] relevance rank: %d candidates → top %d selected for browse",
        len(results), len(kept),
    )
    for i, r in enumerate(kept, 1):
        log.debug(
            "[workflow] rank[%d] score=%d title=%r url=%s",
            i, _score_result(r, terms), r.get("title"), r.get("url"),
        )
    return kept


# ── Job-type classifier ───────────────────────────────────────────────────────


def _categorize_job_type(extracted: dict, description: str) -> str:
    jt = (extracted.get("job_type") or "").strip().lower()
    if jt and jt != "unknown":
        return jt
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


# ── Main workflow ─────────────────────────────────────────────────────────────


async def search_jobs_workflow(user_input: str) -> List[dict]:
    """Entry point called by the API. Accepts plain-text user query only."""
    parsed = _parse_user_input(user_input)
    log.info("[workflow] parsed input: %s", parsed)

    queries = _build_queries(parsed)
    log.debug("[workflow] will run %d queries: %s", len(queries), queries)

    # ── Phase 1: Search — fetch SEARCH_MAX_RESULTS per query, de-dupe by URL ──
    search_per_query = settings.SEARCH_MAX_RESULTS
    browse_top_n = settings.BROWSE_TOP_N

    seen_urls: set = set()
    raw_results: List[dict] = []

    for q in queries:
        batch = provider.search(q, num_results=search_per_query)
        log.info(
            "[workflow] query=%r fetch_per_query=%d → got %d results",
            q, search_per_query, len(batch),
        )
        for r in batch:
            url = r.get("url", "")
            if url and url not in seen_urls:
                seen_urls.add(url)
                raw_results.append(r)

    log.info("[workflow] total unique candidates after search: %d", len(raw_results))

    # ── Phase 2: Rank — score by relevance, keep only top BROWSE_TOP_N for browse
    raw_results = _rank_and_trim(raw_results, parsed["query"], browse_top_n)
    log.info("[workflow] browse phase will process %d results", len(raw_results))

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
            idx + 1,
            len(raw_results),
            url,
            base_title,
        )

        # ── Auto-browse: fetch + extract structured fields ───────────────────
        if url.startswith(("http://", "https://")):
            log.debug("[workflow] [%d] fetching page via camofox: %r", idx + 1, url)
            try:
                raw_json = browse_extract(url, JOB_EXTRACT_SCHEMA)
                extracted = (
                    json.loads(raw_json) if isinstance(raw_json, str) else raw_json
                )
                log.debug(
                    "[workflow] [%d] extract succeeded, keys=%s",
                    idx + 1,
                    list(extracted.keys()),
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
        posted_date = (
            extracted.get("posted_date") or result.get("publishedDate") or None
        )
        apply_url = extracted.get("apply_url") or url or None

        job = JobResult(
            title=title,
            company=company,
            location=location,
            description=description,
            url=url or None,
            skills=skills,
            job_type=job_type,
            posted_date=posted_date,
            apply_url=apply_url,
        )
        job_dict = job.model_dump()

        log.info(
            "[workflow] [%d] job_type=%r  title=%r  url=%r  posted=%r",
            idx + 1,
            job_type,
            title,
            url,
            posted_date,
        )
        print(f"\n{'='*60}")
        print(
            f"[JOB {idx+1}/{len(raw_results)}]  job_type={job_type!r}  posted={posted_date!r}"
        )
        print(json.dumps(job_dict, indent=2, ensure_ascii=False))
        print("=" * 60)

        jobs.append(job_dict)

    log.info("[workflow] done — %d jobs extracted", len(jobs))
    return jobs
