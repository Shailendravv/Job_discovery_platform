"""``PostingFilter``/``list_postings``/``next_postings`` — milestone 2's
shared query layer behind ``jobctl list`` and ``jobctl next``."""

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.ingest.query import DEFAULT_NEXT_LIMIT, PostingFilter, build_query, list_postings, next_postings

NOW = datetime(2026, 9, 7, tzinfo=timezone.utc)


def test_empty_filter_excludes_duplicates_only():
    assert build_query(PostingFilter()) == {"duplicate_of": None}


def test_include_duplicates_drops_the_default_exclusion():
    assert build_query(PostingFilter(include_duplicates=True)) == {}


def test_judged_false_is_distinguished_from_unset():
    assert build_query(PostingFilter(judged=False))["judged"] is False
    assert "judged" not in build_query(PostingFilter(judged=None))


def test_verdict_provider_org_filters():
    query = build_query(PostingFilter(verdict="apply", provider="greenhouse", org="stripe"))
    assert query["verdict"] == "apply"
    assert query["provider"] == "greenhouse"
    assert query["org"] == "stripe"


def test_since_produces_a_gte_window():
    query = build_query(PostingFilter(since=timedelta(hours=24)), now=NOW)
    assert query["first_seen_at"] == {"$gte": NOW - timedelta(hours=24)}


def _mock_db(find_results):
    db = MagicMock()
    db.postings = MagicMock()
    cursor = MagicMock()
    cursor.sort.return_value = cursor
    cursor.limit.return_value = cursor
    cursor.to_list = AsyncMock(return_value=find_results)
    db.postings.find.return_value = cursor
    return db, cursor


@pytest.mark.asyncio
async def test_list_postings_sorts_desc_by_default():
    docs = [{"_id": "a"}]
    db, cursor = _mock_db(docs)

    result = await list_postings(db, PostingFilter(), limit=40)

    assert result == docs
    cursor.sort.assert_called_once_with("first_seen_at", -1)
    cursor.limit.assert_called_once_with(40)


@pytest.mark.asyncio
async def test_next_postings_is_unjudged_ascending_fifo():
    docs = [{"_id": "old"}, {"_id": "new"}]
    db, cursor = _mock_db(docs)

    result = await next_postings(db, limit=DEFAULT_NEXT_LIMIT)

    assert result == docs
    db.postings.find.assert_called_once_with({"judged": False, "duplicate_of": None})
    cursor.sort.assert_called_once_with("first_seen_at", 1)
    cursor.limit.assert_called_once_with(DEFAULT_NEXT_LIMIT)
