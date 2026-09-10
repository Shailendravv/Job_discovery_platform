"""Greenhouse ATS provider.

API endpoint: ``GET https://boards-api.greenhouse.io/v1/boards/{slug}/jobs``
Response shape: ``{ "jobs": [...] }``

URL patterns matched:
- ``job-boards.greenhouse.io/{slug}``
- ``job-boards.eu.greenhouse.io/{slug}``
- ``boards.greenhouse.io/{slug}``
"""

import html
import logging
from datetime import datetime, timezone
from typing import Any, Optional

from app.agents.ats_providers._http import fetch_json
from app.agents.ats_providers.base import AtsProvider, RawPosting
from app.services.html_service import extract_text_from_html

log = logging.getLogger(__name__)

ALLOWED_HOSTS = frozenset({
    "boards-api.greenhouse.io",
    "boards.greenhouse.io",
    "job-boards.greenhouse.io",
    "job-boards.eu.greenhouse.io",
})


def _assert_safe_url(url: str) -> str:
    """Validate URL is HTTPS and host is in the allowlist (SSRF protection)."""
    from urllib.parse import urlparse
    parsed = urlparse(url)
    if parsed.scheme != "https":
        raise ValueError(f"greenhouse: URL must use HTTPS: {url}")
    if parsed.hostname not in ALLOWED_HOSTS:
        raise ValueError(
            f"greenhouse: untrusted hostname '{parsed.hostname}' — "
            f"must be one of: {', '.join(sorted(ALLOWED_HOSTS))}"
        )
    return url


def _resolve_api_url(company: dict) -> Optional[str]:
    """Derive the Greenhouse boards API URL from company config."""
    # Explicit ``api`` URL wins
    api = company.get("api")
    if api:
        _assert_safe_url(api)
        return api

    careers_url = (company.get("careers_url") or "").strip()
    import re
    match = re.search(
        r"job-boards(?:\.eu)?\.greenhouse\.io/([^/?#]+)",
        careers_url,
    )
    if match:
        return f"https://boards-api.greenhouse.io/v1/boards/{match.group(1)}/jobs"

    match = re.search(r"boards\.greenhouse\.io/([^/?#]+)", careers_url)
    if match:
        return f"https://boards-api.greenhouse.io/v1/boards/{match.group(1)}/jobs"

    return None


def _resolve_postings_url(company: dict) -> Optional[str]:
    """Same endpoint as ``_resolve_api_url`` but with ``content=true`` so the
    response includes each job's full HTML description — required for
    ingestion (the legacy ``fetch()`` path never needed descriptions)."""
    api_url = _resolve_api_url(company)
    if not api_url:
        return None
    separator = "&" if "?" in api_url else "?"
    return f"{api_url}{separator}content=true"


def _to_epoch_dt(value: Any) -> Optional[datetime]:
    """Parse ISO date string to an aware datetime. Returns None if unparseable."""
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except (ValueError, TypeError):
        return None


def _to_epoch_ms(value: Any) -> Optional[int]:
    """Parse ISO date string to epoch ms. Returns None if unparseable."""
    if not value:
        return None
    if isinstance(value, (int, float)):
        return int(value)
    try:
        dt = datetime.fromisoformat(str(value))
        return int(dt.timestamp() * 1000)
    except (ValueError, TypeError):
        return None


class GreenhouseProvider(AtsProvider):
    id = "greenhouse"

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
            url = (j.get("absolute_url") or "").strip()
            if not url:
                continue
            results.append({
                "title": (j.get("title") or "").strip(),
                "url": url,
                "company": (company.get("name") or "").strip(),
                "location": _get_nested_str(j, "location", "name"),
                "posted_date": _to_epoch_ms(j.get("first_published")),
                "source": "greenhouse",
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
            url = (j.get("absolute_url") or "").strip()
            job_id = j.get("id")
            if not url or job_id is None:
                continue

            # ``content`` is HTML with entities escaped (e.g. "&amp;nbsp;") —
            # unescape first, then strip tags with the shared helper.
            raw_content = j.get("content") or ""
            description_text = extract_text_from_html(html.unescape(raw_content)) if raw_content else ""

            location_str = _get_nested_str(j, "location", "name")
            offices = j.get("offices") or []
            office_names = " ".join(
                (o.get("name") or "") for o in offices if isinstance(o, dict)
            )
            remote_flag = _looks_remote(location_str, office_names)

            raw_debug = {k: v for k, v in j.items() if k != "content"}

            results.append(RawPosting(
                provider_job_id=str(job_id),
                title=(j.get("title") or "").strip(),
                location=location_str or None,
                remote_flag=remote_flag,
                employment_type=None,  # Greenhouse doesn't expose this in the boards API
                description_text=description_text,
                salary=None,
                url=url,
                apply_url=url,
                posted_at=_to_epoch_dt(j.get("first_published")),
                raw=raw_debug,
            ))
        return results


def _looks_remote(*texts: str) -> Optional[bool]:
    """Best-effort remote detection from free-text location/office fields.

    Returns None (unknown) rather than False when there's no signal either
    way — the prefilter (milestone 3) treats None as "don't hard-filter on
    this", which is safer than guessing wrong.
    """
    combined = " ".join(t for t in texts if t).lower()
    if not combined:
        return None
    if "remote" in combined:
        return True
    return None


def _get_nested_str(obj: Any, *keys: str) -> str:
    """Safely traverse nested dict keys and return the final value as string."""
    current = obj
    for k in keys:
        if isinstance(current, dict):
            current = current.get(k)
        else:
            return ""
    return str(current).strip() if current else ""
