"""
Resume Tailoring Engine — formatting-preserving resume content rewriting.

Pipeline:
    parser.py (Phase 1)     → build Content Map from .docx
    llm_client.py (Phase 2) → send editable spans to Gemma 4 E2B
    validator.py (Phase 2)  → pydantic budget/retry validation
    reinjector.py (Phase 3) → run-level write-back preserving formatting
    verifier.py (Phase 4)   → PDF page-count diff + visual check

Usage:
    from app.services.resume_tailor_engine import tailor_resume

    result = tailor_resume(
        docx_path="path/to/resume.docx",
        job_description="...",
        job_title="Software Engineer",
        job_skills=["Python", "React"],
        output_path="path/to/tailored.docx",
    )
"""

import logging
import os
from typing import Optional

from app.services.resume_tailor_engine.parser import build_content_map, build_table_content_map
from app.services.resume_tailor_engine.reinjector import apply_rewrites
from app.services.resume_tailor_engine.llm_client import tailor_spans_batched
from app.services.resume_tailor_engine.validator import validate_and_apply_budget, retry_over_budget
from app.services.resume_tailor_engine.verifier import verify_page_count

log = logging.getLogger(__name__)


class TailorResult:
    """Result of a resume tailoring operation."""

    def __init__(
        self,
        success: bool,
        output_path: str = "",
        rewrites_applied: int = 0,
        pages_match: Optional[bool] = None,
        needs_manual_review: Optional[list[str]] = None,
        error: str = "",
    ):
        self.success = success
        self.output_path = output_path
        self.rewrites_applied = rewrites_applied
        self.pages_match = pages_match
        self.needs_manual_review = needs_manual_review or []
        self.error = error


# Re-export key functions for direct use/debugging
__all__ = [
    "tailor_resume",
    "build_content_map",
    "build_table_content_map",
    "apply_rewrites",
    "print_content_map",
    "TailorResult",
]


def tailor_resume(
    docx_path: str,
    job_description: str,
    job_title: str = "",
    job_skills: Optional[list[str]] = None,
    output_path: Optional[str] = None,
    original_docx_path: Optional[str] = None,
    model: str = "gemma4:e2b",
    llm_base_url: str = "http://localhost:11434",
    max_retries_per_field: int = 2,
    batch_size: int = 8,
) -> "TailorResult":
    """
    Full pipeline: parse → tailor → validate → reinject → verify.

    Processes content in small batches (default 8 spans) to keep the
    small local model focused on one section at a time.

    Args:
        docx_path: Path to the original resume .docx file.
        job_description: Full job description text.
        job_title: Job title being targeted.
        job_skills: List of skills from the job description.
        output_path: Where to save the tailored .docx. If None, derived from docx_path.
        original_docx_path: If different from docx_path (e.g., docx_path is a temp copy),
                            the original to use for reinjection. Defaults to docx_path.
        model: Ollama model name to use (default: gemma4:e2b).
        llm_base_url: Ollama server URL.
        max_retries_per_field: How many times to retry a field that exceeds budget.
        batch_size: Maximum spans per LLM call (default 8).

    Returns:
        TailorResult with success status and metadata.
    """
    # ── Phase 0: Path setup ──
    if output_path is None:
        base, ext = os.path.splitext(docx_path)
        output_path = f"{base}_tailored{ext}"

    reinject_source = original_docx_path or docx_path

    # ── Phase 1: Parse → Build Content Map ──
    log.info("Phase 1: Parsing %s into content map...", docx_path)
    content_map, _ = build_content_map(docx_path)

    editable_spans = [s for s in content_map if not s.get("needs_manual_review")]
    needs_manual = [s for s in content_map if s.get("needs_manual_review")]

    if needs_manual:
        log.warning(
            "%d span(s) flagged for manual review (mixed formatting): %s",
            len(needs_manual),
            [s["id"] for s in needs_manual],
        )

    if not editable_spans:
        log.warning("No editable spans found in content map.")
        return TailorResult(
            success=True,
            output_path=docx_path,
            rewrites_applied=0,
            needs_manual_review=[s["text"][:80] for s in needs_manual],
        )

    # ── Phase 2: Tailor with LLM (batched) ──
    log.info(
        "Phase 2: Tailoring %d spans with %s (batch_size=%d)...",
        len(editable_spans),
        model,
        batch_size,
    )
    raw_rewrites = tailor_spans_batched(
        spans=editable_spans,
        job_description=job_description,
        job_title=job_title,
        job_skills=job_skills or [],
        model=model,
        base_url=llm_base_url,
        batch_size=batch_size,
    )

    # ── Phase 2b: Validate ──
    log.info("Phase 2b: Validating %d rewrites...", len(raw_rewrites))
    content_map_by_id = {s["id"]: s for s in content_map}
    accepted = validate_and_apply_budget(raw_rewrites, content_map_by_id)

    # Retry over-budget fields
    rejected = [r for r in raw_rewrites if r["id"] not in accepted]
    if rejected and max_retries_per_field > 0:
        log.info("Retrying %d rejected fields...", len(rejected))
        retry_results = retry_over_budget(
            rejected, content_map_by_id, job_description, job_title,
            job_skills or [], model, llm_base_url, max_retries_per_field,
        )
        for r in retry_results:
            if r["id"] not in accepted:
                accepted[r["id"]] = r["new_text"]

    log.info("Accepted %d / %d rewrites.", len(accepted), len(raw_rewrites))

    # ── Phase 3: Reinject ──
    log.info("Phase 3: Reinjecting %d rewrites into %s...", len(accepted), output_path)
    apply_rewrites(reinject_source, content_map, accepted, output_path)

    # ── Phase 4: Verify (optional, best-effort) ──
    pages_match = None
    try:
        pages_match = verify_page_count(reinject_source, output_path)
        if pages_match is False:
            log.warning("Page count mismatch: tailored resume has different page count.")
        else:
            log.info("Page count verified: original and tailored match.")
    except Exception as e:
        log.warning("Page count verification skipped (LibreOffice not available?): %s", e)

    return TailorResult(
        success=True,
        output_path=output_path,
        rewrites_applied=len(accepted),
        pages_match=pages_match,
        needs_manual_review=[s["text"][:80] for s in needs_manual],
    )


def print_content_map(docx_path: str) -> None:
    """
    Calibration helper: print the content map for human review.
    Use this before running the full pipeline to verify section detection
    and tier assignments are correct for your resume template.

    (Plan Section 2.3: Calibration step)
    """
    content_map, _ = build_content_map(docx_path)

    print("=" * 60)
    print("CONTENT MAP — Calibration Output")
    print("=" * 60)
    print()
    print(f"Total spans: {len(content_map)}")
    print()

    for span in content_map:
        tier_label = {1: "BULLET", 2: "SUMMARY", 3: "SKILLS", 4: "HEADER"}.get(
            span.get("tier", 4), "UNKNOWN"
        )
        flag = "⚠️ MANUAL REVIEW" if span.get("needs_manual_review") else ""
        budget = span.get("char_budget", "?")
        print(f"  [{span['id']}] Tier {span.get('tier', '?')} {tier_label} {flag}")
        print(f"         Budget: {budget} chars | Section: {span.get('section', '?')}")
        print(f"         Text: {span['text'][:80]}")
        print()

    print("=" * 60)
    print(f"{len(content_map)} total spans")
    editable = sum(1 for s in content_map if not s.get("needs_manual_review"))
    flagged = sum(1 for s in content_map if s.get("needs_manual_review"))
    print(f"{editable} editable, {flagged} flagged for manual review")
    print("=" * 60)
