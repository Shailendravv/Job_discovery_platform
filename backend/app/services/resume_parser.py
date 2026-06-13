"""
LLM-powered resume parser service.
Uses Groq to extract structured data from resume text.
"""
import json
import re
import logging
from app.core.llm import call_llm

log = logging.getLogger(__name__)

PARSE_PROMPT_TEMPLATE = """You are a resume parser. Extract structured information from the following resume text.
Return ONLY valid JSON with this exact structure:
{{
  "name": "Full Name",
  "email": "email@example.com",
  "phone": "phone number",
  "education": [{{"institution": "University", "degree": "Degree Name", "year": 2024}}],
  "experience": [{{"company": "Company", "title": "Job Title", "duration": "2020-2024", "description": "What they did"}}],
  "skills": ["Skill1", "Skill2"],
  "languages": ["Language1"],
  "certifications": ["Cert1"]
}}

Use null for missing fields. For education year, use integer or null.
For experience duration, use string like "2020-2024" or "3 years".
Do not include markdown formatting or code blocks. Return ONLY the JSON.

RESUME TEXT:
{extracted_text}"""


async def parse_resume_text(extracted_text: str) -> dict:
    """
    Parse resume text into structured data using Groq LLM.

    Returns a dict with keys: name, email, phone, education, experience, skills, languages, certifications.
    Missing fields will have None or empty list values.
    """
    if not extracted_text or not extracted_text.strip():
        return {"name": "", "email": "", "phone": "", "education": [], "experience": [], "skills": [], "languages": [], "certifications": []}

    prompt = PARSE_PROMPT_TEMPLATE.format(extracted_text=extracted_text[:15000])  # Truncate to avoid token limits

    try:
        raw_response = call_llm(prompt, json_format=True, provider="groq")

        # Clean response: strip markdown code blocks
        cleaned = re.sub(r"^```(?:json)?\s*", "", raw_response).strip()
        cleaned = re.sub(r"\s*```$", "", cleaned).strip()

        parsed = json.loads(cleaned)

        # Ensure all expected keys exist
        return {
            "name": parsed.get("name"),
            "email": parsed.get("email"),
            "phone": parsed.get("phone"),
            "education": parsed.get("education", []),
            "experience": parsed.get("experience", []),
            "skills": parsed.get("skills", []),
            "languages": parsed.get("languages", []),
            "certifications": parsed.get("certifications", []),
        }
    except json.JSONDecodeError as e:
        log.error("Failed to parse LLM response as JSON: %s", e)
        log.debug("Raw response: %s", raw_response)
        # Return raw text as fallback
        return {
            "name": "",
            "email": "",
            "phone": "",
            "education": [],
            "experience": [],
            "skills": [],
            "languages": [],
            "certifications": [],
            "_raw_text": extracted_text[:1000],
            "_parse_error": str(e),
        }
    except Exception as e:
        log.error("Resume parsing failed: %s", e, exc_info=True)
        return {
            "name": "",
            "email": "",
            "phone": "",
            "education": [],
            "experience": [],
            "skills": [],
            "languages": [],
            "certifications": [],
            "_raw_text": extracted_text[:1000],
            "_parse_error": str(e),
        }
