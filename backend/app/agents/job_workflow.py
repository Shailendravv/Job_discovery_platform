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
from app.core.config import settings
from app.core.llm import call_llm
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

def _build_queries_dynamic(user_input: str) -> List[str]:
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
        raw = call_llm(prompt, json_format=True, timeout=30)
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


def _rank_and_trim_dynamic(results: List[dict], query: str, top_n: int) -> List[dict]:
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
        raw = call_llm(prompt, json_format=True, timeout=60)
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


async def search_jobs_workflow(user_input: str) -> List[dict]:
    """Entry point called by the API. Accepts plain-text user query only."""
    log.info("[workflow] starting dynamic search for: %s", user_input)

    queries = _build_queries_dynamic(user_input)
    log.debug("[workflow] will run %d queries: %s", len(queries), queries)

    # ── Phase 1: Search — fetch SEARCH_MAX_RESULTS per query, de-dupe by URL ──
    # Fetch 2N results so we have enough to rank/score
    search_per_query = settings.SEARCH_MAX_RESULTS * 2
    browse_top_n = settings.BROWSE_TOP_N

    seen_urls: set = set()
    raw_results: List[dict] = []
    seen_titles: List[str] = []

    for q in queries:
        # Use time_range="day" for latest jobs as requested
        batch = await provider.search(q, num_results=search_per_query, time_range="day")
        log.info(
            "[workflow] query=%r fetch_per_query=%d → got %d results",
            q, search_per_query, len(batch),
        )
        for r in batch:
            url = r.get("url", "")
            title = r.get("title", "")
            if url and url not in seen_urls:
                if _is_duplicate(title, seen_titles):
                    continue
                seen_titles.append(title)
                seen_urls.add(url)
                raw_results.append(r)

    log.info("[workflow] total unique candidates after search: %d", len(raw_results))

    # ── Phase 2: Rank — score by relevance using LLM, keep larger pool to allow skipping bad ones
    pool_size = browse_top_n * 3
    raw_results = _rank_and_trim_dynamic(raw_results, user_input, pool_size)
    log.info("[workflow] browse phase will process up to %d candidates to find %d valid jobs", len(raw_results), browse_top_n)

    jobs: List[dict] = []
    final_seen_titles: List[str] = []

    for idx, result in enumerate(raw_results):
        if len(jobs) >= browse_top_n:
            break
            
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
                
                if not extracted or all(v is None for v in extracted.values()):
                    log.warning("[workflow] [%d] browse extraction empty, falling back to snippet.", idx + 1)
                    extracted = {}
                    
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
            continue
            
        # Dedupe check on final extracted title
        final_title = (extracted.get("title") or base_title).strip()
        if _is_duplicate(final_title, final_seen_titles):
            log.info("[workflow] [%d] duplicate title detected after extraction: %r. Skipping.", idx + 1, final_title)
            continue
        final_seen_titles.append(final_title)

        # ── Build final job record ───────────────────────────────────────────
        title = (extracted.get("title") or base_title).strip()
        company = (extracted.get("company") or result.get("company") or "").strip()
        location = extracted.get("location") or result.get("location") or None
        description = (extracted.get("description") or snippet).strip()

        if not title and not description:
            log.warning("[workflow] [%d] no title or description, skipping.", idx + 1)
            continue
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
            source=result.get("source", "unknown"),
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
