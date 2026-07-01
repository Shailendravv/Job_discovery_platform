from pypdf import PdfReader
from reportlab.lib.pagesizes import LETTER
from reportlab.pdfgen import canvas
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.units import inch
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
from app.services.docx_service import generate_docx as _gen_docx
from app.models.resume_elements import ResumeElement, ResumeLink
import fitz  # PyMuPDF
import io


def extract_text_from_pdf(file_bytes: bytes) -> str:
    reader = PdfReader(io.BytesIO(file_bytes))
    return "\n".join(page.extract_text() or "" for page in reader.pages)


def extract_structured_from_pdf(file_bytes: bytes) -> list[ResumeElement]:
    """
    Extract structured elements from a PDF using font metadata as a proxy
    for bold/heading, and page link annotations for hyperlinks.

    Heuristic, not ground truth: bold is inferred from font name and size
    relative to the page's most common (body) font size.
    """
    elements: list[ResumeElement] = []

    with fitz.open(stream=file_bytes, filetype="pdf") as doc:
        # First pass: collect font sizes to find the body-text baseline
        sizes = []
        for page in doc:
            for block in page.get_text("dict")["blocks"]:
                for line in block.get("lines", []):
                    for span in line.get("spans", []):
                        sizes.append(round(span["size"]))
        body_size = max(set(sizes), key=sizes.count) if sizes else 11

        for page_num, page in enumerate(doc):
            # Map link annotations by their bounding box for this page
            page_links = page.get_links()  # [{"from": Rect, "uri": str, ...}, ...]

            for block in page.get_text("dict")["blocks"]:
                for line in block.get("lines", []):
                    line_text = "".join(span["text"] for span in line.get("spans", [])).strip()
                    if not line_text:
                        continue

                    spans = line.get("spans", [])
                    font_name = spans[0]["font"] if spans else ""
                    size = round(spans[0]["size"]) if spans else body_size
                    is_bold = "bold" in font_name.lower() or "black" in font_name.lower()
                    is_heading = is_bold or size > body_size + 1

                    # Attach any link whose rect overlaps this line's bbox
                    links: list[ResumeLink] = []
                    line_bbox = fitz.Rect(line["bbox"])
                    for link in page_links:
                        if "uri" in link and line_bbox.intersects(link["from"]):
                            links.append(ResumeLink(text=line_text, url=link["uri"]))

                    elements.append(ResumeElement(
                        text=line_text,
                        type="heading" if is_heading else "normal",
                        bold=is_bold,
                        links=links,
                        font_size_pt=float(size),
                    ))

    return elements


def generate_pdf(text: str) -> bytes:
    """Generate a well-formatted PDF from plain text."""
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=LETTER, rightMargin=72, leftMargin=72, topMargin=72, bottomMargin=72)
    styles = getSampleStyleSheet()

    story = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            story.append(Spacer(1, 6))
        elif stripped.isupper() and len(stripped) < 60:
            # Section header
            p = Paragraph(stripped, styles["Heading2"])
            story.append(p)
            story.append(Spacer(1, 4))
        else:
            p = Paragraph(stripped, styles["Normal"])
            story.append(p)

    doc.build(story)
    return buffer.getvalue()


def _xml_escape(text: str) -> str:
    """
    Escape XML special characters for use in reportlab Paragraph text.
    Must be called BEFORE inserting any <a> tags to avoid double-escaping.
    """
    text = text.replace("&", "&amp;")
    text = text.replace("<", "&lt;")
    text = text.replace(">", "&gt;")
    text = text.replace('"', "&quot;")
    return text


def _element_text_with_links(el: ResumeElement) -> str:
    """
    Convert a ResumeElement's text and links into reportlab-compatible
    XML with clickable anchor tags (<a href="url">text</a>).
    Text is XML-escaped first, then links are wrapped in <a> tags.
    """
    # XML-escape the full text first
    text = _xml_escape(el.text)

    if not el.links:
        return text

    # Insert anchor tags for each link (escape URL as well)
    for link in el.links:
        escaped_link_text = _xml_escape(link.text)
        if escaped_link_text in text:
            safe_url = link.url.replace("&", "&amp;").replace('"', "&quot;")
            anchor = f'<a href="{safe_url}" color="blue">{escaped_link_text}</a>'
            text = text.replace(escaped_link_text, anchor, 1)

    return text


def generate_pdf_from_elements(elements: list[ResumeElement]) -> bytes:
    """
    Render a PDF from structured resume elements, preserving bold text,
    proper heading styles, and clickable hyperlinks.
    Uses reportlab with proper built-in heading styles for the best output.
    """
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=LETTER,
        rightMargin=72, leftMargin=72,
        topMargin=72, bottomMargin=72
    )
    styles = getSampleStyleSheet()

    # ── Build a bold variant of the Normal style ──
    bold_style = ParagraphStyle(
        "ResumeBold",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        spaceBefore=2,
        spaceAfter=4,
    )
    normal_style = styles["Normal"]
    normal_style.spaceBefore = 2
    normal_style.spaceAfter = 4

    # ── Tweak heading styles ──
    h2 = styles["Heading2"]
    h2.fontName = "Helvetica-Bold"
    h2.fontSize = 13
    h2.spaceBefore = 12
    h2.spaceAfter = 6
    h2.textColor = None  # use default (black)

    h3 = styles["Heading3"]
    h3.fontName = "Helvetica-Bold"
    h3.fontSize = 12
    h3.spaceBefore = 10
    h3.spaceAfter = 4
    h3.textColor = None

    story = []
    for el in elements:
        if not el.text.strip():
            story.append(Spacer(1, 6))
            continue

        styled_text = _element_text_with_links(el)

        if el.type == "heading":
            p = Paragraph(styled_text, h2)
        elif el.type == "subheading":
            p = Paragraph(styled_text, h3)
        elif el.bold:
            p = Paragraph(styled_text, bold_style)
        else:
            p = Paragraph(styled_text, normal_style)

        story.append(p)

    doc.build(story)
    return buffer.getvalue()


def generate_pdf_from_docx(docx_bytes: bytes) -> bytes:
    """
    Convert DOCX bytes to PDF.

    The recommended approach for production is LibreOffice headless conversion:
        soffice --headless --convert-to pdf resume.docx

    This fallback simply extracts text from the DOCX. For full formatting
    preservation, use generate_pdf_from_elements() directly from the
    ResumeElement list instead.
    """
    from app.services.docx_service import extract_text_from_docx
    return generate_pdf(extract_text_from_docx(docx_bytes))


def generate_docx(text: str) -> bytes:
    """Delegate to docx_service for DOCX generation."""
    return _gen_docx(text)
