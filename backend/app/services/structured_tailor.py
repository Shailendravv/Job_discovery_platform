"""
Structured Resume Tailoring Service.

Pipeline:
    Parsed Resume JSON
        │
        ├── Remove Name (PII)
        ├── Remove Email (PII)
        ├── Remove Phone (PII)
        ├── Remove Education (factual — preserved as-is)
        ├── Remove Certifications (factual — preserved as-is)
        │
        ▼
    Try single LLM call with FULL payload
        │
        ├── Success → done
        │
        └── Failure (rate-limit 429):
                ├── Retry after 10s
                ├── Retry after 20s
                ├── Retry after 30s
                └── Still failing → fall back to chunked approach
                    Split into 2-3 chunks
                    Call LLM once per chunk
                    Merge results
        │
        ▼
    Re-inject Education + Certifications + PII
        │
        ▼
    Generate Final HTML → DOCX / PDF

Uses OpenRouter free-tier models with automatic fallback chain.
Maximum 1 LLM call in the happy path; up to 4+ in worst case (1 single + 3 chunks).
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import Optional

from app.services.llm import get_llm_provider
from app.services.pii_service import extract_pii, reinject_pii

log = logging.getLogger(__name__)

# ── Thresholds ──────────────────────────────────────────────────
# If the editable JSON payload exceeds this, split into chunks.
# Each chunk gets its own LLM call with full JD context.
_MAX_CHUNK_CHARS = 8000

# ── Retry Configuration ────────────────────────────────────────────
# When the single-call approach hits a rate-limit (429), retry
# with increasing delays before falling through to chunking.
# Delays: 1st retry=10s, 2nd=20s, 3rd=30s
_RETRY_DELAYS = [10, 20, 30]
_MAX_RETRIES = len(_RETRY_DELAYS)


# ═══════════════════════════════════════════════════════════════
#  System Prompt — ATS Resume Optimization Engine
# ═══════════════════════════════════════════════════════════════

SYSTEM_PROMPT_TEMPLATE = """# System Role

You are an expert ATS Resume Optimization Engine.

Your task is to tailor a resume for a specific job description while maintaining factual accuracy.

## Critical Rules

1. Never invent experience that does not exist.
2. Never create fake companies.
3. **Never create fake projects.** Only include projects explicitly present in the original resume data. Do not invent project names, even if they sound plausible given the candidate's domain expertise. If the original has N projects, the tailored version must also have exactly N projects — not fewer, not more.
4. Never create fake certifications.
5. Never create fake education.
6. Never fabricate years of experience.
7. Never claim ownership of technologies the candidate has never used.
8. Preserve all factual information.
9. Improve wording, impact, ATS compatibility, and keyword alignment.
10. Optimize for ATS parsing.
11. **Never copy text from the Job Description into the Professional Summary.** The summary must only rephrase the candidate's actual experience and skills. Do not inject JD phrasing, responsibilities, or requirements into the summary.
12. **Every claim in the Professional Summary must be verifiable** from the candidate's experience, skills, or projects sections below. Do not make claims that cannot be traced back to the candidate's own resume data.
13. **Preserve the original format and structure of each section.** Do not convert paragraphs to bullet points, bullet points to paragraphs, or change the overall structure of any section.
    *Exception: The Skills section may be regrouped and reordered by category as specified in the Skills Section instructions below.*
14. **Do not expand content beyond what is present in the original resume.** Rephrase and reword existing content only. Do not add new sentences, claims, achievements, details, technologies, or metrics that were not in the original resume data. **Crucially, do not copy content from the Experience or Projects sections into the Professional Summary.** The Summary should only rephrase what was already in the original summary — it should not become a digest of the entire resume.
15. **Do not add new sub-headings, category labels, duration summaries, or meta-descriptions** to any section that were not present in the original resume.
16. **Never add contact information (LinkedIn URLs, GitHub URLs, personal websites, portfolio links, or any social media profiles)** that were not present in the original resume. Only include contact details explicitly present in the resume data.

---

## Input

You will receive:

### Candidate Resume JSON (partial — editable sections only)

This contains:

* Professional Summary
* Skills
* Work Experience
* Projects

PII, education, and certifications have already been removed as they are factual data that must be preserved exactly.

### Job Description

Raw job description text.

---

## Objective

Analyze the Job Description and identify:

* Required skills
* Preferred skills
* Technologies
* Responsibilities
* Keywords
* Domain terminology

Then optimize the resume to improve alignment.

---

## Allowed Modifications

### Professional Summary

You may:

* Rewrite the summary to improve flow, clarity, and impact
* Emphasize existing skills and domain expertise that align with the job
* Rephrase the candidate's own achievements more effectively

CRITICAL — Anti-Copying & Format Preservation:

* **Do NOT copy any text from the Job Description into the summary.**
* **Do NOT inject keywords just for ATS scoring.** The summary must reflect ONLY the candidate's actual profile, reworded for maximum impact.
* **Preserve the original summary's format EXACTLY.**
  - If the original is a single paragraph → output a single paragraph.
  - If the original has bullet points → keep bullet points.
  - Do NOT add bullet points to a paragraph-formatted summary.
  - Do NOT extract part of the summary as a separate heading or title line.
* **Do NOT add new claims, facts, or details** that are not explicitly present in the original summary text. Only rephrase what is already there.
* **Every claim must be directly quoted or closely paraphrased** from the experience, skills, or projects sections of the resume. If a capability is not present in the candidate's resume data, it must not appear in the summary.
* The summary should sound like a genuine human-written professional profile — not a keyword-stuffed ATS target.

IMPORTANT: Preserve the original summary's length, detail, context, and paragraph structure.
Do NOT shorten it. Do NOT expand it with new content. Maintain all specifics about years of experience,
technologies, domain expertise, and key achievements exactly as stated.

ATS keyword alignment should be handled in the Skills and Experience sections below, not injected into the Professional Summary.

---

### Skills Section

You may:

* Group skills by category
* Reorder skills, putting JD-matching skills first within each group
* Prioritize skills matching the JD

IMPORTANT: Output ALL skills in this exact grouped order within the skills array:
  - Frontend (React.js, Next.js, HTML, CSS, Tailwind, Material UI, etc.)
  - Backend (Node.js, Express.js, FastAPI, Python, REST APIs, etc.)
  - AI/ML/GenAI (OpenAI API, Claude API, LangChain, RAG, Prompt Engineering, etc.)
  - Cloud & DevOps (AWS, GCP, Azure, Docker, CI/CD, etc.)
  - Databases (MongoDB, PostgreSQL, etc.)
  - Tools & Others (Git, Agile, Cross-Functional Collaboration, etc.)

You may only include skills already present in the resume.

**Do NOT infer or assume the candidate knows a technology** because it seems related to their expertise. For example, if the resume only mentions AWS, do not add GCP or Azure. If the resume mentions React.js, do not assume Vue.js or Angular.

---

### Experience Section

You may:

* Rewrite bullet points for better clarity and impact
* Improve action verbs
* Quantify achievements when existing metrics are available (do NOT invent metrics)
* Highlight relevant technologies already used

CRITICAL:
* **Preserve the original structure** — do not add new sub-headings, category labels, duration summaries, or meta-descriptions that were not present in the original.
* **Preserve the original description format.** If the original description is a paragraph → keep it as a paragraph. If it uses bullet points → keep bullet points. Do NOT convert between formats.
* **Do not expand the description** beyond the original level of detail. Only rephrase existing content.
* You must not add technologies that are absent from the candidate's experience.
* Do not add new bullet points or achievements that were not in the original.

---

### Projects

You may:

* Rewrite descriptions for better clarity
* Emphasize relevant technologies already mentioned
* Improve ATS keyword matching using only technologies already present in the description

CRITICAL — No Fabrication:

* **Do not invent projects** — this is already forbidden by Critical Rule #3.
* **Do NOT expand project descriptions** with new details, technologies, features, or outcomes that were not present in the original. Rewording only.
* **Preserve the original description length and level of detail.** If the original was 1-2 sentences, the tailored version must also be 1-2 sentences.
* **Do not add new sections** like "Project Name", "Project Description", or "Technologies Used" labels that were not in the original structure.

---

### Education & Certifications

Not sent to LLM — these factual sections are preserved exactly server-side and merged back into the final output unchanged.

---

## ATS Optimization Rules

Target:

* ATS Friendly
* Keyword Rich (in Skills and Experience sections only)
* Human Readable (especially the Professional Summary)
* Professional Tone

Priority:

1. Required Skills (align in Skills section)
2. Responsibilities (reflect in Experience bullet points)
3. Industry Keywords (integrate naturally only if already implied by existing content)
4. Preferred Skills (secondary alignment in Skills section)

ATS alignment priority by section:
- **Professional Summary:** Do NOT optimize for keywords. Focus on readability and authenticity. No new content.
- **Skills:** Reorder and group skills to prioritize JD-matching ones.
- **Experience:** Incorporate relevant keywords naturally into existing bullet points. Do not add new bullets.
- **Projects:** Do NOT add new technologies or features. Only rephrase existing content with better wording.

---

## Gap Handling

If the Job Description mentions skills that do not exist in the resume:

DO NOT add them.

Instead:

* Increase emphasis on related existing skills.
* Optimize surrounding experience.

---

## Output Requirements

Return ONLY valid JSON.

No markdown.

No explanations.

No comments.

No additional text.

Return the same schema as the input resume (only editable sections).

---

## JSON Schema

{{
"summary": "",
"skills": [],
"experience": [],
"projects": []
}}

---

## Resume JSON

{resume_json}

---

## Job Description

{job_description}"""


# ═══════════════════════════════════════════════════════════════
#  Helpers: Build editable + preserved JSON from parsed data
# ═══════════════════════════════════════════════════════════════


def _extract_summary_from_text(resume_text: str) -> str:
    """Extract a professional summary from raw resume text (heuristic fallback)."""
    lines = [l.strip() for l in resume_text.split("\n") if l.strip()]
    if not lines:
        log.debug("No lines found in resume text for summary extraction")
        return ""

    summary_lines: list[str] = []
    for line in lines:
        if "@" in line or len(line) < 5:
            continue
        if line == line.upper() and len(line) < 60:
            _heading_words = {
                "summary", "profile", "objective", "experience", "employment",
                "work", "education", "skill", "project", "certification",
                "publication", "language", "reference", "training",
            }
            if any(w in line.lower() for w in _heading_words):
                break
        if len(line) > 20:
            summary_lines.append(line)
        if len(summary_lines) >= 3:
            break

    if not summary_lines:
        log.debug("No summary-like section found via heading detection, using first lines fallback")
        for line in lines:
            if len(line) > 15 and "@" not in line:
                summary_lines.append(line)
                if len(summary_lines) >= 2:
                    break

    result = " ".join(summary_lines) if summary_lines else ""
    if result:
        log.debug("Extracted summary (%d chars) via heuristic fallback", len(result))
    return result


def _extract_projects_from_text(resume_text: str) -> list[dict]:
    """Extract project entries from resume text (heuristic fallback)."""
    lines = resume_text.split("\n")
    projects: list[dict] = []
    in_projects_section = False
    buffer: list[str] = []

    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        lower = stripped.lower()

        if lower.startswith("project") and len(stripped) < 60:
            in_projects_section = True
            continue

        if in_projects_section:
            if stripped == stripped.upper() and len(stripped) < 60 and "project" not in lower:
                in_projects_section = False
                continue
            buffer.append(stripped)

    current: dict | None = None
    for line in buffer:
        if not current:
            current = {"name": line, "description": ""}
        elif line[0] in ("-", "•", "*") or (line.startswith("o") and len(line) > 3 and line[1] == " "):
            if current:
                bullet = line.lstrip("-•*o ").strip()
                if current["description"]:
                    current["description"] += "\n" + bullet
                else:
                    current["description"] = bullet
        elif current and current["description"]:
            projects.append(current)
            current = {"name": line, "description": ""}
        else:
            if current:
                if current["description"]:
                    current["description"] += " " + line
                else:
                    current["description"] = line

    if current:
        projects.append(current)

    if projects:
        log.debug("Extracted %d project entries via heuristic fallback", len(projects))
    else:
        log.debug("No projects section found in resume text")
    return projects


# ── Known section headings used for boundary detection ──
_KNOWN_HEADINGS = frozenset({
    "summary", "professional summary", "profile", "objective", "career objective",
    "skills", "technical skills", "core competencies", "key skills",
    "experience", "work experience", "professional experience", "employment",
    "education", "academic background", "qualifications",
    "projects", "project", "personal projects", "professional projects",
    "certifications", "certification", "certificates", "licenses",
    "publications", "publication",
    "languages", "language",
    "references", "reference",
    "interests", "interest", "activities",
    "achievements", "awards", "honors",
    "leadership", "volunteer", "additional",
})
_MAX_FALLBACK_LINES = 80  # hard cap: don't consume more than this per section


def _is_heading_line(stripped: str) -> bool:
    """Check if a line looks like a known section heading."""
    lower = stripped.lower().rstrip(":").strip()
    if lower in _KNOWN_HEADINGS:
        return True
    # Also handle "Technical Skills", "Core Competencies" etc.
    for known in _KNOWN_HEADINGS:
        if known in ("skills",) and lower.endswith("skills"):
            return True
        if known in ("certifications",) and lower.endswith("certifications"):
            return True
    return False


def _parse_year(value: str) -> int | str:
    """Try to parse a year value; return int if possible, else the string."""
    if not value:
        return ""
    try:
        return int(value.strip())
    except ValueError:
        return value.strip()


def _extract_education_from_text(resume_text: str) -> list[dict]:
    """Extract education entries from raw text (heuristic fallback)."""
    lines = resume_text.split("\n")
    in_section = False
    education: list[dict] = []
    line_count = 0

    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue

        if not in_section:
            if _is_heading_line(stripped) and "education" in stripped.lower():
                in_section = True
            continue

        # Inside education section — check for next heading
        if _is_heading_line(stripped) and "education" not in stripped.lower():
            break
        line_count += 1
        if line_count > _MAX_FALLBACK_LINES:
            break

        entry_text = stripped.lstrip("-•*").strip()
        if not entry_text:
            continue

        institution = ""
        degree_text = ""
        year: int | str = ""

        # Try comma-separated: "Degree, Institution, Year" or "Institution, Degree, Year"
        # Also try dash-separated: "Degree — Institution (Year)"
        year_match = re.search(r"(\b\d{4}\b)", entry_text)
        if year_match:
            year = _parse_year(year_match.group(1))

        # Remove year for parsing
        text_no_year = re.sub(r"\(?\b\d{4}\b\)?\s*-?\s*", "", entry_text).strip().rstrip(",").strip()

        # Try comma split
        parts = [p.strip() for p in text_no_year.split(",") if p.strip()]
        if len(parts) >= 2:
            degree_text = parts[0]
            institution = parts[-1]  # Last part is typically institution
        else:
            # Try dash split
            for sep in (" — ", " – ", " - "):
                if sep in text_no_year:
                    dash_parts = [p.strip() for p in text_no_year.split(sep) if p.strip()]
                    if len(dash_parts) >= 2:
                        degree_text = dash_parts[0]
                        institution = dash_parts[-1]
                        break
            else:
                institution = text_no_year

        if institution or degree_text:
            education.append({
                "institution": institution,
                "degree": degree_text,
                "year": year if isinstance(year, int) or year else 0,
            })

    if education:
        log.debug("Extracted %d education entries via heuristic fallback", len(education))
    else:
        log.debug("No education section found in resume text")
    return education


def _extract_skills_from_text(resume_text: str) -> list[str]:
    """Extract skills list from raw text (heuristic fallback)."""
    lines = resume_text.split("\n")
    in_section = False
    skills: list[str] = []
    line_count = 0

    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue

        if not in_section:
            if _is_heading_line(stripped) and "skill" in stripped.lower():
                in_section = True
            continue

        # Detect next section heading
        if _is_heading_line(stripped) and "skill" not in stripped.lower():
            break
        line_count += 1
        if line_count > _MAX_FALLBACK_LINES:
            break

        # Split on comma, semicolon, pipe, bullet
        for s in re.split(r"[,;|•]+", stripped):
            s = s.strip().lstrip("-*").strip()
            if s and len(s) > 1:
                skills.append(s)

    if skills:
        log.debug("Extracted %d skills via heuristic fallback", len(skills))
    else:
        log.debug("No skills section found in resume text")
    return skills


def _extract_experience_from_text(resume_text: str) -> list[dict]:
    """Extract experience entries from raw text (heuristic fallback)."""
    lines = resume_text.split("\n")
    in_section = False
    buffer: list[str] = []
    experience: list[dict] = []
    line_count = 0

    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue

        if not in_section:
            if _is_heading_line(stripped) and "experience" in stripped.lower():
                in_section = True
            continue

        # Detect next section heading (but not "experience")
        if _is_heading_line(stripped) and "experience" not in stripped.lower():
            break
        line_count += 1
        if line_count > _MAX_FALLBACK_LINES:
            break

        buffer.append(stripped)

    # Parse buffer into entries
    current: dict | None = None
    for line_text in buffer:
        is_bullet = line_text and line_text[0] in ("-", "•", "*")

        if not is_bullet:
            if current is None:
                current = {"company": "", "title": "", "duration": "", "description": ""}
                if line_text.lower().startswith("at ") or " at " in line_text.lower():
                    if line_text.lower().startswith("at "):
                        current["company"] = line_text[3:].strip()
                    else:
                        # "Title at Company" or "Title - Company"
                        idx = line_text.lower().index(" at ")
                        current["title"] = line_text[:idx].strip()
                        current["company"] = line_text[idx + 4:].strip()
                else:
                    current["company"] = line_text
            elif current and current.get("description"):
                experience.append(current)
                current = {"company": line_text, "title": "", "duration": "", "description": ""}
            elif current:
                # Could be a duration/date line
                if re.search(r"\d{4}\s*[-–to]+\s*(present|current|\d{4})", line_text, re.IGNORECASE):
                    current["duration"] = line_text.strip()
                elif current["title"]:
                    # Extend company name
                    current["company"] += " " + line_text
                else:
                    # Treat as title line
                    current["title"] = line_text
        else:
            if current is None:
                current = {"company": "", "title": "", "duration": "", "description": ""}
            bullet = line_text.lstrip("-•*").strip()
            if current["description"]:
                current["description"] += "\n" + bullet
            else:
                current["description"] = bullet

    if current:
        experience.append(current)

    if experience:
        log.debug("Extracted %d experience entries via heuristic fallback", len(experience))
    else:
        log.debug("No experience section found in resume text")
    return experience


def _build_editable_and_preserved(parsed_data: dict, resume_text: str) -> tuple[dict, dict]:
    """
    Build TWO JSON dicts:
      - editable: summary, skills, experience, projects  (sent to LLM)
      - preserved: education, certifications              (kept out of LLM, re-injected after)

    PII (name, email, phone) is excluded from BOTH — handled by pii_service separately.

    Args:
        parsed_data: Parsed resume from resume_parser.
        resume_text: Raw text for heuristic fallbacks.

    Returns:
        (editable_dict, preserved_dict)
    """
    # ── Summary ──
    summary = ""
    if isinstance(parsed_data.get("summary"), str) and parsed_data["summary"].strip():
        summary = parsed_data["summary"]
    else:
        summary = _extract_summary_from_text(resume_text)

    # ── Experience ──
    raw_experience = parsed_data.get("experience", [])
    if raw_experience and isinstance(raw_experience, list):
        experience = []
        for exp in raw_experience:
            experience.append({
                "company": exp.get("company", ""),
                "title": exp.get("title", ""),
                "duration": exp.get("duration", ""),
                "description": exp.get("description", ""),
            })
    else:
        experience = _extract_experience_from_text(resume_text)

    # ── Projects ──
    projects = parsed_data.get("projects", [])
    if not projects or not isinstance(projects, list):
        projects = _extract_projects_from_text(resume_text)

    # ── Skills ──
    raw_skills = parsed_data.get("skills", [])
    if raw_skills and isinstance(raw_skills, list):
        skills = raw_skills
    else:
        skills = _extract_skills_from_text(resume_text)

    # ── Preserved (factual — never sent to LLM) ──
    raw_education = parsed_data.get("education", [])
    if raw_education and isinstance(raw_education, list):
        education = []
        for edu in raw_education:
            education.append({
                "institution": edu.get("institution", ""),
                "degree": edu.get("degree", ""),
                "year": edu.get("year", 0),
            })
    else:
        education = _extract_education_from_text(resume_text)

    certifications = parsed_data.get("certifications", [])

    editable = {
        "summary": summary,
        "skills": skills,
        "experience": experience,
        "projects": projects,
    }

    preserved = {
        "education": education,
        "certifications": certifications,
    }

    log.info(
        "Built editable payload: %d skills, %d experience entries, %d projects | "
        "Preserved: %d education entries, %d certifications",
        len(skills), len(experience), len(projects),
        len(education), len(certifications),
    )

    return editable, preserved


# ═══════════════════════════════════════════════════════════════
#  Chunking: split large editable payloads into 2-3 sub-calls
# ═══════════════════════════════════════════════════════════════


def _estimate_json_chars(obj: dict) -> int:
    """Estimate how many chars the JSON string of this dict would be."""
    return len(json.dumps(obj, ensure_ascii=False, default=str))


def _chunk_editable(editable: dict) -> list[dict]:
    """
    Split a large editable payload into 2-3 chunks.

    Each chunk includes the full job context (JD, title, skills) but only
    a subset of the resume data. Chunks are designed so the LLM can
    independently optimize each subset.

    Strategy:
      - Small (≤ MAX_CHUNK_CHARS) → 1 chunk
      - Medium (≤ MAX_CHUNK_CHARS * 2) → 2 chunks
        Chunk 0: summary + skills + first 1/2 of experience + projects
        Chunk 1: summary + second 1/2 of experience
      - Large (> MAX_CHUNK_CHARS * 2) → 3 chunks
        Chunk 0: summary + skills + first 1/3 of experience
        Chunk 1: middle 1/3 of experience + projects
        Chunk 2: last 1/3 of experience
    """
    total_chars = _estimate_json_chars(editable)

    if total_chars <= _MAX_CHUNK_CHARS:
        log.info("Payload is %d chars — single chunk (threshold=%d)", total_chars, _MAX_CHUNK_CHARS)
        return [editable]

    exp_entries = editable.get("experience", [])
    skills = editable.get("skills", [])
    summary = editable.get("summary", "")
    projects = editable.get("projects", [])

    n_exp = len(exp_entries)

    if n_exp == 0:
        # Only skills/summary/projects — all small, keep as 1 chunk
        log.info("No experience entries, keeping single chunk")
        return [editable]

    if total_chars <= _MAX_CHUNK_CHARS * 2:
        # ── 2 chunks ──
        mid = n_exp // 2
        chunk0 = {
            "summary": summary,
            "skills": skills[: len(skills) // 2] if len(skills) > 4 else skills,
            "experience": exp_entries[:mid],
            "projects": projects,
        }
        chunk1 = {
            "summary": summary,
            "skills": skills[len(skills) // 2:] if len(skills) > 4 else skills,
            "experience": exp_entries[mid:],
            "projects": [],
        }
        chunks = [chunk0, chunk1]
        log.info(
            "Payload is %d chars — splitting into 2 chunks (%d + %d entries)",
            total_chars, len(chunk0["experience"]), len(chunk1["experience"]),
        )
    else:
        # ── 3 chunks ──
        third = max(1, n_exp // 3)
        chunk0 = {
            "summary": summary,
            "skills": skills[: len(skills) * 2 // 3] if len(skills) > 6 else skills,
            "experience": exp_entries[:third],
            "projects": [],
        }
        chunk1 = {
            "summary": "",
            "skills": (
                skills[len(skills) * 2 // 3:]
                if len(skills) > 6
                else (skills[len(skills) // 2:] if len(skills) > 4 else [])
            ),
            "experience": exp_entries[third:third * 2],
            "projects": projects,
        }
        chunk2 = {
            "summary": "",
            "skills": [],
            "experience": exp_entries[third * 2:],
            "projects": [],
        }
        chunks = [chunk0, chunk1, chunk2]
        log.info(
            "Payload is %d chars — splitting into 3 chunks (entries: %d, %d, %d)",
            total_chars,
            len(chunk0["experience"]), len(chunk1["experience"]), len(chunk2["experience"]),
        )

    return chunks


# ═══════════════════════════════════════════════════════════════
#  Data Integrity: merge missing entries back from original
# ═══════════════════════════════════════════════════════════════


def _merge_missing_entries(parsed: dict, original: dict) -> dict:
    """
    Ensure all entries from the original data survive the LLM response.

    The LLM may drop projects, experience entries, or skills to stay within
    output token limits. This function detects omissions by comparing the
    returned data against the original and merges back any missing entries.

    Matching strategy per field:
      - projects:    match by project name
      - experience:  match by (company, title) tuple
      - skills:      match by string value
      - summary:     keep whichever is non-empty

    Args:
        parsed: LLM-returned data (may have fewer items than original).
        original: Original resume data (the ground truth).

    Returns:
        Dict with merged data (all original items preserved).
    """
    merged = dict(parsed)

    # ── Projects (match by name) ──
    orig_projects: list[dict] = original.get("projects", []) or []
    ret_projects: list[dict] = merged.get("projects", []) or []
    if orig_projects:
        ret_names = {p.get("name", "") for p in ret_projects}
        missing = [p for p in orig_projects if p.get("name", "") not in ret_names]
        if missing:
            log.warning(
                "LLM dropped %d/%d project(s) — merging back: %s",
                len(missing), len(orig_projects),
                [p.get("name", "") for p in missing],
            )
            merged["projects"] = ret_projects + missing

    # ── Experience (match by company + title) ──
    orig_exp: list[dict] = original.get("experience", []) or []
    ret_exp: list[dict] = merged.get("experience", []) or []
    if orig_exp:
        ret_keys = {(e.get("company", ""), e.get("title", "")) for e in ret_exp}
        missing = [
            e for e in orig_exp
            if (e.get("company", ""), e.get("title", "")) not in ret_keys
        ]
        if missing:
            log.warning(
                "LLM dropped %d/%d experience entr(ies) — merging back",
                len(missing), len(orig_exp),
            )
            merged["experience"] = ret_exp + missing

    # ── Skills (match by exact string) ──
    orig_skills: list[str] = original.get("skills", []) or []
    ret_skills: list[str] = merged.get("skills", []) or []
    if orig_skills:
        ret_set = set(ret_skills)
        missing = [s for s in orig_skills if s not in ret_set]
        if missing:
            log.warning(
                "LLM dropped %d/%d skill(s) — merging back",
                len(missing), len(orig_skills),
            )
            merged["skills"] = ret_skills + missing

    return merged


# ═══════════════════════════════════════════════════════════════
#  Core: call LLM with retry (single-call-first strategy)
# ═══════════════════════════════════════════════════════════════


async def _try_single_with_retry(
    editable: dict,
    job_title: str,
    job_description: str,
    job_skills: list[str],
) -> dict | None:
    """
    Try to process the FULL editable payload in a single LLM call.

    Strategy:
      1. First attempt goes through MultiProvider's chain
         (groq \u2192 cerebras \u2192 sambanova \u2192 nvidia \u2192 openrouter)
      2. On rate-limit failure, retry with increasing delays
         (10s, 20s, 30s) \u2014 a brief pause often resolves free-tier caps
      3. On other failures, the MultiProvider already exhausted all
         providers \u2014 skip retry and return None for chunking fallback
      4. Returns None if all attempts are exhausted \u2014 chunking kicks in

    Returns:
        Parsed dict (with summary/skills/experience/projects + metadata),
        or None if all retries failed.
    """
    for attempt in range(_MAX_RETRIES + 1):
        if attempt > 0:
            delay = _RETRY_DELAYS[attempt - 1]
            log.info(
                "Single call retry %d/%d \u2014 waiting %ds before retry...",
                attempt, _MAX_RETRIES, delay,
            )
            await asyncio.sleep(delay)

        resume_json_str = json.dumps(editable, ensure_ascii=False, indent=2)
        full_system_prompt = SYSTEM_PROMPT_TEMPLATE.format(
            resume_json=resume_json_str,
            job_description=job_description,
        )

        user_prompt = (
            f"Please tailor this resume for the following position.\n\n"
            f"Job Title: {job_title}\n"
            f"Skills: {', '.join(job_skills) if job_skills else 'N/A'}"
        )

        llm = get_llm_provider()
        log.info(
            "Calling LLM (single call, attempt %d/%d, %d chars)...",
            attempt + 1, _MAX_RETRIES + 1, len(resume_json_str),
        )

        result = await llm.generate_async(
            prompt=user_prompt,
            json_format=True,
            timeout=180,
            max_tokens=16384,
            system_prompt=full_system_prompt,
        )

        if result.failure_reason:
            log.warning(
                "LLM call failed (attempt %d/%d): %s",
                attempt + 1, _MAX_RETRIES + 1, result.failure_reason,
            )
            # Only retry on rate-limit errors
            if "rate limit" in result.failure_reason.lower() or "429" in result.failure_reason:
                continue  # Will sleep and retry on next loop iteration
            # Other errors: MultiProvider already tried all providers
            log.info("Non-rate-limit failure \u2014 skipping retry, falling back to chunking")
            return None

        raw_content = result.content
        try:
            parsed = json.loads(raw_content)
        except json.JSONDecodeError as e:
            log.warning("JSON parse failed (attempt %d/%d): %s", attempt + 1, _MAX_RETRIES + 1, e)
            return None

        # Ensure no projects/experience/skills were dropped by the LLM
        merged = _merge_missing_entries(parsed, editable)

        # Success
        log.info(
            "Single LLM call succeeded on attempt %d/%d (model=%s)",
            attempt + 1, _MAX_RETRIES + 1, result.model or "unknown",
        )
        return {
            "summary": merged.get("summary", editable.get("summary", "")),
            "skills": merged.get("skills", editable.get("skills", [])),
            "experience": merged.get("experience", editable.get("experience", [])),
            "projects": merged.get("projects", editable.get("projects", [])),
            "_model": result.model or "unknown",
            "_ats_keywords_matched": parsed.get("ats_keywords_matched", []),
            "_ats_keywords_missing": parsed.get("ats_keywords_missing", []),
            "_optimization_notes": parsed.get("optimization_notes", []),
        }

    # All retries exhausted
    log.warning(
        "Single call failed after %d retries \u2014 falling back to chunked approach",
        _MAX_RETRIES,
    )
    return None


def _merge_chunks_results(chunks: list[dict], results: list[dict]) -> dict:
    """
    Merge results from multiple chunked LLM calls into one unified editable dict.

    Strategy:
      - Summary: take from first chunk that has it
      - Skills: concatenate (deduplicate by order of appearance)
      - Experience: concatenate in original order
      - Projects: take from first chunk that has them
    """
    merged: dict = {
        "summary": "",
        "skills": [],
        "experience": [],
        "projects": [],
    }

    seen_skills: set[str] = set()
    seen_projects: set[str] = set()

    for chunk, result in zip(chunks, results):
        # Summary
        summary = result.get("summary", "") or chunk.get("summary", "")
        if summary and not merged["summary"]:
            merged["summary"] = summary

        # Skills (deduplicate preserving order)
        for skill in result.get("skills", []):
            if skill not in seen_skills:
                merged["skills"].append(skill)
                seen_skills.add(skill)

        # Experience (concatenate in order)
        merged["experience"].extend(result.get("experience", []))

        # Projects (deduplicate by name)
        for proj in result.get("projects", []):
            name = proj.get("name", "")
            if name not in seen_projects:
                merged["projects"].append(proj)
                seen_projects.add(name)

    # Fill any empty fields from original chunks
    if not merged["summary"]:
        for c in chunks:
            if c.get("summary"):
                merged["summary"] = c["summary"]
                break
    if not merged["skills"]:
        for c in chunks:
            if c.get("skills"):
                merged["skills"] = c["skills"]
                break
    if not merged["experience"]:
        for c in chunks:
            if c.get("experience"):
                merged["experience"] = c["experience"]
                break
    if not merged["projects"]:
        for c in chunks:
            if c.get("projects"):
                merged["projects"] = c["projects"]
                break

    log.info(
        "Merged %d chunks → %d skills, %d experience entries, %d projects",
        len(results),
        len(merged["skills"]),
        len(merged["experience"]),
        len(merged["projects"]),
    )
    return merged


async def _call_llm_for_chunk(
    chunk: dict,
    job_title: str,
    job_description: str,
    job_skills: list[str],
    chunk_index: int,
    total_chunks: int,
) -> dict | None:
    """
    Send one chunk to the LLM and return parsed result.

    Returns:
        Parsed dict (with summary/skills/experience/projects keys),
        or None if the call failed.
    """
    resume_json_str = json.dumps(chunk, ensure_ascii=False, indent=2)

    full_system_prompt = SYSTEM_PROMPT_TEMPLATE.format(
        resume_json=resume_json_str,
        job_description=job_description,
    )

    user_prompt = (
        f"Please tailor this resume chunk {chunk_index + 1} of {total_chunks} "
        f"for the following position.\n\n"
        f"Job Title: {job_title}\n"
        f"Skills: {', '.join(job_skills) if job_skills else 'N/A'}"
    )

    llm = get_llm_provider()
    log.info(
        "Calling LLM for chunk %d/%d (%d chars)...",
        chunk_index + 1, total_chunks, len(resume_json_str),
    )

    result = await llm.generate_async(
        prompt=user_prompt,
        json_format=True,
        timeout=180,
        max_tokens=16384,
        system_prompt=full_system_prompt,
    )

    if result.failure_reason:
        log.warning(
            "Chunk %d/%d LLM call failed: %s",
            chunk_index + 1, total_chunks, result.failure_reason,
        )
        return None

    raw_content = result.content
    try:
        parsed = json.loads(raw_content)
    except json.JSONDecodeError as e:
        log.warning("Chunk %d/%d JSON parse failed: %s", chunk_index + 1, total_chunks, e)
        return None

    # Ensure no projects/experience/skills were dropped by the LLM in this chunk
    merged = _merge_missing_entries(parsed, chunk)

    # Normalize: extract only the editable keys (with integrity merge from _merge_missing_entries)
    return {
        "summary": merged.get("summary", chunk.get("summary", "")),
        "skills": merged.get("skills", chunk.get("skills", [])),
        "experience": merged.get("experience", chunk.get("experience", [])),
        "projects": merged.get("projects", chunk.get("projects", [])),
        "_model": result.model or "unknown",
        "_ats_keywords_matched": parsed.get("ats_keywords_matched", []),
        "_ats_keywords_missing": parsed.get("ats_keywords_missing", []),
        "_optimization_notes": parsed.get("optimization_notes", []),
    }


# ═══════════════════════════════════════════════════════════════
#  HTML Generation from Tailored JSON
# ═══════════════════════════════════════════════════════════════

_DEFAULT_RESUME_CSS = """
body {
    font-family: Calibri, Arial, Helvetica, sans-serif;
    font-size: 11pt;
    line-height: 1.4;
    color: #1a1a1a;
    max-width: 7.5in;
    margin: 0 auto;
    padding: 0.5in 0.7in;
}
h1 {
    font-family: Calibri, Arial, Helvetica, sans-serif;
    font-size: 18pt;
    color: #1A1A2E;
    margin-bottom: 2pt;
}
h2 {
    font-family: Calibri, Arial, Helvetica, sans-serif;
    font-size: 13pt;
    color: #1A1A2E;
    margin-top: 14pt;
    margin-bottom: 6pt;
    border-bottom: 1px solid #ddd;
    padding-bottom: 3pt;
}
h3 {
    font-family: Calibri, Arial, Helvetica, sans-serif;
    font-size: 11pt;
    color: #1A1A2E;
    margin-top: 8pt;
    margin-bottom: 2pt;
}
p {
    margin-top: 2pt;
    margin-bottom: 4pt;
}
ul {
    margin-top: 2pt;
    margin-bottom: 4pt;
    padding-left: 22pt;
}
li {
    margin-bottom: 2pt;
}
.contact-line {
    font-size: 10pt;
    color: #555;
    margin-bottom: 8pt;
}
.date-line {
    font-size: 10pt;
    color: #666;
    margin-top: 0pt;
}
"""


def _xml_escape(text: str) -> str:
    if not text:
        return ""
    text = text.replace("&", "&amp;")
    text = text.replace("<", "&lt;")
    text = text.replace(">", "&gt;")
    text = text.replace('"', "&quot;")
    return text


def _wrap_html(body_html: str) -> str:
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<style>
{_DEFAULT_RESUME_CSS}
</style>
</head>
<body>
{body_html}
</body>
</html>"""


def generate_html_from_tailored(
    full_data: dict,
    pii: dict,
    ats_keywords_matched: Optional[list[str]] = None,
    ats_keywords_missing: Optional[list[str]] = None,
    optimization_notes: Optional[list[str]] = None,
) -> str:
    """
    Generate formatted HTML from the FULL resume data (editable + preserved + PII).

    Includes all sections: header, summary, skills, experience, projects, education, certifications.
    ATS metadata is NOT embedded in the HTML (returned separately in API response).
    """
    body_parts: list[str] = []

    name = _xml_escape(pii.get("name", "Candidate"))
    email = _xml_escape(pii.get("email", ""))
    phone = _xml_escape(pii.get("phone", ""))

    # ── Header ──
    body_parts.append(f"<h1>{name}</h1>")
    contact_parts = [p for p in [email, phone] if p]
    if contact_parts:
        body_parts.append(
            f'<p class="contact-line">{" &nbsp;|&nbsp; ".join(contact_parts)}</p>'
        )
    else:
        body_parts.append("<p>&nbsp;</p>")

    # ── Summary ──
    summary = full_data.get("summary", "")
    if summary:
        body_parts.append("<h2>Professional Summary</h2>")
        body_parts.append(f"<p>{_xml_escape(summary)}</p>")

    # ── Skills ──
    skills = full_data.get("skills", [])
    if skills:
        body_parts.append("<h2>Skills</h2>")
        body_parts.append(f"<p>{', '.join(_xml_escape(s) for s in skills)}</p>")

    # ── Experience ──
    experience = full_data.get("experience", [])
    if experience:
        body_parts.append("<h2>Experience</h2>")
        for exp in experience:
            company = _xml_escape(exp.get("company", ""))
            title = _xml_escape(exp.get("title", ""))
            duration = _xml_escape(exp.get("duration", ""))
            description = _xml_escape(exp.get("description", ""))

            title_line_parts = []
            if title:
                title_line_parts.append(title)
            if company:
                if company.startswith("at "):
                    title_line_parts.append(company)
                else:
                    title_line_parts.append(f"<em>at {company}</em>")
            if title_line_parts:
                body_parts.append(f"<h3>{' '.join(title_line_parts)}</h3>")
            elif company:
                body_parts.append(f"<h3>{company}</h3>")

            if duration:
                body_parts.append(f'<p class="date-line">{duration}</p>')
            if description:
                if "\n" in description:
                    bullets = [
                        b.strip().lstrip("-•*")
                        for b in description.split("\n") if b.strip()
                    ]
                    bullet_html = "\n".join(f"<li>{_xml_escape(b)}</li>" for b in bullets)
                    body_parts.append(f"<ul>{bullet_html}</ul>")
                else:
                    body_parts.append(f"<p>{description}</p>")

    # ── Projects ──
    projects = full_data.get("projects", [])
    if projects:
        body_parts.append("<h2>Projects</h2>")
        for proj in projects:
            proj_name = _xml_escape(proj.get("name", ""))
            proj_desc = _xml_escape(proj.get("description", ""))
            if proj_name:
                body_parts.append(f"<h3>{proj_name}</h3>")
            if proj_desc:
                if "\n" in proj_desc:
                    bullets = [
                        b.strip().lstrip("-•*")
                        for b in proj_desc.split("\n") if b.strip()
                    ]
                    bullet_html = "\n".join(f"<li>{_xml_escape(b)}</li>" for b in bullets)
                    body_parts.append(f"<ul>{bullet_html}</ul>")
                else:
                    body_parts.append(f"<p>{proj_desc}</p>")

    # ── Education (preserved — never sent to LLM) ──
    education = full_data.get("education", [])
    if education:
        body_parts.append("<h2>Education</h2>")
        for edu in education:
            institution = _xml_escape(edu.get("institution", ""))
            degree = _xml_escape(edu.get("degree", ""))
            year = edu.get("year", "")
            parts = [p for p in [degree, institution, str(year) if year else ""] if p]
            if parts:
                body_parts.append(f"<p>{', '.join(parts)}</p>")

    # ── Certifications (preserved — never sent to LLM) ──
    certifications = full_data.get("certifications", [])
    if certifications:
        body_parts.append("<h2>Certifications</h2>")
        for cert in certifications:
            body_parts.append(f"<p>{_xml_escape(cert)}</p>")

    body_html = "\n".join(body_parts)
    return _wrap_html(body_html)


# ═══════════════════════════════════════════════════════════════
#  Main Pipeline
# ═══════════════════════════════════════════════════════════════


async def tailor_resume_structured(
    resume_text: str,
    parsed_data: dict,
    job: dict,
) -> dict:
    """
    Full structured tailoring pipeline.

    Steps:
        1. Extract PII (name, email, phone) — NEVER sent to LLM
        2. Separate editable fields (summary, skills, experience, projects)
           from preserved fields (education, certifications)
        3. Try single LLM call with FULL editable payload
           — On rate-limit (429): retry with 10s, 20s, 30s delays
           — On other failure: fall through to chunking
        4. If single call fails after retries: split into 2-3 chunks
           and call LLM once per chunk, merge results
        5. Re-inject preserved fields (education, certifications)
        6. Re-inject PII
        7. Generate HTML
        8. Return everything for API response + file generation

    Maximum 1 LLM call in the happy path; up to 4+ in worst case (1 + 3 chunks).

    Args:
        resume_text: Raw extracted text.
        parsed_data: Parsed resume data from resume_parser.
        job: Job document from MongoDB.

    Returns:
        Dict with keys:
            - tailored_data: Full data WITH PII + preserved fields
            - tailored_html: Formatted HTML
            - pii: Extracted PII
            - ats_keywords_matched: List[str]
            - ats_keywords_missing: List[str]
            - optimization_notes: List[str]
            - llm_model: Model used
            - chunks_count: Number of LLM calls made
    """
    job_title = job.get("title", "Unknown Position")
    job_description = job.get("description", "")
    job_skills = job.get("skills", [])

    # ── Step 1: Extract PII ──
    pii = extract_pii(parsed_data, resume_text=resume_text)
    log.info(
        "Structured tailor: extracted PII — name=%s email=%s phone=%s",
        pii.get("name", "N/A"), pii.get("email", "N/A"), pii.get("phone", "N/A"),
    )

    # ── Step 2: Separate editable vs preserved ──
    editable, preserved = _build_editable_and_preserved(parsed_data, resume_text)
    log.info(
        "Editable payload estimate: %d chars | Preserved: %d education, %d certifications",
        _estimate_json_chars(editable),
        len(preserved.get("education", [])),
        len(preserved.get("certifications", [])),
    )

    # ── Step 3: Try single LLM call with retry ──
    single_result = await _try_single_with_retry(
        editable, job_title, job_description, job_skills,
    )

    if single_result is not None:
        # Single call succeeded
        merged_editable = {k: v for k, v in single_result.items() if not k.startswith("_")}
        ats_matched = single_result.get("_ats_keywords_matched", []) or []
        ats_missing = single_result.get("_ats_keywords_missing", []) or []
        opt_notes = single_result.get("_optimization_notes", []) or []
        llm_model = single_result.get("_model", "unknown")
        n_chunks = 1

    else:
        # ── Single call failed — fall back to chunked approach ──
        log.info("Single LLM call failed — falling back to chunked approach")
        chunks = _chunk_editable(editable)
        n_chunks = len(chunks)

        if n_chunks == 1:
            # Payload fits in one chunk but LLM still failed — use original data
            merged_editable = editable
            ats_matched = []
            ats_missing = []
            opt_notes = ["LLM call failed after retries — using original resume data"]
            llm_model = "unknown"

        else:
            # ── Multi-chunk: call LLM per chunk (each is smaller, more likely to succeed) ──
            chunk_results: list[dict | None] = []
            for i, chunk in enumerate(chunks):
                chunk_result = await _call_llm_for_chunk(
                    chunk, job_title, job_description, job_skills,
                    chunk_index=i, total_chunks=n_chunks,
                )
                chunk_results.append(chunk_result)

            # Filter out failed chunks (use original chunk data as fallback)
            valid_results: list[dict] = []
            valid_chunks: list[dict] = []
            for i, (chunk, result) in enumerate(zip(chunks, chunk_results)):
                if result is not None:
                    valid_results.append(result)
                    valid_chunks.append(chunk)
                else:
                    valid_results.append({
                        "summary": chunk.get("summary", ""),
                        "skills": chunk.get("skills", []),
                        "experience": chunk.get("experience", []),
                        "projects": chunk.get("projects", []),
                    })
                    valid_chunks.append(chunk)
                log.info(
                    "Chunk %d/%d: %s",
                    i + 1, n_chunks,
                    "LLM OK" if chunk_results[i] is not None else "LLM FAILED (using original)",
                )

            # Merge all chunk results
            merged_editable = _merge_chunks_results(valid_chunks, valid_results)

            # Collect ATS metadata from all chunks
            all_matched: list[str] = []
            all_missing: list[str] = []
            all_notes: list[str] = [f"Resume tailored in {n_chunks} chunks (single call failed first)"]
            seen_matched: set[str] = set()
            seen_missing: set[str] = set()

            for r in chunk_results:
                if r is None:
                    continue
                for kw in r.get("_ats_keywords_matched", []):
                    if kw not in seen_matched:
                        all_matched.append(kw)
                        seen_matched.add(kw)
                for kw in r.get("_ats_keywords_missing", []):
                    if kw not in seen_missing:
                        all_missing.append(kw)
                        seen_missing.add(kw)
                for note in r.get("_optimization_notes", []):
                    if note not in all_notes:
                        all_notes.append(note)

            ats_matched = all_matched
            ats_missing = all_missing
            opt_notes = all_notes
            failed_chunks = sum(1 for r in chunk_results if r is None)
            if failed_chunks:
                opt_notes.append(f"{failed_chunks} chunk(s) fell back to original content")

            # Use model from first successful chunk
            llm_model = "unknown"
            for r in chunk_results:
                if r is not None and r.get("_model", "unknown") != "unknown":
                    llm_model = r["_model"]
                    break

    # ── Step 4: Build full data (editable + preserved + PII) ──
    full_data = {}
    full_data.update(merged_editable)
    full_data.update(preserved)  # education + certifications (never sent to LLM)
    full_data = reinject_pii(full_data, pii)  # name, email, phone

    # ── Step 5: Generate HTML ──
    tailored_html = generate_html_from_tailored(
        full_data, pii,
        ats_keywords_matched=ats_matched,
        ats_keywords_missing=ats_missing,
        optimization_notes=opt_notes,
    )

    log.info(
        "Tailoring complete: %d chunk(s), final data has %d skills, %d experience, "
        "%d projects, %d education, %d certifications",
        n_chunks,
        len(full_data.get("skills", [])),
        len(full_data.get("experience", [])),
        len(full_data.get("projects", [])),
        len(full_data.get("education", [])),
        len(full_data.get("certifications", [])),
    )

    return {
        "tailored_data": full_data,
        "tailored_html": tailored_html,
        "pii": pii,
        "ats_keywords_matched": ats_matched,
        "ats_keywords_missing": ats_missing,
        "optimization_notes": opt_notes,
        "llm_model": llm_model,
        "chunks_count": n_chunks,
    }
