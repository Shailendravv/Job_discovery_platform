"""``upsert_postings`` insert-only field handling. Milestone 1 already
protects ``judged``/``verdict`` from being reset by a re-ingest; milestone 3
adds ``prefiltered``/``prefilter_status``/``prefilter_reason`` to that same
protected set — a re-ingest of an already-classified posting must not
un-classify it back to ``prefiltered=False``, or ``jobctl next`` would keep
re-surfacing postings the prefilter already rejected."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from pymongo import UpdateOne

from app.ingest.models import Posting
from app.ingest.store import upsert_postings


def _posting(doc_id: str = "a" * 64) -> Posting:
    return Posting(
        _id=doc_id,
        provider="greenhouse",
        org="stripe",
        company_name="Stripe",
        title="Backend Engineer",
        title_normalized="backend engineer",
        url="https://example.com/job",
    )


def _mock_bulk_write_result(upserted=1, modified=0):
    result = MagicMock()
    result.upserted_count = upserted
    result.modified_count = modified
    return result


@pytest.mark.asyncio
async def test_prefilter_fields_are_insert_only_not_in_update_set():
    db = MagicMock()
    db.postings = MagicMock()
    db.postings.bulk_write = AsyncMock(return_value=_mock_bulk_write_result())

    await upsert_postings(db, [_posting()], "run1")

    ops: list[UpdateOne] = db.postings.bulk_write.await_args.args[0]
    op = ops[0]
    update_fields = op._doc["$set"]
    set_on_insert = op._doc["$setOnInsert"]

    assert "prefiltered" not in update_fields
    assert "prefilter_status" not in update_fields
    assert "prefilter_reason" not in update_fields
    assert set_on_insert["prefiltered"] is False
    assert set_on_insert["prefilter_status"] is None
