"""
ATS-Optimised HTML template renderer.

Loads cv-template.html and replaces {{PLACEHOLDER}} tokens with
section HTML built from structured resume data.
"""

import logging
from pathlib import Path

log = logging.getLogger(__name__)

_HEADER_CACHE: dict[str, str] = {}


def _section_header(title: str) -> str:
    if title not in _HEADER_CACHE:
        _HEADER_CACHE[title] = f'<h2 class="section-header">{_xml_escape(title)}</h2>'
    return _HEADER_CACHE[title]


def render_cv_template(
    lang: str = "en",
    page_width: str = "8.5in",
    name: str = "",
    contact_items: str = "",
    summary_text: str = "",
    competency_tags: str = "",
    experience_html: str = "",
    projects_html: str = "",
    education_html: str = "",
    certifications_html: str = "",
    skills_html: str = "",
) -> str:
    """
    Render the ATS-optimised CV template with the given section HTML.

    Each section is rendered only when its corresponding HTML is non-empty.
    Empty sections produce no heading and no content.
    """
    template_path = Path(__file__).resolve().parent.parent.parent / "templates" / "cv-template.html"
    html = template_path.read_text(encoding="utf-8")

    replacements = {
        "{{LANG}}": lang,
        "{{PAGE_WIDTH}}": page_width,
        "{{NAME}}": _xml_escape(name),
        "{{CONTACT_ITEMS}}": contact_items,
        "{{SECTION_SUMMARY}}": _section_header("Professional Summary") if summary_text else "",
        "{{SUMMARY_HTML}}": f'<p class="summary-text">{_xml_escape(summary_text)}</p>' if summary_text else "",
        "{{SECTION_COMPETENCIES}}": _section_header("Core Competencies") if competency_tags else "",
        "{{COMPETENCIES_HTML}}": f'<p class="competency-grid">{competency_tags}</p>' if competency_tags else "",
        "{{SECTION_EXPERIENCE}}": _section_header("Work Experience") if experience_html else "",
        "{{EXPERIENCE_HTML}}": experience_html,
        "{{SECTION_PROJECTS}}": _section_header("Projects") if projects_html else "",
        "{{PROJECTS_HTML}}": projects_html,
        "{{SECTION_EDUCATION}}": _section_header("Education") if education_html else "",
        "{{EDUCATION_HTML}}": education_html,
        "{{SECTION_CERTIFICATIONS}}": _section_header("Certifications") if certifications_html else "",
        "{{CERTIFICATIONS_HTML}}": certifications_html,
        "{{SECTION_SKILLS}}": _section_header("Skills") if skills_html else "",
        "{{SKILLS_HTML}}": f'<p class="skills-text">{skills_html}</p>' if skills_html else "",
    }

    for placeholder, value in replacements.items():
        html = html.replace(placeholder, value)
    return html


def build_contact_items(
    email: str = "",
    phone: str = "",
    location: str = "",
    linkedin_url: str = "",
    linkedin_display: str = "LinkedIn",
    portfolio_url: str = "",
    portfolio_display: str = "Portfolio",
) -> str:
    """Build the contact row HTML with pipe separators between items."""
    parts: list[str] = []
    if email:
        parts.append(f'<span>{_xml_escape(email)}</span>')
    if phone:
        parts.append(f'<span>{_xml_escape(phone)}</span>')
    if location:
        parts.append(f'<span>{_xml_escape(location)}</span>')
    if linkedin_url:
        parts.append(f'<a href="{_xml_escape(linkedin_url)}">{_xml_escape(linkedin_display)}</a>')
    if portfolio_url:
        parts.append(f'<a href="{_xml_escape(portfolio_url)}">{_xml_escape(portfolio_display)}</a>')

    result = ""
    for i, part in enumerate(parts):
        if i > 0:
            result += '<span class="separator"> | </span>'
        result += part
    return result


def build_competency_tags(keywords: list[str]) -> str:
    """Build competency tag HTML from a list of keyword phrases."""
    return " ".join(
        f'<span class="competency-tag">{_xml_escape(kw)}</span>'
        for kw in keywords
    )


def build_experience_html(experience: list[dict]) -> str:
    """Build Work Experience section HTML with reordered bullets."""
    parts: list[str] = []
    for exp in experience:
        company = _xml_escape(exp.get("company", ""))
        title = _xml_escape(exp.get("title", ""))
        duration = _xml_escape(exp.get("duration", ""))
        description = exp.get("description", "")

        parts.append('<div class="experience-entry">')
        title_line = title
        if company:
            title_line += f' — {company}'
        parts.append(f'<h3 class="experience-header">{title_line}</h3>')
        if duration:
            parts.append(f'<p class="duration">{duration}</p>')

        if description:
            bullets = [b.strip() for b in description.split("\n") if b.strip()]
            if len(bullets) > 1:
                bullet_html = "\n".join(
                    f"<li>{_xml_escape(b.lstrip('-•*').strip())}</li>" for b in bullets
                )
                parts.append(f'<ul class="experience-bullets">{bullet_html}</ul>')
            else:
                parts.append(f'<p class="summary-text">{_xml_escape(bullets[0])}</p>')

        parts.append('</div>')
    return "\n".join(parts)


def build_projects_html(projects: list[dict]) -> str:
    """Build Projects section HTML (top N most relevant)."""
    parts: list[str] = []
    for proj in projects:
        name = _xml_escape(proj.get("name", ""))
        desc = proj.get("description", "")
        parts.append('<div class="project-entry">')
        parts.append(f'<h4 class="project-name">{name}</h4>')
        if desc:
            lines = [l.strip() for l in desc.split("\n") if l.strip()]
            if len(lines) > 1:
                bullet_html = "\n".join(
                    f"<li>{_xml_escape(l.lstrip('-•*').strip())}</li>" for l in lines
                )
                parts.append(f'<ul class="experience-bullets">{bullet_html}</ul>')
            else:
                parts.append(f'<p class="project-description">{_xml_escape(lines[0])}</p>')
        parts.append('</div>')
    return "\n".join(parts)


def build_education_html(education: list[dict]) -> str:
    """Build Education section HTML (preserved data, never sent to LLM)."""
    parts: list[str] = []
    for edu in education:
        institution = _xml_escape(edu.get("institution", ""))
        degree = _xml_escape(edu.get("degree", ""))
        year = edu.get("year", "")
        text_parts = [p for p in [degree, institution, str(year) if year else ""] if p]
        if text_parts:
            parts.append(f'<p class="education-entry">{", ".join(text_parts)}</p>')
    return "\n".join(parts)


def build_certifications_html(certifications: list[str]) -> str:
    """Build Certifications section HTML (preserved data)."""
    return "\n".join(
        f'<p class="cert-entry">{_xml_escape(c)}</p>'
        for c in certifications
    )


def _xml_escape(text: str) -> str:
    if not text:
        return ""
    text = text.replace("&", "&amp;")
    text = text.replace("<", "&lt;")
    text = text.replace(">", "&gt;")
    text = text.replace('"', "&quot;")
    return text
