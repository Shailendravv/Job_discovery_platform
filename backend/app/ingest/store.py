"""Bulk upsert normalized postings into the ``postings`` collection.

The ``(inserted, updated)`` counts this returns are the milestone 1 gate:
a second ``jobctl ingest`` run over the same data must return
``inserted == 0``.
"""

import logging
from dataclasses import dataclass
from datetime import datetime, timezone

from motor.motor_asyncio import AsyncIOMotorDatabase
from pymongo import UpdateOne
from pymongo.errors import BulkWriteError

from app.ingest.models import Posting

log = logging.getLogger(__name__)

# Fields set only when a document is first created — re-ingesting an
# already-judged posting must never clobber the verdict milestone 2 writes,
# and (milestone 3) must never un-classify an already-prefiltered posting.
_INSERT_ONLY_DEFAULTS = {
    "judged": False, "verdict": None,
    "prefiltered": False, "prefilter_status": None, "prefilter_reason": None,
}


@dataclass
class StoreResult:
    inserted: int = 0
    updated: int = 0
    skipped: int = 0
    write_errors: list[dict] = None  # type: ignore[assignment]

    def __post_init__(self):
        if self.write_errors is None:
            self.write_errors = []


async def upsert_postings(db: AsyncIOMotorDatabase, postings: list[Posting], run_id: str) -> StoreResult:
    if not postings:
        return StoreResult()

    now = datetime.now(timezone.utc)
    operations: list[UpdateOne] = []

    for posting in postings:
        doc = posting.model_dump(by_alias=True, exclude={"first_seen_at", "last_seen_at"})
        doc_id = doc.pop("_id")
        # Never let a re-ingest touch judging or prefilter state — those are
        # jobctl judge's / jobctl prefilter run's job, not ingest's.
        for field_name in _INSERT_ONLY_DEFAULTS:
            doc.pop(field_name, None)

        update_fields = {k: v for k, v in doc.items() if v is not None or k == "duplicate_of"}
        update_fields["last_seen_at"] = now

        set_on_insert = {
            "_id": doc_id,
            "first_seen_at": now,
            "created_at": now,
            **_INSERT_ONLY_DEFAULTS,
        }

        operations.append(UpdateOne(
            {"_id": doc_id},
            {
                "$set": update_fields,
                "$setOnInsert": set_on_insert,
                "$addToSet": {"ingest_run_ids": run_id},
            },
            upsert=True,
        ))

    result = StoreResult()
    try:
        bulk_result = await db.postings.bulk_write(operations, ordered=False)
        result.inserted = bulk_result.upserted_count
        result.updated = bulk_result.modified_count
    except BulkWriteError as e:
        # Unordered bulk_write already applied every valid operation before
        # raising — one bad document (e.g. a length-capped field a provider
        # slipped past normalize.py) must not make the whole run look like
        # it inserted nothing. Recover the partial counts and surface the
        # per-document failures for visibility instead of crashing the run.
        details = e.details or {}
        result.inserted = details.get("nUpserted", 0)
        result.updated = details.get("nModified", 0)
        result.write_errors = [
            {"index": err.get("index"), "code": err.get("code"), "errmsg": err.get("errmsg")}
            for err in details.get("writeErrors", [])
        ]
        log.error(
            "[ingest] bulk_write had %d error(s) out of %d ops — %d inserted, %d updated anyway",
            len(result.write_errors), len(operations), result.inserted, result.updated,
        )
    except Exception as e:
        log.error("[ingest] bulk_write failed: %s", e, exc_info=True)
        raise

    return result
