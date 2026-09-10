"""``PostingFilter``/``list_postings``/``next_postings`` — milestone 2's
shared query layer behind ``jobctl list`` and ``jobctl next``."""

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.ingest.query import (
    DEFAULT_NEXT_LIMIT,
    DEFAULT_SHORTLIST_LIMIT,
    PostingFilter,
    ShortlistFilter,
    build_query,
    build_shortlist_match,
    list_postings,
    next_postings,
    shortlist_postings,
)

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


# ---- Job Discovery filters --------------------------------------------

def test_posted_since_matches_posted_at_or_falls_back_to_first_seen_at():
    """store.py drops None values, so a posting whose provider gave no date
    has no posted_at *field*. Mongo's {"posted_at": None} matches both
    missing and explicitly-null, which is exactly the fallback wanted."""
    query = build_query(PostingFilter(posted_since=timedelta(hours=24)), now=NOW)
    cutoff = NOW - timedelta(hours=24)

    assert query["$or"] == [
        {"posted_at": {"$gte": cutoff}},
        {"posted_at": None, "first_seen_at": {"$gte": cutoff}},
    ]


def test_posted_since_is_independent_of_since():
    """They answer different questions -- when it was *posted* vs when we
    first *saw* it -- and the Discovery read sends both."""
    query = build_query(
        PostingFilter(since=timedelta(days=14), posted_since=timedelta(hours=24)), now=NOW
    )

    assert query["first_seen_at"] == {"$gte": NOW - timedelta(days=14)}
    assert query["$or"][0]["posted_at"] == {"$gte": NOW - timedelta(hours=24)}


def test_no_posted_since_leaves_the_query_untouched():
    """The Dashboard read must keep its existing behaviour."""
    assert "$or" not in build_query(PostingFilter(since=timedelta(days=14)), now=NOW)


def test_role_query_becomes_a_title_regex():
    query = build_query(PostingFilter(role_query="backend engineer"))
    pattern = query["title_normalized"]["$regex"]

    assert "backend" in pattern
    assert "engineer" in pattern
    # title_normalized is already lowercase, so no case-insensitivity flag --
    # and a regex without it can use the index migration 016 adds.
    assert "$options" not in query["title_normalized"]


def test_empty_role_query_adds_no_clause():
    """"No role filter" must not become "match nothing" -- that is the
    difference between showing everything and showing zero results."""
    assert "title_normalized" not in build_query(PostingFilter(role_query=""))
    assert "title_normalized" not in build_query(PostingFilter(role_query="the a of"))
    assert "title_normalized" not in build_query(PostingFilter(role_query=None))


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
    db.postings.find.assert_called_once_with(
        {"judged": False, "duplicate_of": None, "prefilter_status": "passed"}
    )
    cursor.sort.assert_called_once_with("first_seen_at", 1)
    cursor.limit.assert_called_once_with(DEFAULT_NEXT_LIMIT)


def test_next_postings_only_serves_prefilter_passed():
    query = build_query(PostingFilter(judged=False, prefilter_status="passed"))
    assert query["prefilter_status"] == "passed"


# --- shortlist (milestone 4, PLAN.md §3 `jobctl shortlist`) ---


def test_shortlist_match_defaults_to_apply_and_maybe_at_min_score():
    match = build_shortlist_match(ShortlistFilter())
    assert match["score"] == {"$gte": 7}
    assert match["verdict"] == {"$in": ["apply", "maybe"]}
    assert "judged_at" not in match


def test_shortlist_match_applies_since_window():
    match = build_shortlist_match(ShortlistFilter(since=timedelta(hours=24)), now=NOW)
    assert match["judged_at"] == {"$gte": NOW - timedelta(hours=24)}


def test_shortlist_match_custom_min_score():
    match = build_shortlist_match(ShortlistFilter(min_score=9))
    assert match["score"] == {"$gte": 9}


def _mock_aggregate_db(results):
    db = MagicMock()
    db.verdicts = MagicMock()
    cursor = MagicMock()
    cursor.to_list = AsyncMock(return_value=results)
    db.verdicts.aggregate.return_value = cursor
    return db, cursor


@pytest.mark.asyncio
async def test_shortlist_postings_builds_lookup_pipeline_and_returns_joined_docs():
    joined = [{"_id": "a" * 64, "score": 9, "verdict": "apply", "posting": {"title": "Backend Engineer"}}]
    db, cursor = _mock_aggregate_db(joined)

    result = await shortlist_postings(db, ShortlistFilter())

    assert result == joined
    pipeline = db.verdicts.aggregate.call_args.args[0]
    assert pipeline[0] == {"$match": build_shortlist_match(ShortlistFilter())}
    assert pipeline[2] == {"$unwind": "$posting"}
    # Duplicate filter, sort, and limit all run *after* the join — limiting
    # before filtering out duplicates could silently drop eligible results.
    assert pipeline[3] == {"$match": {"posting.duplicate_of": None}}
    assert pipeline[-1] == {"$limit": DEFAULT_SHORTLIST_LIMIT}
    cursor.to_list.assert_awaited_once_with(length=DEFAULT_SHORTLIST_LIMIT)


@pytest.mark.asyncio
async def test_shortlist_postings_empty_when_nothing_clears_the_bar():
    db, _ = _mock_aggregate_db([])
    result = await shortlist_postings(db, ShortlistFilter(min_score=10))
    assert result == []
