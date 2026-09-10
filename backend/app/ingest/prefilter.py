"""Rule-based prefilter between ``jobctl ingest`` and ``jobctl next`` —
PLAN.md §4 "Phase 3 — prefilter before the agent sees anything", milestone 3.

Every posting ``jobctl next`` hands the judging agent costs subscription
quota, so this module cuts the obvious rejects with cheap rules *before*
that: title/location/years/disqualifier hard filters, then a keyword floor.
Embedding similarity (PLAN.md §4 step 3) is wired as a third stage but ships
**disabled by default** this milestone — it needs a resume to embed against,
and ``profile/resume.md`` doesn't exist yet (deferred to milestone 4). See
``backend/docs/prefilter.md`` for the full design and the recorded
deviation.

``backend/config/prefilter.yml`` ships as a documented *sample*, the same
way milestone 1's ``ats_companies.yml`` started as a seed list — it proves
the mechanism (fixture tests assert >=80% rejected) but needs tuning to a
real resume/preferences before the acceptance criterion means anything
against the live registry.
"""

import logging
import os
import re
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Optional

import yaml
from motor.motor_asyncio import AsyncIOMotorDatabase
from pydantic import BaseModel, Field
from pymongo import UpdateOne
from pymongo.errors import BulkWriteError

log = logging.getLogger(__name__)

# backend/app/ingest/prefilter.py -> up 3 levels -> backend/ -> config/prefilter.yml
CONFIG_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "config",
    "prefilter.yml",
)

_embedding_unavailable_warned = False


class HardFilterConfig(BaseModel):
    title_blocklist: list[str] = Field(default_factory=list)
    title_allowlist: list[str] = Field(default_factory=list)
    allowed_locations: list[str] = Field(default_factory=list)
    remote_ok: bool = True
    max_years_experience: Optional[int] = None
    disqualifying_keywords: list[str] = Field(default_factory=list)


class KeywordFloorConfig(BaseModel):
    skills: list[str] = Field(default_factory=list)
    min_matches: int = 0


class EmbeddingConfig(BaseModel):
    enabled: bool = False
    resume_path: Optional[str] = None
    threshold: float = 0.35


class PrefilterConfig(BaseModel):
    hard_filters: HardFilterConfig = Field(default_factory=HardFilterConfig)
    keyword_floor: KeywordFloorConfig = Field(default_factory=KeywordFloorConfig)
    embedding: EmbeddingConfig = Field(default_factory=EmbeddingConfig)


def load_prefilter_config(path: str = CONFIG_PATH) -> PrefilterConfig:
    """Parse ``prefilter.yml``. Raises ``FileNotFoundError`` if missing —
    unlike the ATS registry (which degrades to an empty list), a missing
    prefilter config is a setup error worth failing loudly on rather than
    silently letting everything through."""
    if not os.path.isfile(path):
        raise FileNotFoundError(f"prefilter config not found: {path}")
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return PrefilterConfig.model_validate(data)


# Matches "5+ years", "3-5 years", "at least 10 years" — takes the first
# (lowest bound of a range) number found before "year(s)".
_YEARS_RE = re.compile(r"(\d{1,2})\s*(?:\+|-\s*\d{1,2})?\s*years?", re.IGNORECASE)


def extract_years_required(text: str) -> Optional[int]:
    """Lowest years-of-experience figure mentioned in a posting description,
    or None if nothing matches. Used against ``max_years_experience`` — a
    posting demanding 7+ years when the ceiling is 3 is a hard-filter skip."""
    if not text:
        return None
    match = _YEARS_RE.search(text)
    if not match:
        return None
    return int(match.group(1))


def hard_filter_reject(posting: dict, config: HardFilterConfig) -> Optional[str]:
    """First hard-filter rule that fires, as a human-readable reason, or
    None if the posting clears all of them. Order matches PLAN.md §4 step 1
    (title -> location -> years -> disqualifiers)."""
    title = posting.get("title") or ""
    description = posting.get("description_text") or ""

    for pattern in config.title_blocklist:
        if re.search(pattern, title, re.IGNORECASE):
            return f"title matches blocklist pattern: {pattern}"

    if config.title_allowlist and not any(
        re.search(pattern, title, re.IGNORECASE) for pattern in config.title_allowlist
    ):
        return "title does not match any allowlist pattern"

    if config.allowed_locations:
        is_remote = bool(posting.get("remote_flag")) and config.remote_ok
        location = (posting.get("location") or "").lower()
        location_ok = any(allowed.lower() in location for allowed in config.allowed_locations)
        if not is_remote and not location_ok:
            return f"location not allowed: {posting.get('location') or 'unknown'}"

    if config.max_years_experience is not None:
        years = extract_years_required(description)
        if years is not None and years > config.max_years_experience:
            return f"requires {years}+ years, ceiling is {config.max_years_experience}"

    haystack = f"{title} {description}".lower()
    for keyword in config.disqualifying_keywords:
        if keyword.lower() in haystack:
            return f"disqualifying keyword: {keyword}"

    return None


def keyword_floor_pass(posting: dict, config: KeywordFloorConfig) -> bool:
    """True if the posting mentions at least ``min_matches`` of the
    configured skills. An empty skill list is treated as "no floor
    configured" and always passes — PLAN.md §4 step 2."""
    if not config.skills:
        return True
    haystack = f"{posting.get('title', '')} {posting.get('description_text', '')}".lower()
    matches = sum(1 for skill in config.skills if skill.lower() in haystack)
    return matches >= config.min_matches


def embedding_similarity_reject(
    posting: dict,
    config: EmbeddingConfig,
    resume_vector=None,
) -> Optional[str]:
    """PLAN.md §4 step 3. Ships a no-op this milestone: returns None (pass)
    whenever the stage is disabled (the default), and also degrades to a
    pass — logging once, never raising — if it's enabled but
    sentence-transformers isn't installed. A prefilter run must never crash
    because an optional dependency is missing; see backend/docs/prefilter.md
    Open Issues for what completing this stage requires."""
    global _embedding_unavailable_warned
    if not config.enabled:
        return None

    try:
        import sentence_transformers  # noqa: F401
    except ImportError:
        if not _embedding_unavailable_warned:
            log.warning(
                "[prefilter] embedding stage enabled in config but sentence-transformers "
                "is not installed; skipping this stage for the whole run"
            )
            _embedding_unavailable_warned = True
        return None

    # Full embedding-similarity scoring is deferred until a real resume
    # exists at config.resume_path (milestone 4) — see Open Issues.
    return None


@dataclass
class PrefilterRunResult:
    input: int = 0
    hard_filter_rejected: int = 0
    keyword_floor_rejected: int = 0
    embedding_rejected: int = 0
    embedding_skipped: int = 0
    passed: int = 0
    duration_ms: float = 0.0

    def to_dict(self) -> dict:
        return asdict(self)


async def run_prefilter(
    db: AsyncIOMotorDatabase,
    config: PrefilterConfig,
    *,
    limit: Optional[int] = None,
    dry_run: bool = False,
    reclassify: bool = False,
) -> PrefilterRunResult:
    """Classify every posting not yet prefiltered, writing
    ``prefiltered``/``prefilter_status``/``prefilter_reason`` back and
    logging one ``prefilter_runs`` document with the stage counts (PLAN.md
    §4: "Log counts at each stage so I can see where postings die").
    ``dry_run=True`` computes the same counts without writing anything —
    for previewing the effect of an edited ``prefilter.yml``.

    ``reclassify=True`` re-runs over *every* posting, not just the
    unclassified ones, and is what makes an edit to ``prefilter.yml``
    actually take effect. Without it the config is inert for anything
    already in the collection: a posting rejected under a stale
    ``allowed_locations`` stays rejected forever, because the default query
    never looks at it again. Ingest deliberately keeps the incremental
    behaviour — reclassifying the whole corpus on every nightly run would
    be pure waste — so this is opt-in, via ``jobctl prefilter run --all``.
    A reclassify can move a posting in either direction, including back to
    ``passed`` with its stale rejection reason cleared."""
    started = time.perf_counter()

    cursor = db.postings.find({} if reclassify else {"prefiltered": False})
    if limit is not None:
        cursor = cursor.limit(limit)
    docs = await cursor.to_list(length=limit)

    result = PrefilterRunResult(input=len(docs))
    operations: list[UpdateOne] = []

    for doc in docs:
        reason = hard_filter_reject(doc, config.hard_filters)
        if reason:
            result.hard_filter_rejected += 1
            status, status_reason = "hard_filter", reason
        elif not keyword_floor_pass(doc, config.keyword_floor):
            result.keyword_floor_rejected += 1
            status, status_reason = "keyword_floor", "below required skill keyword floor"
        elif config.embedding.enabled and (
            reason := embedding_similarity_reject(doc, config.embedding)
        ):
            result.embedding_rejected += 1
            status, status_reason = "embedding", reason
        else:
            if not config.embedding.enabled:
                result.embedding_skipped += 1
            result.passed += 1
            status, status_reason = "passed", None

        if not dry_run:
            operations.append(UpdateOne(
                {"_id": doc["_id"]},
                {"$set": {
                    "prefiltered": True,
                    "prefilter_status": status,
                    "prefilter_reason": status_reason,
                }},
            ))

    if not dry_run and operations:
        # One round trip instead of one per posting. At the registry's real
        # volume (thousands of unclassified postings after an ingest) the
        # await-per-document loop this replaces was the whole cost of the
        # stage. Unordered + partial-failure recovery follows store.py:
        # a single document that trips the collection validator must not
        # discard the classifications that did land.
        try:
            await db.postings.bulk_write(operations, ordered=False)
        except BulkWriteError as e:
            write_errors = (e.details or {}).get("writeErrors", [])
            log.error(
                "[prefilter] bulk_write had %d error(s) out of %d ops -- "
                "the remaining classifications were still applied",
                len(write_errors), len(operations),
            )

    result.duration_ms = round((time.perf_counter() - started) * 1000.0, 1)

    if not dry_run:
        await db.prefilter_runs.insert_one({
            "run_at": datetime.now(timezone.utc),
            **result.to_dict(),
        })

    log.info(
        "[prefilter] %d classified -- %d passed, %d hard-filtered, %d below keyword floor (%.0fms)",
        result.input, result.passed, result.hard_filter_rejected,
        result.keyword_floor_rejected, result.duration_ms,
    )

    return result
