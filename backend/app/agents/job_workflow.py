"""
Unified job search workflow.
All search targeting config (sites, freshness, result counts) lives in
backend config/settings — the frontend sends only user_input.
"""

import json
import logging
import re
import difflib
from typing import List

from app.agents.tools.skill_extraction import extract_skills_from_text
from app.agents.tools.browse_jobs import browse_extract
from app.agents.search_provider import provider
from app.agents.ats_workflow import scan_ats_companies
from app.core.config import settings
from app.core.llm import call_llm_async
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
            "description": "Complete and un-truncated full job description. Do not summarize - include every detail from the original posting.",
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

def _parse_user_input(user_input: str) -> dict:
    """Fallback plain-text parser if LLM fails."""
    text = str(user_input).strip()
    sites: List[str] = list(settings.search_sites_list)
    fresh = settings.SEARCH_FRESH
    company_careers = settings.SEARCH_CAREERS

    site_matches = re.findall(r"site:(\S+)", text, re.IGNORECASE)
    if site_matches:
        sites = site_matches
        text = re.sub(r"site:\S+", "", text, flags=re.IGNORECASE).strip()

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

    text = re.sub(r"\b(latest|recent|new|today|this\s+week)\b", "", text, flags=re.IGNORECASE).strip()

    return {"query": text, "sites": sites, "fresh": fresh, "company_careers": company_careers}

def _build_queries(parsed: dict) -> List[str]:
    """Fallback query builder if LLM fails."""
    base = parsed["query"]
    sites = parsed["sites"]
    careers_mode = parsed["company_careers"]
    queries: List[str] = []
    if careers_mode and sites:
        for site in sites:
            domain = site.split("/")[0]
            queries.append(f"{base} site:{domain}/careers")
            queries.append(f"{base} site:{domain}/jobs")
        return queries
    if sites:
        for site in sites:
            queries.append(f"{base} site:{site}")
        return queries
    for site in settings.search_sites_list:
        queries.append(f"{base} site:{site}")
    return queries

async def _build_queries_dynamic(user_input: str) -> List[str]:
    """Uses LLM to dynamically generate SearXNG queries targeting ATS platforms."""
    log.info("[workflow] Dynamically building search queries using LLM")
    sites_str = ", ".join(settings.search_sites_list)
    
    prompt = (
        f"You are a job search assistant. The user wants to find a job: '{user_input}'\n"
        "Generate up to 3 distinct search queries to find this job. "
        f"Target these specific job platforms: {sites_str}. "
        "Each query MUST use the 'site:' operator. "
        "Format the output strictly as a JSON array of strings, for example: "
        "[\"React developer site:greenhouse.io\", \"React engineer site:lever.co\"]"
    )
    
    try:
        raw = await call_llm_async(prompt, json_format=True, timeout=30)
        import re
        # try to parse just the array
        raw = re.sub(r"^```(?:json)?\s*", "", raw).strip()
        raw = re.sub(r"\s*```$", "", raw).strip()
        
        start = raw.find("[")
        end = raw.rfind("]")
        if start != -1 and end != -1:
            queries = json.loads(raw[start:end+1])
            if isinstance(queries, list) and all(isinstance(q, str) for q in queries) and len(queries) > 0:
                log.info("[workflow] LLM generated %d queries: %s", len(queries), queries)
                return queries
    except Exception as e:
        log.warning("[workflow] LLM query generation failed: %s. Falling back to default logic.", e)
        
    parsed = _parse_user_input(user_input)
    return _build_queries(parsed)


def _rank_and_trim(results: List[dict], query: str, top_n: int) -> List[dict]:
    """Fallback ranking logic using simple keywords."""
    terms = [t.lower() for t in re.split(r"\W+", query) if len(t) > 2]
    
    def score(result):
        haystack = " ".join([
            (result.get("title") or ""),
            (result.get("content") or result.get("description") or result.get("snippet") or ""),
        ]).lower()
        return sum(1 for t in terms if t in haystack)

    scored = sorted(results, key=score, reverse=True)
    return scored[:top_n]


async def _rank_and_trim_dynamic(results: List[dict], query: str, top_n: int) -> List[dict]:
    """Score every result against the base query using LLM, return top_n."""
    if not results:
        return []
        
    log.info("[workflow] LLM ranking %d candidates for query: %r", len(results), query)
    
    snippets = []
    for i, r in enumerate(results):
        title = r.get("title", "")
        url = r.get("url", "")
        snip = r.get("content") or r.get("description") or r.get("snippet") or ""
        snippets.append(f"[{i}] Title: {title}\nURL: {url}\nSnippet: {snip}")
        
    snippets_text = "\n\n".join(snippets)
    
    prompt = (
        f"You are a job search ranker. The user is looking for: '{query}'.\n"
        "Score each of the following search results from 0 to 10 based on how well it matches the user's intent. "
        "A score of 10 means a perfect match (recent, exact job, trusted site). "
        "A score of 0 means irrelevant.\n\n"
        f"{snippets_text}\n\n"
        "Return ONLY a JSON array of integers, where the index corresponds to the result index. "
        f"For example, if there are {len(results)} results, return: [8, 2, 9, ...]"
    )
    
    try:
        raw = await call_llm_async(prompt, json_format=True, timeout=60)
        import re
        raw = re.sub(r"^```(?:json)?\s*", "", raw).strip()
        raw = re.sub(r"\s*```$", "", raw).strip()
        
        start = raw.find("[")
        end = raw.rfind("]")
        if start != -1 and end != -1:
            scores = json.loads(raw[start:end+1])
            if isinstance(scores, list):
                if len(scores) != len(results):
                    log.warning("[workflow] LLM returned invalid scores array (length mismatch): expected %d, got %d. Padding/truncating.", len(results), len(scores))
                    if len(scores) < len(results):
                        scores.extend([0] * (len(results) - len(scores)))
                    else:
                        scores = scores[:len(results)]

                scored = list(zip(results, scores))
                scored.sort(key=lambda x: x[1], reverse=True)
                kept = [r for r, s in scored[:top_n]]
                log.info("[workflow] LLM ranking successful. Top scores: %s", [s for r, s in scored[:top_n]])
                return kept
            else:
                log.warning("[workflow] LLM returned invalid scores array (not a list): %s", scores)
    except Exception as e:
        log.warning("[workflow] LLM ranking failed: %s", e)
        
    return _rank_and_trim(results, query, top_n)


def _categorize_job_type(extracted: dict, description: str) -> str:
    jt = (extracted.get("job_type") or "").strip().lower()
    if jt and jt != "unknown":
        return jt
    desc_lower = description.lower()
    for kw in (
        "internship", "contract", "freelance", "part-time", "part time",
        "remote", "hybrid", "full-time", "full time",
    ):
        if kw in desc_lower:
            return kw.replace(" ", "-")
    return "unknown"


def _is_duplicate(new_title: str, existing_titles: List[str]) -> bool:
    if not new_title: return False
    new_norm = re.sub(r'\W+', ' ', new_title.lower()).strip()
    for et in existing_titles:
        et_norm = re.sub(r'\W+', ' ', et.lower()).strip()
        if not et_norm: continue
        # Increased to 0.95 to be much more lenient (only near-identical strings are discarded)
        if difflib.SequenceMatcher(None, new_norm, et_norm).ratio() > 0.95:
            return True
    return False


def _collect_unique_urls_only(batch: List[dict], seen_urls: set) -> List[dict]:
    """Filter duplicates by URL only, mutating seen_urls in place."""
    out = []
    for r in batch:
        url = r.get("url", "")
        apply_url = r.get("apply_url", "")
        # Use URL as primary dedup key, fallback to apply_url
        dedup_key = url or apply_url
        if not dedup_key or dedup_key in seen_urls:
            continue
        seen_urls.add(dedup_key)
        out.append(r)
    return out


def _build_job(result: dict, extracted: dict, snippet: str, base_title: str, url: str) -> dict | None:
    """Build a JobResult dict from extracted + raw result data. Returns None if unusable."""
    title = (extracted.get("title") or base_title).strip()
    description = (extracted.get("description") or snippet).strip()
    if not title and not description:
        return None
    return JobResult(
        title=title,
        company=(extracted.get("company") or result.get("company") or "").strip(),
        location=extracted.get("location") or result.get("location") or None,
        description=description,
        url=url or None,
        skills=extracted.get("skills") or extract_skills_from_text(description),
        job_type=_categorize_job_type(extracted, description),
        posted_date=extracted.get("posted_date") or result.get("publishedDate") or None,
        apply_url=extracted.get("apply_url") or url or None,
        source=result.get("source", "unknown"),
    ).model_dump()


def _browse_and_build(candidates: List[dict], quota: int, label: str, final_seen_titles: List[str]) -> List[dict]:
    """Browse up to len(candidates) URLs, collecting up to `quota` valid jobs."""
    jobs: List[dict] = []
    for idx, result in enumerate(candidates):
        if len(jobs) >= quota:
            break
        url = result.get("url") or ""
        snippet = (result.get("description") or result.get("snippet") or result.get("content") or "").strip()
        base_title = (result.get("title") or result.get("name") or "").strip()

        if not url.startswith(("http://", "https://")):
            log.warning("[workflow][%s][%d] no valid URL, skipping", label, idx + 1)
            continue

        extracted: dict = {}
        try:
            raw_json = browse_extract(url, JOB_EXTRACT_SCHEMA)
            extracted = json.loads(raw_json) if isinstance(raw_json, str) else raw_json
            if not extracted or all(v is None for v in extracted.values()):
                extracted = {}
        except Exception as exc:
            log.warning("[workflow][%s][%d] browse_extract failed (%s), falling back to snippet", label, idx + 1, exc)

        final_title = (extracted.get("title") or base_title).strip()
        if _is_duplicate(final_title, final_seen_titles):
            log.info("[workflow][%s][%d] duplicate after extraction: %r, skipping", label, idx + 1, final_title)
            continue
        final_seen_titles.append(final_title)

        job_dict = _build_job(result, extracted, snippet, base_title, url)
        if job_dict is None:
            log.warning("[workflow][%s][%d] no title or description, skipping", label, idx + 1)
            continue

        log.info("[workflow][%s][%d] job_type=%r title=%r", label, idx + 1, job_dict["job_type"], job_dict["title"])
        # Debug print — use ensure_ascii=True to avoid UnicodeEncodeError
        # on Windows terminals (cp1252) that can't encode chars like ₹
        print(f"\n{'='*60}\n[{label.upper()} JOB {len(jobs)+1}/{quota}]")
        print(json.dumps(job_dict, indent=2, ensure_ascii=True))
        print("=" * 60)
        jobs.append(job_dict)

    return jobs


async def search_jobs_workflow(user_input: str) -> List[dict]:
    """Entry point called by the API. Accepts plain-text user query only."""
    log.info("[workflow] starting dynamic search for: %s", user_input)

    queries = await _build_queries_dynamic(user_input)
    log.info("[workflow] will run %d queries: %s", len(queries), queries)

    searxng_quota = settings.SEARCH_MAX_RESULTS   # e.g. 15 final jobs from SearXNG
    linkedin_quota = settings.LINKEDIN_GUEST_API_MAX_RESULTS  # e.g. 15 final jobs from LinkedIn

    # Separate dedup contexts per source (URLs only)
    searxng_seen_urls: set = set()
    linkedin_seen_urls: set = set()
    searxng_candidates: List[dict] = []
    linkedin_candidates: List[dict] = []

    # ── Phase 1a: SearXNG — run all queries, collect unique results ───────────
    if settings.SEARXNG_ENABLED:
        for q in queries:
            batch = await provider._search_mcp_async(q, searxng_quota * 2, "day")
            log.info("[workflow] searxng query=%r → %d raw results", q, len(batch))
            searxng_candidates.extend(_collect_unique_urls_only(batch, searxng_seen_urls))
        log.info("[workflow] searxng unique candidates: %d", len(searxng_candidates))
        searxng_candidates = await _rank_and_trim_dynamic(searxng_candidates, user_input, searxng_quota * 2)

    # ── Phase 1c (NEW): ATS direct API fetch (zero-LLM) ───────────────────────
    # Fetches jobs directly from ATS APIs for configured companies.
    # ATS jobs have higher data quality (no LLM extraction artifacts).
    # Filtered by relevance to user_input, then deduplicated against SearXNG URLs.
    ats_jobs: List[dict] = []
    try:
        raw_ats_jobs = await scan_ats_companies(user_input=user_input)
        log.info("[workflow] ats raw results: %d", len(raw_ats_jobs))
        # Dedup ATS jobs against SearXNG URLs (ATS data higher quality)
        for job in raw_ats_jobs:
            url = job.get("url") or ""
            if url and url not in searxng_seen_urls:
                searxng_seen_urls.add(url)  # reserve the URL so SearXNG dedup skips it too
                ats_jobs.append(job)
        log.info("[workflow] ats unique after dedup: %d", len(ats_jobs))
    except Exception as e:
        log.warning("[workflow] ats phase failed: %s", e, exc_info=True)

    # ── Phase 1b: LinkedIn — called ONCE with its own quota ───────────────────
    log.info("[workflow] LINKEDIN_GUEST_API_ENABLED=%r", settings.LINKEDIN_GUEST_API_ENABLED)
    if settings.LINKEDIN_GUEST_API_ENABLED:
        log.info("[workflow] calling linkedin with query=%r count=%d", user_input, linkedin_quota * 2)
        try:
            batch = await provider._search_linkedin_async(user_input, linkedin_quota * 2)
            log.info("[workflow] linkedin raw results: %d — sample titles: %s", len(batch), [r.get('title') for r in batch[:3]])
            unique = _collect_unique_urls_only(batch, linkedin_seen_urls)
            log.info("[workflow] linkedin unique after dedup: %d (dropped %d)", len(unique), len(batch) - len(unique))
            linkedin_candidates.extend(unique)
            linkedin_candidates = await _rank_and_trim_dynamic(linkedin_candidates, user_input, linkedin_quota * 2)
        except Exception as e:
            log.error("[workflow] linkedin phase failed: %s", e, exc_info=True)

    # ── Phase 2: Browse each source independently up to its quota ─────────────
    final_seen_titles: List[str] = []
    searxng_jobs = _browse_and_build(searxng_candidates, searxng_quota, "searxng", final_seen_titles)
    linkedin_jobs = _browse_and_build(linkedin_candidates, linkedin_quota, "linkedin", final_seen_titles)

    # ATS jobs are already well-structured (no LLM browsing needed)
    # Build JobResult dicts for ATS jobs
    ats_structured: List[dict] = []
    for job in ats_jobs:
        title = (job.get("title") or "").strip()
        url = (job.get("url") or "").strip()
        description = (job.get("description") or "").strip()
        if not title and not description:
            continue
        if _is_duplicate(title, final_seen_titles):
            continue
        final_seen_titles.append(title)

        ats_structured.append(JobResult(
            title=title,
            company=(job.get("company") or "").strip(),
            location=job.get("location") or None,
            description=description,
            url=url or None,
            skills=extract_skills_from_text(description) if description else [],
            job_type="unknown",
            posted_date=str(job.get("posted_date")) if job.get("posted_date") else None,
            salary=job.get("salary") or None,
            source=job.get("source", "ats"),
        ).model_dump())

    jobs = ats_structured + searxng_jobs + linkedin_jobs
    log.info(
        "[workflow] done — %d jobs extracted (ats=%d, searxng=%d, linkedin=%d)",
        len(jobs), len(ats_structured), len(searxng_jobs), len(linkedin_jobs),
    )
    return jobs
