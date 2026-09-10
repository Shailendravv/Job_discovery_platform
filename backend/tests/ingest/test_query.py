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
    list_postings_relaxed,
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


# ---- relaxed role search ----------------------------------------------

def test_role_tokens_take_precedence_over_role_query():
    """The relaxed search walks a ladder of pre-parsed token sets; it must
    be able to ask for one rung without re-serializing it back into a
    string and hoping the parser round-trips."""
    query = build_query(PostingFilter(role_query="ai fullstack developer",
                                      role_tokens=["developer"]))
    pattern = query["title_normalized"]["$regex"]

    assert "developer" in pattern
    assert "fullstack" not in pattern


def test_empty_role_tokens_add_no_clause():
    assert "title_normalized" not in build_query(PostingFilter(role_tokens=[]))


def _sequenced_db(results_per_call):
    """A db whose successive .find() calls return successive result sets --
    one per rung of the relaxation ladder."""
    db = MagicMock()
    db.postings = MagicMock()
    cursors = []
    for res in results_per_call:
        cursor = MagicMock()
        cursor.sort.return_value = cursor
        cursor.limit.return_value = cursor
        cursor.to_list = AsyncMock(return_value=res)
        cursors.append(cursor)
    db.postings.find.side_effect = cursors
    return db


@pytest.mark.asyncio
async def test_relaxed_search_returns_the_strictest_rung_that_matches():
    """The bug this fixes: "AI full stack developer" matched nothing, so
    the page showed 0 even though dropping the "ai" qualifier found real
    full-stack roles."""
    hits = [{"_id": "a"}, {"_id": "b"}]
    db = _sequenced_db([[], hits])

    result = await list_postings_relaxed(
        db, PostingFilter(role_query="AI full stack developer"), limit=200
    )

    assert result.postings == hits
    assert result.tokens == ["fullstack", "developer"]
    assert result.relaxed is True
    assert db.postings.find.call_count == 2


@pytest.mark.asyncio
async def test_relaxed_search_does_not_relax_when_the_exact_query_matches():
    hits = [{"_id": "a"}]
    db = _sequenced_db([hits])

    result = await list_postings_relaxed(
        db, PostingFilter(role_query="AI full stack developer"), limit=200
    )

    assert result.postings == hits
    assert result.relaxed is False
    assert result.tokens == ["ai", "fullstack", "developer"]
    db.postings.find.assert_called_once()


@pytest.mark.asyncio
async def test_relaxed_search_reports_empty_without_widening_past_the_last_rung():
    """A genuinely empty corpus must still come back empty -- relaxation
    stops at one token, it never degrades into an unfiltered read."""
    db = _sequenced_db([[], [], []])

    result = await list_postings_relaxed(
        db, PostingFilter(role_query="AI full stack developer"), limit=200
    )

    assert result.postings == []
    assert result.relaxed is False
    assert db.postings.find.call_count == 3


@pytest.mark.asyncio
async def test_relaxed_search_with_no_role_query_is_a_single_plain_read():
    docs = [{"_id": "a"}]
    db = _sequenced_db([docs])

    result = await list_postings_relaxed(db, PostingFilter(), limit=200)

    assert result.postings == docs
    assert result.relaxed is False
    assert result.tokens == []
    db.postings.find.assert_called_once()
