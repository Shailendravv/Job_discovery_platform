"""
HTML-based resume formatting service.
DOCX ──mammoth──▶ HTML, PDF ──PyMuPDF──▶ elements ──elements_to_html()──▶ HTML
HTML ──htmldocx──▶ DOCX
HTML ──playwright──▶ PDF
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
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn

    # Strip the full document wrapper — htmldocx expects just body-level HTML
    body_html = _extract_body_html(html_content)

    doc = Document()

    # ── Add bottom border to Heading 2 and 3 (matches PDF .section-header border-bottom) ──
    for level in (2, 3):
        style = doc.styles[f"Heading {level}"]
        pPr = style.element.get_or_add_pPr()
        # Check if a border element already exists
        existing = pPr.findall(qn("w:pBdr"))
        if not existing:
            pBdr = OxmlElement("w:pBdr")
            bottom = OxmlElement("w:bottom")
            bottom.set(qn("w:val"), "single")
            bottom.set(qn("w:sz"), "4")       # ~0.25 pt
            bottom.set(qn("w:space"), "4")     # gap between text and line
            bottom.set(qn("w:color"), "E0E0E0")
            pBdr.append(bottom)
            pPr.append(pBdr)

    parser = HtmlToDocx()
    parser.add_html_to_document(body_html, doc)

    buffer = io.BytesIO()
    doc.save(buffer)
    return buffer.getvalue()


# ═══════════════════════════════════════════════════════════════
#  HTML → PDF
# ═══════════════════════════════════════════════════════════════

async def html_to_pdf_async(html_content: str, format: str = "Letter") -> bytes:
    """Convert HTML to PDF asynchronously using Playwright (headless Chromium).

    Args:
        html_content: Full HTML document string.
        format: Paper size — "Letter" (US/Canada) or "A4" (rest of world).

    Runs the synchronous Playwright call in a thread pool to avoid blocking
    the async event loop. Falls back to reportlab if Playwright unavailable."""
    import asyncio

    if HAS_PLAYWRIGHT:
        try:
            loop = asyncio.get_running_loop()
            pdf_bytes = await loop.run_in_executor(None, _playwright_pdf, html_content, format)
            return pdf_bytes
        except Exception as e:
            log.warning("Playwright PDF generation failed: %s", e)

    # Fallback: extract plain text and use reportlab
    log.info("Falling back to text-based PDF generation via reportlab")
    text = extract_text_from_html(html_content)
    from app.services.PDF_service import generate_pdf
    return generate_pdf(text)


def _playwright_pdf(html_content: str, format: str = "Letter") -> bytes:
    """Render HTML to PDF using headless Chromium via Playwright.

    Args:
        html_content: Full HTML document string.
        format: Paper size — "Letter" or "A4".
    """
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
                format=format,
                margin={
                    "top": "0.6in",
                    "right": "0.6in",
                    "bottom": "0.6in",
                    "left": "0.6in",
                },
                print_background=True,
            )
            browser.close()

        with open(pdf_path, "rb") as f:
            return f.read()


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
