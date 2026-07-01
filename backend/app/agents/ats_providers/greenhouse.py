"""Greenhouse ATS provider.

API endpoint: ``GET https://boards-api.greenhouse.io/v1/boards/{slug}/jobs``
Response shape: ``{ "jobs": [...] }``

URL patterns matched:
- ``job-boards.greenhouse.io/{slug}``
- ``job-boards.eu.greenhouse.io/{slug}``
- ``boards.greenhouse.io/{slug}``
"""

import logging
from datetime import datetime, timezone
from typing import Any, Optional

from app.agents.ats_providers._http import fetch_json
from app.agents.ats_providers.base import AtsProvider

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


def _get_nested_str(obj: Any, *keys: str) -> str:
    """Safely traverse nested dict keys and return the final value as string."""
    current = obj
    for k in keys:
        if isinstance(current, dict):
            current = current.get(k)
        else:
            return ""
    return str(current).strip() if current else ""
