"""``jobctl sources doctor`` — PLAN.md §2 acceptance criteria:

"``jobctl sources doctor`` reports which orgs returned 0 jobs or errored, so
dead tokens get caught."

Runs against every resolved source, including ones that don't support
``fetch_postings()`` yet (Workday, this milestone) — those still get probed
via the legacy ``fetch()`` so a dead Workday token is caught even though it
can't be ingested yet.
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
    status: str  # "ok" | "zero_jobs" | "not_ingestable_probe_ok" | "no_provider_match" | "error" | "disabled"
    job_count: int = 0
    error: Optional[str] = None


def _supports_ingestion(provider: AtsProvider) -> bool:
    return type(provider).fetch_postings is not AtsProvider.fetch_postings


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
            if _supports_ingestion(provider):
                jobs = await provider.fetch_postings(source.company, source.api_url)
            else:
                jobs = await provider.fetch(source.company, source.api_url)
        except Exception as e:
            return DoctorEntry(source.name, source.org, source.provider_id, "error", error=str(e))

    count = len(jobs)
    if count == 0:
        return DoctorEntry(source.name, source.org, source.provider_id, "zero_jobs", job_count=0)
    status = "ok" if _supports_ingestion(provider) else "not_ingestable_probe_ok"
    return DoctorEntry(source.name, source.org, source.provider_id, status, job_count=count)


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
