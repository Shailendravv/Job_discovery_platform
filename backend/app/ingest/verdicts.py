"""Verdict schema + apply logic — PLAN.md §3 "Verdict schema (verdicts.json)"
and milestone 2's acceptance test: verdicts round-trip end to end.

``jobctl judge --apply`` validates the *shape* of the whole file up front
(a malformed entry means nothing in the file can be trusted, so that's a
hard failure of the whole command) but rejects bad *ids* one at a time —
"rejects unknown ids" and "refuses to overwrite an existing verdict unless
--force is passed" (PLAN.md §3) both read as per-verdict outcomes, not an
all-or-nothing batch. A single stale id in a 25-item batch shouldn't cost
the other 24 judgments.
"""

from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Literal, Optional

from motor.motor_asyncio import AsyncIOMotorDatabase
from pydantic import BaseModel, Field

from app.ingest.ids import resolve_posting_id
from app.ingest.models import now_utc

VerdictLabel = Literal["apply", "maybe", "skip"]


class Verdict(BaseModel):
    """One entry of ``verdicts.json`` (PLAN.md §3). ``id`` is whatever the
    agent copied from ``jobctl next`` — a full id or the short display id;
    resolved against the store in ``apply_verdicts``."""

    id: str
    verdict: VerdictLabel
    score: int = Field(ge=1, le=10)
    reasons: list[str] = Field(default_factory=list)
    concerns: list[str] = Field(default_factory=list)
    matched_requirements: list[str] = Field(default_factory=list)
    missing_requirements: list[str] = Field(default_factory=list)
    judged_by: str = "claude-code"
    judged_at: Optional[datetime] = None


@dataclass
class RejectedVerdict:
    id: str
    reason: str


@dataclass
class VerdictApplyResult:
    applied: int = 0
    rejected: list[RejectedVerdict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {"applied": self.applied, "rejected": [asdict(r) for r in self.rejected]}


async def apply_verdicts(
    db: AsyncIOMotorDatabase,
    verdicts: list[Verdict],
    *,
    force: bool = False,
) -> VerdictApplyResult:
    result = VerdictApplyResult()
    seen_in_file: set[str] = set()
    now = now_utc()

    for v in verdicts:
        if v.id in seen_in_file:
            result.rejected.append(RejectedVerdict(v.id, "duplicate id in this file"))
            continue
        seen_in_file.add(v.id)

        doc, error = await resolve_posting_id(db, v.id)
        if error:
            result.rejected.append(RejectedVerdict(v.id, error))
            continue

        if doc.get("judged") and not force:
            result.rejected.append(
                RejectedVerdict(v.id, "already judged (use --force to overwrite)")
            )
            continue

        full_id = doc["_id"]
        judged_at = v.judged_at or now

        # Write the verdict detail before flipping the posting's judged flag:
        # if the process dies between the two writes, a posting stuck with
        # judged=True but no verdicts row would silently vanish from every
        # future `next`/`list --unjudged` call with no way to tell it was
        # never actually judged. This order fails the other way instead —
        # worst case a verdicts row with judged=False on its posting, which
        # `jobctl judge --apply --force` can simply redo.
        await db.verdicts.update_one(
            {"_id": full_id},
            {
                "$set": {
                    **v.model_dump(exclude={"id", "judged_at"}),
                    "judged_at": judged_at,
                    "applied_at": now,
                }
            },
            upsert=True,
        )
        await db.postings.update_one(
            {"_id": full_id},
            {"$set": {"judged": True, "verdict": v.verdict, "updated_at": now}},
        )
        result.applied += 1

    return result
