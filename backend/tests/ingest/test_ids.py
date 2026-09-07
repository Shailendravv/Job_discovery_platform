"""Short-id display + prefix resolution (milestone 2, PLAN.md §3's
``## [a3f9c1] ...`` id shown in ``jobctl next`` output)."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.ingest.ids import FULL_ID_LENGTH, assign_short_ids, resolve_posting_id, short_id

FULL_ID_A = "a" * 63 + "1"
FULL_ID_B = "a" * 63 + "2"


def _mock_db(find_one_result=None, find_results=None):
    db = MagicMock()
    db.postings = MagicMock()
    db.postings.find_one = AsyncMock(return_value=find_one_result)

    cursor = MagicMock()
    cursor.limit.return_value = cursor
    cursor.to_list = AsyncMock(return_value=find_results or [])
    db.postings.find.return_value = cursor
    return db


def test_short_id_default_width():
    assert short_id(FULL_ID_A) == FULL_ID_A[:8]


def test_assign_short_ids_uses_default_width_when_unambiguous():
    result = assign_short_ids(["abc123def456", "111222333444"])
    assert result["abc123def456"] == "abc123de"
    assert result["111222333444"] == "11122233"


def test_assign_short_ids_widens_on_collision():
    ids = ["abcdefgh0001", "abcdefgh0002"]
    result = assign_short_ids(ids, width=8)
    assert len(set(result.values())) == 2
    for full_id, display in result.items():
        assert full_id.startswith(display)


def test_assign_short_ids_empty_input():
    assert assign_short_ids([]) == {}


@pytest.mark.asyncio
async def test_resolve_full_id_hit():
    doc = {"_id": FULL_ID_A}
    db = _mock_db(find_one_result=doc)
    result, error = await resolve_posting_id(db, FULL_ID_A)
    assert result == doc
    assert error is None


@pytest.mark.asyncio
async def test_resolve_full_id_miss():
    db = _mock_db(find_one_result=None)
    result, error = await resolve_posting_id(db, FULL_ID_A)
    assert result is None
    assert "unknown id" in error


@pytest.mark.asyncio
async def test_resolve_unique_prefix_hit():
    doc = {"_id": FULL_ID_A}
    db = _mock_db(find_results=[doc])
    result, error = await resolve_posting_id(db, "a1b2c3d4")
    assert result == doc
    assert error is None


@pytest.mark.asyncio
async def test_resolve_ambiguous_prefix_is_rejected():
    db = _mock_db(find_results=[{"_id": FULL_ID_A}, {"_id": FULL_ID_B}])
    result, error = await resolve_posting_id(db, "a1b2c3d4")
    assert result is None
    assert "ambiguous" in error


@pytest.mark.asyncio
async def test_resolve_unknown_prefix_is_rejected():
    db = _mock_db(find_results=[])
    result, error = await resolve_posting_id(db, "deadbeef")
    assert result is None
    assert "unknown id" in error


@pytest.mark.asyncio
async def test_resolve_rejects_non_hex_input():
    db = _mock_db()
    result, error = await resolve_posting_id(db, "not-hex!!")
    assert result is None
    assert "invalid id" in error
    db.postings.find_one.assert_not_called()
    db.postings.find.assert_not_called()


def test_full_id_length_matches_sha256_hex_digest():
    assert FULL_ID_LENGTH == 64
