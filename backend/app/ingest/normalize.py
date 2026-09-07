"""RawPosting (provider-shaped) + Source -> Posting (normalized, PLAN.md §2)."""

import logging

from app.agents.ats_providers.base import RawPosting
from app.ingest.models import Posting, normalize_text_key, posting_id
from app.ingest.registry import Source

log = logging.getLogger(__name__)

# Vocabulary normalization for employment_type — providers use different
# casings/phrasings ("Full-time", "FULLTIME", "full_time").
_EMPLOYMENT_TYPE_MAP = {
    "fulltime": "full-time",
    "full time": "full-time",
    "full-time": "full-time",
    "parttime": "part-time",
    "part time": "part-time",
    "part-time": "part-time",
    "contract": "contract",
    "contractor": "contract",
    "intern": "internship",
    "internship": "internship",
    "temporary": "temporary",
    "freelance": "freelance",
}


def _normalize_employment_type(value: str | None) -> str | None:
    if not value:
        return None
    key = value.strip().lower().replace("_", " ")
    return _EMPLOYMENT_TYPE_MAP.get(key, value.strip() or None)


# Match the $jsonSchema caps in migrations/012_add_postings_collection.py —
# Ashby in particular can fold in many secondary office locations
# (see ashby.py::_format_location) and blow well past a "normal" length.
_TITLE_MAX = 300
_COMPANY_NAME_MAX = 200
_LOCATION_MAX = 500


def _truncate(value: str, max_len: int) -> str:
    return value if len(value) <= max_len else value[: max_len - 1].rstrip() + "…"


def normalize_posting(raw: RawPosting, source: Source) -> Posting | None:
    """Convert one provider's ``RawPosting`` into a ``Posting``.

    Returns None if required fields (id, title, url) are missing — the
    caller counts these as skipped, not errored.
    """
    provider_job_id = raw.get("provider_job_id")
    title = (raw.get("title") or "").strip()
    url = (raw.get("url") or "").strip()
    if not provider_job_id or not title or not url:
        return None

    if not source.provider_id:
        log.warning("[ingest] normalize_posting called with unresolved source %s", source.name)
        return None

    doc_id = posting_id(source.provider_id, source.org, str(provider_job_id))
    location = raw.get("location") or None
    if location:
        location = _truncate(location, _LOCATION_MAX)
    title = _truncate(title, _TITLE_MAX)
    company_name = _truncate(source.name, _COMPANY_NAME_MAX)

    return Posting(
        _id=doc_id,
        provider=source.provider_id,
        org=source.org,
        company_name=company_name,
        title=title,
        title_normalized=normalize_text_key(title),
        location=location,
        location_normalized=normalize_text_key(location),
        remote_flag=raw.get("remote_flag"),
        employment_type=_normalize_employment_type(raw.get("employment_type")),
        description_text=(raw.get("description_text") or "").strip(),
        salary=raw.get("salary") or None,
        url=url,
        apply_url=raw.get("apply_url") or url,
        posted_at=raw.get("posted_at"),
        tags=list(source.tags),
        raw=raw.get("raw") or {},
    )
