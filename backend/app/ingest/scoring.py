"""Deterministic scoring — the stage that decides which postings a Claude
Code judging session ever has to look at.

The prefilter (``prefilter.py``) answers a binary question: is this posting
disqualified outright? Everything that survives it used to go to a Claude
Code session for a 1-10 judgement, one posting at a time. Most of those
judgements are not judgement calls at all — a posting matching eight of your
core skills, in an allowed location, at your seniority, is an ``apply``; one
matching none of them is a ``skip``. Both are decidable from rules.

So this module scores every prefiltered posting deterministically and splits
the result into three bands:

- ``score >= auto_apply_min``  -> verdict ``apply``, written automatically
- ``score <= auto_skip_max``   -> verdict ``skip``,  written automatically
- anything between             -> left **unjudged**, so ``jobctl next`` hands
                                  it to Claude Code exactly as before

Nothing here calls an LLM, makes an HTTP request, or reads a model. It is
arithmetic over ``config/scoring.yml``.

Auto-decided verdicts are written through the existing
``verdicts.apply_verdicts`` path with ``judged_by="deterministic"``, so they
are indistinguishable downstream from agent-written ones except by that
field — ``jobctl shortlist`` and ``GET /postings/shortlist`` need no changes.
"""

import logging
import math
import os
import re
from dataclasses import asdict, dataclass, field
from typing import Any, Optional

import yaml
from motor.motor_asyncio import AsyncIOMotorDatabase
from pydantic import BaseModel, Field

from app.ingest.models import now_utc
from app.ingest.prefilter import extract_years_required
from app.ingest.verdicts import Verdict, apply_verdicts

log = logging.getLogger(__name__)

# backend/app/ingest/scoring.py -> up 3 levels -> backend/ -> config/scoring.yml
SCORING_CONFIG_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "config",
    "scoring.yml",
)

# How many postings one scoring pass will read at a time. Scoring is pure
# CPU over already-stored documents, so this only bounds memory.
SCORING_BATCH = 1000


class SkillsConfig(BaseModel):
    """Skills that earn points, and how many points a full match is worth."""

    core: list[str] = Field(default_factory=list)
    bonus: list[str] = Field(default_factory=list)
    core_weight: float = 3.0
    bonus_weight: float = 1.0
    max_points: float = 4.0


class SeniorityConfig(BaseModel):
    """Title patterns for the band you actually want, and the ones above it.

    ``preferred`` earns points; ``too_senior`` loses them. Both are
    case-insensitive regexes matched against the title.
    """

    preferred: list[str] = Field(default_factory=list)
    too_senior: list[str] = Field(default_factory=list)
    preferred_points: float = 1.5
    too_senior_penalty: float = 3.0


class LocationConfig(BaseModel):
    allowed: list[str] = Field(default_factory=list)
    remote_ok: bool = True
    match_points: float = 0.5
    miss_penalty: float = 2.5


class ExperienceConfig(BaseModel):
    """Points for a years-of-experience requirement you comfortably meet,
    penalty scaled by how far past your ceiling it asks."""

    max_years: Optional[int] = None
    within_points: float = 1.0
    per_year_over_penalty: float = 1.0
    max_penalty: float = 4.0


class BandConfig(BaseModel):
    auto_apply_min: int = 8
    auto_skip_max: int = 3

    # A gate, not a weight: seniority, location and years-of-experience are
    # all weak or table-stakes signals, and together they can carry a
    # posting to auto_apply_min with no skill overlap at all. Observed on
    # the live registry: "Associate Manager, Strategic Partnerships" scored
    # 8/10 on a preferred-seniority title, a remote location and a 3-year
    # requirement, matching none of the core skills.
    #
    # Below this many core-skill hits a posting can still score highly, but
    # it is held at needs_review rather than auto-applied. Auto-*skip* is
    # deliberately not gated -- a posting with no skill overlap being
    # skipped is the correct outcome, not a risky one.
    min_core_skills_for_auto_apply: int = 2


class ScoringConfig(BaseModel):
    base_score: float = 4.0
    skills: SkillsConfig = Field(default_factory=SkillsConfig)
    seniority: SeniorityConfig = Field(default_factory=SeniorityConfig)
    location: LocationConfig = Field(default_factory=LocationConfig)
    experience: ExperienceConfig = Field(default_factory=ExperienceConfig)
    bands: BandConfig = Field(default_factory=BandConfig)


def load_scoring_config(path: str = SCORING_CONFIG_PATH) -> ScoringConfig:
    """Parse ``scoring.yml``. Raises ``FileNotFoundError`` if missing, the
    same contract as ``load_prefilter_config`` — the runner catches it and
    skips the stage rather than failing an otherwise-good ingest."""
    if not os.path.isfile(path):
        raise FileNotFoundError(f"scoring config not found: {path}")
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return ScoringConfig.model_validate(data)


@dataclass
class ScoreResult:
    """One posting's deterministic judgement, shaped to fit ``Verdict``."""

    score: int
    band: str  # "apply" | "needs_review" | "skip"
    core_skill_hits: int = 0
    reasons: list[str] = field(default_factory=list)
    concerns: list[str] = field(default_factory=list)
    matched_requirements: list[str] = field(default_factory=list)
    missing_requirements: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


def _haystack(doc: dict) -> str:
    return f"{doc.get('title') or ''} {doc.get('description_text') or ''}".lower()


def _score_skills(doc: dict, config: SkillsConfig, result: ScoreResult) -> float:
    """Points for skill overlap, capped so a keyword-stuffed description
    cannot alone push a posting into the auto-apply band."""
    if not config.core and not config.bonus:
        return 0.0

    haystack = _haystack(doc)
    core_hits = [s for s in config.core if s.lower() in haystack]
    bonus_hits = [s for s in config.bonus if s.lower() in haystack]

    result.core_skill_hits = len(core_hits)
    result.matched_requirements.extend(core_hits + bonus_hits)
    missing_core = [s for s in config.core if s not in core_hits]
    result.missing_requirements.extend(missing_core)

    if core_hits:
        result.reasons.append(f"matches {len(core_hits)} core skill(s): {', '.join(core_hits)}")
    else:
        result.concerns.append("mentions none of the core skills")

    raw = len(core_hits) * config.core_weight + len(bonus_hits) * config.bonus_weight
    # Normalize against a "full marks" baseline so max_points means the same
    # thing regardless of how long the configured skill list is.
    denominator = max(len(config.core) * config.core_weight, config.core_weight)
    return min(config.max_points, (raw / denominator) * config.max_points)


def _score_seniority(doc: dict, config: SeniorityConfig, result: ScoreResult) -> float:
    title = doc.get("title") or ""

    for pattern in config.too_senior:
        if re.search(pattern, title, re.IGNORECASE):
            result.concerns.append(f"title is above target seniority ({pattern})")
            result.missing_requirements.append("seniority fit")
            return -config.too_senior_penalty

    for pattern in config.preferred:
        if re.search(pattern, title, re.IGNORECASE):
            result.reasons.append("title is in the target seniority band")
            result.matched_requirements.append("seniority fit")
            return config.preferred_points

    return 0.0


def _score_location(doc: dict, config: LocationConfig, result: ScoreResult) -> float:
    """Same rule shape as ``prefilter.hard_filter_reject``'s location check —
    a posting is fine if it is remote (and remote is acceptable) or its
    location contains an allowed place."""
    if not config.allowed:
        return 0.0

    if bool(doc.get("remote_flag")) and config.remote_ok:
        result.reasons.append("remote")
        result.matched_requirements.append("location")
        return config.match_points

    location = (doc.get("location") or "").lower()
    if any(allowed.lower() in location for allowed in config.allowed):
        result.reasons.append(f"location is workable: {doc.get('location')}")
        result.matched_requirements.append("location")
        return config.match_points

    result.concerns.append(f"location not in the allowed list: {doc.get('location') or 'unknown'}")
    result.missing_requirements.append("location")
    return -config.miss_penalty


def _score_experience(doc: dict, config: ExperienceConfig, result: ScoreResult) -> float:
    if config.max_years is None:
        return 0.0

    years = extract_years_required(doc.get("description_text") or "")
    if years is None:
        # No stated requirement is not evidence either way.
        return 0.0

    if years <= config.max_years:
        result.reasons.append(f"asks for {years} years, within the {config.max_years}-year ceiling")
        result.matched_requirements.append("years of experience")
        return config.within_points

    over = years - config.max_years
    result.concerns.append(f"asks for {years} years, {over} beyond the {config.max_years}-year ceiling")
    result.missing_requirements.append("years of experience")
    return -min(config.max_penalty, over * config.per_year_over_penalty)


def score_posting(doc: dict, config: ScoringConfig) -> ScoreResult:
    """Score one posting 1-10 and assign it a band. Pure function — no I/O,
    no randomness, no model. The same posting and config always produce the
    same result, which is what makes the auto-written verdicts defensible."""
    result = ScoreResult(score=0, band="needs_review")

    total = config.base_score
    total += _score_skills(doc, config.skills, result)
    total += _score_seniority(doc, config.seniority, result)
    total += _score_location(doc, config.location, result)
    total += _score_experience(doc, config.experience, result)

    # Verdict.score is constrained to 1..10 by its pydantic Field.
    # floor(x + 0.5), not round(): round() is banker's rounding, which
    # would make a band edge depend on whether the neighbour is even.
    result.score = max(1, min(10, math.floor(total + 0.5)))

    if result.score >= config.bands.auto_apply_min:
        result.band = "apply"
    elif result.score <= config.bands.auto_skip_max:
        result.band = "skip"
    else:
        result.band = "needs_review"

    # Skill overlap is a necessary condition for an automatic apply, not
    # just one term among four -- see BandConfig.min_core_skills_for_auto_apply.
    needed = config.bands.min_core_skills_for_auto_apply
    if result.band == "apply" and config.skills.core and result.core_skill_hits < needed:
        result.band = "needs_review"
        result.concerns.append(
            f"scores {result.score}/10 but matches only {result.core_skill_hits} "
            f"core skill(s) — held for review rather than auto-applied"
        )

    return result


@dataclass
class ScoringRunResult:
    input: int = 0
    auto_applied: int = 0
    auto_skipped: int = 0
    needs_review: int = 0
    verdicts_written: int = 0
    verdicts_rejected: int = 0
    duration_ms: float = 0.0

    def to_dict(self) -> dict:
        return asdict(self)


async def run_scoring(
    db: AsyncIOMotorDatabase,
    config: ScoringConfig,
    *,
    limit: Optional[int] = None,
    dry_run: bool = False,
) -> ScoringRunResult:
    """Score every unjudged posting that cleared the prefilter, write the
    clear-cut verdicts, and leave the ambiguous band for Claude Code.

    ``dry_run=True`` computes the same band counts without writing anything —
    for previewing the effect of an edited ``scoring.yml`` before it starts
    auto-deciding postings.
    """
    import time

    started = time.perf_counter()

    # Only postings the prefilter passed and nobody has judged: a posting the
    # prefilter rejected is already out, and re-scoring a judged one would
    # fight with either the agent or a previous scoring pass.
    cursor = db.postings.find({"judged": False, "prefilter_status": "passed", "duplicate_of": None})
    if limit is not None:
        cursor = cursor.limit(limit)
    docs = await cursor.to_list(length=limit or SCORING_BATCH)

    result = ScoringRunResult(input=len(docs))
    verdicts: list[Verdict] = []
    score_writes = []

    for doc in docs:
        scored = score_posting(doc, config)

        if scored.band == "apply":
            result.auto_applied += 1
        elif scored.band == "skip":
            result.auto_skipped += 1
        else:
            result.needs_review += 1

        score_writes.append((doc["_id"], scored))

        if scored.band in ("apply", "skip"):
            verdicts.append(Verdict(
                id=doc["_id"],
                verdict=scored.band,
                score=scored.score,
                reasons=scored.reasons,
                concerns=scored.concerns,
                matched_requirements=scored.matched_requirements,
                missing_requirements=scored.missing_requirements,
                judged_by="deterministic",
                judged_at=now_utc(),
            ))

    if not dry_run:
        # Every posting gets its score recorded, decided or not — a
        # needs_review posting showing its score is how you tell whether the
        # bands are set sensibly.
        from pymongo import UpdateOne

        operations = [
            UpdateOne(
                {"_id": doc_id},
                {"$set": {"score": scored.score, "score_band": scored.band}},
            )
            for doc_id, scored in score_writes
        ]
        if operations:
            await db.postings.bulk_write(operations, ordered=False)

        if verdicts:
            applied = await apply_verdicts(db, verdicts)
            result.verdicts_written = applied.applied
            result.verdicts_rejected = len(applied.rejected)

        await db.scoring_runs.insert_one({
            "run_at": now_utc(),
            **{k: v for k, v in result.to_dict().items() if k != "duration_ms"},
        })

    result.duration_ms = round((time.perf_counter() - started) * 1000.0, 1)

    log.info(
        "[scoring] %d scored - %d auto-apply, %d auto-skip, %d left for review (%.0fms)",
        result.input, result.auto_applied, result.auto_skipped, result.needs_review,
        result.duration_ms,
    )
    return result
