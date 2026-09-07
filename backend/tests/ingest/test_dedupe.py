"""Near-duplicate detection (PLAN.md §2): same org + normalized title +
location within 30 days -> mark ``duplicate_of``."""

from datetime import datetime, timedelta, timezone

from app.ingest.dedupe import DedupeIndex, apply_dedupe, dedupe_key
from app.ingest.models import Posting

NOW = datetime(2026, 9, 7, tzinfo=timezone.utc)


def _posting(doc_id: str, org: str, title: str, location: str = "remote", first_seen=None) -> Posting:
    return Posting(
        _id=doc_id,
        provider="greenhouse",
        org=org,
        company_name=org,
        title=title,
        title_normalized=title.lower(),
        location=location,
        location_normalized=location.lower(),
        url=f"https://example.com/{doc_id}",
        first_seen_at=first_seen or NOW,
    )


def test_no_duplicates_when_index_is_empty():
    postings = [_posting("a", "stripe", "Backend Engineer")]
    index = DedupeIndex()
    marked = apply_dedupe(postings, index, now=NOW)
    assert marked == 0
    assert postings[0].duplicate_of is None


def test_marks_duplicate_within_window_against_existing_doc():
    existing_docs = [{
        "_id": "old-id",
        "org": "stripe",
        "title_normalized": "backend engineer",
        "location_normalized": "remote",
        "first_seen_at": NOW - timedelta(days=10),
    }]
    index = DedupeIndex.from_existing_docs(existing_docs)

    postings = [_posting("new-id", "stripe", "Backend Engineer")]
    marked = apply_dedupe(postings, index, now=NOW)

    assert marked == 1
    assert postings[0].duplicate_of == "old-id"


def test_does_not_mark_duplicate_outside_window():
    existing_docs = [{
        "_id": "old-id",
        "org": "stripe",
        "title_normalized": "backend engineer",
        "location_normalized": "remote",
        "first_seen_at": NOW - timedelta(days=45),  # outside the 30-day window
    }]
    index = DedupeIndex.from_existing_docs(existing_docs)

    postings = [_posting("new-id", "stripe", "Backend Engineer")]
    marked = apply_dedupe(postings, index, now=NOW)

    assert marked == 0
    assert postings[0].duplicate_of is None


def test_different_org_is_not_a_duplicate():
    existing_docs = [{
        "_id": "old-id",
        "org": "airbnb",
        "title_normalized": "backend engineer",
        "location_normalized": "remote",
        "first_seen_at": NOW - timedelta(days=5),
    }]
    index = DedupeIndex.from_existing_docs(existing_docs)

    postings = [_posting("new-id", "stripe", "Backend Engineer")]
    marked = apply_dedupe(postings, index, now=NOW)

    assert marked == 0


def test_within_batch_duplicates_are_caught():
    """Two postings in the SAME ingest run with the same near-dup key —
    e.g. a company re-opening a requisition under a new provider_job_id
    on the same day — should also be caught, not just cross-run ones."""
    index = DedupeIndex()
    first = _posting("id-1", "stripe", "Backend Engineer", first_seen=NOW)
    second = _posting("id-2", "stripe", "Backend Engineer", first_seen=NOW)

    marked = apply_dedupe([first, second], index, now=NOW)

    assert marked == 1
    assert first.duplicate_of is None
    assert second.duplicate_of == "id-1"


def test_reingesting_the_same_posting_is_not_flagged_as_duplicate_of_itself():
    """A posting being re-ingested (same _id as its own earlier record)
    must never point duplicate_of at itself."""
    existing_docs = [{
        "_id": "same-id",
        "org": "stripe",
        "title_normalized": "backend engineer",
        "location_normalized": "remote",
        "first_seen_at": NOW - timedelta(days=2),
    }]
    index = DedupeIndex.from_existing_docs(existing_docs)

    postings = [_posting("same-id", "stripe", "Backend Engineer")]
    marked = apply_dedupe(postings, index, now=NOW)

    assert marked == 0
    assert postings[0].duplicate_of is None


def test_naive_datetime_from_db_does_not_crash():
    """Motor/PyMongo returns naive UTC datetimes on read even though we
    write tz-aware ones — from_existing_docs must reattach tzinfo rather
    than blow up on aware-vs-naive subtraction."""
    naive_first_seen = datetime(2026, 8, 28)  # no tzinfo, like a Mongo read
    existing_docs = [{
        "_id": "old-id",
        "org": "stripe",
        "title_normalized": "backend engineer",
        "location_normalized": "remote",
        "first_seen_at": naive_first_seen,
    }]
    index = DedupeIndex.from_existing_docs(existing_docs)

    postings = [_posting("new-id", "stripe", "Backend Engineer")]
    marked = apply_dedupe(postings, index, now=NOW)  # must not raise

    assert marked == 1


def test_dedupe_key_shape():
    assert dedupe_key("stripe", "backend engineer", "remote") == ("stripe", "backend engineer", "remote")
