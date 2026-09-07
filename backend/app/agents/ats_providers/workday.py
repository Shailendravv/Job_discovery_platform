"""Workday ATS provider.

Workday uses a POST-based paginated API rather than a simple GET.

Endpoint:
    ``POST {origin}/wday/cxs/{tenant}/{site}/jobs``

URL patterns matched:
- ``https://{tenant}.{instance}.myworkdayjobs.com/{site}``

Special handling:
- Paginated (20 results/page, max 50 pages = 1000 results safety cap)
- Relative date parsing ("Posted Today" → now, "Posted 5 Days Ago" → now - 5*86400000)
- Unbounded "Posted 30+ Days Ago" → date omitted (no usable timestamp)
"""

import asyncio
import json
import logging
import re
from datetime import datetime, timezone
from typing import Any, Optional

from app.agents.ats_providers._http import fetch_json
from app.agents.ats_providers.base import AtsProvider, RawPosting
from app.services.html_service import extract_text_from_html

log = logging.getLogger(__name__)

PAGE_SIZE = 20
MAX_PAGES = 50  # safety cap — at most 1 000 postings per site

# 86 400 000 ms in a day
_DAY_MS = 86_400_000

# Like SmartRecruiters, Workday's description lives behind a second,
# per-job GET — no bulk-content option exists. Real Workday tenants
# routinely run into the hundreds of open postings, so capping to the N
# most-recent keeps a nightly run's per-org cost bounded (see
# smartrecruiters.py's MAX_DESCRIPTION_FETCHES for the same reasoning).
MAX_DESCRIPTION_FETCHES = 60


def _resolve_endpoint(company: dict) -> Optional[dict]:
    """Extract API endpoint and job base URL from a Workday careers URL.

    Returns a dict with ``api`` and ``jobBase`` keys, or None if no match.
    """
    careers_url = (company.get("careers_url") or "").strip()
    # Pattern: https://<tenant>.<instance>.myworkdayjobs.com[/<locale>]/<site>
    m = re.search(
        r"^https://([\w-]+)\.(wd[\w-]*)\.myworkdayjobs\.com(?:/[a-z]{2}-[A-Z]{2})?/([^/?#]+)",
        careers_url,
    )
    if not m:
        return None
    tenant, instance, site = m.group(1), m.group(2), m.group(3)
    origin = f"https://{tenant}.{instance}.myworkdayjobs.com"
    return {
        "api": f"{origin}/wday/cxs/{tenant}/{site}/jobs",
        # externalPath is relative to the site, not the host root
        "jobBase": f"{origin}/{site}",
    }


def _parse_posted_on(label: Any) -> Optional[int]:
    """Parse Workday's relative date label into epoch ms.

    Returns None for unbounded dates like "30+ Days Ago".
    """
    if not label or not isinstance(label, str):
        return None
    now = datetime.now(timezone.utc)
    now_ms = int(now.timestamp() * 1000)

    if re.search(r"posted\s+today", label, re.IGNORECASE):
        return now_ms
    if re.search(r"posted\s+yesterday", label, re.IGNORECASE):
        return now_ms - _DAY_MS

    m = re.search(r"posted\s+(\d+)(\+?)\s*day", label, re.IGNORECASE)
    if not m:
        return None

    if m.group(2) == "+":
        # "30+ Days Ago" — unbounded, no usable date
        return None

    days = int(m.group(1))
    return now_ms - days * _DAY_MS


def _parse_posted_on_dt(label: Any) -> Optional[datetime]:
    """Same parsing as ``_parse_posted_on`` but as an aware ``datetime``."""
    ms = _parse_posted_on(label)
    return datetime.fromtimestamp(ms / 1000.0, tz=timezone.utc) if ms is not None else None


async def _fetch_raw_postings(ep: dict) -> list[dict]:
    """Page through the CXS ``/jobs`` list endpoint. Returns raw job dicts
    (``title``, ``externalPath``, ``locationsText``, ``postedOn``,
    ``remoteType``, ...) — shared by ``fetch()`` and ``fetch_postings()``."""
    all_jobs: list[dict] = []
    for page in range(MAX_PAGES):
        body = {
            "limit": PAGE_SIZE,
            "offset": page * PAGE_SIZE,
            "searchText": "",
            "appliedFacets": {},
        }
        json_data = await fetch_json(
            ep["api"],
            method="POST",
            body=json.dumps(body),
            headers={"content-type": "application/json", "accept": "application/json"},
            redirect="error",
        )
        postings = (json_data.get("jobPostings") or []) if isinstance(json_data, dict) else []
        valid = [j for j in postings if isinstance(j, dict) and (j.get("externalPath") or "").strip()]
        all_jobs.extend(valid)

        if len(postings) < PAGE_SIZE:
            break
    return all_jobs


async def _fetch_detail(ep: dict, external_path: str) -> Optional[dict]:
    detail_url = ep["api"].rsplit("/jobs", 1)[0] + external_path
    try:
        json_data = await fetch_json(detail_url, headers={"accept": "application/json"}, redirect="error")
        return json_data.get("jobPostingInfo") if isinstance(json_data, dict) else None
    except Exception as e:
        log.warning("[workday] detail fetch failed for %s: %s", external_path, e)
        return None


def _remote_flag(remote_type: Any) -> Optional[bool]:
    if not remote_type or not isinstance(remote_type, str):
        return None
    lowered = remote_type.strip().lower()
    if "remote" in lowered:
        return True
    if lowered in ("on-site", "onsite"):
        return False
    return None


class WorkdayProvider(AtsProvider):
    id = "workday"

    def detect(self, company: dict) -> Optional[str]:
        ep = _resolve_endpoint(company)
        return ep["api"] if ep else None

    async def fetch(self, company: dict, api_url: str) -> list[dict]:
        ep = _resolve_endpoint(company)
        if not ep:
            raise ValueError(f"workday: cannot derive CXS endpoint for {company.get('name')}")

        raw_jobs = await _fetch_raw_postings(ep)
        all_jobs = [{
            "title": (j.get("title") or "").strip(),
            "url": ep["jobBase"] + j["externalPath"].strip(),
            "company": (company.get("name") or "").strip(),
            "location": (j.get("locationsText") or "").strip(),
            "posted_date": _parse_posted_on(j.get("postedOn")),
            "source": "workday",
        } for j in raw_jobs]

        log.info("[workday] fetched %d jobs for %s", len(all_jobs), company.get("name"))
        return all_jobs

    async def fetch_postings(self, company: dict, api_url: str) -> list[RawPosting]:
        ep = _resolve_endpoint(company)
        if not ep:
            return []

        raw_jobs = await _fetch_raw_postings(ep)

        # Newest first (unparseable/unbounded dates sort last), then cap —
        # see MAX_DESCRIPTION_FETCHES.
        raw_jobs.sort(key=lambda j: _parse_posted_on(j.get("postedOn")) or -1, reverse=True)
        truncated = len(raw_jobs) > MAX_DESCRIPTION_FETCHES
        raw_jobs = raw_jobs[:MAX_DESCRIPTION_FETCHES]
        if truncated:
            log.info(
                "[workday] %s: capping description fetch to %d most-recent postings",
                company.get("name"), MAX_DESCRIPTION_FETCHES,
            )

        details = await asyncio.gather(*(_fetch_detail(ep, j["externalPath"].strip()) for j in raw_jobs))

        results: list[RawPosting] = []
        for j, detail in zip(raw_jobs, details):
            ext_path = j["externalPath"].strip()
            title = (j.get("title") or "").strip()
            if not title:
                continue
            url = ep["jobBase"] + ext_path

            description_text = ""
            provider_job_id = None
            employment_type = None
            if isinstance(detail, dict):
                provider_job_id = detail.get("id")
                if detail.get("jobDescription"):
                    description_text = extract_text_from_html(detail["jobDescription"])
                employment_type = (detail.get("timeType") or "").strip() or None

            if not provider_job_id:
                # No stable id without the detail call succeeding — skip
                # rather than fall back to something less stable (externalPath
                # embeds the title, which can change and break idempotency).
                continue

            results.append(RawPosting(
                provider_job_id=str(provider_job_id),
                title=title,
                location=(j.get("locationsText") or "").strip() or None,
                remote_flag=_remote_flag(j.get("remoteType")),
                employment_type=employment_type,
                description_text=description_text,
                salary=None,
                url=url,
                apply_url=url,
                posted_at=_parse_posted_on_dt(j.get("postedOn")),
                raw=j,
            ))
        return results
