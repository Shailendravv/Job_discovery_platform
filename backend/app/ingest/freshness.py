"""Recency rules for the Job Discovery session — "only jobs posted in the
last 24 hours".

Deterministic and cheap on purpose: this is a datetime comparison, nothing
more. No LLM, no heuristics beyond the documented ``posted_at`` ->
``first_seen_at`` fallback.

Why the fallback exists: ``posted_at`` is whatever the upstream ATS gave us
and its quality varies by provider (see ``backend/docs/ingest.md``).

- Real timestamps: lever (``createdAt``), ashby (``publishedAt``),
  greenhouse (``first_published``), smartrecruiters (``releasedDate``),
  recruitee (``published_at``).
- Day-granularity only: workable (``published_on`` is ``YYYY-MM-DD``, parsed
  to midnight UTC), so a 24h window there is really a 1-2 calendar-day window.
- Relative English label: workday (``postedOn`` = "Posted Today" / "Posted 5
  Days Ago"), reconstructed by subtracting whole days at fetch time and
  ``None`` for "Posted 30+ Days Ago".

``store.py`` drops ``None`` values from its ``$set``, so a posting whose
provider supplied no date has no ``posted_at`` field at all. Rather than make
those invisible, we fall back to ``first_seen_at`` — the moment ingestion
first saw the posting, which for a genuinely new posting is a good proxy and
for an old one is safely in the past.
"""

from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from app.ingest.time_util import parse_duration

# The window a Discovery session uses when the caller names none.
DEFAULT_WINDOW = timedelta(hours=24)


def resolve_window(value: Optional[str], *, default: timedelta = DEFAULT_WINDOW) -> timedelta:
    """Turn a ``"24h"``/``"48h"``/``"7d"`` string into a ``timedelta``.

    ``None``/empty falls back to ``default`` rather than raising — an unset
    window means "use the default", not "the caller made a mistake". A
    *malformed* string still raises ``ValueError`` from ``parse_duration``,
    which callers surface as a 4xx / CLI usage error.
    """
    if not value:
        return default
    return parse_duration(value)


def _as_aware(value: Any) -> Optional[datetime]:
    """Coerce a Mongo-read datetime to tz-aware UTC, or None.

    Motor/PyMongo hands back naive UTC datetimes even though we write
    tz-aware ones, and comparing the two raises — the same trap
    ``dedupe.py::DedupeIndex.from_existing_docs`` already handles.
    """
    if not isinstance(value, datetime):
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def effective_posted_at(doc: Any) -> Optional[datetime]:
    """The timestamp freshness is judged against: ``posted_at`` when the
    provider supplied a parseable one, otherwise ``first_seen_at``.

    Accepts either a raw Mongo dict or anything with the two attributes (a
    ``Posting``), so the same rule applies before and after storage.
    """
    if isinstance(doc, dict):
        posted_at, first_seen_at = doc.get("posted_at"), doc.get("first_seen_at")
    else:
        posted_at = getattr(doc, "posted_at", None)
        first_seen_at = getattr(doc, "first_seen_at", None)

    return _as_aware(posted_at) or _as_aware(first_seen_at)


def is_fresh(
    doc: Any,
    *,
    window: timedelta = DEFAULT_WINDOW,
    now: Optional[datetime] = None,
) -> bool:
    """True if the posting's effective date falls inside ``window``.

    A posting with no usable date at all (neither ``posted_at`` nor
    ``first_seen_at`` — only possible pre-storage) is **not** fresh: we
    cannot show it under a "posted in the last 24 hours" promise without
    evidence that it was.
    """
    effective = effective_posted_at(doc)
    if effective is None:
        return False
    reference = now or datetime.now(timezone.utc)
    return effective >= reference - window


def cutoff_for(window: timedelta, *, now: Optional[datetime] = None) -> datetime:
    """The absolute instant a posting must be at or after to count as fresh.

    Providers take this (as ``posted_since``) to skip per-job description
    fetches for postings that cannot make the window — the single biggest
    time saving available to a Discovery run.
    """
    return (now or datetime.now(timezone.utc)) - window
