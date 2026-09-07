"""Ingest orchestrator — PLAN.md §2 acceptance criteria:

- ``jobctl ingest --all`` completes over the full registry with per-source
  error isolation (one broken org must not kill the run).
- Second consecutive run inserts ~0 new rows.
- Rate limiting: max 1 request/sec per host, retry with backoff on
  429/5xx (``fetch_with_retry``, already in ``_http.py``), real User-Agent.
"""

import asyncio
import logging
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Optional

from motor.motor_asyncio import AsyncIOMotorDatabase

from app.agents.ats_providers import AtsProvider
from app.agents.ats_providers._http import HostThrottle, reset_host_throttle, set_host_throttle
from app.ingest.dedupe import DedupeIndex, apply_dedupe
from app.ingest.models import Posting
from app.ingest.normalize import normalize_posting
from app.ingest.prefilter import CONFIG_PATH as PREFILTER_CONFIG_PATH
from app.ingest.prefilter import load_prefilter_config, run_prefilter
from app.ingest.registry import CONFIG_PATH, Source, load_and_resolve_sources
from app.ingest.store import StoreResult, upsert_postings

log = logging.getLogger(__name__)

MAX_CONCURRENT_FETCHES = 10
MIN_HOST_INTERVAL_SECONDS = 1.0


@dataclass
class SourceOutcome:
    name: str
    org: str
    provider: Optional[str]
    status: str  # "ok" | "no_provider_match" | "not_ingestable" | "error" | "skipped_disabled"
    jobs_fetched: int = 0
    jobs_normalized: int = 0
    error: Optional[str] = None


@dataclass
class IngestRunResult:
    run_id: str
    started_at: str
    finished_at: str = ""
    sources_total: int = 0
    sources_ok: int = 0
    sources_error: int = 0
    sources_skipped: int = 0
    postings_fetched: int = 0
    postings_normalized: int = 0
    duplicates_marked: int = 0
    inserted: int = 0
    updated: int = 0
    dry_run: bool = False
    write_errors: list[dict] = field(default_factory=list)
    outcomes: list[SourceOutcome] = field(default_factory=list)
    prefilter: Optional[dict] = None  # milestone 3 stage counts, None on dry-run

    def to_dict(self) -> dict:
        d = asdict(self)
        d["outcomes"] = [asdict(o) for o in self.outcomes]
        return d


def _select_sources(
    sources: list[Source],
    source_filter: Optional[str],
    org_filter: Optional[str],
) -> list[Source]:
    selected = [s for s in sources if s.enabled]
    if source_filter:
        selected = [s for s in selected if s.provider_id == source_filter]
    if org_filter:
        needle = org_filter.strip().lower()
        selected = [s for s in selected if s.org.lower() == needle or s.name.lower() == needle]
    return selected


async def _fetch_source(
    source: Source,
    providers_by_id: dict[str, AtsProvider],
    semaphore: asyncio.Semaphore,
) -> tuple[SourceOutcome, list[Posting]]:
    if not source.provider_id:
        return SourceOutcome(source.name, source.org, None, "no_provider_match"), []

    provider = providers_by_id.get(source.provider_id)
    if provider is None:
        return SourceOutcome(source.name, source.org, source.provider_id, "no_provider_match"), []

    async with semaphore:
        try:
            raw_postings = await provider.fetch_postings(source.company, source.api_url)
        except NotImplementedError:
            return SourceOutcome(source.name, source.org, source.provider_id, "not_ingestable"), []
        except Exception as e:
            log.warning("[ingest] %s/%s fetch_postings failed: %s", source.provider_id, source.name, e)
            return SourceOutcome(source.name, source.org, source.provider_id, "error", error=str(e)), []

    postings: list[Posting] = []
    for raw in raw_postings:
        posting = normalize_posting(raw, source)
        if posting is not None:
            postings.append(posting)

    outcome = SourceOutcome(
        source.name, source.org, source.provider_id, "ok",
        jobs_fetched=len(raw_postings), jobs_normalized=len(postings),
    )
    return outcome, postings


async def run_ingest(
    db: AsyncIOMotorDatabase,
    *,
    config_path: str = CONFIG_PATH,
    source_filter: Optional[str] = None,
    org_filter: Optional[str] = None,
    dry_run: bool = False,
    run_id: Optional[str] = None,
) -> IngestRunResult:
    run_id = run_id or uuid.uuid4().hex[:12]
    started_at = datetime.now(timezone.utc)
    result = IngestRunResult(run_id=run_id, started_at=started_at.isoformat(), dry_run=dry_run)

    all_sources = load_and_resolve_sources(config_path)
    disabled_count = sum(1 for s in all_sources if not s.enabled)
    selected = _select_sources(all_sources, source_filter, org_filter)
    result.sources_total = len(selected)
    result.sources_skipped += disabled_count

    providers_by_id = {p.id: p for p in AtsProvider.get_providers()}
    semaphore = asyncio.Semaphore(MAX_CONCURRENT_FETCHES)
    throttle_token = set_host_throttle(HostThrottle(MIN_HOST_INTERVAL_SECONDS))

    all_postings: list[Posting] = []
    try:
        fetch_results = await asyncio.gather(
            *(_fetch_source(s, providers_by_id, semaphore) for s in selected)
        )
    finally:
        reset_host_throttle(throttle_token)

    for outcome, postings in fetch_results:
        result.outcomes.append(outcome)
        if outcome.status == "ok":
            result.sources_ok += 1
        elif outcome.status == "error":
            result.sources_error += 1
        else:
            result.sources_skipped += 1
        result.postings_fetched += outcome.jobs_fetched
        result.postings_normalized += outcome.jobs_normalized
        all_postings.extend(postings)

    if all_postings:
        touched_orgs = list({p.org for p in all_postings})
        existing_docs = await db.postings.find(
            {"org": {"$in": touched_orgs}},
            projection={"_id": 1, "org": 1, "title_normalized": 1, "location_normalized": 1, "first_seen_at": 1},
        ).to_list(length=None)
        dedupe_index = DedupeIndex.from_existing_docs(existing_docs)
        result.duplicates_marked = apply_dedupe(all_postings, dedupe_index, now=started_at)

        if not dry_run:
            store_result: StoreResult = await upsert_postings(db, all_postings, run_id)
            result.inserted = store_result.inserted
            result.updated = store_result.updated
            result.write_errors = store_result.write_errors

    if not dry_run:
        # PLAN.md §4 (milestone 3): classify everything not yet prefiltered
        # after every ingest, not just what this run fetched -- so a run
        # that itself finds 0 new postings still works through any backlog
        # (e.g. the first run after the prefilter fields were migrated in).
        try:
            prefilter_config = load_prefilter_config(PREFILTER_CONFIG_PATH)
            prefilter_result = await run_prefilter(db, prefilter_config)
            result.prefilter = prefilter_result.to_dict()
        except FileNotFoundError:
            log.warning(
                "[ingest] prefilter config not found at %s -- skipping prefilter this run",
                PREFILTER_CONFIG_PATH,
            )

    finished_at = datetime.now(timezone.utc)
    result.finished_at = finished_at.isoformat()

    if not dry_run:
        await db.ingest_runs.insert_one({
            "_id": run_id,
            "started_at": started_at,
            "finished_at": finished_at,
            "sources_total": result.sources_total,
            "sources_ok": result.sources_ok,
            "sources_error": result.sources_error,
            "sources_skipped": result.sources_skipped,
            "postings_fetched": result.postings_fetched,
            "postings_normalized": result.postings_normalized,
            "duplicates_marked": result.duplicates_marked,
            "inserted": result.inserted,
            "updated": result.updated,
            "errors": [asdict(o) for o in result.outcomes if o.status == "error"],
            "write_errors": result.write_errors,
            "prefilter": result.prefilter,
        })

    return result
