"""
DOCX file handling service.
"""
import io
from docx import Document
from docx.shared import Pt, Inches, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH


def extract_text_from_docx(file_bytes: bytes) -> str:
    """Extract plain text from a DOCX file."""
    doc = Document(io.BytesIO(file_bytes))
    paragraphs = []
    for p in doc.paragraphs:
        text = p.text.strip()
        if text:
            paragraphs.append(text)
    return "\n".join(paragraphs)


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
