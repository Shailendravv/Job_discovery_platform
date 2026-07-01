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
import re
from typing import Any

log = logging.getLogger(__name__)

# Fields considered PII — stripped before sending to external LLMs
PII_FIELDS = frozenset({"name", "email", "phone"})

# Regex patterns for fallback PII extraction from raw text
_EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")
_PHONE_RE = re.compile(
    r"(\+?\d{1,3}[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}"
)
_SECTION_HEADING_WORDS = frozenset({
    "summary", "profile", "objective", "experience", "employment",
    "work", "education", "skill", "project", "certification",
    "publication", "language", "reference", "training", "professional",
    "technical", "core", "additional",
})


def _extract_email_from_text(text: str) -> str:
    """Extract the first email address found in raw text."""
    match = _EMAIL_RE.search(text)
    return match.group(0) if match else ""


def _extract_phone_from_text(text: str) -> str:
    """Extract the first phone number found in raw text."""
    match = _PHONE_RE.search(text)
    return match.group(0) if match else ""


def _extract_name_from_text(text: str) -> str:
    """
    Extract a candidate name from raw text heuristically.

    Strategy: scan the first several lines and return the first line that
    looks like a name (2-4 words, capitalized, not a section heading,
    not an email or phone).
    """
    lines = [l.strip() for l in text.split("\n") if l.strip()]
    for line in lines[:10]:
        if _EMAIL_RE.search(line) or _PHONE_RE.search(line):
            continue
        if line == line.upper() and len(line) < 60:
            if any(w in line.lower() for w in _SECTION_HEADING_WORDS):
                continue
        words = line.split()
        if 2 <= len(words) <= 4:
            if all(w[0].isupper() for w in words if w):
                return line
    log.debug("No name-like line found in first 10 lines")
    return ""


def extract_pii(
    parsed_data: dict,
    resume_text: str = "",
) -> dict:
    """
    Extract PII fields from parsed resume data.

    Falls back to regex/heuristic extraction from raw text when the LLM
    parser did not find PII fields.

    Args:
        parsed_data: The full parsed resume data dict (from resume_parser).
        resume_text: Raw extracted text (used as fallback when parsed_data
                     is missing PII).

    Returns:
        Dict with keys: name, email, phone (only if non-empty).
    """
    pii: dict[str, str] = {}

    # 1. Try parsed_data first (LLM-extracted)
    for field in PII_FIELDS:
        value = parsed_data.get(field)
        if value and isinstance(value, str) and value.strip():
            pii[field] = value.strip()

    # 2. Fallback from raw text for missing fields
    if resume_text:
        if "email" not in pii:
            email = _extract_email_from_text(resume_text)
            if email:
                pii["email"] = email
        if "phone" not in pii:
            phone = _extract_phone_from_text(resume_text)
            if phone:
                pii["phone"] = phone
        if "name" not in pii:
            name = _extract_name_from_text(resume_text)
            if name:
                pii["name"] = name

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
