import logging
import re
from datetime import timedelta

from fastapi import APIRouter, BackgroundTasks, Body, Depends, HTTPException, Query

from app.api.deps import get_db
from app.core.config import settings
from app.core.database import get_database
from app.ingest.freshness import resolve_window
from app.ingest.models import Posting
from app.ingest.query import (
    DEFAULT_SHORTLIST_LIMIT,
    DEFAULT_SHORTLIST_MIN_SCORE,
    PostingFilter,
    ShortlistFilter,
    list_postings,
    shortlist_postings,
)
from app.ingest.runner import mark_run_failed, run_ingest
from app.models.posting import (
    ActiveResumeInfo,
    IngestRunStatus,
    IngestStage,
    IngestTriggerRequest,
    IngestTriggerResponse,
    PostingDetailResponse,
    PostingListResponse,
    ShortlistEntry,
    ShortlistResponse,
    TailoringDownloadUrls,
    TailoringStatus,
)
from app.services.db_service import get_latest_resume, get_tailor_session_for_job

log = logging.getLogger(__name__)
router = APIRouter()

# "200 latest" per the plan — only postings seen in this window count as
# "latest"; older prefiltered-but-unjudged backlog doesn't silently appear
# under a plain GET.
DEFAULT_LATEST_LIMIT = 200
DEFAULT_LATEST_SINCE_DAYS = 14

# ``Posting.id`` is declared ``Field(..., alias="_id")`` so a Mongo document
# validates straight into the model and ``model_dump(by_alias=True)`` writes
# it back as ``_id`` (store.py). FastAPI, though, serializes response models
# with ``by_alias=True`` by default, which would leak that storage-level name
# into the public JSON — the frontend routes on ``posting.id``. These reads
# opt out so the wire format stays ``id``; the model keeps its alias.
BY_FIELD_NAME = {"response_model_by_alias": False}

# A posting ``_id`` is always the sha256 hex digest from
# ``app.ingest.models.posting_id`` — 64 lowercase hex chars, nothing else.
POSTING_ID_RE = re.compile(r"[0-9a-f]{64}")


@router.get("", response_model=PostingListResponse, **BY_FIELD_NAME)
async def get_postings(
    limit: int = Query(DEFAULT_LATEST_LIMIT, ge=1, le=500),
    since_days: int = Query(DEFAULT_LATEST_SINCE_DAYS, ge=1, le=365),
    provider: str | None = Query(None),
    org: str | None = Query(None),
    prefilter_status: str | None = Query(
        "passed", description="Filter by prefilter outcome. Pass empty to disable."
    ),
    q: str | None = Query(
        None,
        description=(
            "Role search, e.g. 'backend engineer'. Deterministic token match "
            "against the posting title, with a fixed synonym table "
            "(app/ingest/role_match.py) - no LLM, no ranking."
        ),
    ),
    posted_within: str | None = Query(
        None,
        description=(
            "Only postings posted within this window, e.g. '24h', '48h', '7d'. "
            "Judged on posted_at, falling back to first_seen_at when the "
            "provider supplied no date. This is what the Job Discovery page "
            "sends; leave unset for the Dashboard's since_days behaviour."
        ),
    ),
    db=Depends(get_db),
):
    """The latest read the frontend polls: most recent postings that cleared
    the prefilter, newest first, excluding near-duplicates.

    Two independent windows, deliberately: ``since_days`` bounds when we
    *first saw* a posting (the Dashboard's backlog view), while
    ``posted_within`` bounds when it was *posted* (the Discovery view's
    "last 24 hours" promise). The Discovery page sends ``posted_within`` and
    widens ``since_days``, because a posting published an hour ago may well
    have been sitting in our corpus for a fortnight."""
    try:
        posted_since = resolve_window(posted_within) if posted_within else None
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))

    filters = PostingFilter(
        provider=provider,
        org=org,
        prefilter_status=prefilter_status or None,
        since=timedelta(days=since_days),
        posted_since=posted_since,
        role_query=q,
    )
    docs = await list_postings(
        db, filters, limit=limit, sort_field="posted_at", sort_direction=-1
    )
    postings = [Posting.model_validate(d) for d in docs]
    return PostingListResponse(postings=postings, total=len(postings))


@router.get("/shortlist", response_model=ShortlistResponse, **BY_FIELD_NAME)
async def get_shortlist(
    min_score: int = Query(DEFAULT_SHORTLIST_MIN_SCORE, ge=0, le=10),
    since_days: int | None = Query(None, ge=1, le=365),
    limit: int = Query(DEFAULT_SHORTLIST_LIMIT, ge=1, le=200),
    db=Depends(get_db),
):
    """Judged postings worth applying to — verdict apply/maybe, score >= min_score."""
    filters = ShortlistFilter(
        min_score=min_score,
        since=timedelta(days=since_days) if since_days else None,
    )
    rows = await shortlist_postings(db, filters, limit=limit)
    entries = [
        ShortlistEntry(
            id=row["_id"],
            verdict=row["verdict"],
            score=row["score"],
            reasons=row.get("reasons", []),
            concerns=row.get("concerns", []),
            judged_at=row.get("judged_at").isoformat() if row.get("judged_at") else None,
            posting=Posting.model_validate(row["posting"]),
        )
        for row in rows
    ]
    return ShortlistResponse(entries=entries)


@router.post("/ingest", response_model=IngestTriggerResponse, status_code=202)
async def trigger_ingest(
    background_tasks: BackgroundTasks,
    request: IngestTriggerRequest | None = Body(None),
):
    """Kick off a Job Discovery run in the background and return immediately.

    Mirrors ``jobctl ingest`` (app/ingest/runner.run_ingest) — never runs
    inline on the request, unlike the old /search endpoint, which is exactly
    what made that endpoint hang for hours. Poll
    ``GET /api/v1/postings/ingest/{run_id}`` for live progress.

    The body is optional: ``POST /ingest`` with no body still starts a full,
    unscoped run, which is what the nightly loop and any pre-existing caller
    expects."""
    import uuid

    request = request or IngestTriggerRequest()
    run_id = uuid.uuid4().hex[:12]

    window_label = request.window or settings.DISCOVERY_WINDOW
    try:
        window = resolve_window(window_label)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))

    async def _run():
        db = get_database()
        try:
            result = await run_ingest(
                db,
                run_id=run_id,
                role=request.role,
                window=window,
                window_label=window_label,
                source_filter=request.source,
                org_filter=request.org,
            )
            log.info(
                "[ingest:background] run_id=%s role=%r window=%s sources_ok=%d "
                "sources_error=%d fetched=%d fresh=%d inserted=%d updated=%d elapsed=%.1fs",
                run_id, request.role, window_label, result.sources_ok, result.sources_error,
                result.postings_fetched, result.postings_fresh, result.inserted,
                result.updated, result.elapsed_ms / 1000.0,
            )
        except Exception as e:
            log.exception("[ingest:background] run_id=%s failed", run_id)
            # Without this the run document is stuck on "running" and the
            # Discovery page polls it forever.
            await mark_run_failed(db, run_id, str(e))

    background_tasks.add_task(_run)
    return IngestTriggerResponse(run_id=run_id, status="started")


@router.get("/ingest/{run_id}", response_model=IngestRunStatus)
async def get_ingest_run(run_id: str, db=Depends(get_db)):
    """Live progress for one discovery run.

    ``run_ingest`` writes the run document when the run *starts* and updates
    it as each stage lands, so this returns meaningful stage timings while
    the run is still in flight — that is what the Discovery page renders."""
    doc = await db.ingest_runs.find_one({"_id": run_id})
    if not doc:
        raise HTTPException(status_code=404, detail=f"No discovery run with id {run_id}.")

    def _iso(value):
        return value.isoformat() if value else None

    return IngestRunStatus(
        run_id=doc["_id"],
        # A run recorded before this endpoint existed has no status field;
        # it finished long ago, so report it as completed rather than
        # leaving a poller hanging on a missing key.
        status=doc.get("status") or ("completed" if doc.get("finished_at") else "running"),
        started_at=_iso(doc.get("started_at")),
        finished_at=_iso(doc.get("finished_at")),
        elapsed_ms=doc.get("elapsed_ms") or 0.0,
        role=doc.get("role"),
        window=doc.get("window"),
        stages=[IngestStage(**stage) for stage in doc.get("stages") or []],
        sources_total=doc.get("sources_total") or 0,
        sources_ok=doc.get("sources_ok") or 0,
        sources_error=doc.get("sources_error") or 0,
        postings_fetched=doc.get("postings_fetched") or 0,
        postings_normalized=doc.get("postings_normalized") or 0,
        postings_fresh=doc.get("postings_fresh") or 0,
        inserted=doc.get("inserted") or 0,
        updated=doc.get("updated") or 0,
        error=doc.get("error"),
    )


@router.get("/{posting_id}", response_model=PostingDetailResponse, **BY_FIELD_NAME)
async def get_posting_detail(posting_id: str, db=Depends(get_db)):
    """A single posting plus the active base resume and tailoring status,
    for the Job Details page."""
    # Two different 404s, and the client renders them differently. Every
    # ``_id`` is a sha256 digest (models.posting_id), so an id that isn't
    # one can never match anything — that's a stale/broken *link*, not a
    # missing posting, and it isn't worth a database round trip. The
    # row-index URLs the old Dashboard minted (/jobs/9, /jobs/0) land here
    # and used to come back as a bare "Posting not found: 9", which reads
    # like the pipeline dropped a posting it never had.
    if not POSTING_ID_RE.fullmatch(posting_id):
        raise HTTPException(
            status_code=404,
            detail=(
                f"'{posting_id}' is not a posting id, so this link is stale — "
                "posting ids are 64-character hex digests. Open the job from "
                "the dashboard again."
            ),
        )

    doc = await db.postings.find_one({"_id": posting_id})
    if not doc:
        raise HTTPException(
            status_code=404,
            detail=(
                f"Posting {posting_id} is no longer available — it may have "
                "been removed from the source ATS."
            ),
        )

    posting = Posting.model_validate(doc)

    active_resume = None
    latest_resume = await get_latest_resume(db)
    if latest_resume:
        parsed = latest_resume.get("parsed_data", {}) or {}
        active_resume = ActiveResumeInfo(
            resume_id=str(latest_resume["_id"]),
            cloudinary_url=latest_resume.get("cloudinary_url", ""),
            filename=latest_resume.get("filename", ""),
            name=parsed.get("name") or None,
            skills=parsed.get("skills", []) or [],
            processing_status=latest_resume.get("processing_status", "completed"),
        )

    tailor_session = await get_tailor_session_for_job(db, posting_id)
    if tailor_session:
        tailoring_status = TailoringStatus(
            tailored=True,
            resume_id=tailor_session.get("resume_id"),
            job_id=tailor_session.get("job_id"),
            download_urls=TailoringDownloadUrls(
                pdf=tailor_session.get("cloudinary_pdf_url") or None,
                docx=tailor_session.get("cloudinary_docx_url") or None,
                cover_letter_pdf=tailor_session.get("cloudinary_cover_letter_url") or None,
            ),
        )
    else:
        tailoring_status = TailoringStatus(tailored=False)

    return PostingDetailResponse(
        **posting.model_dump(by_alias=True),
        active_resume=active_resume,
        tailoring_status=tailoring_status,
    )
