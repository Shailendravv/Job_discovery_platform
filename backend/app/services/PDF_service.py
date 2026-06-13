from pypdf import PdfReader
from reportlab.lib.pagesizes import LETTER
from reportlab.pdfgen import canvas
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
from app.services.docx_service import generate_docx as _gen_docx
import io


def extract_text_from_pdf(file_bytes: bytes) -> str:
    reader = PdfReader(io.BytesIO(file_bytes))
    return "\n".join(page.extract_text() or "" for page in reader.pages)


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


def generate_docx(text: str) -> bytes:
    """Delegate to docx_service for DOCX generation."""
    return _gen_docx(text)
