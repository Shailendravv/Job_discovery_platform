"""Posting id resolution for the human/agent-facing commands (milestone 2:
``list``, ``show``, ``next``, ``judge --apply`` — PLAN.md §3).

``Posting.id`` is a full 64-char sha256 hex digest (see
``app.ingest.models.posting_id``) — unwieldy to read or type. PLAN.md's
``jobctl next`` example addresses postings by a short id
(``## [a3f9c1] Backend Engineer...``), so this module provides:

- ``assign_short_ids`` — pick the shortest common prefix width that stays
  unique *within one displayed batch*, for ``list``/``next`` output.
- ``resolve_posting_id`` — the reverse direction, accepting either a full id
  or any unambiguous prefix of one, for ``show``/``judge --apply``. A prefix
  that matches more than one stored posting is refused rather than guessed
  at — the caller must supply more characters.
"""

import re
from typing import Optional

from motor.motor_asyncio import AsyncIOMotorDatabase

FULL_ID_LENGTH = 64  # sha256 hex digest length
DEFAULT_SHORT_ID_WIDTH = 8

_HEX_RE = re.compile(r"^[0-9a-f]+$")


def short_id(full_id: str, width: int = DEFAULT_SHORT_ID_WIDTH) -> str:
    return full_id[:width]


def assign_short_ids(full_ids: list[str], width: int = DEFAULT_SHORT_ID_WIDTH) -> dict[str, str]:
    """Map each full id to a display id, widening (git-abbrev style) only if
    the starting width collides within this batch. Collisions across the
    whole store (not just this batch) are still caught at resolve time —
    this only has to be unambiguous among the ids being shown together."""
    if not full_ids:
        return {}

    candidate_width = width
    while candidate_width < FULL_ID_LENGTH:
        prefixes = [fid[:candidate_width] for fid in full_ids]
        if len(set(prefixes)) == len(prefixes):
            return {fid: fid[:candidate_width] for fid in full_ids}
        candidate_width += 2

    return {fid: fid for fid in full_ids}


async def resolve_posting_id(db: AsyncIOMotorDatabase, id_str: str) -> tuple[Optional[dict], Optional[str]]:
    """Resolve a full id or unique prefix to its ``postings`` document.

    Returns ``(doc, None)`` on success or ``(None, error_message)`` — never
    raises for a bad/unknown/ambiguous id, since ``show``/``judge`` need to
    report these per-id without killing the whole command."""
    needle = (id_str or "").strip().lower()
    if not needle or not _HEX_RE.match(needle):
        return None, f"invalid id: {id_str!r}"

    if len(needle) == FULL_ID_LENGTH:
        doc = await db.postings.find_one({"_id": needle})
        return (doc, None) if doc else (None, f"unknown id: {id_str!r}")

    cursor = db.postings.find({"_id": {"$regex": f"^{re.escape(needle)}"}}).limit(2)
    matches = await cursor.to_list(length=2)
    if not matches:
        return None, f"unknown id: {id_str!r}"
    if len(matches) > 1:
        return None, f"ambiguous id {id_str!r} — matches multiple postings, use more characters"
    return matches[0], None
