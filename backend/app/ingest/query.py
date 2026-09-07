"""Shared query building for ``jobctl list``/``jobctl next`` (milestone 2,
PLAN.md §3). Both commands read the same ``postings`` collection with the
same shape of filter — ``next`` is just ``list`` pinned to
``unjudged=True``, sorted oldest-first, with duplicates excluded.

Why ``next`` needs no offset/cursor: judging a batch via ``jobctl judge
--apply`` flips ``judged`` to ``True`` on every accepted verdict, so the
next ``jobctl next`` call naturally excludes them and returns the following
batch. "Loop until it returns empty" (PLAN.md §5) falls out of that for
free — no pagination state to track between calls.

``shortlist_postings`` (milestone 4, PLAN.md §3 ``jobctl shortlist``) is a
different shape of query: score lives on the ``verdicts`` document, not on
``postings`` (PLAN.md §3's own "Why" note in judging.md), so it starts from
``verdicts`` and ``$lookup``s the posting rather than filtering
``postings`` directly.
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Optional

from motor.motor_asyncio import AsyncIOMotorDatabase

DEFAULT_LIST_LIMIT = 40
DEFAULT_NEXT_LIMIT = 25
DEFAULT_SHORTLIST_LIMIT = 50
DEFAULT_SHORTLIST_MIN_SCORE = 7


@dataclass
class PostingFilter:
    judged: Optional[bool] = None       # None = don't filter on judged state
    verdict: Optional[str] = None
    provider: Optional[str] = None
    org: Optional[str] = None
    since: Optional[timedelta] = None   # first_seen_at >= now - since
    include_duplicates: bool = False    # duplicate_of postings are excluded by default
    prefilter_status: Optional[str] = None  # None = don't filter on prefilter outcome (milestone 3)


def build_query(filters: PostingFilter, *, now: Optional[datetime] = None) -> dict:
    query: dict = {}

    if filters.judged is not None:
        query["judged"] = filters.judged
    if filters.verdict is not None:
        query["verdict"] = filters.verdict
    if filters.prefilter_status is not None:
        query["prefilter_status"] = filters.prefilter_status
    if filters.provider is not None:
        query["provider"] = filters.provider
    if filters.org is not None:
        query["org"] = filters.org
    if filters.since is not None:
        reference = now or datetime.now(timezone.utc)
        query["first_seen_at"] = {"$gte": reference - filters.since}
    if not filters.include_duplicates:
        query["duplicate_of"] = None

    return query


async def list_postings(
    db: AsyncIOMotorDatabase,
    filters: PostingFilter,
    *,
    limit: int,
    sort_field: str = "first_seen_at",
    sort_direction: int = -1,
) -> list[dict]:
    query = build_query(filters)
    cursor = db.postings.find(query).sort(sort_field, sort_direction).limit(limit)
    return await cursor.to_list(length=limit)


async def next_postings(db: AsyncIOMotorDatabase, *, limit: int = DEFAULT_NEXT_LIMIT) -> list[dict]:
    """The agent's judging queue: unjudged, non-duplicate postings that
    cleared the milestone-3 prefilter (``prefilter_status="passed"``),
    oldest first (FIFO) so nothing waits forever behind a stream of fresher
    ones. A posting not yet prefiltered (``prefiltered=False``) is excluded
    until ``jobctl prefilter run`` classifies it -- ingest runs that
    automatically, so this is only a concern for postings that predate
    milestone 3."""
    filters = PostingFilter(judged=False, prefilter_status="passed")
    return await list_postings(db, filters, limit=limit, sort_field="first_seen_at", sort_direction=1)


@dataclass
class ShortlistFilter:
    min_score: int = DEFAULT_SHORTLIST_MIN_SCORE
    since: Optional[timedelta] = None          # judged_at >= now - since
    verdicts: tuple[str, ...] = field(default_factory=lambda: ("apply", "maybe"))


def build_shortlist_match(filters: ShortlistFilter, *, now: Optional[datetime] = None) -> dict:
    match: dict = {
        "score": {"$gte": filters.min_score},
        "verdict": {"$in": list(filters.verdicts)},
    }
    if filters.since is not None:
        reference = now or datetime.now(timezone.utc)
        match["judged_at"] = {"$gte": reference - filters.since}
    return match


async def shortlist_postings(
    db: AsyncIOMotorDatabase,
    filters: ShortlistFilter,
    *,
    limit: int = DEFAULT_SHORTLIST_LIMIT,
) -> list[dict]:
    """Judged postings worth applying to: score >= min_score, verdict in
    (apply, maybe) — a ``skip`` never belongs on a shortlist regardless of
    score, per PLAN.md §4's rubric ("skip — hard filter hit, or the gap is
    disqualifying"). Joins ``verdicts`` (where score lives) to ``postings``
    (where the rest of the display fields live) on their shared ``_id``
    (``apply_verdicts`` writes both under the same resolved posting id).
    Highest score first, near-duplicate postings excluded. The duplicate
    filter runs (and ``$sort``/``$limit`` apply) *after* the join, not
    before — ``duplicate_of`` only exists on the joined posting, and
    limiting before filtering it out could silently return fewer than
    ``limit`` results even when more eligible entries exist further down
    the score order."""
    pipeline = [
        {"$match": build_shortlist_match(filters)},
        {
            "$lookup": {
                "from": "postings",
                "localField": "_id",
                "foreignField": "_id",
                "as": "posting",
            }
        },
        {"$unwind": "$posting"},
        {"$match": {"posting.duplicate_of": None}},
        {"$sort": {"score": -1, "judged_at": -1}},
        {"$limit": limit},
    ]
    cursor = db.verdicts.aggregate(pipeline)
    return await cursor.to_list(length=limit)
