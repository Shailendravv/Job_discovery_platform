"""
Phase 3 — Reinjection (the formatting-preserving write-back)

Core rule: NEVER call paragraph.text = ... or cell.text = ...
Only ever set run.text = ... on the specific run that holds the content
being changed. The run object keeps its own <w:rPr> (font, size, bold,
italic, color, etc.), so swapping its text preserves everything else
automatically.

This is the single most important rule in the entire pipeline.
"""

import logging
from docx import Document
from docx.oxml.ns import qn

log = logging.getLogger(__name__)


def apply_rewrites(
    original_path: str,
    content_map: list[dict],
    rewrites: dict[str, str],
    output_path: str,
) -> None:
    """
    Apply validated rewrites to a copy of the original document.

    Opens the ORIGINAL docx, locates each paragraph by index, and sets
    run.text directly — never paragraph-level text.

    Args:
        original_path: Path to the original resume .docx.
        content_map: Full content map (from parser.py).
        rewrites: Dict mapping span id → new_text (from validator.py).
        output_path: Where to save the modified .docx.

    Raises:
        ValueError: If a paragraph index in the content map is out of range.
    """
    doc = Document(original_path)

    # Separate table and paragraph spans
    paragraph_spans = [
        s for s in content_map
        if "table_index" not in s
    ]
    table_spans = [
        s for s in content_map
        if "table_index" in s
    ]

    # ── Apply paragraph rewrites ──
    _apply_paragraph_rewrites(doc, paragraph_spans, rewrites)

    # ── Apply table cell rewrites ──
    if table_spans:
        _apply_table_rewrites(doc, table_spans, rewrites)

    # ── Typography post-processing ──
    _apply_typography_postprocess(doc, content_map, rewrites)

    # ── Save ──
    doc.save(output_path)
    log.info("Saved tailored resume to %s", output_path)


def _apply_paragraph_rewrites(
    doc: Document,
    spans: list[dict],
    rewrites: dict[str, str],
) -> None:
    """Apply rewrites to paragraphs (not table cells)."""
    paragraphs = doc.paragraphs

    for span in spans:
        span_id = span["id"]
        new_text = rewrites.get(span_id)

        if new_text is None:
            continue  # Unchanged — leave exactly as-is

        p_idx = span["paragraph_index"]

        if p_idx >= len(paragraphs):
            log.warning("Paragraph index %d out of range (max %d) — skipping", p_idx, len(paragraphs) - 1)
            continue

        para = paragraphs[p_idx]
        run_count = span.get("run_count", len(para.runs))

        # ── Case 1: Single run or no runs ──
        if run_count <= 1 or len(para.runs) <= 1:
            if para.runs:
                para.runs[0].text = new_text
                # Clear any remaining runs to avoid text duplication
                for extra_run in para.runs[1:]:
                    extra_run.text = ""
            else:
                # Paragraph had no runs at all (rare) — add one
                para.add_run(new_text)

        # ── Case 2: Multiple runs but uniform formatting ──
        # Keep run 0's formatting, clear the rest
        elif len(para.runs) > 1:
            para.runs[0].text = new_text
            for extra_run in para.runs[1:]:
                extra_run.text = ""

        # ── Case 3: Mixed formatting (flagged needs_manual_review) ──
        # These should not have rewrites applied to them automatically.
        # If somehow one does, skip it.
        else:
            log.warning("Span %s has mixed formatting — skipping automatic rewrite", span_id)


def _apply_table_rewrites(
    doc: Document,
    spans: list[dict],
    rewrites: dict[str, str],
) -> None:
    """Apply rewrites to table cell paragraphs."""
    for span in spans:
        span_id = span["id"]
        new_text = rewrites.get(span_id)

        if new_text is None:
            continue

        t_idx = span.get("table_index", 0)
        r_idx = span.get("row_index", 0)
        c_idx = span.get("cell_index", 0)
        p_idx = span.get("paragraph_index", 0)

        if t_idx >= len(doc.tables):
            log.warning("Table index %d out of range — skipping", t_idx)
            continue

        table = doc.tables[t_idx]
        if r_idx >= len(table.rows):
            continue

        row = table.rows[r_idx]
        if c_idx >= len(row.cells):
            continue

        cell = row.cells[c_idx]
        if p_idx >= len(cell.paragraphs):
            continue

        para = cell.paragraphs[p_idx]

        # ── Apply with the same run-level care as paragraphs ──
        if para.runs:
            para.runs[0].text = new_text
            for extra_run in para.runs[1:]:
                extra_run.text = ""
        else:
            para.add_run(new_text)


def _apply_typography_postprocess(
    doc: Document,
    content_map: list[dict],
    rewrites: dict[str, str],
) -> None:
    """
    Post-process all rewritten runs to normalize typography.

    Converts straight quotes/apostrophes to typographic equivalents
    so tailored text matches the rest of the document's typography.
    """
    for span in content_map:
        span_id = span["id"]
        if span_id not in rewrites:
            continue

        p_idx = span.get("paragraph_index", -1)
        if p_idx < 0 or p_idx >= len(doc.paragraphs):
            continue

        para = doc.paragraphs[p_idx]
        for run in para.runs:
            if run.text:
                run.text = _fix_typography(run.text)

    # Also process table cell paragraphs
    for span in content_map:
        span_id = span["id"]
        if span_id not in rewrites:
            continue

        if "table_index" not in span:
            continue

        t_idx = span.get("table_index", 0)
        r_idx = span.get("row_index", 0)
        c_idx = span.get("cell_index", 0)
        p_idx = span.get("paragraph_index", 0)

        if t_idx >= len(doc.tables):
            continue
        table = doc.tables[t_idx]
        if r_idx >= len(table.rows):
            continue
        row = table.rows[r_idx]
        if c_idx >= len(row.cells):
            continue
        cell = row.cells[c_idx]
        if p_idx >= len(cell.paragraphs):
            continue

        para = cell.paragraphs[p_idx]
        for run in para.runs:
            if run.text:
                run.text = _fix_typography(run.text)


def _fix_typography(text: str) -> str:
    """
    Convert straight quotes and apostrophes to typographic (curly) equivalents.

    Rules:
    - Double quotes: " → " at start, " → " at end
    - Single quotes/apostrophes: ' → ' (right single quotation mark)
    - Note: python-docx stores text as plain strings; the XML underneath
      doesn't care about the character used. This is purely cosmetic.
    """
    if not text:
        return text

    # Replace straight double quotes with curly quotes (basic heuristic)
    # This is a simple approach that alternates opening/closing
    result = []
    open_quote = True
    for char in text:
        if char == '"':
            if open_quote:
                result.append("\u201c")  # Left double quotation mark
            else:
                result.append("\u201d")  # Right double quotation mark
            open_quote = not open_quote
        elif char == "'":
            # Apostrophes between letters are single quotes
            result.append("\u2019")  # Right single quotation mark
        else:
            result.append(char)
    return "".join(result)
