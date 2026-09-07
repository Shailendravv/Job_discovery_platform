"""Ashby ATS provider.

API endpoint:
    ``GET https://api.ashbyhq.com/posting-api/job-board/{slug}?includeCompensation=true``
Response shape: ``{ "jobs": [...] }``

URL patterns matched:
- ``jobs.ashbyhq.com/{slug}``

Special handling:
- 30s timeout (API has ~10s+ latency floor)
- 2 retries with exponential backoff + jitter (dodge rate-limiting)
- Compensation parsing + annualisation (hourly → yearly)
- Secondary location aggregation
"""

import logging
from datetime import datetime, timezone
from typing import Any, Optional

from app.agents.ats_providers._http import fetch_with_retry
from app.agents.ats_providers.base import AtsProvider, RawPosting

log = logging.getLogger(__name__)

ASHBY_TIMEOUT_MS = 30_000
ASHBY_RETRIES = 2

# Annualisation multipliers for different compensation intervals
_INTERVAL_MULTIPLIERS = {
    "1 HOUR": 2080,
    "1 DAY": 260,
    "1 WEEK": 52,
    "2 WEEK": 26,
    "0.5 MONTH": 24,
    "1 MONTH": 12,
    "2 MONTH": 6,
    "3 MONTH": 4,
    "6 MONTH": 2,
    "1 YEAR": 1,
}


def _parse_compensation(job: dict) -> Optional[str]:
    """Parse Ashby's structured compensation object into a formatted string.

    Returns a string like "USD $150,000 - $200,000" or None if unavailable.
    """
    comp = job.get("compensation")
    if not comp or not isinstance(comp, dict):
        return None

    interval = str(comp.get("interval", "1 YEAR"))
    multiplier = _INTERVAL_MULTIPLIERS.get(interval)
    if not multiplier:
        return None

    min_val = _normalise_num(comp.get("minValue"))
    max_val = _normalise_num(comp.get("maxValue"))
    currency = str(comp.get("currency") or "").strip().upper()

    if min_val is None and max_val is None:
        return None

    min_annual = (min_val * multiplier) if min_val is not None else None
    max_annual = (max_val * multiplier) if max_val is not None else None

    if min_annual is None and max_annual is None:
        return None

    resolved_min = min_annual if min_annual is not None else max_annual
    resolved_max = max_annual if max_annual is not None else min_annual

    if resolved_min is not None and resolved_max is not None:
        actual_min = min(resolved_min, resolved_max)
        actual_max = max(resolved_min, resolved_max)
        resolved_min = actual_min
        resolved_max = actual_max

    salary_str = ""
    if resolved_min is not None and resolved_max is not None and resolved_min != resolved_max:
        salary_str = f"{_fmt_salary(resolved_min)} - {_fmt_salary(resolved_max)}"
    elif resolved_min is not None:
        salary_str = f"From {_fmt_salary(resolved_min)}"
    elif resolved_max is not None:
        salary_str = f"Up to {_fmt_salary(resolved_max)}"

    if currency:
        salary_str = f"{currency} {salary_str}" if salary_str else currency

    return salary_str.strip() or None


def _fmt_salary(value: float) -> str:
    """Format a salary number, e.g. 150000 → '$150,000'."""
    if value >= 1000:
        formatted = f"${value:,.0f}"
    else:
        formatted = f"${value:.0f}"
    return formatted


def _normalise_num(value: Any) -> Optional[float]:
    """Coerce a value to a non-negative float, or None if invalid."""
    if value is None:
        return None
    try:
        n = float(value)
        return n if n >= 0 else None
    except (ValueError, TypeError):
        return None


def _resolve_api_url(company: dict) -> Optional[str]:
    import re
    careers_url = (company.get("careers_url") or "").strip()
    match = re.search(r"jobs\.ashbyhq\.com/([^/?#]+)", careers_url)
    if not match:
        return None
    return f"https://api.ashbyhq.com/posting-api/job-board/{match.group(1)}?includeCompensation=true"


def _format_location(job: dict) -> str:
    """Fold primary and secondary locations into a single string.

    Ashby's API puts extra hiring regions in ``secondaryLocations[]``.
    We fold them in so location filters can match e.g. "Europe", "Berlin".
    """
    parts: list[str] = []
    primary = (job.get("location") or "").strip()
    if primary:
        parts.append(primary)

    for sec in (job.get("secondaryLocations") or []):
        if not isinstance(sec, dict):
            continue
        loc = (sec.get("location") or "").strip()
        if loc:
            parts.append(loc)
        address = sec.get("address", {})
        pa = address.get("postalAddress") if isinstance(address, dict) else None
        if isinstance(pa, dict):
            for key in ("addressLocality", "addressCountry"):
                val = (pa.get(key) or "").strip()
                if val:
                    parts.append(val)

    seen: list[str] = []
    for p in parts:
        if p not in seen:
            seen.append(p)
    return " · ".join(seen)


def _to_epoch_ms(value: Any) -> Optional[int]:
    """Parse ISO date to epoch ms."""
    if not value:
        return None
    if isinstance(value, (int, float)):
        return int(value)
    try:
        dt = datetime.fromisoformat(str(value))
        return int(dt.timestamp() * 1000)
    except (ValueError, TypeError):
        return None


class AshbyProvider(AtsProvider):
    id = "ashby"

    def detect(self, company: dict) -> Optional[str]:
        return _resolve_api_url(company)

    async def fetch(self, company: dict, api_url: str) -> list[dict]:
        json_data = await fetch_with_retry(
            api_url,
            timeout_ms=ASHBY_TIMEOUT_MS,
            retries=ASHBY_RETRIES,
            redirect="error",
        )
        jobs_raw = json_data.get("jobs") if isinstance(json_data, dict) else []
        if not isinstance(jobs_raw, list):
            return []

        results: list[dict] = []
        for j in jobs_raw:
            if not isinstance(j, dict):
                continue
            url = (j.get("jobUrl") or "").strip()
            if not url:
                continue

            salary_str = _parse_compensation(j)
            posted = _to_epoch_ms(j.get("publishedAt"))

            results.append({
                "title": (j.get("title") or "").strip(),
                "url": url,
                "company": (company.get("name") or "").strip(),
                "location": _format_location(j),
                "salary": salary_str,
                "posted_date": posted,
                "source": "ashby",
            })
        return results

    async def fetch_postings(self, company: dict, api_url: str) -> list[RawPosting]:
        json_data = await fetch_with_retry(
            api_url,
            timeout_ms=ASHBY_TIMEOUT_MS,
            retries=ASHBY_RETRIES,
            redirect="error",
        )
        jobs_raw = json_data.get("jobs") if isinstance(json_data, dict) else []
        if not isinstance(jobs_raw, list):
            return []

        results: list[RawPosting] = []
        for j in jobs_raw:
            if not isinstance(j, dict):
                continue
            # Unlisted jobs are typically closed/internal — the legacy fetch()
            # doesn't check this since Ashby usually omits them entirely, but
            # ingestion should not treat a stale unlisted row as "new" either.
            if j.get("isListed") is False:
                continue

            url = (j.get("jobUrl") or "").strip()
            job_id = j.get("id")
            if not url or not job_id:
                continue

            posted_at = None
            posted_ms = _to_epoch_ms(j.get("publishedAt"))
            if posted_ms is not None:
                posted_at = datetime.fromtimestamp(posted_ms / 1000.0, tz=timezone.utc)

            employment_type = (j.get("employmentType") or "").strip() or None
            remote_flag = bool(j.get("isRemote")) if "isRemote" in j else None

            results.append(RawPosting(
                provider_job_id=str(job_id),
                title=(j.get("title") or "").strip(),
                location=_format_location(j) or None,
                remote_flag=remote_flag,
                employment_type=employment_type,
                description_text=(j.get("descriptionPlain") or "").strip(),
                salary=_parse_compensation(j),
                url=url,
                apply_url=(j.get("applyUrl") or "").strip() or url,
                posted_at=posted_at,
                raw=j,
            ))
        return results
