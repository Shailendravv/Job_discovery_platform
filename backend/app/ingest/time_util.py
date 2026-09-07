"""Duration string parsing shared by ``list --since``/``--new`` (milestone 2)
and future ``ingest --since`` / ``shortlist --since`` (PLAN.md §3, §7)."""

import re
from datetime import timedelta

_UNIT_SECONDS = {
    "m": 60,           # minutes
    "h": 3600,         # hours
    "d": 86400,        # days
    "w": 604800,       # weeks
}

_PATTERN = re.compile(r"^\s*(\d+)\s*([mhdw])\s*$", re.IGNORECASE)


def parse_duration(value: str) -> timedelta:
    """Parse a short duration string like ``"24h"``, ``"7d"``, ``"30m"``,
    ``"2w"`` into a ``timedelta``. Raises ``ValueError`` on anything else —
    callers should surface that as a CLI usage error, not a stack trace."""
    match = _PATTERN.match(value or "")
    if not match:
        raise ValueError(
            f"invalid duration {value!r} — expected e.g. '24h', '7d', '30m', '2w'"
        )
    amount, unit = match.groups()
    return timedelta(seconds=int(amount) * _UNIT_SECONDS[unit.lower()])
