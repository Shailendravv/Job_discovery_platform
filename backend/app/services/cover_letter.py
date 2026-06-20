"""
Cover letter generation service.
Uses Groq to write a professional cover letter based on resume and job description.
"""

import logging
from app.core.llm import call_llm

log = logging.getLogger(__name__)

COVER_LETTER_PROMPT = """You are a professional cover letter writer. Write a compelling cover letter
for a job application.

Candidate Name: {candidate_name}
Candidate Skills: {candidate_skills}
Candidate Experience Summary:
{candidate_experience}

Job Title: {job_title}
Company Name: {company_name}
Job Description:
{job_description}

Instructions:
1. Address the letter to "Dear Hiring Manager"
2. First paragraph: Express enthusiasm for the role and the company, mention the specific position
3. Second paragraph: Connect the candidate's relevant skills and experience to the job requirements with specific examples
4. Third paragraph: Show knowledge of the company/industry and how the candidate can contribute
5. Closing paragraph: Reiterate interest, include a call to action, thank the reader
6. Sign with the candidate's name
7. Keep it to 3-4 paragraphs, professional tone
8. Do NOT include placeholders like [Your Name] — use the actual candidate name

Return the complete cover letter as plain text only. Do not include markdown formatting."""


async def generate_cover_letter(
    candidate_name: str,
    candidate_skills: list,
    candidate_experience: str,
    job_title: str,
    company_name: str,
    job_description: str,
) -> str:
    """
    Generate a professional cover letter for a job application.

    Args:
        candidate_name: Full name of the candidate.
        candidate_skills: List of candidate's skills.
        candidate_experience: Summary or full text of candidate's work experience.
        job_title: Title of the job being applied for.
        company_name: Name of the hiring company.
        job_description: Full job description text.

    Returns:
        Cover letter as plain text.
    """
    if not candidate_name:
        candidate_name = "Applicant"

    prompt = COVER_LETTER_PROMPT.format(
        candidate_name=candidate_name,
        candidate_skills=(
            ", ".join(candidate_skills)
            if candidate_skills
            else "Various professional skills"
        ),
        candidate_experience=(
            candidate_experience[:4000] if candidate_experience else "Not provided"
        ),
        job_title=job_title,
        company_name=company_name or "Your Company",
        job_description=job_description[:6000] if job_description else "Not provided",
    )

    try:
        letter = call_llm(prompt, json_format=False)
        return letter.strip()
    except Exception as e:
        log.error("Cover letter generation failed: %s", e, exc_info=True)
        return f"Dear Hiring Manager,\n\nI am writing to express my interest in the {job_title} position at {company_name}. "
