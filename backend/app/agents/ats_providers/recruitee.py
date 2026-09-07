"""Recruitee ATS provider.

API endpoint: ``GET https://{org}.recruitee.com/api/offers/``
Response shape: ``{ "offers": [...] }``

URL patterns matched:
- ``{org}.recruitee.com``
- a custom careers domain fronting the same API is common (e.g.
  ``careers.example.com``) but isn't detectable from the URL alone — only
  the default ``*.recruitee.com`` hostname is supported here, same
  limitation the other providers accept for their default hosts.

Key differentiator: unlike Workable/SmartRecruiters, the list endpoint
already includes the full HTML ``description`` (and a separate
``requirements`` block) — no per-job detail call needed, no pagination
either (a normal-size careers page returns everything in one response).
"""

import logging
import re
from datetime import datetime, timezone
from typing import Any, Optional

from app.agents.ats_providers._http import fetch_json
from app.agents.ats_providers.base import AtsProvider, RawPosting
from app.services.html_service import extract_text_from_html

log = logging.getLogger(__name__)

# Anchored to require the literal ``.recruitee.com`` suffix and restrict the
# subdomain to word characters/hyphens — same approach as workday.py (a
# per-tenant hostname provider), rather than a fixed ALLOWED_HOSTS set.
_ORG_PATTERN = re.compile(r"^https://([\w-]+)\.recruitee\.com", re.IGNORECASE)


def _org(company: dict) -> Optional[str]:
    careers_url = (company.get("careers_url") or "").strip()
    match = _ORG_PATTERN.search(careers_url)
    return match.group(1) if match else None


def _resolve_api_url(company: dict) -> Optional[str]:
    api = company.get("api")
    if api:
        if not re.match(r"^https://[\w-]+\.recruitee\.com/", api, re.IGNORECASE):
            raise ValueError(f"recruitee: untrusted api URL: {api}")
        return api
    org = _org(company)
    if not org:
        return None
    return f"https://{org}.recruitee.com/api/offers/"


def _to_epoch_dt(value: Any) -> Optional[datetime]:
    """Parse Recruitee's ``"YYYY-MM-DD HH:MM:SS UTC"`` timestamp."""
    if not value or not isinstance(value, str):
        return None
    try:
        dt = datetime.strptime(value.replace(" UTC", ""), "%Y-%m-%d %H:%M:%S")
        return dt.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _to_epoch_ms(value: Any) -> Optional[int]:
    dt = _to_epoch_dt(value)
    return int(dt.timestamp() * 1000) if dt else None


def _format_location(job: dict) -> str:
    parts: list[str] = []
    top_city = (job.get("city") or "").strip()
    if top_city and top_city.lower() != "various locations":
        parts.append(top_city)

    for loc in (job.get("locations") or []):
        if not isinstance(loc, dict):
            continue
        for key in ("city", "state", "country"):
            val = (loc.get(key) or "").strip()
            if val and val not in parts:
                parts.append(val)

    seen: list[str] = []
    for p in parts:
        if p not in seen:
            seen.append(p)
    return " · ".join(seen)


class RecruiteeProvider(AtsProvider):
    id = "recruitee"

    def detect(self, company: dict) -> Optional[str]:
        try:
            return _resolve_api_url(company)
        except ValueError:
            return None

    async def fetch(self, company: dict, api_url: str) -> list[dict]:
        json_data = await fetch_json(api_url, redirect="error")
        offers = json_data.get("offers") if isinstance(json_data, dict) else []
        if not isinstance(offers, list):
            return []

        results: list[dict] = []
        for j in offers:
            if not isinstance(j, dict):
                continue
            url = (j.get("careers_url") or "").strip()
            if not url:
                continue
            results.append({
                "title": (j.get("title") or "").strip(),
                "url": url,
                "company": (company.get("name") or "").strip(),
                "location": _format_location(j),
                "posted_date": _to_epoch_ms(j.get("published_at") or j.get("created_at")),
                "source": "recruitee",
            })
        return results

    async def fetch_postings(self, company: dict, api_url: str) -> list[RawPosting]:
        json_data = await fetch_json(api_url, redirect="error")
        offers = json_data.get("offers") if isinstance(json_data, dict) else []
        if not isinstance(offers, list):
            return []

        results: list[RawPosting] = []
        for j in offers:
            if not isinstance(j, dict):
                continue
            url = (j.get("careers_url") or "").strip()
            offer_id = j.get("id")
            if not url or offer_id is None:
                continue

            parts = []
            if j.get("description"):
                parts.append(extract_text_from_html(j["description"]))
            if j.get("requirements"):
                parts.append(extract_text_from_html(j["requirements"]))
            description_text = "\n\n".join(p for p in parts if p)

            employment_type = (j.get("employment_type_code") or "").replace("_", " ").strip() or None

            results.append(RawPosting(
                provider_job_id=str(offer_id),
                title=(j.get("title") or "").strip(),
                location=_format_location(j) or None,
                remote_flag=bool(j["remote"]) if "remote" in j else None,
                employment_type=employment_type,
                description_text=description_text,
                salary=None,
                url=url,
                apply_url=(j.get("careers_apply_url") or "").strip() or url,
                posted_at=_to_epoch_dt(j.get("published_at") or j.get("created_at")),
                raw={k: v for k, v in j.items() if k not in ("description", "requirements", "translations")},
            ))
        return results
