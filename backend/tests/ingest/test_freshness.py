"""The 24h discovery window: which timestamp it judges, what happens when a
provider gave us none, and how the window string is resolved."""

from datetime import datetime, timedelta, timezone

import pytest

from app.ingest.freshness import (
    DEFAULT_WINDOW,
    cutoff_for,
    effective_posted_at,
    is_fresh,
    resolve_window,
)

NOW = datetime(2026, 9, 8, 12, 0, 0, tzinfo=timezone.utc)


def _doc(posted_at=None, first_seen_at=None) -> dict:
    doc = {}
    if posted_at is not None:
        doc["posted_at"] = posted_at
    if first_seen_at is not None:
        doc["first_seen_at"] = first_seen_at
    return doc


# ---- resolve_window ---------------------------------------------------

def test_resolve_window_defaults_when_unset():
    """An unset window means "use the default", not "the caller erred"."""
    assert resolve_window(None) == DEFAULT_WINDOW
    assert resolve_window("") == DEFAULT_WINDOW
    assert DEFAULT_WINDOW == timedelta(hours=24)


@pytest.mark.parametrize("value,expected", [
    ("24h", timedelta(hours=24)),
    ("48h", timedelta(hours=48)),
    ("7d", timedelta(days=7)),
    ("30m", timedelta(minutes=30)),
])
def test_resolve_window_parses_durations(value, expected):
    assert resolve_window(value) == expected


def test_resolve_window_rejects_garbage():
    """A malformed window is a caller mistake and must not silently become
    the default -- callers surface this as a 4xx / CLI usage error."""
    with pytest.raises(ValueError):
        resolve_window("last tuesday")


# ---- effective_posted_at ----------------------------------------------

def test_prefers_posted_at_when_present():
    posted = NOW - timedelta(hours=2)
    seen = NOW - timedelta(hours=1)
    assert effective_posted_at(_doc(posted_at=posted, first_seen_at=seen)) == posted


def test_falls_back_to_first_seen_at():
    """store.py drops None values, so a posting whose provider supplied no
    date has no posted_at field at all -- Workday's "Posted 30+ Days Ago"
    and any provider parse failure land here."""
    seen = NOW - timedelta(hours=3)
    assert effective_posted_at(_doc(first_seen_at=seen)) == seen


def test_reattaches_utc_to_naive_datetimes():
    """Motor hands back naive UTC datetimes even though we write aware ones;
    comparing the two raises."""
    naive = datetime(2026, 9, 8, 9, 0, 0)
    assert effective_posted_at(_doc(posted_at=naive)).tzinfo is timezone.utc


def test_returns_none_when_there_is_no_date_at_all():
    assert effective_posted_at({}) is None


def test_accepts_an_object_not_just_a_dict():
    """The same rule has to apply pre-storage (a Posting) and post-storage
    (a Mongo dict), or the runner and the query would disagree."""
    class Stub:
        posted_at = NOW
        first_seen_at = None

    assert effective_posted_at(Stub()) == NOW


# ---- is_fresh ---------------------------------------------------------

def test_inside_the_window_is_fresh():
    assert is_fresh(_doc(posted_at=NOW - timedelta(hours=23)), now=NOW)


def test_outside_the_window_is_not_fresh():
    assert not is_fresh(_doc(posted_at=NOW - timedelta(hours=25)), now=NOW)


def test_boundary_is_inclusive():
    assert is_fresh(_doc(posted_at=NOW - timedelta(hours=24)), now=NOW)


def test_a_widened_window_admits_older_postings():
    doc = _doc(posted_at=NOW - timedelta(days=3))
    assert not is_fresh(doc, now=NOW)
    assert is_fresh(doc, window=timedelta(days=7), now=NOW)


def test_stale_posted_at_is_not_rescued_by_a_recent_first_seen_at():
    """The fallback is for a *missing* date, not a second chance -- a posting
    the provider says is a month old stays out however recently we saw it."""
    doc = _doc(posted_at=NOW - timedelta(days=30), first_seen_at=NOW)
    assert not is_fresh(doc, now=NOW)


def test_dateless_posting_is_never_fresh():
    """We cannot show a posting under a "posted in the last 24 hours"
    promise without evidence that it was."""
    assert not is_fresh({}, now=NOW)


# ---- cutoff_for -------------------------------------------------------

def test_cutoff_is_the_instant_providers_filter_against():
    assert cutoff_for(timedelta(hours=24), now=NOW) == NOW - timedelta(hours=24)
