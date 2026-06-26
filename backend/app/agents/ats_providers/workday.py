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

import json
import logging
import re
from datetime import datetime, timezone
from typing import Any, Optional

from app.agents.ats_providers._http import fetch_json
from app.agents.ats_providers.base import AtsProvider

log = logging.getLogger(__name__)

PAGE_SIZE = 20
MAX_PAGES = 50  # safety cap — at most 1 000 postings per site

# 86 400 000 ms in a day
_DAY_MS = 86_400_000


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


class WorkdayProvider(AtsProvider):
    id = "workday"

    def detect(self, company: dict) -> Optional[str]:
        ep = _resolve_endpoint(company)
        return ep["api"] if ep else None

    async def fetch(self, company: dict, api_url: str) -> list[dict]:
        ep = _resolve_endpoint(company)
        if not ep:
            raise ValueError(f"workday: cannot derive CXS endpoint for {company.get('name')}")

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
            for j in postings:
                if not isinstance(j, dict):
                    continue
                ext_path = (j.get("externalPath") or "").strip()
                if not ext_path:
                    continue
                all_jobs.append({
                    "title": (j.get("title") or "").strip(),
                    "url": ep["jobBase"] + ext_path,
                    "company": (company.get("name") or "").strip(),
                    "location": (j.get("locationsText") or "").strip(),
                    "posted_date": _parse_posted_on(j.get("postedOn")),
                    "source": "workday",
                })

            if len(postings) < PAGE_SIZE:
                break

        log.info("[workday] fetched %d jobs for %s", len(all_jobs), company.get("name"))
        return all_jobs
