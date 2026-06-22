"""
PII (Personally Identifiable Information) service.

Handles extraction, stripping, and reinjection of PII from resume data
so candidate contact info is never sent to external LLM providers.

Pipeline:
    extract_pii()   → save PII before tailoring
    strip_pii()     → remove PII from data sent to LLM
    reinject_pii()  → merge PII back after tailoring
"""

from __future__ import annotations

import logging
from typing import Any

log = logging.getLogger(__name__)

# Fields considered PII — stripped before sending to external LLMs
PII_FIELDS = frozenset({"name", "email", "phone"})


def extract_pii(parsed_data: dict) -> dict:
    """
    Extract PII fields from parsed resume data.

    Returns a dict containing only the PII fields that had values.
    This dict is saved and later passed to reinject_pii().

    Args:
        parsed_data: The full parsed resume data dict (from resume_parser).

    Returns:
        Dict with keys: name, email, phone (only if non-empty).
    """
    pii: dict[str, str] = {}
    for field in PII_FIELDS:
        value = parsed_data.get(field)
        if value and isinstance(value, str) and value.strip():
            pii[field] = value.strip()
    if pii:
        log.info("Extracted PII: %s", {k: v for k, v in pii.items()})
    else:
        log.info("No PII fields found to extract")
    return pii


def strip_pii(parsed_data: dict) -> dict:
    """
    Remove PII fields from parsed resume data.

    Returns a new dict preserving all non-PII data.
    The original parsed_data is not modified.

    Args:
        parsed_data: The full parsed resume data dict.

    Returns:
        New dict with PII fields removed.
    """
    return {k: v for k, v in parsed_data.items() if k not in PII_FIELDS}


def reinject_pii(tailored_data: dict, pii: dict) -> dict:
    """
    Re-inject PII fields back into tailored resume data.

    Args:
        tailored_data: The tailored resume data dict (without PII).
        pii: The extracted PII dict from extract_pii().

    Returns:
        New dict combining tailored data with PII merged back in.
    """
    result = dict(tailored_data)
    result.update(pii)
    return result
