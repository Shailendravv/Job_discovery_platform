"""
Phase 1 — Parsing the Resume into a "Content Map"

Walks a .docx file paragraph by paragraph, identifies sections by heading
styles, and builds a structured content map where each editable text span
gets a stable ID, run index, current text, and character budget.

Core rule:  Never set paragraph.text or cell.text — only run.text on
individual runs.  This rule is enforced downstream in reinjector.py.

Tier system:
    Tier 1 — Bullets (achievement/responsibility bullets under each role)
    Tier 2 — Summary/Objective (top-of-resume summary paragraph)
    Tier 3 — Skills list (reorder/re-emphasize; drop/add if plausible)
    Tier 4 — Headers (names, titles, companies, dates, contact) — NEVER edit
"""

import logging
import re
from typing import Optional

from docx import Document
from docx.oxml.ns import qn

log = logging.getLogger(__name__)

# Section headings that trigger editable tiers
SUMMARY_SECTIONS = {"summary", "profile", "objective", "professional summary"}
EXPERIENCE_SECTIONS = {
    "experience", "work experience", "professional experience", "employment",
    "work history", "employment history", "career history", "career",
    "professional background", "work background", "relevant experience",
}
SKILLS_SECTIONS = {"skills", "technical skills", "core competencies", "technologies"}
EDUCATION_SECTIONS = {"education", "academic background"}
# Everything else (certifications, projects, publications, etc.) is Tier 4 (non-editable)
# Unless it appears under experience headings — then it's Tier 1 bullets.

# ── Bullet-detection style names ──
_BULLET_STYLE_NAMES = {
    "list bullet", "listbullet", "list", "listnumber",
    "bullet", "bulet", "dash", "bullet char",
}


def build_content_map(path: str) -> tuple[list[dict], dict[str, str]]:
    """
    Walk a .docx file and return (content_map, section_map).

    content_map: list of span dicts with keys:
        id, tier, paragraph_index, run_index, run_count, text,
        char_budget, needs_manual_review (optional), section (optional)

    section_map: dict mapping paragraph_index → section_name (lowercase)
    """
    doc = Document(path)
    content_map: list[dict] = []
    section_map: dict[int, str] = {}
    current_section: Optional[str] = None

    for p_idx, para in enumerate(doc.paragraphs):
        style_name = (para.style.name or "").lower()
        text = para.text.strip()

        # ── Track section boundaries via heading styles ──
        if style_name.startswith("heading"):
            current_section = text.lower() if text else current_section
            # Headings themselves are never editable
            section_map[p_idx] = current_section or "heading"
            continue

        if not text:
            continue

        # ── Detect section by heuristics when no heading style is used ──
        # Common templates use ALL-CAPS or bold short lines as headings
        detected_section = _detect_section(para, current_section)
        if detected_section and detected_section != current_section:
            # This paragraph itself is a section header — skip it
            if _looks_like_section_header(para):
                section_map[p_idx] = detected_section
                current_section = detected_section
                continue
            current_section = detected_section

        section_map[p_idx] = current_section or "unknown"

        # ── Determine tier ──
        tier = _determine_tier(para, current_section)

        if tier == 4:
            # Tier 4 (headers, titles, company names, dates) — skip entirely
            continue

        # ── Build span entry ──
        is_uniform, reason = _check_uniform(para)
        span = {
            "id": f"p{p_idx}",
            "tier": tier,
            "paragraph_index": p_idx,
            "run_count": len(para.runs),
            "text": text,
            "section": current_section or "unknown",
        }

        if is_uniform:
            span["run_index"] = 0  # We'll merge into run 0 on write-back
            span["char_budget"] = _compute_budget(text, tier)
        else:
            # Mixed-formatting paragraph — flag for manual review
            span["needs_manual_review"] = True
            span["run_index"] = -1
            span["char_budget"] = _compute_budget(text, tier)
            log.debug("Mixed-formatting at p%d (tier %d): %s", p_idx, tier, text[:60])

        content_map.append(span)

    return content_map, section_map


def _is_bullet(para) -> bool:
    """
    Check if a paragraph is a bullet item by examining its style name
    and the presence of numPr (numbering properties) in the XML.
    """
    style = (para.style.name or "").lower()
    if style in _BULLET_STYLE_NAMES:
        return True
    if "bullet" in style or "list" in style:
        return True
    # Check for numPr element (numbering/bullet properties)
    try:
        numPr = para._p.find(qn("w:pPr"))
        if numPr is not None:
            numPr = numPr.find(qn("w:numPr"))
            if numPr is not None:
                return True
    except Exception:
        pass
    return False


def _determine_tier(para, current_section: Optional[str]) -> int:
    """
    Determine the edit tier for a paragraph based on the current section
    and paragraph style.
    """
    style = (para.style.name or "").lower()

    if not current_section:
        return 4  # Unknown section → non-editable

    section = current_section.lower()

    # ── Tier 2: Summary sections ──
    if section in SUMMARY_SECTIONS:
        return 2

    # ── Tier 1: Bullets under experience ──
    if section in EXPERIENCE_SECTIONS:
        return 1

    # ── Tier 3: Skills sections ──
    if section in SKILLS_SECTIONS:
        return 3

    # ── Treat bullets as Tier 1 even outside experience sections ──
    if _is_bullet(para):
        return 1

    # ── Education entries are Tier 4 (facts, never edit) ─-
    if section in EDUCATION_SECTIONS:
        return 4

    return 4


def _detect_section(para, current_section: Optional[str]) -> Optional[str]:
    """
    Try to detect section type from paragraph text and style when heading
    styles are not used. Returns detected section name or None.
    """
    text = para.text.strip().lower()
    style = (para.style.name or "").lower()

    # ALL-CAPS short lines often denote section headers
    if para.text.strip().isupper() and len(para.text.strip()) < 60:
        if "summary" in text or "objective" in text or "profile" in text:
            return "summary"
        if _text_matches_experience(text):
            return "experience"
        if "skill" in text or "technolog" in text or "competenc" in text:
            return "skills"
        if "education" in text or "academic" in text:
            return "education"
        return current_section  # Could be a section header we don't track

    # Bold short lines are often section headers in resume templates
    is_bold = bool(para.runs) and all(r.bold for r in para.runs if r.text.strip())
    if is_bold and len(text) < 40 and not text.endswith("."):
        if "summary" in text or "objective" in text or "profile" in text:
            return "summary"
        if _text_matches_experience(text):
            return "experience"
        if "skill" in text or "technolog" in text or "competenc" in text:
            return "skills"
        if "education" in text or "academic" in text:
            return "education"

    return None


def _text_matches_experience(text: str) -> bool:
    """Check if text matches any experience-related section name."""
    text_lower = text.lower().strip()
    for exp_key in EXPERIENCE_SECTIONS:
        if exp_key in text_lower:
            return True
    # Also check word-level: "work" + "history", "career" + "history", etc.
    if "work" in text_lower and ("history" in text_lower or "background" in text_lower):
        return True
    return False


def _looks_like_section_header(para) -> bool:
    """Check if a paragraph looks like a section header rather than content."""
    text = para.text.strip()
    if not text:
        return False

    style = (para.style.name or "").lower()
    if style.startswith("heading"):
        return True

    # ALL-CAPS short line
    if text.isupper() and len(text) < 60:
        return True

    # Bold short line without ending punctuation
    is_bold = bool(para.runs) and all(r.bold for r in para.runs if r.text.strip())
    if is_bold and len(text) < 40 and not text.rstrip(".").endswith("."):
        return True

    return False


def _check_uniform(para) -> tuple[bool, str]:
    """
    Check whether a paragraph has "uniform" formatting — either a single run,
    or all runs share identical bold/italic/underline/font/size/color.

    Returns (is_uniform, reason).
    """
    runs = para.runs
    if not runs:
        return True, "no_runs"

    if len(runs) <= 1:
        return True, "single_run"

    # Compare all runs against the first non-empty run
    first_non_empty = None
    for r in runs:
        if r.text.strip():
            first_non_empty = r
            break

    if first_non_empty is None:
        return True, "all_empty"

    fmt = {
        "bold": first_non_empty.bold,
        "italic": first_non_empty.italic,
        "underline": first_non_empty.underline,
        "font_name": _run_font_name(first_non_empty),
        "font_size": _run_font_size(first_non_empty),
        "color": _run_color(first_non_empty),
    }

    for r in runs:
        if not r.text.strip():
            continue
        if r.bold != fmt["bold"]:
            return False, "mixed_bold"
        if r.italic != fmt["italic"]:
            return False, "mixed_italic"
        if r.underline != fmt["underline"]:
            return False, "mixed_underline"
        if _run_font_name(r) != fmt["font_name"]:
            return False, "mixed_font_name"
        if _run_font_size(r) != fmt["font_size"]:
            return False, "mixed_font_size"
        if _run_color(r) != fmt["color"]:
            return False, "mixed_color"

    return True, "uniform"


def _run_font_name(run) -> str:
    """Get the font name of a run, or empty string if not set."""
    try:
        return run.font.name or ""
    except Exception:
        return ""


def _run_font_size(run):
    """Get the font size of a run (as string for comparison), or empty string."""
    try:
        size = run.font.size
        return str(size) if size else ""
    except Exception:
        return ""


def _run_color(run) -> str:
    """Get the color of a run as hex string, or empty string."""
    try:
        color = run.font.color
        if color and color.rgb:
            return str(color.rgb)
        return ""
    except Exception:
        return ""


def _compute_budget(text: str, tier: int) -> int:
    """
    Compute the character budget for a text span.

    Tier 1 (bullets): up to 25% slack — bullets need room for expansion
    Tier 2 (summary): up to 20% slack — summaries may grow with keywords
    Tier 3 (skills):  10% slack — skills are concise
    Tier 4 (headers): not applicable (not editable)
    Default:          15% slack
    """
    slack_map = {1: 0.25, 2: 0.20, 3: 0.10}
    slack = slack_map.get(tier, 0.15)
    return int(len(text) * (1 + slack)) + 1  # +1 ensures at least 1 char


# ── Table handling ──

def build_table_content_map(doc) -> list[dict]:
    """
    Extract editable spans from table cells (common in two-column resume templates).

    Same rules as paragraphs: never set cell.text, only cell.paragraphs[i].runs[j].text.
    Each cell paragraph gets an id like "t{t_idx}_r{r_idx}_p{p_idx}".
    """
    content_map = []

    for t_idx, table in enumerate(doc.tables):
        for r_idx, row in enumerate(table.rows):
            for c_idx, cell in enumerate(row.cells):
                for p_idx, para in enumerate(cell.paragraphs):
                    text = para.text.strip()
                    if not text:
                        continue

                    # Table cells are hard to classify — blacklist certain patterns
                    if _is_contact_info(text):
                        continue
                    if _is_date_like(text):
                        continue
                    if _is_job_title_like(text, para):
                        continue

                    is_uniform, _ = _check_uniform(para)
                    span = {
                        "id": f"t{t_idx}_r{r_idx}_c{c_idx}_p{p_idx}",
                        "tier": 1,  # Default to editable for table content
                        "table_index": t_idx,
                        "row_index": r_idx,
                        "cell_index": c_idx,
                        "paragraph_index": p_idx,
                        "run_count": len(para.runs),
                        "run_index": 0,
                        "text": text,
                        "char_budget": _compute_budget(text, tier=1),
                        "section": "table",
                    }
                    if not is_uniform:
                        span["needs_manual_review"] = True

                    content_map.append(span)

    return content_map


def _is_contact_info(text: str) -> bool:
    """Heuristic: detect email, phone, LinkedIn, GitHub, or website patterns."""
    text_lower = text.lower().strip()
    if re.search(r"[\w.+-]+@[\w-]+\.[\w.-]+", text):
        return True
    if re.search(r"[\+\d][\d\s\-\(\)]{7,}", text):
        return True
    if "linkedin.com" in text_lower:
        return True
    if "github.com" in text_lower:
        return True
    if text_lower.startswith("http://") or text_lower.startswith("https://"):
        return True
    return False


def _is_date_like(text: str) -> bool:
    """Heuristic: detect date patterns like 'Jan 2020 – Present' or '2020-2024'."""
    # "Month Year – Present" or "Month Year – Month Year"
    if re.search(r"(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)\w*\s+\d{4}", text.lower()):
        return True
    # "2020 - 2024" or "2020–Present"
    if re.search(r"\b\d{4}\s*[–\-]\s*(\d{4}|present|current)\b", text.lower()):
        return True
    # Just a year
    if re.match(r"^\d{4}$", text.strip()):
        return True
    return False


def _is_job_title_like(text: str, para) -> bool:
    """
    Heuristic: detect job title lines that often appear as bold short lines
    under experience sections. These should NOT be edited.
    """
    # Usually short, bold, and at the start of a role entry
    if len(text) > 60:
        return False
    is_bold = bool(para.runs) and any(r.bold for r in para.runs if r.text.strip())
    if not is_bold:
        return False
    # Common patterns: "Senior Engineer at Acme Corp" or "Job Title | Company"
    if " at " in text.lower() or " | " in text:
        return True
    if "/" in text and is_bold and len(text) < 40:
        return True
    return False
