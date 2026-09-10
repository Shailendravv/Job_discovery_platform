"""Lever ATS provider.

API endpoint: ``GET https://api.lever.co/v0/postings/{slug}``
Response shape: bare JSON array (no wrapper object).

URL patterns matched:
- ``jobs.lever.co/{slug}``

Key differentiator: Lever's list endpoint ships ``descriptionPlain``
(plain-text job description) for free — no per-job fetch required.
"""

import logging
from datetime import datetime, timezone
from typing import Any, Optional

from app.agents.ats_providers._http import fetch_json
from app.agents.ats_providers.base import AtsProvider, RawPosting

log = logging.getLogger(__name__)


def _resolve_api_url(company: dict) -> Optional[str]:
    import re
    careers_url = (company.get("careers_url") or "").strip()
    match = re.search(r"jobs\.lever\.co/([^/?#]+)", careers_url)
    if not match:
        return None
    return f"https://api.lever.co/v0/postings/{match.group(1)}"


class LeverProvider(AtsProvider):
    id = "lever"

    def detect(self, company: dict) -> Optional[str]:
        return _resolve_api_url(company)

    async def fetch(self, company: dict, api_url: str) -> list[dict]:
        json_data = await fetch_json(api_url, redirect="error")
        # Lever returns a bare array (not wrapped in { jobs: [...] })
        jobs_raw = json_data if isinstance(json_data, list) else []
        results: list[dict] = []
        for j in jobs_raw:
            if not isinstance(j, dict):
                continue
            url = (j.get("hostedUrl") or "").strip()
            if not url:
                continue
            # Lever provides descriptionPlain for free — enables content filtering
            description = ""
            if isinstance(j.get("descriptionPlain"), str):
                description = j["descriptionPlain"].strip()

            posted_at = None
            if isinstance(j.get("createdAt"), (int, float)):
                posted_at = int(j["createdAt"])

            results.append({
                "title": (j.get("text") or "").strip(),
                "url": url,
                "company": (company.get("name") or "").strip(),
                "location": _get_nested_str(j, "categories", "location"),
                "description": description,
                "posted_date": posted_at,
                "source": "lever",
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
        json_data = await fetch_json(api_url, redirect="error")
        jobs_raw = json_data if isinstance(json_data, list) else []

        results: list[RawPosting] = []
        for j in jobs_raw:
            if not isinstance(j, dict):
                continue
            url = (j.get("hostedUrl") or "").strip()
            job_id = j.get("id")
            if not url or not job_id:
                continue

            parts = []
            if isinstance(j.get("descriptionPlain"), str) and j["descriptionPlain"].strip():
                parts.append(j["descriptionPlain"].strip())
            if isinstance(j.get("additionalPlain"), str) and j["additionalPlain"].strip():
                parts.append(j["additionalPlain"].strip())
            description_text = "\n\n".join(parts)

            posted_at = None
            if isinstance(j.get("createdAt"), (int, float)):
                posted_at = datetime.fromtimestamp(j["createdAt"] / 1000.0, tz=timezone.utc)

            workplace_type = str(j.get("workplaceType") or "").strip().lower()
            remote_flag = True if workplace_type == "remote" else (False if workplace_type else None)

            categories = j.get("categories") or {}
            employment_type = None
            if isinstance(categories, dict):
                commitment = (categories.get("commitment") or "").strip()
                employment_type = commitment or None

            results.append(RawPosting(
                provider_job_id=str(job_id),
                title=(j.get("text") or "").strip(),
                location=_get_nested_str(j, "categories", "location") or None,
                remote_flag=remote_flag,
                employment_type=employment_type,
                description_text=description_text,
                salary=None,
                url=url,
                apply_url=(j.get("applyUrl") or "").strip() or url,
                posted_at=posted_at,
                raw=j,
            ))
        return results


def _get_nested_str(obj: Any, *keys: str) -> str:
    current = obj
    for k in keys:
        if isinstance(current, dict):
            current = current.get(k)
        else:
            return ""
    return str(current).strip() if current else ""
