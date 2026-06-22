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
    If payload is large (>8K chars):
        Split into 2-3 chunks
        Call LLM once per chunk
        Merge results
    Else:
        Call LLM once
        │
        ▼
    Re-inject Education + Certifications + PII
        │
        ▼
    Generate Final HTML → DOCX / PDF

Uses OpenRouter free-tier models with automatic fallback chain.
Maximum 3 LLM calls (not 20+ like the old section-by-section approach).
"""

from __future__ import annotations

import json
import logging
from typing import Optional

from app.services.llm import get_llm_provider
from app.services.pii_service import extract_pii, reinject_pii

log = logging.getLogger(__name__)

# ── Thresholds ──────────────────────────────────────────────────
# If the editable JSON payload exceeds this, split into chunks.
# Each chunk gets its own LLM call with full JD context.
_MAX_CHUNK_CHARS = 8000


# ═══════════════════════════════════════════════════════════════
#  System Prompt — ATS Resume Optimization Engine
# ═══════════════════════════════════════════════════════════════

SYSTEM_PROMPT_TEMPLATE = """# System Role

You are an expert ATS Resume Optimization Engine.

Your task is to tailor a resume for a specific job description while maintaining factual accuracy.

## Critical Rules

1. Never invent experience that does not exist.
2. Never create fake companies.
3. Never create fake projects.
4. Never create fake certifications.
5. Never create fake education.
6. Never fabricate years of experience.
7. Never claim ownership of technologies the candidate has never used.
8. Preserve all factual information.
9. Improve wording, impact, ATS compatibility, and keyword alignment.
10. Optimize for ATS parsing.

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

* Rewrite summary
* Add relevant keywords
* Improve ATS matching

---

### Skills Section

You may:

* Reorder skills
* Group skills
* Prioritize skills matching the JD

You may only include skills already present in the resume.

---

### Experience Section

You may:

* Rewrite bullet points
* Improve action verbs
* Quantify achievements when existing metrics are available
* Highlight relevant technologies already used

You must not add technologies that are absent from the candidate's experience.

---

### Projects

You may:

* Rewrite descriptions
* Emphasize relevant technologies
* Improve ATS keyword matching

Do not invent projects.

---

### Education & Certifications

Not sent to LLM — these factual sections are preserved exactly server-side and merged back into the final output unchanged.

---

## ATS Optimization Rules

Target:

* ATS Friendly
* Keyword Rich
* Human Readable
* Professional Tone

Priority:

1. Required Skills
2. Responsibilities
3. Industry Keywords
4. Preferred Skills

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
    experience = []
    for exp in parsed_data.get("experience", []):
        experience.append({
            "company": exp.get("company", ""),
            "title": exp.get("title", ""),
            "duration": exp.get("duration", ""),
            "description": exp.get("description", ""),
        })

    # ── Projects ──
    projects = parsed_data.get("projects", [])
    if not projects or not isinstance(projects, list):
        projects = _extract_projects_from_text(resume_text)

    # ── Skills ──
    skills = parsed_data.get("skills", [])

    # ── Preserved (factual — never sent to LLM) ──
    education = []
    for edu in parsed_data.get("education", []):
        education.append({
            "institution": edu.get("institution", ""),
            "degree": edu.get("degree", ""),
            "year": edu.get("year", 0),
        })

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
#  Core: call LLM for one chunk
# ═══════════════════════════════════════════════════════════════


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
        max_tokens=8192,
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

    # Normalize: extract only the editable keys
    return {
        "summary": parsed.get("summary", chunk.get("summary", "")),
        "skills": parsed.get("skills", chunk.get("skills", [])),
        "experience": parsed.get("experience", chunk.get("experience", [])),
        "projects": parsed.get("projects", chunk.get("projects", [])),
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
        3. If editable payload is large: split into 2-3 chunks,
           call LLM once per chunk, merge results
        4. If editable payload is small: call LLM once
        5. Re-inject preserved fields (education, certifications)
        6. Re-inject PII
        7. Generate HTML
        8. Return everything for API response + file generation

    Maximum 3 LLM calls (not 20+ like the old section-by-section approach).

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
    pii = extract_pii(parsed_data)
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

    # ── Step 3: Chunk and call LLM ──
    chunks = _chunk_editable(editable)
    n_chunks = len(chunks)

    if n_chunks == 1:
        # ── Single call ──
        result = await _call_llm_for_chunk(
            chunks[0], job_title, job_description, job_skills,
            chunk_index=0, total_chunks=1,
        )
        if result is None:
            merged_editable = editable
            ats_matched = []
            ats_missing = []
            opt_notes = ["LLM call failed — using original resume data"]
            llm_model = "unknown"
        else:
            merged_editable = {k: v for k, v in result.items() if not k.startswith("_")}
            ats_matched = result.get("_ats_keywords_matched", []) or []
            ats_missing = result.get("_ats_keywords_missing", []) or []
            opt_notes = result.get("_optimization_notes", []) or []
            llm_model = result.get("_model", "unknown")

    else:
        # ── Multi-chunk: call LLM per chunk ──
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
                # Fall back to original chunk data
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
        all_notes: list[str] = [f"Resume tailored in {n_chunks} chunks"]
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
