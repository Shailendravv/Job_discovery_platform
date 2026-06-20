"""
Resume tailoring service.
Uses Groq to rewrite resume sections based on job description.
"""

import json
import logging
from app.core.llm import call_llm
from app.models.resume_elements import ResumeElement

log = logging.getLogger(__name__)

TAILOR_PROMPT = """You are a professional resume writer. Given a candidate's resume and a job description,
rewrite the resume to best match the job requirements.

Candidate's Resume:
{resume_text}

Job Title: {job_title}
Job Description:
{job_description}

Required Skills: {job_skills}

Instructions:
1. Write a compelling Professional Summary that aligns with the job requirements
2. Reorder and rewrite experience bullets to emphasize relevant skills and achievements
3. Tailor the skills section to prioritize skills mentioned in the job description
4. Keep all factual information accurate — do NOT fabricate experience or qualifications
5. Use strong action verbs and quantify achievements where possible
6. Format as a clean, professional resume with clear sections

Return the complete tailored resume as plain text only. Do not include markdown formatting."""

TAILOR_STRUCTURED_PROMPT = """You are a professional resume writer. You will receive a candidate's
resume as a JSON array of elements, and a job description. Rewrite the resume
to best match the job, returning the SAME JSON shape back.

Each input element has: "text", "type" (heading/subheading/bullet/normal),
"bold" (true/false), "links" (array of {{text, url}}).

Candidate's Resume (JSON):
{resume_json}

Job Title: {job_title}
Job Description:
{job_description}
Required Skills: {job_skills}

Instructions:
1. Rewrite "text" fields to better match the job — stronger action verbs,
   relevant keywords, quantified achievements where the original supports it.
2. You may reorder bullet elements within a section to put the most relevant
   ones first. Do NOT reorder heading elements or move bullets across sections.
3. Do NOT fabricate experience, employers, dates, or qualifications not present
   in the input.
4. Preserve "type", "bold", and "links" EXACTLY as given on each element you keep.
   If you split one bullet into two, copy the original element's "type" and
   "bold" onto both, and keep "links" only on the one that contains the link text.
5. Do not add new elements with links you invented. Do not delete elements that
   contain a link unless their text becomes truly redundant.

Return ONLY a JSON object in the format: {{"elements": [...]}}
where each element has the same shape as the input.
No markdown, no commentary, no code fences — raw JSON only."""

TAILOR_HTML_PROMPT = """You are a professional resume writer. You will receive a candidate's resume
as formatted HTML, and a job description. Rewrite the resume text to best match
the job requirements.

CRITICAL RULE: You must PRESERVE all HTML tags and structure EXACTLY as they are.
Only change the TEXT content between tags.
- DO NOT add, remove, or modify any HTML tags or attributes
- DO NOT change heading text (section names like "Experience" are fine as-is)
- You MAY rewrite bullet items and paragraph text
- Preserve ALL <a href="..."> tags and their href attributes

Candidate's Resume HTML:
{resume_html}

Job Title: {job_title}
Job Description:
{job_description}
Required Skills: {job_skills}

Instructions:
1. Rewrite paragraph and bullet text to use stronger action verbs and keywords.
2. Reorder bullet points within sections to put the most relevant ones first.
3. Keep all factual information accurate — do NOT fabricate experience.
4. Return ONLY the modified HTML — no commentary, no markdown formatting."""


async def tailor_resume_text(resume_text: str, job: dict) -> str:
    """
    Tailor resume text to match a job description.

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

    prompt = TAILOR_PROMPT.format(
        resume_text=resume_text[:12000],  # Truncate to avoid token limits
        job_title=job_title,
        job_description=job_description[:8000],
        job_skills=job_skills or "Not specified",
    )

    try:
        tailored = call_llm(prompt, json_format=False)
        return tailored.strip()
    except Exception as e:
        log.error("Resume tailoring failed: %s", e, exc_info=True)
        # Return original on failure
        return resume_text


async def tailor_resume_html(resume_html: str, job: dict) -> str:
    """
    Tailor resume HTML content to match a job description.
    Preserves all HTML tags and structure; only modifies text content.

    Args:
        resume_html: Full HTML of the resume.
        job: Job document from MongoDB with title, description, skills, etc.

    Returns:
        Tailored resume as HTML.
    """
    if not resume_html or not resume_html.strip():
        return resume_html

    job_title = job.get("title", "Unknown Position")
    job_description = job.get("description", "")
    job_skills = ", ".join(job.get("skills", []))

    # Truncate HTML to avoid token limits (HTML is verbose)
    truncated_html = resume_html[:14000]

    prompt = TAILOR_HTML_PROMPT.format(
        resume_html=truncated_html,
        job_title=job_title,
        job_description=job_description[:8000],
        job_skills=job_skills or "Not specified",
    )

    try:
        tailored = call_llm(prompt, json_format=False)
        # Validate/sanitize the returned HTML
        from app.services.html_service import validate_html

        return validate_html(tailored.strip())
    except Exception as e:
        log.error("HTML resume tailoring failed: %s", e, exc_info=True)
        return resume_html


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
        raw = call_llm(prompt, json_format=True)
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
