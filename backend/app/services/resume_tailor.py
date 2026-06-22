"""
Resume tailoring service.

Processes resume section-by-section instead of sending the entire resume
in one LLM call — preventing truncation and keeping the model focused on
one section's content at a time.

Each editable section (summary, experience, skills) gets its own LLM call
with the full job description for context. Non-editable sections
(education, contact info, etc.) are passed through unchanged.
"""

import json
import logging
import os
import tempfile

from app.core.llm import call_llm_async
from app.models.resume_elements import ResumeElement
from app.services.html_service import (
    parse_html_into_sections,
    reassemble_html,
    _extract_body_html,
    validate_html,
)

log = logging.getLogger(__name__)


# ── Section types that should NEVER be sent to the LLM ──
# These are purely factual sections (institutions, degrees, dates, license names)
# where rewriting would only introduce errors or JD content bleed.
_NON_EDITABLE_SECTION_TYPES = frozenset({
    "education",
    "certifications",
    "languages",
    "publications",
})


# ── Section-level HTML prompt (one section at a time) ──

SECTION_HTML_PROMPT = """You are a professional resume writer. You are tailoring ONE section of a resume to match a job description.

<job_title>{job_title}</job_title>

<job_description>
{job_description}
</job_description>

<required_skills>{job_skills}</required_skills>

<resume_section type="{section_type}" name="{section_name}">
{section_html}
</resume_section>

Instructions:
1. Only rewrite the content that is inside the <resume_section>...</resume_section> tags. Do NOT add content that was not already inside those tags.
2. Everything inside the <job_description> is reference material only — never copy its headings, structure, sentences, or boilerplate into your output.
3. Rewrite the TEXT CONTENT of the <resume_section> to better align with the job's top skills. Use stronger action verbs. Keep the same facts, same entities, same experiences, same roles.
4. CRITICAL: PRESERVE ALL HTML TAGS AND STRUCTURE EXACTLY as they are. Only change text content between tags.
5. CRITICAL: Do NOT change your name, contact info, job titles, company names, dates, or section headings.
6. Keep all factual information accurate — do NOT fabricate experience, titles, dates, or metrics.
7. If this section is already a strong match for the JD, return it unchanged.
8. Return ONLY the modified HTML that belongs inside <resume_section> — no commentary, no markdown formatting, no code fences."""


# ── Section-level plain text prompt ──

SECTION_TEXT_PROMPT = """You are a professional resume writer. You are tailoring ONE section of a resume to match a job description.

<job_title>{job_title}</job_title>

<job_description>
{job_description}
</job_description>

<required_skills>{job_skills}</required_skills>

<resume_section type="{section_type}" name="{section_name}">
{section_text}
</resume_section>

Instructions:
1. Only rewrite the content that is inside the <resume_section>...</resume_section> tags. Do NOT add content that was not already inside those tags.
2. Everything inside the <job_description> is reference material only — never copy its headings, structure, sentences, or boilerplate into your output.
3. Rewrite the TEXT CONTENT of the <resume_section> to better align with the job's top skills. Use stronger action verbs. Keep the same facts, same entities, same experiences, same roles.
4. CRITICAL: Do NOT change your name, job titles, company names, dates, or section headings.
5. Keep all factual information accurate — do NOT fabricate experience, titles, dates, or metrics.
6. Use strong action verbs specific to the job's domain to reword the existing content.
7. If this section is already a strong match for the JD, return it unchanged.
8. Return ONLY the modified content that belongs inside <resume_section> — no commentary, no markdown formatting, no tags, no fences."""


# ── Section parsing for plain text resumes (dynamic) ──

# Common resume section heading words — if an ALL-CAPS or short line
# contains any of these, it's treated as a section heading.
_SECTION_HEADING_WORDS = [
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


def _is_text_heading_line(stripped: str, *, prev_line_empty: bool = True) -> bool:
    """Dynamically check if a plain text line looks like a section heading.

    Args:
        stripped: The stripped text of the current line.
        prev_line_empty: Whether the preceding line was empty (blank line).
                         Section headings in resumes are always preceded by
                         a blank line — without this guard, short capitalized
                         lines inside bullet content get misidentified.
    """
    if not stripped or len(stripped) > 60:
        return False

    # A genuine section heading is almost always preceded by a blank line.
    # Without this guard, short capitalized lines inside bullets (e.g. a
    # project name or inline skill label) get misidentified as headings.
    if not prev_line_empty:
        return False

    # ALL-CAPS line (most resume section headers)
    if stripped.isupper() and len(stripped) >= 3:
        # Filter out meaningless all-caps lines like dates, BUT NOT section headers
        # A section header will contain at least one recognizable word
        lower_stripped = stripped.lower()
        for word in _SECTION_HEADING_WORDS:
            if word in lower_stripped:
                return True
        return False

    # Title-case or sentence-case short line with common heading words
    if len(stripped) < 40:
        lower_stripped = stripped.lower()
        for word in _SECTION_HEADING_WORDS:
            if lower_stripped == word or lower_stripped.startswith(word):
                return True

    return False


def _classify_text_section(heading_text: str) -> str:
    """Dynamically classify a text section based on its heading."""
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


def _split_text_into_sections(text: str) -> list[dict]:
    """
    Split plain text into sections by dynamically detecting heading lines.

    Uses heuristics:
    1. Section headings must be preceded by a blank line (or start of text).
    2. ALL-CAPS short lines containing section-like words
    3. Short lines (< 40 chars) with common section heading words
    4. Content before the first detected heading is treated as "preamble"

    ALL sections are editable — the LLM decides what to rewrite.

    Returns:
        List of dicts with keys: type (str), content (str), heading (str)
    """
    lines = text.split("\n")
    sections = []
    current_type = "preamble"
    current_heading = ""
    current_lines = []

    for i, line in enumerate(lines):
        stripped = line.strip()

        # A line must be preceded by a blank line (or be the first line)
        # to be considered a section heading. This prevents short capitalized
        # lines inside bullet content (skill names, project names) from being
        # misidentified as section boundaries.
        prev_line_empty = i == 0 or not lines[i - 1].strip()

        if _is_text_heading_line(stripped, prev_line_empty=prev_line_empty):
            # Save previous section
            if current_lines:
                sections.append({
                    "type": current_type,
                    "heading": current_heading,
                    "content": "\n".join(current_lines).strip(),
                })

            # Start new section
            current_type = _classify_text_section(stripped)
            current_heading = stripped
            current_lines = [stripped]
        else:
            current_lines.append(line)

    # Save last section
    if current_lines:
        sections.append({
            "type": current_type,
            "heading": current_heading,
            "content": "\n".join(current_lines).strip(),
        })

    return sections


# ═══════════════════════════════════════════════════════════════
#  HTML Tailoring (section-by-section)
# ═══════════════════════════════════════════════════════════════

async def tailor_resume_html(resume_html: str, job: dict) -> str:
    """
    Tailor resume HTML content to match a job description.

    Processes the resume ONE SECTION AT A TIME (split by <h2>/<h3> boundaries).
    Each section gets its own LLM call, preventing truncation and keeping the
    model focused on one section at a time.

    Args:
        resume_html: Full HTML of the resume.
        job: Job document from MongoDB with title, description, skills, etc.

    Returns:
        Tailored resume as full HTML document.
    """
    if not resume_html or not resume_html.strip():
        return resume_html

    job_title = job.get("title", "Unknown Position")
    job_description = job.get("description", "")
    job_skills = ", ".join(job.get("skills", []))

    # ── Parse into sections ──
    try:
        sections = parse_html_into_sections(resume_html)
    except Exception as e:
        log.warning("HTML section parsing failed (%s), falling back to whole-document tailoring", e)
        return await _fallback_html_tailor(resume_html, job)

    if not sections:
        log.warning("No sections found in resume HTML, falling back to whole-document tailoring")
        return await _fallback_html_tailor(resume_html, job)

    log.info(
        "Resume has %d sections: %s",
        len(sections),
        [s["type"] for s in sections],
    )        # ── Process each section ──
    tailored_count = 0
    for section in sections:
        section_type = section.get("type", "unknown")
        section_name = section.get("section_name", "")
        section_body = section.get("body_html", "")

        if not section_body.strip():
            continue

        # Skip purely factual sections (education, certifications, etc.)
        # These should NEVER be sent to the LLM — they are reference-only data.
        if section_type in _NON_EDITABLE_SECTION_TYPES:
            log.debug("Skipping non-editable section '%s' (%s)", section_type, section_name)
            continue

        # Truncate section content if needed (sections should be small, but safety check)
        truncated_section = section_body[:6000]

        prompt = SECTION_HTML_PROMPT.format(
            section_html=truncated_section,
            section_type=section_type,
            section_name=section_name or section_type,
            job_title=job_title,
            job_description=job_description[:10000],
            job_skills=job_skills or "Not specified",
        )

        try:
            tailored = await call_llm_async(prompt, json_format=False, max_tokens=4096)

            # Debug: log raw LLM output to diagnose JD content bleed issues
            log.debug("Raw LLM output for section '%s': %r", section_type, tailored[:300])

            # Validate the tailored section HTML
            validated = validate_html(tailored.strip())
            if validated and len(validated) > 10:
                # Extract just the body HTML from the validated response
                section["body_html"] = _extract_body_html(validated) or validated
                tailored_count += 1
                log.debug("Section '%s' tailored successfully (%d chars)", section_type, len(validated))
            else:
                log.warning("Section '%s' returned empty/too-short response — keeping original", section_type)
        except Exception as e:
            log.error("Section '%s' tailoring failed: %s — keeping original", section_type, e)

    log.info("Tailored %d / %d sections", tailored_count, len(sections))

    # ── Reassemble ──
    try:
        return reassemble_html(sections)
    except Exception as e:
        log.error("HTML reassembly failed: %s — returning original", e)
        return resume_html


# ── Fallback prompt with explicit education preservation instruction ──

FALLBACK_HTML_PROMPT = """You are a professional resume writer. You are tailoring a resume to match a job description.

<job_title>{job_title}</job_title>

<job_description>
{job_description}
</job_description>

<required_skills>{job_skills}</required_skills>

<resume>
{resume_html}
</resume>

IMPORTANT — PRESERVE THESE SECTIONS EXACTLY AS WRITTEN (do NOT modify any content under these headings):
- EDUCATION (or "Academic Background", "Academic History"): institutions, degrees, dates, and all content must remain EXACTLY as in the original.
- CERTIFICATIONS (or "Certifications & Licenses"): must remain EXACTLY as in the original.
- LANGUAGES: must remain EXACTLY as in the original.
- PUBLICATIONS (or "Publications & Awards"): must remain EXACTLY as in the original.

Instructions:
1. Rewrite only the work experience, skills, summary/profile sections — even if they use different headings like "Professional Experience", "Technical Skills", "Career Summary", "Work History", etc.
2. Everything inside <job_description> is reference material only — never copy its headings, structure, sentences, or boilerplate into your output.
3. Rewrite TEXT CONTENT to better align with the job's top skills. Use stronger action verbs.
4. CRITICAL: PRESERVE ALL HTML TAGS AND STRUCTURE EXACTLY as they are. Only change text content between tags.
5. CRITICAL: Do NOT change your name, contact info, job titles, company names, dates, or section headings.
6. Keep all factual information accurate — do NOT fabricate experience, titles, dates, or metrics.
7. If a section is already a strong match for the JD, return it unchanged.
8. Return ONLY the modified HTML — no commentary, no markdown formatting, no code fences."""


async def _fallback_html_tailor(resume_html: str, job: dict) -> str:
    """
    Fallback: send the entire resume HTML in one call.
    Used only if section parsing completely fails.

    Uses a dedicated prompt that explicitly lists which sections
    must be preserved verbatim (education, certifications, etc.).
    """
    job_title = job.get("title", "Unknown Position")
    job_description = job.get("description", "")
    job_skills = ", ".join(job.get("skills", []))

    truncated_html = resume_html[:12000]

    prompt = FALLBACK_HTML_PROMPT.format(
        resume_html=truncated_html,
        job_title=job_title,
        job_description=job_description[:8000],
        job_skills=job_skills or "Not specified",
    )

    try:
        tailored = await call_llm_async(prompt, json_format=False, max_tokens=4096)
        return validate_html(tailored.strip())
    except Exception as e:
        log.error("Fallback HTML tailoring failed: %s", e)
        return resume_html


# ═══════════════════════════════════════════════════════════════
#  Plain Text Tailoring (section-by-section)
# ═══════════════════════════════════════════════════════════════

async def tailor_resume_text(resume_text: str, job: dict) -> str:
    """
    Tailor resume text to match a job description.

    Processes the resume ONE SECTION AT A TIME by detecting section
    heading patterns. Each section gets its own LLM call.

    Args:
        resume_text: Full extracted text of the resume.
        job: Job document from MongoDB with title, description, skills, etc.

    Returns:
        Tailored resume as plain text.
    """
    if not resume_text or not resume_text.strip():
        return resume_text

    job_title = job.get("title", "Unknown Position")
    job_description = job.get("description", "")
    job_skills = ", ".join(job.get("skills", []))

    # ── Parse into sections ──
    sections = _split_text_into_sections(resume_text)

    if not sections:
        log.warning("No sections found in resume text, returning original")
        return resume_text

    log.info(
        "Resume text has %d sections: %s",
        len(sections),
        [s["type"] for s in sections],
    )

    # ── Process each section ──
    tailored_count = 0
    for section in sections:
        section_type = section.get("type", "unknown")
        section_content = section.get("content", "")

        if not section_content.strip():
            continue

        # Skip purely factual sections (education, certifications, etc.)
        # These should NEVER be sent to the LLM — they are reference-only data.
        if section_type in _NON_EDITABLE_SECTION_TYPES:
            log.debug("Skipping non-editable text section '%s' (%s)", section_type, section.get("heading", ""))
            continue

        # Truncate section content as safety net
        truncated_content = section_content[:6000]

        prompt = SECTION_TEXT_PROMPT.format(
            section_text=truncated_content,
            section_type=section_type,
            section_name=section_type,
            job_title=job_title,
            job_description=job_description[:10000],
            job_skills=job_skills or "Not specified",
        )

        try:
            tailored = await call_llm_async(prompt, json_format=False, max_tokens=4096)
            tailored = tailored.strip()

            # Debug: log raw LLM output to diagnose JD content bleed issues
            log.debug("Raw LLM output for section '%s': %r", section_type, tailored[:300])

            if tailored and len(tailored) > 10:
                # Preserve the section heading if the LLM dropped it
                heading = section.get("heading", "")
                if heading and not tailored.startswith(heading):
                    tailored = heading + "\n" + tailored
                section["content"] = tailored
                tailored_count += 1
                log.debug("Section '%s' tailored successfully (%d chars)", section_type, len(tailored))
            else:
                log.warning("Section '%s' returned empty response — keeping original", section_type)
        except Exception as e:
            log.error("Section '%s' tailoring failed: %s — keeping original", section_type, e)

    log.info("Tailored %d / %d text sections", tailored_count, len(sections))

    # ── Reassemble ──
    result_parts = []
    current_type = None
    for section in sections:
        # Add spacing between sections
        if current_type is not None:
            result_parts.append("")
        result_parts.append(section["content"])
        current_type = section["type"]

    return "\n".join(result_parts).strip()


# ═══════════════════════════════════════════════════════════════
#  Structured Element Tailoring (unchanged)
# ═══════════════════════════════════════════════════════════════

TAILOR_STRUCTURED_PROMPT = """You are a professional resume writer. You will receive a candidate's
resume as a JSON array of elements, and a job description. Rewrite the resume
to best match the job, returning the SAME JSON shape back.

Each input element has: "text", "type" (heading/subheading/bullet/normal),
"bold" (true/false), "links" (array of {{text, url}}).

<job_title>{job_title}</job_title>

<job_description>
{job_description}
</job_description>

<required_skills>{job_skills}</required_skills>

<resume_elements>
{resume_json}
</resume_elements>

Instructions:
1. Only rewrite the "text" fields of elements inside <resume_elements>...</resume_elements>.
2. Everything inside <job_description> is reference material only — never copy its
   headings, structure, sentences, or boilerplate into your output.
3. Rewrite "text" fields to better match the job — stronger action verbs,
   relevant keywords, quantified achievements where the original supports it.
4. You may reorder bullet elements within a section to put the most relevant
   ones first. Do NOT reorder heading elements or move bullets across sections.
5. Do NOT add new elements, sections, experiences, education entries, projects,
   or skills that did not exist in the input.
6. Do NOT fabricate experience, employers, dates, or qualifications not present
   in the input.
7. Preserve "type", "bold", and "links" EXACTLY as given on each element you keep.
   If you split one bullet into two, copy the original element's "type" and
   "bold" onto both, and keep "links" only on the one that contains the link text.
8. Do not add new elements with links you invented. Do not delete elements that
   contain a link unless their text becomes truly redundant.

Return ONLY a JSON object in the format: {{"elements": [...]}}
where each element has the same shape as the input.
No markdown, no commentary, no code fences — raw JSON only."""


async def tailor_resume_structured(
    elements: list[ResumeElement], job: dict
) -> list[ResumeElement]:
    """
    Tailor structured resume elements to match a job description.
    Preserves bold/type/links per element; only rewrites "text" content
    (and may reorder bullets within a section).
    """
    if not elements:
        return elements

    resume_json = json.dumps(
        [el.model_dump() for el in elements], ensure_ascii=False, indent=2
    )[:16000]

    job_title = job.get("title", "Unknown Position")
    job_description = job.get("description", "")
    job_skills = ", ".join(job.get("skills", []))

    prompt = TAILOR_STRUCTURED_PROMPT.format(
        resume_json=resume_json,
        job_title=job_title,
        job_description=job_description[:8000],
        job_skills=job_skills or "Not specified",
    )

    try:
        raw = await call_llm_async(prompt, json_format=True, max_tokens=4096)
        parsed = json.loads(raw) if isinstance(raw, str) else raw
        if isinstance(parsed, dict) and "elements" in parsed:
            raw_elements = parsed["elements"]
        elif isinstance(parsed, list):
            raw_elements = parsed
        else:
            log.error("Unexpected JSON structure from LLM: %s", type(parsed))
            return elements

        tailored: list[ResumeElement] = []
        for el in raw_elements:
            try:
                tailored.append(ResumeElement(**el))
            except Exception as inner_e:
                log.warning("Skipping malformed element from LLM: %s", inner_e)
                continue

        return tailored if tailored else elements
    except Exception as e:
        log.error("Structured resume tailoring failed: %s", e, exc_info=True)
        return elements


# ═══════════════════════════════════════════════════════════════
#  New Engine Integration
# ═══════════════════════════════════════════════════════════════

async def tailor_resume_docx_v2(
    docx_bytes: bytes,
    job: dict,
    output_format: str = "docx",
) -> dict:
    """
    Tailor a resume using the new formatting-preserving engine.

    This function:
    1. Saves docx_bytes to a temporary file
    2. Runs the content-map-based tailoring pipeline
    3. Returns the tailored DOCX bytes (and optionally PDF)

    Args:
        docx_bytes: Raw DOCX bytes of the original resume.
        job: Job document from MongoDB.
        output_format: "docx" for DOCX, "pdf" for PDF, or "both".

    Returns:
        Dict with keys:
            - "docx_bytes": Tailored DOCX bytes (if output_format is "docx" or "both")
            - "pdf_bytes": Tailored PDF bytes (if output_format is "pdf" or "both")
            - "rewrites_applied": Number of rewrites applied
            - "error": Error message if failed (optional)
    """
    from app.services.resume_tailor_engine import tailor_resume

    job_title = job.get("title", "")
    job_description = job.get("description", "")
    job_skills = job.get("skills", [])

    with tempfile.TemporaryDirectory() as tmp_dir:
        input_path = os.path.join(tmp_dir, "original_resume.docx")
        output_path = os.path.join(tmp_dir, "tailored_resume.docx")

        with open(input_path, "wb") as f:
            f.write(docx_bytes)

        result = tailor_resume(
            docx_path=input_path,
            job_description=job_description,
            job_title=job_title,
            job_skills=job_skills,
            output_path=output_path,
        )

        if not result.success:
            return {
                "error": result.error or "Unknown tailoring error",
                "rewrites_applied": 0,
            }

        with open(output_path, "rb") as f:
            tailored_docx_bytes = f.read()

        response: dict = {
            "docx_bytes": tailored_docx_bytes,
            "rewrites_applied": result.rewrites_applied,
        }

        if output_format in ("pdf", "both"):
            try:
                from app.services.html_service import docx_to_html, html_to_pdf_async
                tailored_html = docx_to_html(tailored_docx_bytes)
                pdf_bytes = await html_to_pdf_async(tailored_html)
                response["pdf_bytes"] = pdf_bytes
            except Exception as e:
                log.warning("PDF conversion from tailored DOCX failed: %s", e)

        if result.needs_manual_review:
            log.info(
                "%d spans flagged for manual review (mixed formatting): %s",
                len(result.needs_manual_review),
                result.needs_manual_review[:3],
            )

        return response
