"""ATS workflow orchestrator — fetches jobs from all configured ATS companies.

Flow:
1. Load ``ats_companies.yml`` from the config directory
2. Discover all registered ``AtsProvider`` subclasses
3. For each enabled company, find the matching provider via ``detect()``
4. Fetch jobs and collect normalised results

Called as Phase 1c from ``search_jobs_workflow`` in ``job_workflow.py``.
"""

import logging
import os
import re
from typing import Optional

import yaml

from app.agents.ats_providers import AtsProvider

log = logging.getLogger(__name__)

# Path to the ATS companies YAML config — relative to the project root
# ats_workflow.py is at backend/app/agents/ats_workflow.py, so we go up 3 levels to project root
_CONFIG_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "config", "ats_companies.yml")


def _load_ats_companies() -> list[dict]:
    """Parse the ATS companies YAML file.

    Returns a list of company config dicts. Returns empty list if the file
    is missing or malformed.
    """
    if not os.path.isfile(_CONFIG_PATH):
        log.info("[ats] config file not found: %s — skipping ATS phase", _CONFIG_PATH)
        return []

    try:
        with open(_CONFIG_PATH, encoding="utf-8") as f:
            data = yaml.safe_load(f)
        companies = data.get("ats_companies") if isinstance(data, dict) else None
        if not isinstance(companies, list):
            log.warning("[ats] ats_companies is not a list in %s — skipping", _CONFIG_PATH)
            return []
        return companies
    except Exception as e:
        log.warning("[ats] failed to load %s: %s — skipping ATS phase", _CONFIG_PATH, e)
        return []


def _load_providers() -> list[AtsProvider]:
    """Instantiate all registered ATS providers in a fixed priority order."""
    return AtsProvider.get_providers()


def _extract_keywords(user_input: str) -> list[str]:
    """Lowercase, split, remove stop words from user input."""
    stop_words = frozenset({
        "a", "an", "the", "and", "or", "but", "in", "on", "at", "to", "for",
        "of", "with", "by", "is", "are", "was", "were", "be", "been", "being",
        "have", "has", "had", "do", "does", "did", "will", "would", "can",
        "could", "shall", "should", "may", "might", "i", "you", "he", "she",
        "it", "we", "they", "this", "that", "these", "those", "am", "its",
        "my", "your", "his", "her", "our", "their", "no", "not", "nor",
        "as", "if", "than", "so", "about", "into", "over", "after", "before",
        "between", "under", "above", "from", "up", "down", "out", "off",
        "just", "because", "very", "too", "also", "more", "some", "any",
        "each", "every", "all", "both", "few", "most", "other", "such",
        # Experience-level qualifiers (filtered out so they don't dilute skill keywords)
        "entry", "intern", "intermediate", "junior", "lead", "mid", "principal", "senior", "staff",
    })

    words = re.split(r"\W+", user_input.lower())
    return [w for w in words if len(w) > 1 and w not in stop_words]


def _filter_by_relevance(jobs: list[dict], user_input: str) -> list[dict]:
    """Filter and rank ATS jobs by relevance to the user's search input.

    ATS APIs return ALL jobs from a company (no keyword search), so we apply
    a simple keyword-based relevance filter. Scoring: title (3x), description
    (2x), company (1x), location (1x). Sorted descending by score.
    """
    if not user_input or not jobs:
        return jobs

    keywords = _extract_keywords(user_input)
    if not keywords:
        return jobs

    patterns = [re.compile(r'\b' + re.escape(kw) + r'\b') for kw in keywords]

    scored: list[tuple[int, dict]] = []
    for job in jobs:
        score = 0
        title = (job.get("title") or "").lower()
        company = (job.get("company") or "").lower()
        location = (job.get("location") or "").lower()
        description = (job.get("description") or "").lower()

        for pat in patterns:
            if pat.search(title):
                score += 3
            if pat.search(description):
                score += 2
            if pat.search(company):
                score += 1
            if pat.search(location):
                score += 1

        if score >= 3:
            scored.append((score, job))

    scored.sort(key=lambda x: -x[0])
    return [job for _, job in scored]


async def scan_ats_companies(user_input: Optional[str] = None, location: Optional[str] = None) -> list[dict]:
    """Fetch all jobs from all configured ATS companies.

    Parameters
    ----------
    user_input : str or None
        The user's search query. Used for relevance filtering.
        If None, all jobs are returned unfiltered.
    location : str or None
        Location filter, e.g. "Remote", "India", "San Francisco".
        Applied as a hard filter — jobs not matching are dropped.

    Returns
    -------
    list[dict]
        Normalised job results with keys matching ``JobResult``.
    """
    companies = _load_ats_companies()
    if not companies:
        log.info("[ats] no companies configured — skipping ATS phase")
        return []

    providers = _load_providers()
    log.info("[ats] loaded %d providers, %d companies configured", len(providers), len(companies))

    all_jobs: list[dict] = []
    for company in companies:
        if not company.get("enabled", True):
            continue

        company_name = company.get("name", "Unknown")
        matched = False

        for provider in providers:
            try:
                api_url = provider.detect(company)
                if not api_url:
                    continue
                matched = True
                log.info("[ats] %s → %s provider (api=%s)", company_name, provider.id, api_url)
                jobs = await provider.fetch(company, api_url)
                log.info("[ats] %s returned %d jobs from %s", company_name, len(jobs), provider.id)
                all_jobs.extend(jobs)
                break
            except Exception as e:
                log.warning("[ats] %s/%s detect failed: %s", provider.id, company_name, e)

        if not matched:
            log.info("[ats] %s: no provider matched careers_url=%s", company_name, company.get("careers_url"))

    if user_input:
        filtered = _filter_by_relevance(all_jobs, user_input)
        log.info("[ats] %d jobs after relevance filter (from %d raw)", len(filtered), len(all_jobs))
    else:
        filtered = all_jobs

    if location:
        loc_lower = location.lower()
        loc_pat = re.compile(r'\b' + re.escape(loc_lower) + r'\b')
        location_filtered = [job for job in filtered if loc_pat.search((job.get("location") or "").lower())]
        log.info("[ats] %d jobs after location filter '%s' (from %d)", len(location_filtered), location, len(filtered))
        return location_filtered

    log.info("[ats] total jobs collected: %d", len(filtered))
    return filtered
