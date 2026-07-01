"""
Shared data model for structured resume elements.
Flows through extraction → tailoring → rendering.
"""

from pydantic import BaseModel
from typing import Literal, Optional


class ResumeLink(BaseModel):
    """A hyperlink with display text and URL."""
    text: str
    url: str


class ResumeElement(BaseModel):
    """
    One structural unit of a resume: a heading, a bullet, a paragraph line,
    or a contact-info line. This is the single shape that flows through
    extraction -> tailoring -> rendering.
    """
    text: str
    type: Literal["heading", "subheading", "bullet", "normal"] = "normal"
    bold: bool = False
    links: list[ResumeLink] = []
    # font/size are optional overrides; if None, renderer uses its default
    # for that `type`. Only set when extraction found an explicit value
    # worth preserving (e.g., a DOCX run with unusual size).
    font_size_pt: Optional[float] = None
