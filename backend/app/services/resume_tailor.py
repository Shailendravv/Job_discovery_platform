"""
Resume tailoring service.
Uses Groq to rewrite resume sections based on job description.
"""
import logging
from app.core.llm import call_llm

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
        tailored = call_llm(prompt, json_format=False, provider="groq")
        return tailored.strip()
    except Exception as e:
        log.error("Resume tailoring failed: %s", e, exc_info=True)
        # Return original on failure
        return resume_text
