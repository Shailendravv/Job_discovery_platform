"""Shared query building for ``jobctl list``/``jobctl next`` (milestone 2,
PLAN.md §3). Both commands read the same ``postings`` collection with the
same shape of filter — ``next`` is just ``list`` pinned to
``unjudged=True``, sorted oldest-first, with duplicates excluded.

Why ``next`` needs no offset/cursor: judging a batch via ``jobctl judge
--apply`` flips ``judged`` to ``True`` on every accepted verdict, so the
next ``jobctl next`` call naturally excludes them and returns the following
batch. "Loop until it returns empty" (PLAN.md §5) falls out of that for
free — no pagination state to track between calls.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

from motor.motor_asyncio import AsyncIOMotorDatabase

DEFAULT_LIST_LIMIT = 40
DEFAULT_NEXT_LIMIT = 25


@dataclass
class PostingFilter:
    judged: Optional[bool] = None       # None = don't filter on judged state
    verdict: Optional[str] = None
    provider: Optional[str] = None
    org: Optional[str] = None
    since: Optional[timedelta] = None   # first_seen_at >= now - since
    include_duplicates: bool = False    # duplicate_of postings are excluded by default


def build_query(filters: PostingFilter, *, now: Optional[datetime] = None) -> dict:
    query: dict = {}

    if filters.judged is not None:
        query["judged"] = filters.judged
    if filters.verdict is not None:
        query["verdict"] = filters.verdict
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
    """The agent's judging queue: unjudged, non-duplicate postings, oldest
    first (FIFO) so nothing waits forever behind a stream of fresher ones."""
    filters = PostingFilter(judged=False)
    return await list_postings(db, filters, limit=limit, sort_field="first_seen_at", sort_direction=1)
