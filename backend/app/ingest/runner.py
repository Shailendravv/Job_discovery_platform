"""Ingest orchestrator — PLAN.md §2 acceptance criteria:

- ``jobctl ingest --all`` completes over the full registry with per-source
  error isolation (one broken org must not kill the run).
- Second consecutive run inserts ~0 new rows.
- Rate limiting: max 1 request/sec per host, retry with backoff on
  429/5xx (``fetch_with_retry``, already in ``_http.py``), real User-Agent.
"""

import asyncio
import contextlib
import logging
import time
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Optional

from motor.motor_asyncio import AsyncIOMotorDatabase

from app.agents.ats_providers import AtsProvider
from app.agents.ats_providers._http import HostThrottle, reset_host_throttle, set_host_throttle
from app.ingest.dedupe import DedupeIndex, apply_dedupe
from app.ingest.freshness import cutoff_for, is_fresh
from app.ingest.models import Posting
from app.ingest.normalize import normalize_posting
from app.ingest.prefilter import CONFIG_PATH as PREFILTER_CONFIG_PATH
from app.ingest.prefilter import load_prefilter_config, run_prefilter
from app.ingest.registry import CONFIG_PATH, Source, load_and_resolve_sources
from app.ingest.scoring import SCORING_CONFIG_PATH, load_scoring_config, run_scoring
from app.ingest.store import StoreResult, upsert_postings

log = logging.getLogger(__name__)

MAX_CONCURRENT_FETCHES = 10
MIN_HOST_INTERVAL_SECONDS = 1.0


@dataclass
class StageTiming:
    """How long one stage of a run took, and how much it handled.

    ``count`` is stage-specific (sources fetched, postings normalized,
    postings written...) and is there so a slow stage can be read as
    "slow because there was a lot" vs. "slow per item".
    """

    name: str
    duration_ms: float
    count: int = 0


@dataclass
class SourceOutcome:
    name: str
    org: str
    provider: Optional[str]
    status: str  # "ok" | "no_provider_match" | "not_ingestable" | "error" | "skipped_disabled"
    jobs_fetched: int = 0
    jobs_normalized: int = 0
    error: Optional[str] = None
    duration_ms: float = 0.0


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
    score: Optional[dict] = None      # deterministic scoring band counts, None on dry-run

    # Job Discovery session fields.
    role: Optional[str] = None            # role query this run was scoped to
    window: Optional[str] = None          # freshness window as given, e.g. "24h"
    postings_fresh: int = 0               # normalized postings inside the window
    elapsed_ms: float = 0.0
    stages: list[StageTiming] = field(default_factory=list)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["outcomes"] = [asdict(o) for o in self.outcomes]
        d["stages"] = [asdict(t) for t in self.stages]
        return d


@contextlib.contextmanager
def _stage(result: "IngestRunResult", name: str):
    """Time one stage and record it on the run result.

    Yields a one-element list the body sets to the stage's item count — a
    list because the count is usually only known once the stage has run.
    """
    holder = [0]
    started = time.perf_counter()
    try:
        yield holder
    finally:
        duration_ms = (time.perf_counter() - started) * 1000.0
        result.stages.append(StageTiming(name=name, duration_ms=round(duration_ms, 1), count=holder[0]))
        log.info("[ingest] run=%s stage=%s %.0fms items=%d", result.run_id, name, duration_ms, holder[0])


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
    posted_since: Optional[datetime] = None,
) -> tuple[SourceOutcome, list[Posting]]:
    if not source.provider_id:
        return SourceOutcome(source.name, source.org, None, "no_provider_match"), []

    provider = providers_by_id.get(source.provider_id)
    if provider is None:
        return SourceOutcome(source.name, source.org, source.provider_id, "no_provider_match"), []

    # Timed inside the semaphore so the number reflects real wall time,
    # including the per-host throttle wait — that is what makes a slow
    # source actually slow for the run.
    started = time.perf_counter()

    def _elapsed_ms() -> float:
        return round((time.perf_counter() - started) * 1000.0, 1)

    async with semaphore:
        try:
            raw_postings = await provider.fetch_postings(
                source.company, source.api_url, posted_since=posted_since
            )
        except NotImplementedError:
            return SourceOutcome(
                source.name, source.org, source.provider_id, "not_ingestable",
                duration_ms=_elapsed_ms(),
            ), []
        except Exception as e:
            # str(e) is blank for plenty of real exceptions (bare
            # RuntimeError(), asyncio.TimeoutError(), some httpx transport
            # errors) — always prefix the type so a source can never error
            # out with an empty, undiagnosable reason.
            detail = f"{type(e).__name__}: {e}" if str(e) else type(e).__name__
            log.warning(
                "[ingest] %s/%s fetch_postings failed: %s", source.provider_id, source.name, detail,
                exc_info=True,
            )
            return SourceOutcome(
                source.name, source.org, source.provider_id, "error", error=detail,
                duration_ms=_elapsed_ms(),
            ), []

    postings: list[Posting] = []
    for raw in raw_postings:
        posting = normalize_posting(raw, source)
        if posting is not None:
            postings.append(posting)

    outcome = SourceOutcome(
        source.name, source.org, source.provider_id, "ok",
        jobs_fetched=len(raw_postings), jobs_normalized=len(postings),
        duration_ms=_elapsed_ms(),
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
    role: Optional[str] = None,
    window: Optional[timedelta] = None,
    window_label: Optional[str] = None,
) -> IngestRunResult:
    """Fetch -> normalize -> dedupe -> store -> prefilter -> score.

    Every stage is deterministic; nothing here calls an LLM.

    ``window`` scopes the run to a Job Discovery freshness window. It is
    passed to the providers as ``posted_since`` so the two that pay a
    per-job description fetch (smartrecruiters, workday) can skip stale
    postings *before* spending that call, and it is used to count
    ``postings_fresh``. It deliberately does **not** drop postings before
    storage: the corpus stays complete and the window is applied again at
    read time (``PostingFilter.posted_since``), which is what the user
    actually sees.

    ``role`` is recorded on the run for display; role filtering itself
    happens at read time (``PostingFilter.role_query``) because no ATS API
    in the registry supports a server-side keyword filter.
    """
    run_id = run_id or uuid.uuid4().hex[:12]
    started_at = datetime.now(timezone.utc)
    result = IngestRunResult(
        run_id=run_id,
        started_at=started_at.isoformat(),
        dry_run=dry_run,
        role=role,
        window=window_label,
    )
    posted_since = cutoff_for(window, now=started_at) if window is not None else None

    log.info(
        "[ingest] run=%s starting - role=%r window=%s posted_since=%s dry_run=%s",
        run_id, role, window_label, posted_since.isoformat() if posted_since else None, dry_run,
    )

    # Publish the run as soon as it starts so the Discovery page can poll it
    # for live progress. Before this, ingest_runs was written only at
    # completion, which made progress impossible to observe.
    if not dry_run:
        await _record_run_start(db, run_id, started_at, result)

    with _stage(result, "load_registry") as count:
        all_sources = load_and_resolve_sources(config_path)
        disabled_count = sum(1 for s in all_sources if not s.enabled)
        selected = _select_sources(all_sources, source_filter, org_filter)
        result.sources_total = len(selected)
        result.sources_skipped += disabled_count
        count[0] = len(selected)

    # Published before the fetch rather than after it: fetching the whole
    # registry is the longest stage by far (minutes), and without this the
    # Discovery page would show an empty run document for all of it.
    await _publish_progress(db, result, dry_run)

    providers_by_id = {p.id: p for p in AtsProvider.get_providers()}
    semaphore = asyncio.Semaphore(MAX_CONCURRENT_FETCHES)
    throttle_token = set_host_throttle(HostThrottle(MIN_HOST_INTERVAL_SECONDS))

    all_postings: list[Posting] = []
    with _stage(result, "fetch") as count:
        try:
            fetch_results = await asyncio.gather(
                *(_fetch_source(s, providers_by_id, semaphore, posted_since) for s in selected)
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
        count[0] = result.postings_fetched

    _log_slowest_sources(result)

    if window is not None:
        # Counted, not dropped - see the docstring. first_seen_at is not set
        # until store.py runs, so at this point is_fresh() judges on
        # posted_at alone, which is the strict reading of the window.
        result.postings_fresh = sum(
            1 for p in all_postings if is_fresh(p, window=window, now=started_at)
        )
        log.info(
            "[ingest] run=%s freshness - %d of %d normalized postings inside %s",
            run_id, result.postings_fresh, result.postings_normalized, window_label,
        )

    await _publish_progress(db, result, dry_run)

    if all_postings:
        with _stage(result, "dedupe") as count:
            touched_orgs = list({p.org for p in all_postings})
            existing_docs = await db.postings.find(
                {"org": {"$in": touched_orgs}},
                projection={"_id": 1, "org": 1, "title_normalized": 1, "location_normalized": 1, "first_seen_at": 1},
            ).to_list(length=None)
            dedupe_index = DedupeIndex.from_existing_docs(existing_docs)
            result.duplicates_marked = apply_dedupe(all_postings, dedupe_index, now=started_at)
            count[0] = len(all_postings)

        if not dry_run:
            with _stage(result, "store") as count:
                store_result: StoreResult = await upsert_postings(db, all_postings, run_id)
                result.inserted = store_result.inserted
                result.updated = store_result.updated
                result.write_errors = store_result.write_errors
                count[0] = store_result.inserted + store_result.updated

        await _publish_progress(db, result, dry_run)

    if not dry_run:
        # PLAN.md §4 (milestone 3): classify everything not yet prefiltered
        # after every ingest, not just what this run fetched -- so a run
        # that itself finds 0 new postings still works through any backlog
        # (e.g. the first run after the prefilter fields were migrated in).
        with _stage(result, "prefilter") as count:
            try:
                prefilter_config = load_prefilter_config(PREFILTER_CONFIG_PATH)
                prefilter_result = await run_prefilter(db, prefilter_config)
                result.prefilter = prefilter_result.to_dict()
                count[0] = prefilter_result.input
            except FileNotFoundError:
                log.warning(
                    "[ingest] prefilter config not found at %s -- skipping prefilter this run",
                    PREFILTER_CONFIG_PATH,
                )

        await _publish_progress(db, result, dry_run)

        # Deterministic scoring: auto-decides the clear-cut apply/skip cases
        # with zero LLM calls, leaving only the ambiguous band for a Claude
        # Code judging session. Same "missing config is not fatal" contract
        # as the prefilter above.
        with _stage(result, "score") as count:
            try:
                scoring_config = load_scoring_config(SCORING_CONFIG_PATH)
                score_result = await run_scoring(db, scoring_config)
                result.score = score_result.to_dict()
                count[0] = score_result.input
            except FileNotFoundError:
                log.warning(
                    "[ingest] scoring config not found at %s -- skipping scoring this run",
                    SCORING_CONFIG_PATH,
                )

    finished_at = datetime.now(timezone.utc)
    result.finished_at = finished_at.isoformat()
    result.elapsed_ms = round((finished_at - started_at).total_seconds() * 1000.0, 1)
    result.stages.append(
        StageTiming(name="total", duration_ms=result.elapsed_ms, count=result.postings_normalized)
    )

    log.info(
        "[ingest] run=%s complete in %.1fs - sources %d ok / %d error, "
        "postings %d fetched / %d normalized / %d fresh, store %d inserted / %d updated",
        run_id, result.elapsed_ms / 1000.0, result.sources_ok, result.sources_error,
        result.postings_fetched, result.postings_normalized, result.postings_fresh,
        result.inserted, result.updated,
    )

    if not dry_run:
        await _record_run_finish(db, run_id, finished_at, result)

    return result


def _log_slowest_sources(result: IngestRunResult, top_n: int = 5) -> None:
    """One line naming the sources that dominated the fetch stage - the
    actionable half of "why did this run take so long"."""
    timed = sorted(result.outcomes, key=lambda o: o.duration_ms, reverse=True)[:top_n]
    if not timed:
        return
    summary = ", ".join(f"{o.name}({o.provider}) {o.duration_ms:.0f}ms" for o in timed)
    log.info("[ingest] run=%s slowest sources - %s", result.run_id, summary)


def _run_document(result: IngestRunResult) -> dict:
    """The mutable half of an ``ingest_runs`` document - everything that can
    change as the run progresses. Shared by the start/progress/finish writes
    so the three cannot drift apart."""
    return {
        "role": result.role,
        "window": result.window,
        "sources_total": result.sources_total,
        "sources_ok": result.sources_ok,
        "sources_error": result.sources_error,
        "sources_skipped": result.sources_skipped,
        "postings_fetched": result.postings_fetched,
        "postings_normalized": result.postings_normalized,
        "postings_fresh": result.postings_fresh,
        "duplicates_marked": result.duplicates_marked,
        "inserted": result.inserted,
        "updated": result.updated,
        "errors": [asdict(o) for o in result.outcomes if o.status == "error"],
        "write_errors": result.write_errors,
        "prefilter": result.prefilter,
        "score": result.score,
        "stages": [asdict(t) for t in result.stages],
        "elapsed_ms": result.elapsed_ms,
    }


async def _record_run_start(
    db: AsyncIOMotorDatabase, run_id: str, started_at: datetime, result: IngestRunResult
) -> None:
    await db.ingest_runs.insert_one({
        "_id": run_id,
        "status": "running",
        "started_at": started_at,
        "finished_at": None,
        **_run_document(result),
    })


async def _publish_progress(db: AsyncIOMotorDatabase, result: IngestRunResult, dry_run: bool) -> None:
    """Mid-run update so a poller sees stages land as they complete.

    Never allowed to fail the run: progress reporting is a convenience, and
    an ingest that actually fetched postings must not be lost to a failed
    status write.
    """
    if dry_run:
        return
    try:
        await db.ingest_runs.update_one(
            {"_id": result.run_id},
            {"$set": {"status": "running", **_run_document(result)}},
        )
    except Exception as e:
        log.warning("[ingest] run=%s progress update failed: %s", result.run_id, e)


async def _record_run_finish(
    db: AsyncIOMotorDatabase, run_id: str, finished_at: datetime, result: IngestRunResult
) -> None:
    await db.ingest_runs.update_one(
        {"_id": run_id},
        {"$set": {
            "status": "completed",
            "finished_at": finished_at,
            **_run_document(result),
        }},
        # A run whose start write was lost (or a caller that pre-dates the
        # start write) still gets a complete record rather than vanishing.
        upsert=True,
    )


async def mark_run_failed(db: AsyncIOMotorDatabase, run_id: str, error: str) -> None:
    """Flip a run to ``failed`` so a poller stops waiting on it. Called by
    the API background task wrapper when run_ingest raises."""
    try:
        await db.ingest_runs.update_one(
            {"_id": run_id},
            {"$set": {
                "status": "failed",
                "finished_at": datetime.now(timezone.utc),
                "error": error,
            }},
            upsert=True,
        )
    except Exception as e:
        log.warning("[ingest] run=%s could not be marked failed: %s", run_id, e)
