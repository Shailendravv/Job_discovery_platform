"""Near-duplicate detection — PLAN.md §2:

"Near-duplicate check: same org + normalized title + location within 30
days -> mark ``duplicate_of``."

This catches the same role re-posted under a fresh ``provider_job_id``
(companies often close and re-open a requisition), which the deterministic
``posting_id`` alone cannot catch since that id is keyed on provider_job_id.

Two passes are combined into one index so cross-run and within-run
duplicates are both caught with a single DB read per ingest run rather than
one query per posting:

1. ``existing_index`` — built once from a DB query, covers postings from
   earlier runs.
2. As each new ``Posting`` in the current batch is confirmed canonical (not
   itself a duplicate), it's added to the same index — catching duplicates
   introduced within this very run.
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from app.ingest.models import Posting

DEDUPE_WINDOW = timedelta(days=30)

DedupeKey = tuple[str, str, str]  # (org, title_normalized, location_normalized)


def dedupe_key(org: str, title_normalized: str, location_normalized: str) -> DedupeKey:
    return (org, title_normalized, location_normalized)


@dataclass
class DedupeIndex:
    """key -> list of (id, first_seen_at) seen so far, earliest-registered
    entry per key acts as the canonical id new duplicates point to."""

    _entries: dict[DedupeKey, list[tuple[str, datetime]]] = field(default_factory=dict)

    @classmethod
    def from_existing_docs(cls, docs: list[dict]) -> "DedupeIndex":
        idx = cls()
        for doc in docs:
            key = dedupe_key(
                doc.get("org", ""),
                doc.get("title_normalized", ""),
                doc.get("location_normalized", ""),
            )
            first_seen = doc.get("first_seen_at")
            doc_id = doc.get("_id")
            if doc_id and isinstance(first_seen, datetime):
                # Motor/PyMongo returns naive UTC datetimes on read even
                # though we write tz-aware ones — reattach tzinfo so the
                # subtraction in find_canonical() doesn't blow up.
                if first_seen.tzinfo is None:
                    first_seen = first_seen.replace(tzinfo=timezone.utc)
                idx._entries.setdefault(key, []).append((doc_id, first_seen))
        return idx

    def find_canonical(self, key: DedupeKey, reference_time: datetime) -> str | None:
        """Return the id of the earliest entry for ``key`` within the
        dedupe window of ``reference_time``, or None if no match."""
        candidates = self._entries.get(key)
        if not candidates:
            return None
        in_window = [
            (doc_id, seen) for doc_id, seen in candidates
            if abs(reference_time - seen) <= DEDUPE_WINDOW
        ]
        if not in_window:
            return None
        in_window.sort(key=lambda pair: pair[1])
        return in_window[0][0]

    def register(self, key: DedupeKey, doc_id: str, first_seen_at: datetime) -> None:
        self._entries.setdefault(key, []).append((doc_id, first_seen_at))


def apply_dedupe(postings: list[Posting], existing_index: DedupeIndex, now: datetime | None = None) -> int:
    """Mutates ``postings`` in place, setting ``duplicate_of`` where a
    near-duplicate is found. Returns the count marked as duplicates.

    Postings that are themselves already-seen (i.e. this is a re-ingest of
    the exact same provider_job_id) are skipped — that's an idempotent
    upsert, not a near-duplicate, and is handled by ``store.py`` instead.
    """
    reference_time = now or datetime.now(timezone.utc)
    duplicate_count = 0

    for posting in postings:
        key = dedupe_key(posting.org, posting.title_normalized, posting.location_normalized)
        canonical_id = existing_index.find_canonical(key, reference_time)

        if canonical_id and canonical_id != posting.id:
            posting.duplicate_of = canonical_id
            duplicate_count += 1
        else:
            # This posting is canonical (or is the existing canonical
            # itself, re-ingested) — register it so later postings in this
            # batch can point at it.
            existing_index.register(key, posting.id, posting.first_seen_at or reference_time)

    return duplicate_count
