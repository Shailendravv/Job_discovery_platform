"""
DOCX file handling service.
"""
import io
from docx import Document
from docx.shared import Pt, Inches, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn
from docx.oxml import OxmlElement

from app.models.resume_elements import ResumeElement, ResumeLink


def extract_text_from_docx(file_bytes: bytes) -> str:
    """Extract plain text from a DOCX file."""
    doc = Document(io.BytesIO(file_bytes))
    paragraphs = []
    for p in doc.paragraphs:
        text = p.text.strip()
        if text:
            paragraphs.append(text)
    return "\n".join(paragraphs)


def extract_structured_from_docx(file_bytes: bytes) -> list[ResumeElement]:
    """
    Extract paragraphs as structured elements preserving bold flags and
    hyperlink URLs. This is ground truth — bold/links come from the actual
    OOXML runs, not a guess based on text shape.
    """
    doc = Document(io.BytesIO(file_bytes))
    elements: list[ResumeElement] = []

    for p in doc.paragraphs:
        if not p.text.strip():
            continue

        is_bold = bool(p.runs) and any(r.bold for r in p.runs if r.text.strip())
        is_heading_style = p.style.name.startswith("Heading")

        links: list[ResumeLink] = []
        for hyperlink in p._p.findall(qn("w:hyperlink")):
            r_id = hyperlink.get(qn("r:id"))
            if r_id and r_id in doc.part.rels:
                url = doc.part.rels[r_id].target_ref
                link_text = "".join(node.text or "" for node in hyperlink.iter(qn("w:t")))
                if link_text:
                    links.append(ResumeLink(text=link_text, url=url))

        el_type = "heading" if (is_bold or is_heading_style) else "normal"

        elements.append(ResumeElement(
            text=p.text.strip(),
            type=el_type,
            bold=is_bold or is_heading_style,
            links=links,
        ))

    return elements


def generate_docx(text: str) -> bytes:
    """
    Generate a well-formatted DOCX file from plain text.

    Detects section headers (all caps or short lines) and formats them
    with Heading style for a professional look.
    """
    doc = Document()

    # Set default font
    style = doc.styles["Normal"]
    font = style.font
    font.name = "Calibri"
    font.size = Pt(11)

    # Configure heading styles
    for i in range(1, 4):
        heading_style = doc.styles[f"Heading {i}"]
        heading_style.font.name = "Calibri"
        heading_style.font.color.rgb = RGBColor(0x1A, 0x1A, 0x2E)

    lines = text.split("\n")
    for line in lines:
        stripped = line.strip()
        if not stripped:
            doc.add_paragraph("")
            continue

        # Detect section headers: all caps (e.g., "PROFESSIONAL SUMMARY")
        # or short centered-style lines
        if stripped.isupper() and len(stripped) < 60:
            p = doc.add_paragraph(stripped, style="Heading 2")
            p.alignment = WD_ALIGN_PARAGRAPH.LEFT
        elif len(stripped) < 40 and stripped.endswith(":") and not stripped[0].islower():
            # Sub-headers like "Experience:" or "Education:"
            p = doc.add_paragraph(stripped, style="Heading 3")
        else:
            doc.add_paragraph(stripped)

    buffer = io.BytesIO()
    doc.save(buffer)
    return buffer.getvalue()


def add_hyperlink_run(paragraph, url: str, text: str, bold: bool = False, color: str = "0563C1"):
    """Add a clickable hyperlink run to a paragraph."""
    part = paragraph.part
    r_id = part.relate_to(
        url,
        "http://schemas.openxmlformats.org/officeDocument/2006/relationships/hyperlink",
        is_external=True,
    )
    hyperlink = OxmlElement("w:hyperlink")
    hyperlink.set(qn("r:id"), r_id)

    new_run = OxmlElement("w:r")
    rPr = OxmlElement("w:rPr")
    color_el = OxmlElement("w:color")
    color_el.set(qn("w:val"), color)
    rPr.append(color_el)
    underline = OxmlElement("w:u")
    underline.set(qn("w:val"), "single")
    rPr.append(underline)
    if bold:
        rPr.append(OxmlElement("w:b"))
    new_run.append(rPr)

    t = OxmlElement("w:t")
    t.text = text
    new_run.append(t)
    hyperlink.append(new_run)
    paragraph._p.append(hyperlink)


def generate_docx_from_elements(elements: list[ResumeElement]) -> bytes:
    """
    Render a DOCX from structured elements, applying real bold formatting,
    proper heading styles, and real clickable hyperlinks.
    """
    doc = Document()

    # ── Configure default font ──
    normal_style = doc.styles["Normal"]
    normal_style.font.name = "Calibri"
    normal_style.font.size = Pt(11)
    normal_style.paragraph_format.space_after = Pt(4)
    normal_style.paragraph_format.space_before = Pt(0)

    # ── Configure heading styles ──
    for i in range(1, 4):
        heading_style = doc.styles[f"Heading {i}"]
        heading_style.font.name = "Calibri"
        heading_style.font.color.rgb = RGBColor(0x1A, 0x1A, 0x2E)
        heading_style.paragraph_format.space_before = Pt(10)
        heading_style.paragraph_format.space_after = Pt(4)

    for el in elements:
        if not el.text.strip():
            continue

        # ── Determine paragraph style ──
        if el.type == "heading":
            p = doc.add_paragraph(el.text, style="Heading 2")
        elif el.type == "subheading":
            p = doc.add_paragraph(el.text, style="Heading 3")
        else:
            # Normal text (may have bold and/or hyperlinks)
            p = doc.add_paragraph()

            if el.links:
                _render_text_with_hyperlinks(p, el)
            else:
                run = p.add_run(el.text)
                run.bold = el.bold
                if el.font_size_pt:
                    run.font.size = Pt(el.font_size_pt)

    buffer = io.BytesIO()
    doc.save(buffer)
    return buffer.getvalue()


def _render_text_with_hyperlinks(paragraph, el: ResumeElement):
    """Render an element's text with inline hyperlinks into a paragraph.
    Uses partition() to split text around link text, and only creates
    hyperlink runs when the link text is actually found in the element text.
    Applies font_size_pt override to all runs if present.
    """
    remaining = el.text
    for link in el.links:
        before, sep, rest = remaining.partition(link.text)
        if sep:
            # Link text was found — add text before the link (if any), then the hyperlink
            if before:
                run = paragraph.add_run(before)
                run.bold = el.bold
                if el.font_size_pt:
                    run.font.size = Pt(el.font_size_pt)
            add_hyperlink_run(paragraph, link.url, link.text, bold=el.bold)
            remaining = rest
        else:
            # Link text not found in element text — skip this link silently
            pass

    # Add any remaining text after the last link
    if remaining:
        run = paragraph.add_run(remaining)
        run.bold = el.bold
        if el.font_size_pt:
            run.font.size = Pt(el.font_size_pt)
