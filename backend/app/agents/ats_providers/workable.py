"""Workable ATS provider.

API endpoint: ``GET https://apply.workable.com/api/v1/widget/accounts/{token}``
Response shape: ``{ "name": ..., "description": ..., "jobs": [...] }``

URL patterns matched:
- ``apply.workable.com/{token}``
- ``{token}.workable.com`` (Workable's other public-facing hostname format)

Key differentiator: the list endpoint omits the job description by default —
mirrors Greenhouse's ``?content=true`` trick, ``?details=true`` adds an HTML
``description`` field to every job in the same single call (no per-job cost).
"""

import logging
from datetime import datetime, timezone
from typing import Any, Optional

from app.agents.ats_providers._http import fetch_json
from app.agents.ats_providers.base import AtsProvider, RawPosting
from app.services.html_service import extract_text_from_html

log = logging.getLogger(__name__)

ALLOWED_HOSTS = frozenset({"apply.workable.com"})


def _assert_safe_url(url: str) -> str:
    """Validate URL is HTTPS and host is in the allowlist (SSRF protection)."""
    from urllib.parse import urlparse
    parsed = urlparse(url)
    if parsed.scheme != "https":
        raise ValueError(f"workable: URL must use HTTPS: {url}")
    if parsed.hostname not in ALLOWED_HOSTS:
        raise ValueError(
            f"workable: untrusted hostname '{parsed.hostname}' — "
            f"must be one of: {', '.join(sorted(ALLOWED_HOSTS))}"
        )
    return url


def _resolve_api_url(company: dict) -> Optional[str]:
    """Derive the Workable widget-accounts API URL from company config."""
    api = company.get("api")
    if api:
        _assert_safe_url(api)
        return api

    careers_url = (company.get("careers_url") or "").strip()
    import re
    # apply.workable.com/{token}[/...]
    match = re.search(r"apply\.workable\.com/([^/?#]+)", careers_url)
    if match:
        return f"https://apply.workable.com/api/v1/widget/accounts/{match.group(1)}"

    # {token}.workable.com — a second public hostname Workable issues per account
    match = re.search(r"^https?://([^./]+)\.workable\.com", careers_url)
    if match:
        return f"https://apply.workable.com/api/v1/widget/accounts/{match.group(1)}"

    return None


def _resolve_postings_url(company: dict) -> Optional[str]:
    """Same endpoint as ``_resolve_api_url`` but with ``details=true`` so the
    response includes each job's full HTML description — required for
    ingestion (the legacy ``fetch()`` path never needed descriptions)."""
    api_url = _resolve_api_url(company)
    if not api_url:
        return None
    separator = "&" if "?" in api_url else "?"
    return f"{api_url}{separator}details=true"


def _to_epoch_ms(value: Any) -> Optional[int]:
    """Parse a ``YYYY-MM-DD`` date string to epoch ms. Returns None if unparseable."""
    if not value:
        return None
    try:
        dt = datetime.strptime(str(value), "%Y-%m-%d").replace(tzinfo=timezone.utc)
        return int(dt.timestamp() * 1000)
    except (ValueError, TypeError):
        return None


def _to_epoch_dt(value: Any) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.strptime(str(value), "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return None


def _format_location(job: dict) -> str:
    """Fold the top-level city/state/country and any extra ``locations[]``
    entries into one string (mirrors ashby.py::_format_location — Workable
    also supports multi-location postings)."""
    parts: list[str] = []
    primary = ", ".join(p for p in (job.get("city"), job.get("state"), job.get("country")) if p)
    if primary:
        parts.append(primary)

    for loc in (job.get("locations") or []):
        if not isinstance(loc, dict) or loc.get("hidden"):
            continue
        extra = ", ".join(p for p in (loc.get("city"), loc.get("region"), loc.get("country")) if p)
        if extra and extra not in parts:
            parts.append(extra)

    seen: list[str] = []
    for p in parts:
        if p not in seen:
            seen.append(p)
    return " · ".join(seen)


class WorkableProvider(AtsProvider):
    id = "workable"

    def detect(self, company: dict) -> Optional[str]:
        try:
            return _resolve_api_url(company)
        except ValueError:
            return None

    async def fetch(self, company: dict, api_url: str) -> list[dict]:
        _assert_safe_url(api_url)
        json_data = await fetch_json(api_url, redirect="error")
        jobs_raw = json_data.get("jobs") if isinstance(json_data, dict) else []
        if not isinstance(jobs_raw, list):
            return []

        results: list[dict] = []
        for j in jobs_raw:
            if not isinstance(j, dict):
                continue
            url = (j.get("url") or "").strip()
            if not url:
                continue
            results.append({
                "title": (j.get("title") or "").strip(),
                "url": url,
                "company": (company.get("name") or "").strip(),
                "location": _format_location(j),
                "posted_date": _to_epoch_ms(j.get("published_on") or j.get("created_at")),
                "source": "workable",
            })
        return results

    async def fetch_postings(
        self,
        company: dict,
        api_url: str,
        *,
        posted_since: Optional[datetime] = None,
    ) -> list[RawPosting]:
        # ``posted_since`` is deliberately ignored: this endpoint returns the
        # description in the same bulk response, so there is no per-job fetch
        # to skip. The ingest layer applies the freshness window afterwards
        # (app/ingest/freshness.py), which keeps the stored corpus and
        # ``last_seen_at`` complete. See AtsProvider.fetch_postings.
        postings_url = _resolve_postings_url(company)
        if not postings_url:
            return []
        _assert_safe_url(postings_url)
        json_data = await fetch_json(postings_url, redirect="error")
        jobs_raw = json_data.get("jobs") if isinstance(json_data, dict) else []
        if not isinstance(jobs_raw, list):
            return []

        results: list[RawPosting] = []
        for j in jobs_raw:
            if not isinstance(j, dict):
                continue
            url = (j.get("url") or "").strip()
            shortcode = j.get("shortcode")
            if not url or not shortcode:
                continue

            description_text = extract_text_from_html(j["description"]) if j.get("description") else ""
            posted_date = j.get("published_on") or j.get("created_at")

            results.append(RawPosting(
                provider_job_id=str(shortcode),
                title=(j.get("title") or "").strip(),
                location=_format_location(j) or None,
                remote_flag=bool(j["telecommuting"]) if "telecommuting" in j else None,
                employment_type=(j.get("employment_type") or "").strip() or None,
                description_text=description_text,
                salary=None,
                url=url,
                apply_url=(j.get("application_url") or "").strip() or url,
                posted_at=_to_epoch_dt(posted_date),
                raw={k: v for k, v in j.items() if k != "description"},
            ))
        return results
