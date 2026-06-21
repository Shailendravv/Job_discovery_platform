"""
HTML-based resume formatting service.
DOCX ──mammoth──▶ HTML ──LLM edits──▶ modified HTML ──htmldocx──▶ DOCX
                                               └──playwright──▶ PDF

For PDF uploads: PyMuPDF extracts text → elements_to_html() generates HTML.
"""

import io
import logging
import os
import tempfile
from typing import Optional

from app.models.resume_elements import ResumeElement

log = logging.getLogger(__name__)

# ── Optional dependency checks ──

try:
    import mammoth
    HAS_MAMMOTH = True
except ImportError:
    HAS_MAMMOTH = False
    log.warning("mammoth not installed — DOCX→HTML conversion disabled")

try:
    from htmldocx import HtmlToDocx
    HAS_HTMLDOCX = True
except ImportError:
    HAS_HTMLDOCX = False
    log.warning("htmldocx not installed — HTML→DOCX conversion disabled")

try:
    from bs4 import BeautifulSoup
    HAS_BS4 = True
except ImportError:
    HAS_BS4 = False

try:
    from playwright.sync_api import sync_playwright
    HAS_PLAYWRIGHT = True
except ImportError:
    HAS_PLAYWRIGHT = False
    log.warning("playwright not installed — HTML→PDF via Playwright disabled")


# ═══════════════════════════════════════════════════════════════
#  DOCX → HTML
# ═══════════════════════════════════════════════════════════════

def docx_to_html(docx_bytes: bytes) -> str:
    """Convert DOCX bytes to HTML using mammoth.
    Preserves bold, italic, links, headings, lists."""
    if not HAS_MAMMOTH:
        raise RuntimeError("mammoth is required for DOCX→HTML conversion")

    with io.BytesIO(docx_bytes) as docx_file:
        result = mammoth.convert_to_html(docx_file)
        html = result.value
        for msg in result.messages:
            log.debug("mammoth: %s", msg)

    # Wrap in a full document with print-friendly CSS
    return _wrap_html(html, style=_DEFAULT_CSS)


# ═══════════════════════════════════════════════════════════════
#  ResumeElement list → HTML  (for PDF uploads)
# ═══════════════════════════════════════════════════════════════

def elements_to_html(elements: list[ResumeElement]) -> str:
    """Convert structured ResumeElements to HTML.
    Used for PDF uploads where mammoth can't extract from PDF."""
    body_parts: list[str] = []

    for el in elements:
        if not el.text.strip():
            body_parts.append('<p>&nbsp;</p>')
            continue

        text = _xml_escape(el.text)

        # Insert clickable links
        if el.links:
            for link in el.links:
                safe_url = link.url.replace("&", "&amp;").replace('"', "&quot;")
                safe_text = _xml_escape(link.text)
                if safe_text in text:
                    anchor = f'<a href="{safe_url}">{safe_text}</a>'
                    text = text.replace(safe_text, anchor, 1)

        if el.type == "heading":
            body_parts.append(f'<h2>{text}</h2>')
        elif el.type == "subheading":
            body_parts.append(f'<h3>{text}</h3>')
        elif el.bold:
            body_parts.append(f'<p><strong>{text}</strong></p>')
        else:
            body_parts.append(f'<p>{text}</p>')

    body = '\n'.join(body_parts)
    return _wrap_html(body, style=_DEFAULT_CSS)


# ═══════════════════════════════════════════════════════════════
#  HTML → DOCX
# ═══════════════════════════════════════════════════════════════

def html_to_docx(html_content: str) -> bytes:
    """Convert HTML to DOCX using htmldocx (wraps python-docx).
    Extracts only the body inner HTML since htmldocx doesn't handle
    full document wrappers (<html>, <head>, <style>)."""
    if not HAS_HTMLDOCX:
        raise RuntimeError("htmldocx is required for HTML→DOCX conversion")

    from docx import Document

    # Strip the full document wrapper — htmldocx expects just body-level HTML
    body_html = _extract_body_html(html_content)

    parser = HtmlToDocx()
    doc = Document()
    parser.add_html_to_document(body_html, doc)

    buffer = io.BytesIO()
    doc.save(buffer)
    return buffer.getvalue()


# ═══════════════════════════════════════════════════════════════
#  HTML → PDF
# ═══════════════════════════════════════════════════════════════

async def html_to_pdf_async(html_content: str) -> bytes:
    """Convert HTML to PDF asynchronously using Playwright (headless Chromium).
    Runs the synchronous Playwright call in a thread pool to avoid blocking
    the async event loop. Falls back to reportlab if Playwright unavailable."""
    import asyncio

    if HAS_PLAYWRIGHT:
        try:
            loop = asyncio.get_running_loop()
            pdf_bytes = await loop.run_in_executor(None, _playwright_pdf, html_content)
            return pdf_bytes
        except Exception as e:
            log.warning("Playwright PDF generation failed: %s", e)

    # Fallback: extract plain text and use reportlab
    log.info("Falling back to text-based PDF generation via reportlab")
    text = extract_text_from_html(html_content)
    from app.services.PDF_service import generate_pdf
    return generate_pdf(text)


def _playwright_pdf(html_content: str) -> bytes:
    """Render HTML to PDF using headless Chromium via Playwright."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        html_path = os.path.join(tmp_dir, "resume.html")
        pdf_path = os.path.join(tmp_dir, "resume.pdf")

        with open(html_path, "w", encoding="utf-8") as f:
            f.write(html_content)

        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page()
            page.goto(f"file://{html_path}")
            page.pdf(
                path=pdf_path,
                format="letter",
                margin={
                    "top": "0.5in",
                    "right": "0.7in",
                    "bottom": "0.5in",
                    "left": "0.7in",
                },
                print_background=True,
            )
            browser.close()

        with open(pdf_path, "rb") as f:
            return f.read()


# ═══════════════════════════════════════════════════════════════
#  HTML validation / sanitization
# ═══════════════════════════════════════════════════════════════

def validate_html(html: str) -> str:
    """Validate and sanitize HTML using BeautifulSoup.
    Ensures well-formed HTML after LLM editing.

    Defensively strips ```html ... ``` code fences first,
    since many local models ignore the "no markdown" instruction.
    """
    import re

    raw = html.strip()
    if not raw:
        return html

    # Strip ```html ... ``` or ``` ... ``` fences unconditionally.
    # Running these regexes on non-fenced content is a no-op (no match -> no replacement),
    # so we don't need a startswith guard — this also catches fences that are
    # preceded by commentary (e.g. "Here is the tailored section:\n```html\n...").
    raw = re.sub(r"^```[a-zA-Z]*\n?", "", raw)
    raw = re.sub(r"\n?```$", "", raw)
    raw = raw.strip()

    if not HAS_BS4:
        return raw

    soup = BeautifulSoup(raw, "html.parser")

    # Remove any script or style that might have been injected
    for tag in soup.find_all(["script", "style"]):
        tag.decompose()

    return str(soup)


# ═══════════════════════════════════════════════════════════════
#  Helpers
# ═══════════════════════════════════════════════════════════════

_DEFAULT_CSS = """
body {
    font-family: Calibri, Arial, Helvetica, sans-serif;
    font-size: 11pt;
    line-height: 1.4;
    color: #1a1a1a;
    max-width: 7.5in;
    margin: 0 auto;
    padding: 0.5in 0.7in;
}
h1 {
    font-family: Calibri, Arial, Helvetica, sans-serif;
    font-size: 18pt;
    color: #1A1A2E;
    margin-bottom: 4pt;
}
h2 {
    font-family: Calibri, Arial, Helvetica, sans-serif;
    font-size: 13pt;
    color: #1A1A2E;
    margin-top: 14pt;
    margin-bottom: 6pt;
    border-bottom: 1px solid #ddd;
    padding-bottom: 3pt;
}
h3 {
    font-family: Calibri, Arial, Helvetica, sans-serif;
    font-size: 12pt;
    color: #1A1A2E;
    margin-top: 10pt;
    margin-bottom: 4pt;
}
p {
    margin-top: 2pt;
    margin-bottom: 4pt;
}
strong, b {
    font-weight: bold;
}
ul, ol {
    margin-top: 2pt;
    margin-bottom: 4pt;
    padding-left: 22pt;
}
li {
    margin-bottom: 2pt;
}
a {
    color: #0563C1;
    text-decoration: underline;
}
"""


def _wrap_html(body_html: str, style: str = "") -> str:
    """Wrap HTML body content in a full document with CSS."""
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<style>
{style}
</style>
</head>
<body>
{body_html}
</body>
</html>"""


# ═══════════════════════════════════════════════════════════════
#  HTML Section Parsing (for section-by-section tailoring)
# ═══════════════════════════════════════════════════════════════

def _is_heading_like(element) -> bool:
    """
    Dynamically detect if an HTML element looks like a section heading.

    Detects:
    1. <h1>-<h4> tags (standard HTML headings)
    2. <p> elements that are ALL-CAPS and short (< 60 chars)
    3. <p> elements whose first child is <strong>/<b> and text is short (< 60 chars)
    4. <p> elements that are short, bold-looking, don't end with period

    This makes section parsing fully dynamic — works with any resume template.
    """
    tag_name = getattr(element, "name", None) or ""
    if tag_name.lower() in ("h1", "h2", "h3", "h4"):
        return True

    if tag_name.lower() not in ("p", "div"):
        return False

    text = element.get_text(strip=True)
    if not text or len(text) > 60:
        return False

    # ALL-CAPS short line — must also contain a recognized section word
    # (filters out dates like "JANUARY 2020" or data lines like "PHONE 555-0100")
    if text.isupper() and len(text) >= 3:
        text_lower = text.lower()
        common_section_words = _get_section_words()
        for word in common_section_words:
            if word in text_lower:
                return True
        return False

    # Has <strong> or <b> as direct first non-whitespace child
    first_child = None
    for child in element.children:
        if hasattr(child, "name") and child.name in ("strong", "b"):
            return True
        if child.string and child.string.strip():
            break
        break

    # Short line that starts with common resume section words
    common_section_words = _get_section_words()
    if len(text) < 40 and not text.endswith("."):
        text_lower = text.lower()
        for word in common_section_words:
            if (text_lower == word or text_lower.startswith(word)) and text_lower[:3].isalpha():
                return True

    return False


# Shared section word list (used by both HTML and text parsers)
_COMMON_SECTION_WORDS = [
    "summary", "profile", "objective",
    "experience", "employment", "history", "work",
    "education", "academic",
    "skill", "technolog", "competenc", "expertise",
    "project", "certification", "publication",
    "award", "honor", "language", "interest",
    "reference", "volunteer", "leadership",
    "professional", "qualification", "training",
    "affiliation", "activity", "internship",
    "research", "achievement", "background",
    "core", "additional", "development",
]


def _get_section_words() -> list[str]:
    """Get the list of recognized section heading words."""
    return _COMMON_SECTION_WORDS


def parse_html_into_sections(full_html: str) -> list[dict]:
    """
    Parse the full resume HTML into sections split by heading-like elements.
    Dynamically detects ANY heading-like element:
    - <h1>-<h4> tags
    - <p><strong>HEADING</strong></p>
    - ALL-CAPS short paragraphs
    - Bold short paragraphs

    Returns a list of dicts:
        {
            "type": str,               # Dynamically classified section type
            "editable": True,           # Always True — LLM decides what to rewrite
            "html": str,               # Section's HTML wrapped with CSS
            "body_html": str,          # Just the body content (no html/head/style wrapper)
            "section_name": str,       # Section heading text normalized
        }

    All sections are editable. The LLM prompt instructs it not to change
    names, job titles, company names, dates, or factual information.
    """
    if not HAS_BS4:
        return [{
            "type": "unknown",
            "editable": True,
            "html": full_html,
            "body_html": _extract_body_html(full_html),
            "section_name": "full_resume",
        }]

    soup = BeautifulSoup(full_html, "html.parser")
    body = soup.find("body")
    if not body:
        return [{
            "type": "unknown",
            "editable": True,
            "html": full_html,
            "body_html": full_html,
            "section_name": "full_resume",
        }]

    # Extract style from head for re-wrapping
    head_style = _DEFAULT_CSS
    head = soup.find("head")
    if head:
        style_tag = head.find("style")
        if style_tag and style_tag.string:
            head_style = style_tag.string

    sections = []
    current_heading_text = ""
    current_nodes: list = []

    for child in body.children:
        if not getattr(child, "name", None):
            # Text node or NavigableString — append to current section
            current_nodes.append(child)
            continue

        if _is_heading_like(child):
            # Save previous section
            if current_nodes:
                sections.append({
                    "type": _classify_section(current_heading_text),
                    "editable": True,
                    "body_html": _nodes_to_html(current_nodes),
                    "html": _wrap_html(_nodes_to_html(current_nodes), style=head_style),
                    "section_name": current_heading_text.lower().strip(),
                })

            # Start new section with this heading
            current_heading_text = child.get_text(strip=True)
            current_nodes = [child]
        else:
            current_nodes.append(child)

    # Save the last section
    if current_nodes:
        sections.append({
            "type": _classify_section(current_heading_text),
            "editable": True,
            "body_html": _nodes_to_html(current_nodes),
            "html": _wrap_html(_nodes_to_html(current_nodes), style=head_style),
            "section_name": current_heading_text.lower().strip(),
        })

    return sections


def _nodes_to_html(nodes: list) -> str:
    """Convert a list of BeautifulSoup nodes back to HTML string."""
    return "".join(str(node) for node in nodes)


def _classify_section(heading_text: str) -> str:
    """
    Dynamically classify a section based on its heading text.
    Returns a readable type string for logging/debugging.
    """
    text = heading_text.lower().strip()

    if not text:
        return "preamble"
    if "summary" in text or "profile" in text or "objective" in text:
        return "summary"
    if "experience" in text or "employment" in text or "history" in text:
        return "experience"
    if "skill" in text or "technolog" in text or "competenc" in text:
        return "skills"
    if "education" in text or "academic" in text:
        return "education"
    if "project" in text:
        return "projects"
    if "certification" in text or "license" in text:
        return "certifications"
    if "publication" in text or "award" in text or "honor" in text:
        return "publications"
    if "language" in text:
        return "languages"
    if "volunteer" in text:
        return "volunteer"
    return "other"


def reassemble_html(sections: list[dict]) -> str:
    """
    Reassemble the full HTML document from tailored sections.
    Each section's body_html is concatenated and wrapped.
    """
    body_parts = [s["body_html"] for s in sections]
    body_html = "\n".join(body_parts)
    return _wrap_html(body_html, style=_DEFAULT_CSS)


def _xml_escape(text: str) -> str:
    """Escape XML special characters."""
    text = text.replace("&", "&amp;")
    text = text.replace("<", "&lt;")
    text = text.replace(">", "&gt;")
    text = text.replace('"', "&quot;")
    return text


def _extract_body_html(html: str) -> str:
    """Extract just the inner HTML of the <body> tag.
    If no body tag found, return the original HTML as-is."""
    if HAS_BS4:
        soup = BeautifulSoup(html, "html.parser")
        body = soup.find("body")
        if body:
            return "".join(str(child) for child in body.children)
    return html


def extract_text_from_html(html: str) -> str:
    """Extract plain text from HTML for fallback PDF generation.
    Public function used by API endpoints."""
    if HAS_BS4:
        soup = BeautifulSoup(html, "html.parser")
        return soup.get_text(separator="\n").strip()

    import re
    text = re.sub(r"<[^>]+>", "\n", html)
    text = re.sub(r"\n\s*\n", "\n\n", text)
    return text.strip()


def plain_text_to_html(text: str) -> str:
    """Wrap plain text in basic HTML paragraphs.
    Used as fallback when HTML conversion is unavailable."""
    safe_text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    lines = "\n".join(f"<p>{line}</p>" for line in safe_text.split("\n") if line.strip())
    return _wrap_html(lines, style=_DEFAULT_CSS)
