"""SmartRecruiters ATS provider.

List endpoint:
    ``GET https://api.smartrecruiters.com/v1/companies/{identifier}/postings``
    — paginated (``limit``/``offset``), response shape ``{ "totalFound",
    "content": [...] }``. Live-verified 2026-09-07 against ``ServiceNow``
    (614 jobs) and 15 other companies — see ``config/ats_companies.yml``.

Detail endpoint (one extra call per job — no bulk-content flag exists on the
public Posting API, confirmed against the live docs):
    ``GET https://api.smartrecruiters.com/v1/companies/{identifier}/postings/{id}``
    — has ``jobAd.sections.*.text`` (HTML), ``postingUrl``, ``applyUrl``.

URL patterns matched:
- ``jobs.smartrecruiters.com/{identifier}``

Key gotcha: the list endpoint has no public apply URL, only an internal API
``ref`` link. But the public job page ignores its own cosmetic title slug —
``jobs.smartrecruiters.com/{identifier}/{id}`` (no slug at all) resolves
correctly (verified live) — so ``fetch()`` builds a working URL from the id
alone, with zero extra calls. Only ``fetch_postings()`` pays the per-job
detail cost, for the description.
"""

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, Optional

from app.agents.ats_providers._http import fetch_json
from app.agents.ats_providers.base import AtsProvider, RawPosting
from app.services.html_service import extract_text_from_html

log = logging.getLogger(__name__)

ALLOWED_HOSTS = frozenset({"api.smartrecruiters.com"})

PAGE_SIZE = 100
MAX_PAGES = 10  # safety cap, same shape as workday.py — at most 1 000 postings/org

# Fetching a description costs one extra HTTP request per posting (no bulk
# option exists). A handful of these orgs run into the hundreds/thousands of
# open postings (see ingest.md), and every SmartRecruiters org shares the
# same host — so they're all serialized through the same 1 req/sec throttle
# during a run. Capping to the N most-recently-posted jobs per org keeps a
# nightly run's SmartRecruiters cost bounded and, since the whole point of
# this pipeline is "what's new since yesterday", biases toward exactly the
# postings that matter most.
MAX_DESCRIPTION_FETCHES = 60


def _assert_safe_url(url: str) -> str:
    """Validate URL is HTTPS and host is in the allowlist (SSRF protection)."""
    from urllib.parse import urlparse
    parsed = urlparse(url)
    if parsed.scheme != "https":
        raise ValueError(f"smartrecruiters: URL must use HTTPS: {url}")
    if parsed.hostname not in ALLOWED_HOSTS:
        raise ValueError(
            f"smartrecruiters: untrusted hostname '{parsed.hostname}' — "
            f"must be one of: {', '.join(sorted(ALLOWED_HOSTS))}"
        )
    return url


def _identifier(company: dict) -> Optional[str]:
    import re
    careers_url = (company.get("careers_url") or "").strip()
    match = re.search(r"jobs\.smartrecruiters\.com/([^/?#]+)", careers_url)
    return match.group(1) if match else None


def _resolve_api_url(company: dict) -> Optional[str]:
    api = company.get("api")
    if api:
        _assert_safe_url(api)
        return api
    identifier = _identifier(company)
    if not identifier:
        return None
    return f"https://api.smartrecruiters.com/v1/companies/{identifier}/postings"


def _public_url(identifier: str, posting_id: str) -> str:
    """The id alone resolves correctly — verified live; the slug SmartRecruiters
    normally appends is purely cosmetic."""
    return f"https://jobs.smartrecruiters.com/{identifier}/{posting_id}"


def _to_epoch_dt(value: Any) -> Optional[datetime]:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except (ValueError, TypeError):
        return None


def _to_epoch_ms(value: Any) -> Optional[int]:
    dt = _to_epoch_dt(value)
    return int(dt.timestamp() * 1000) if dt else None


def _format_location(location: dict) -> str:
    if not isinstance(location, dict):
        return ""
    parts: list[str] = []
    for key in ("city", "region", "country"):
        val = (location.get(key) or "").strip()
        if val and val not in parts:
            parts.append(val)
    return " · ".join(parts)


async def _fetch_all_summaries(api_url: str) -> list[dict]:
    """Page through the postings list endpoint. Returns the raw ``content`` items."""
    all_postings: list[dict] = []
    offset = 0
    for _ in range(MAX_PAGES):
        separator = "&" if "?" in api_url else "?"
        page_url = f"{api_url}{separator}limit={PAGE_SIZE}&offset={offset}"
        json_data = await fetch_json(page_url, redirect="error")
        content = json_data.get("content") if isinstance(json_data, dict) else []
        if not isinstance(content, list) or not content:
            break
        all_postings.extend(content)
        if len(content) < PAGE_SIZE:
            break
        offset += PAGE_SIZE
    return all_postings


async def _fetch_detail(api_url: str, posting_id: str) -> Optional[dict]:
    detail_url = f"{api_url}/{posting_id}"
    try:
        return await fetch_json(detail_url, redirect="error")
    except Exception as e:
        log.warning("[smartrecruiters] detail fetch failed for %s: %s", posting_id, e)
        return None


class SmartRecruitersProvider(AtsProvider):
    id = "smartrecruiters"

    def detect(self, company: dict) -> Optional[str]:
        try:
            return _resolve_api_url(company)
        except ValueError:
            return None

    async def fetch(self, company: dict, api_url: str) -> list[dict]:
        _assert_safe_url(api_url)
        identifier = _identifier(company) or ""
        summaries = await _fetch_all_summaries(api_url)

        results: list[dict] = []
        for j in summaries:
            if not isinstance(j, dict):
                continue
            posting_id = j.get("id")
            if not posting_id:
                continue
            results.append({
                "title": (j.get("name") or "").strip(),
                "url": _public_url(identifier, str(posting_id)),
                "company": (company.get("name") or "").strip(),
                "location": _format_location(j.get("location") or {}),
                "posted_date": _to_epoch_ms(j.get("releasedDate")),
                "source": "smartrecruiters",
            })
        return results

    async def fetch_postings(self, company: dict, api_url: str) -> list[RawPosting]:
        _assert_safe_url(api_url)
        identifier = _identifier(company) or ""
        summaries = await _fetch_all_summaries(api_url)
        summaries = [s for s in summaries if isinstance(s, dict) and s.get("id")]

        # Newest first, then cap — see MAX_DESCRIPTION_FETCHES.
        summaries.sort(key=lambda s: s.get("releasedDate") or "", reverse=True)
        total_found = len(summaries)
        summaries = summaries[:MAX_DESCRIPTION_FETCHES]
        if total_found > MAX_DESCRIPTION_FETCHES:
            log.info(
                "[smartrecruiters] %s: capping description fetch to %d most-recent of %d postings",
                company.get("name"), MAX_DESCRIPTION_FETCHES, total_found,
            )

        details = await asyncio.gather(*(_fetch_detail(api_url, str(s["id"])) for s in summaries))

        results: list[RawPosting] = []
        for summary, detail in zip(summaries, details):
            posting_id = str(summary["id"])
            title = (summary.get("name") or "").strip()
            url = _public_url(identifier, posting_id)
            if not title:
                continue

            description_text = ""
            apply_url = url
            posted_at = _to_epoch_dt(summary.get("releasedDate"))
            employment_type = None
            if isinstance(detail, dict):
                job_ad = detail.get("jobAd") or {}
                sections = job_ad.get("sections") or {}
                parts = []
                if isinstance(sections, dict):
                    for section in sections.values():
                        text = (section or {}).get("text") if isinstance(section, dict) else None
                        if text:
                            parts.append(extract_text_from_html(text))
                description_text = "\n\n".join(parts)
                apply_url = (detail.get("applyUrl") or detail.get("postingUrl") or url).strip() or url
                type_of_employment = detail.get("typeOfEmployment") or {}
                employment_type = (type_of_employment.get("label") or "").strip() or None

            location = summary.get("location") or {}
            results.append(RawPosting(
                provider_job_id=posting_id,
                title=title,
                location=_format_location(location) or None,
                remote_flag=location.get("remote") if isinstance(location, dict) else None,
                employment_type=employment_type,
                description_text=description_text,
                salary=None,
                url=url,
                apply_url=apply_url,
                posted_at=posted_at,
                raw=summary,
            ))
        return results
