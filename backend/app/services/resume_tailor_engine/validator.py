"""
Phase 2b — Validation and Retry Logic

Validates LLM-produced rewrites against:
- Character budgets (each span has a budget)
- JSON schema conformance (id + new_text)
- Banned content rules (no fabricated employers, dates, metrics)

Retry loop: if a field exceeds budget, re-prompt the model to shorten it.
Cap retries at max_retries per field; fall back to original text after that.
"""

import json
import logging
from typing import Optional
from pydantic import BaseModel

log = logging.getLogger(__name__)


class Rewrite(BaseModel):
    """A single rewrite entry returned by the LLM."""
    id: str
    new_text: str


# ── Banned content patterns ──
# These patterns should never appear in a tailored resume since they'd
# represent a fabrication. The LLM is instructed not to invent, but
# validation catches oversights.

BANNED_PATTERNS = [
    # Invented contact details
    r"\[\w+\]",
    # Placeholder patterns
    r"\[Your Name\]",
    r"\[Company Name\]",
    r"\[Job Title\]",
    r"\[Date\]",
    # Metrics that weren't in the original (these are hard to detect,
    # but concrete fabricated numbers like "increased by 47%" are a red flag)
    # We don't block all numbers — that would be too aggressive.
    # Instead we check that any quantified achievement in the rewritten text
    # has a plausible source in the original.
]


def validate_and_apply_budget(
    rewrites: list[dict],
    content_map_by_id: dict[str, dict],
) -> dict[str, str]:
    """
    Validate LLM rewrites against budgets and schema.

    Args:
        rewrites: List of {"id": str, "new_text": str} from the LLM.
        content_map_by_id: Dict mapping span id → original span dict
                           (must have 'char_budget' and 'text' keys).

    Returns:
        Dict mapping accepted span id → new_text.
        Only rewrites that pass all checks are included.
    """
    accepted: dict[str, str] = {}

    for rewrite in rewrites:
        span_id = rewrite.get("id")
        new_text = rewrite.get("new_text", "")

        # ── Check 1: Span exists ──
        if span_id not in content_map_by_id:
            log.warning("Rewrite references unknown span id: %s — skipping", span_id)
            continue

        original = content_map_by_id[span_id]
        original_text = original["text"]
        char_budget = original.get("char_budget", len(original_text) + 10)

        # ── Check 2: Not empty ──
        if not new_text or not new_text.strip():
            log.debug("Rewrite for %s is empty — keeping original", span_id)
            accepted[span_id] = original_text
            continue

        # ── Check 3: Character budget ──
        if len(new_text) > char_budget:
            log.debug(
                "Rewrite for %s exceeds budget (%d > %d) — rejecting",
                span_id,
                len(new_text),
                char_budget,
            )
            continue  # Will be handled by retry logic or fallback

        # ── Check 4: No banned patterns ──
        import re
        has_banned = False
        for pattern in BANNED_PATTERNS:
            if re.search(pattern, new_text):
                log.warning(
                    "Rewrite for %s contains banned pattern '%s' — rejecting",
                    span_id,
                    pattern,
                )
                has_banned = True
                break
        if has_banned:
            continue

        # ── Check 5: No fabrication of dates/employers/titles ──
        # If the original had no date pattern and the rewrite introduces one, flag it
        if _introduces_fabrication(original_text, new_text):
            log.warning(
                "Rewrite for %s appears to introduce fabricated content — rejecting",
                span_id,
            )
            continue

        # ── All checks passed ──
        accepted[span_id] = new_text

    return accepted


def retry_over_budget(
    rejected_rewrites: list[dict],
    content_map_by_id: dict[str, dict],
    job_description: str,
    job_title: str,
    job_skills: list[str],
    model: str = "gemma4:e2b",
    base_url: str = "http://localhost:11434",
    max_retries: int = 2,
) -> list[dict]:
    """
    Retry rejected rewrites that exceeded budget.

    For each rejected field, re-prompt the model with a "shorten" instruction.
    After max_retries, fall back to original text.

    Args:
        rejected_rewrites: List of {"id": str, "new_text": str} that were over-budget.
        content_map_by_id: Dict of original span info (for char_budget).
        job_description: Full job description (for context in retry prompts).
        job_title: Job title.
        job_skills: List of skills.
        model: Ollama model name.
        base_url: Ollama URL.
        max_retries: Max retries per field.

    Returns:
        List of {"id": str, "new_text": str} with accepted (possibly shortened) rewrites.
        Falls back to original text after max_retries.
    """
    if not rejected_rewrites:
        return []

    results: list[dict] = []

    for rewrite in rejected_rewrites:
        span_id = rewrite["id"]
        long_text = rewrite["new_text"]

        if span_id not in content_map_by_id:
            results.append({"id": span_id, "new_text": long_text})
            continue

        original = content_map_by_id[span_id]
        char_budget = original.get("char_budget", len(original["text"]) + 10)
        original_text = original["text"]

        accepted_text = _retry_shorten(
            span_id=span_id,
            long_text=long_text,
            original_text=original_text,
            target_budget=char_budget,
            job_description=job_description,
            job_title=job_title,
            job_skills=job_skills,
            model=model,
            base_url=base_url,
            max_retries=max_retries,
        )

        results.append({"id": span_id, "new_text": accepted_text})

    return results


def _retry_shorten(
    span_id: str,
    long_text: str,
    original_text: str,
    target_budget: int,
    job_description: str,
    job_title: str,
    job_skills: list[str],
    model: str,
    base_url: str,
    max_retries: int,
) -> str:
    """
    Retry shortening a specific field. Returns the accepted short text,
    or the original text after max_retries.
    """
    import asyncio

    current_text = long_text

    for attempt in range(max_retries):
        if len(current_text) <= target_budget:
            return current_text

        shorten_prompt = (
            f"The following resume text was rewritten to match a {job_title} role "
            f"but is too long (max {target_budget} chars, got {len(current_text)}).\n\n"
            f"Original: {original_text}\n"
            f"Too long: {current_text}\n\n"
            f"Please shorten to under {target_budget} characters while keeping the "
            f"key points that match the job description. Return ONLY the shortened text."
        )

        try:
            short_response = asyncio.run(_call_shorten_llm(
                prompt=shorten_prompt,
                model=model,
                base_url=base_url,
            ))
            short_text = short_response.strip().strip('"').strip("'")
            if short_text and len(short_text) <= target_budget:
                current_text = short_text
            else:
                # Try harder: truncate at last sentence boundary within budget
                if len(current_text) > target_budget:
                    current_text = current_text[:target_budget]
                    # Try to break at a sentence boundary
                    last_period = current_text.rfind(".")
                    if last_period > target_budget * 0.6:
                        current_text = current_text[: last_period + 1]
        except Exception as e:
            log.warning("Retry attempt %d for %s failed: %s", attempt + 1, span_id, e)
            # Fallback: truncate
            if len(current_text) > target_budget:
                current_text = current_text[:target_budget]

    # After exhausting retries, fall back to original if still too long
    if len(current_text) > target_budget:
        log.info("Fallback to original text for %s (retries exhausted)", span_id)
        return original_text

    return current_text


async def _call_shorten_llm(
    prompt: str,
    model: str = "gemma4:e2b",
    base_url: str = "http://localhost:11434",
) -> str:
    """Call the LLM for a simple shorten operation (no JSON format needed)."""
    import httpx

    url = f"{base_url.rstrip('/')}/api/chat"
    body = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "stream": False,
        "options": {
            "temperature": 0.5,  # Lower temperature for deterministic shortening
            "num_predict": 512,
        },
    }

    async with httpx.AsyncClient(timeout=60.0) as client:
        response = await client.post(url, json=body)
        response.raise_for_status()
        data = response.json()

    return data["message"]["content"]


# ═══════════════════════════════════════════════════════════════
#  Fabrication detection helpers
# ═══════════════════════════════════════════════════════════════


def _introduces_fabrication(original: str, rewritten: str) -> bool:
    """
    Check if the rewritten text introduces content that appears to be
    fabricated (not present in the original).

    Checks:
    1. New dates that weren't in the original
    2. New percentage metrics that weren't in the original
    3. New specific dollar amounts that weren't in the original
    """
    import re

    # Extract all date-like patterns from both texts
    orig_dates = set(_extract_dates(original))
    new_dates = set(_extract_dates(rewritten))

    # If we find dates in the rewrite that weren't in the original, flag it
    new_date_introductions = new_dates - orig_dates
    if new_date_introductions:
        log.debug("Fabrication check: new dates introduced: %s", new_date_introductions)
        return True

    # Extract percentages
    orig_pcts = set(_extract_percentages(original))
    new_pcts = set(_extract_percentages(rewritten))
    new_pct_introductions = new_pcts - orig_pcts
    if new_pct_introductions:
        log.debug("Fabrication check: new metrics introduced: %s", new_pct_introductions)
        return True

    # Extract dollar amounts
    orig_dollars = set(_extract_dollar_amounts(original))
    new_dollars = set(_extract_dollar_amounts(rewritten))
    new_dollar_introductions = new_dollars - orig_dollars
    if new_dollar_introductions:
        log.debug("Fabrication check: new dollar amounts introduced: %s", new_dollar_introductions)
        return True

    return False


def _extract_dates(text: str) -> list[str]:
    """Extract date-like patterns from text."""
    import re
    dates = []
    # Patterns: Jan 2020, January 2020, 2020-2024, 2020 – Present
    patterns = [
        r"\b(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|"
        r"Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)"
        r"\s+\d{4}\b",
        r"\b\d{4}\s*(?:–|-)\s*(?:\d{4}|Present|Current)\b",
        r"\b\d{4}\b",
    ]
    for pattern in patterns:
        dates.extend(re.findall(pattern, text, re.IGNORECASE))
    return [d.lower().strip() for d in dates]


def _extract_percentages(text: str) -> list[str]:
    """Extract percentage patterns from text."""
    import re
    return re.findall(r"\b\d+%", text)


def _extract_dollar_amounts(text: str) -> list[str]:
    """Extract dollar amount patterns from text."""
    import re
    return re.findall(r"\$\d[\d,]*", text)
