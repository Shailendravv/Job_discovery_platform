"""Normalized posting schema — one shape regardless of ATS provider.

See PLAN.md §2 "Normalization". ``posting_id()`` is the deterministic
primary key that makes re-ingestion idempotent — the whole point of
milestone 1's acceptance test (`jobctl ingest` twice → ~0 new rows).
"""

import hashlib
from datetime import datetime, timezone
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field


def posting_id(provider: str, org: str, provider_job_id: str) -> str:
    """Deterministic sha256 id: same (provider, org, provider_job_id) always
    hashes to the same id, so re-ingesting the same posting is an upsert,
    never a duplicate insert."""
    key = f"{provider}:{org}:{provider_job_id}"
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


class Posting(BaseModel):
    """One normalized job posting, regardless of source ATS."""

    id: str = Field(..., alias="_id")
    provider: str
    org: str
    company_name: str

    title: str
    title_normalized: str
    location: Optional[str] = None
    location_normalized: str = ""
    remote_flag: Optional[bool] = None
    employment_type: Optional[str] = None

    description_text: str = ""
    salary: Optional[str] = None

    url: str
    apply_url: Optional[str] = None

    posted_at: Optional[datetime] = None
    first_seen_at: Optional[datetime] = None
    last_seen_at: Optional[datetime] = None

    duplicate_of: Optional[str] = None
    tags: list[str] = Field(default_factory=list)

    # Original payload minus the description (kept small; description is
    # already in description_text). Debugging aid per PLAN.md §2.
    raw: dict[str, Any] = Field(default_factory=dict)

    # Judging lifecycle fields — populated starting milestone 2, present
    # here so the schema/indexes exist from the start.
    judged: bool = False
    verdict: Optional[str] = None

    # Prefilter lifecycle fields — milestone 3 (PLAN.md §4). Insert-only in
    # store.py, same as judged/verdict: a re-ingest must never un-classify
    # an already-prefiltered posting back to prefiltered=False.
    prefiltered: bool = False
    prefilter_status: Optional[str] = None
    prefilter_reason: Optional[str] = None

    model_config = ConfigDict(populate_by_name=True)


def normalize_text_key(value: Optional[str]) -> str:
    """Lowercase, collapse whitespace — used for the near-dup key and for
    title/location comparisons. Not meant for display."""
    if not value:
        return ""
    return " ".join(value.split()).lower()


def now_utc() -> datetime:
    return datetime.now(timezone.utc)
