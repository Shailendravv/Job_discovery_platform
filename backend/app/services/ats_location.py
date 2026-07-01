"""
Company location → paper format detection.

US/Canada  → Letter  (8.5in × 11in)
Rest of world → A4   (210mm × 297mm)
"""

import re
import logging
from typing import Optional

log = logging.getLogger(__name__)

_US_CANADA_PATTERNS = [
    "us", "usa", "united states", "united states of america",
    "canada", "ca",
    "al", "ak", "az", "ar", "ca", "co", "ct", "de", "fl", "ga",
    "hi", "id", "il", "in", "ia", "ks", "ky", "la", "me", "md",
    "ma", "mi", "mn", "ms", "mo", "mt", "ne", "nv", "nh", "nj",
    "nm", "ny", "nc", "nd", "oh", "ok", "or", "pa", "ri", "sc",
    "sd", "tn", "tx", "ut", "vt", "va", "wa", "wv", "wi", "wy",
    "ab", "bc", "mb", "nb", "nl", "ns", "nt", "nu", "on", "pe", "qc", "sk", "yt",
    "california", "texas", "new york", "florida", "illinois",
    "ontario", "british columbia", "quebec",
]

_US_CANADA_SET = frozenset(_US_CANADA_PATTERNS)

_EU_PATTERNS = [
    "united kingdom", "uk", "england", "scotland", "wales", "northern ireland",
    "europe", "european", "eu",
    "germany", "deutschland", "france", "spain", "italy", "netherlands",
    "sweden", "norway", "denmark", "finland", "switzerland", "austria",
    "belgium", "ireland", "portugal", "poland", "czech", "hungary",
    "australia", "new zealand", "nz",
    "india", "china", "japan", "singapore", "hong kong",
    "brazil", "mexico", "argentina", "chile",
    "africa", "south africa", "nigeria", "kenya",
    "middle east", "uae", "dubai", "saudi arabia", "israel",
]


def detect_paper_format(
    job_location: str | None,
    job_description: str,
    default_format: str = "letter",
) -> str:
    """
    Detect Letter vs A4 paper format based on job location.

    Priority:
      1. job_location field (highest confidence)
      2. job_description fallback text
      3. default_format when indeterminate
    """
    if job_location:
        result = _check_text(job_location)
        if result:
            log.info("Paper format '%s' from location '%s'", result, job_location)
            return result

    if job_description:
        result = _check_text(job_description)
        if result:
            log.info("Paper format '%s' from description text", result)
            return result

    log.info("Location indeterminate — using default format '%s'", default_format)
    return default_format


def _check_text(text: str) -> str | None:
    """Check text for US/Canada vs rest-of-world location clues."""
    text_lower = text.lower()

    # Remote-with-location patterns
    if "remote" in text_lower:
        if any(pat in text_lower for pat in ["(us", "(canada", "us)", "canada)", "usa"]):
            return "letter"
        if any(pat in text_lower for pat in _EU_PATTERNS):
            return "a4"
        return None

    # US/Canada state/province abbreviations
    words = re.findall(r"[a-zA-Z]+", text_lower)
    for word in words:
        clean = word.rstrip(".").strip()
        if clean in _US_CANADA_SET:
            return "letter"

    # Non-US country names → A4
    for pat in _EU_PATTERNS:
        if pat in text_lower:
            return "a4"

    return None


def paper_format_to_page_width(format_name: str) -> str:
    return "210mm" if format_name == "a4" else "8.5in"


def paper_format_to_playwright_format(format_name: str) -> str:
    return "A4" if format_name == "a4" else "Letter"
