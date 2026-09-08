import logging
import re
from datetime import timedelta

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query

from app.api.deps import get_db
from app.core.database import get_database
from app.ingest.models import Posting
from app.ingest.query import (
    DEFAULT_SHORTLIST_LIMIT,
    DEFAULT_SHORTLIST_MIN_SCORE,
    PostingFilter,
    ShortlistFilter,
    list_postings,
    shortlist_postings,
)
from app.ingest.runner import run_ingest
from app.models.posting import (
    ActiveResumeInfo,
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
    db=Depends(get_db),
):
    """The 200-latest read the frontend polls: most recent postings that
    cleared the prefilter, newest first, excluding near-duplicates."""
    filters = PostingFilter(
        provider=provider,
        org=org,
        prefilter_status=prefilter_status or None,
        since=timedelta(days=since_days),
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
async def trigger_ingest(background_tasks: BackgroundTasks):
    """Kick off an ATS ingest run in the background and return immediately.

    Mirrors ``jobctl ingest`` (app/ingest/runner.run_ingest) — never runs
    inline on the request, unlike the old /search endpoint, which is
    exactly what made that endpoint hang for hours. Poll ingest_runs (or
    GET /api/v1/postings once it lands) for progress."""
    import uuid

    run_id = uuid.uuid4().hex[:12]

    async def _run():
        db = get_database()
        try:
            result = await run_ingest(db, run_id=run_id)
            log.info(
                "[ingest:background] run_id=%s sources_ok=%d sources_error=%d inserted=%d updated=%d",
                run_id, result.sources_ok, result.sources_error, result.inserted, result.updated,
            )
        except Exception:
            log.exception("[ingest:background] run_id=%s failed", run_id)

    background_tasks.add_task(_run)
    return IngestTriggerResponse(run_id=run_id, status="started")


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
