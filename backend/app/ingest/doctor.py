"""``jobctl sources doctor`` — PLAN.md §2 acceptance criteria:

"``jobctl sources doctor`` reports which orgs returned 0 jobs or errored, so
dead tokens get caught."

Runs against every resolved source via the legacy ``fetch()`` — cheap, one
call per org (or one call per page for Workday) — never ``fetch_postings()``.

    Deviation (milestone 5, 2026-09-07): before this milestone, ``fetch()``
    was the fallback only for providers without ``fetch_postings()`` yet
    (Workday). Now that SmartRecruiters and Workday's ``fetch_postings()``
    also do a per-job detail call for the description (see ingest.md's
    "Edge Cases"), calling it here for a live health-check would serialize
    hundreds of extra requests per org behind the shared per-host 1 req/sec
    throttle — a "few seconds" diagnostic turning into ~20 minutes on this
    registry. Doctor only needs a job count and a dead/alive signal, which
    ``fetch()`` already gives for every provider; ``fetch_postings()``'s own
    correctness (description parsing, ids, etc.) is covered by the fixture
    tests in tests/ingest/, not by a live probe.
"""

import asyncio
import logging
from dataclasses import asdict, dataclass
from typing import Optional

from app.agents.ats_providers import AtsProvider
from app.agents.ats_providers._http import HostThrottle, reset_host_throttle, set_host_throttle
from app.ingest.registry import CONFIG_PATH, Source, load_and_resolve_sources
from app.ingest.runner import MAX_CONCURRENT_FETCHES, MIN_HOST_INTERVAL_SECONDS

log = logging.getLogger(__name__)


@dataclass
class DoctorEntry:
    name: str
    org: str
    provider: Optional[str]
    status: str  # "ok" | "zero_jobs" | "no_provider_match" | "error" | "disabled"
    job_count: int = 0
    error: Optional[str] = None


async def _probe_source(source: Source, providers_by_id: dict[str, AtsProvider], semaphore: asyncio.Semaphore) -> DoctorEntry:
    if not source.enabled:
        return DoctorEntry(source.name, source.org, source.provider_id, "disabled")
    if not source.provider_id:
        return DoctorEntry(source.name, source.org, None, "no_provider_match")

    provider = providers_by_id.get(source.provider_id)
    if provider is None:
        return DoctorEntry(source.name, source.org, source.provider_id, "no_provider_match")

    async with semaphore:
        try:
            jobs = await provider.fetch(source.company, source.api_url)
        except Exception as e:
            return DoctorEntry(source.name, source.org, source.provider_id, "error", error=str(e))

    count = len(jobs)
    if count == 0:
        return DoctorEntry(source.name, source.org, source.provider_id, "zero_jobs", job_count=0)
    return DoctorEntry(source.name, source.org, source.provider_id, "ok", job_count=count)


async def run_doctor(config_path: str = CONFIG_PATH) -> list[DoctorEntry]:
    sources = load_and_resolve_sources(config_path)
    providers_by_id = {p.id: p for p in AtsProvider.get_providers()}
    semaphore = asyncio.Semaphore(MAX_CONCURRENT_FETCHES)

    token = set_host_throttle(HostThrottle(MIN_HOST_INTERVAL_SECONDS))
    try:
        entries = await asyncio.gather(*(_probe_source(s, providers_by_id, semaphore) for s in sources))
    finally:
        reset_host_throttle(token)
    return list(entries)


def summarize(entries: list[DoctorEntry]) -> dict:
    summary: dict[str, int] = {}
    for e in entries:
        summary[e.status] = summary.get(e.status, 0) + 1
    return summary
