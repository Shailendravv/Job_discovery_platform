# Resume Tailor — Complete Flow Documentation

**Version:** 2.0 (current code)
**Last updated:** June 21, 2026
**Scope:** Full end-to-end flow from file upload to tailored resume download

---

## Table of Contents

1. [Purpose & Audience](#1-purpose--audience)
2. [System Architecture Overview](#2-system-architecture-overview)
3. [Understanding the Resume Data Model](#3-understanding-the-resume-data-model)
4. [Flow 0: Resume Upload (POST /upload)](#4-flow-0-resume-upload-post-upload)
5. [Flow 1: Resume Tailor (POST /tailor) — Main Entry Point](#5-flow-1-resume-tailor-post-tailor--main-entry-point)
6. [Path A: HTML Tailoring (tailor_resume_html)](#6-path-a-html-tailoring-tailor_resume_html)
7. [Path B: Plain Text Tailoring (tailor_resume_text)](#7-path-b-plain-text-tailoring-tailor_resume_text)
8. [Path C: Fallback HTML Tailor (_fallback_html_tailor)](#8-path-c-fallback-html-tailor-_fallback_html_tailor)
9. [Path D: Structured Element Tailoring (tailor_resume_structured)](#9-path-d-structured-element-tailoring-tailor_resume_structured)
10. [Path E: DOCX v2 Engine (tailor_resume_docx_v2)](#10-path-e-docx-v2-engine-tailor_resume_docx_v2)
11. [The Non-Editable Sections System](#11-the-non-editable-sections-system)
12. [HTML Section Parser (html_service.py)](#12-html-section-parser-html_servicepy)
13. [Plain Text Section Parser (inline in resume_tailor.py)](#13-plain-text-section-parser-inline-in-resume_tailorpy)
14. [LLM Prompts Reference](#14-llm-prompts-reference)
15. [Defensive Guards Against JD Content Bleed](#15-defensive-guards-against-jd-content-bleed)
16. [Output Pipeline: DOCX & PDF Generation](#16-output-pipeline-docx--pdf-generation)
17. [Cover Letter Generation](#17-cover-letter-generation)
18. [Debugging Checklist](#18-debugging-checklist)
19. [Common Issues & Solutions](#19-common-issues--solutions)
20. [How to Run & Test Locally](#20-how-to-run--test-locally)
21. [File Inventory](#21-file-inventory)

---

## 1. Purpose & Audience

This document describes the **complete resume tailoring system** as it exists in the codebase today (June 2026). It is written for:

- **New developers** who need to understand the system from scratch
- **Debuggers** who need to trace why a specific section was modified incorrectly
- **Modifiers** who want to add new section types, change prompts, or fix bugs

**Prerequisites:** Basic Python, FastAPI, MongoDB, and LLM concepts.

---

## 2. System Architecture Overview

```
┌──────────────────────────────────────────────────────────────────┐
│                    API Layer (FastAPI)                            │
│              backend/app/api/v1/resumes.py                        │
│           POST /upload  |  POST /tailor  |  POST /download       │
└──────────────────────────┬───────────────────────────────────────┘
                           │
              ┌────────────▼────────────┐
              │  resume_tailor.py        │
              │  (main orchestrator)     │
              │                          │
              │  5 tailoring paths:      │
              │  ┌────────────────────┐  │
              │  │ A. tailor_resume_  │  │ ← PRIMARY PATH (has HTML)
              │  │    html()          │  │
              │  ├────────────────────┤  │
              │  │ B. tailor_resume_  │  │ ← TEXT FALLBACK (no HTML)
              │  │    text()          │  │
              │  ├────────────────────┤  │
              │  │ C. _fallback_html_ │  │ ← PARSING FAILURE
              │  │    tailor()        │  │
              │  ├────────────────────┤  │
              │  │ D. tailor_resume_  │  │ ← LEGACY (JSON elements)
              │  │    structured()    │  │
              │  ├────────────────────┤  │
              │  │ E. tailor_resume_  │  │ ← DOCX ENGINE (not in API)
              │  │    docx_v2()       │  │
              │  └────────────────────┘  │
              └──────────────────────────┘
                          │
         ┌────────────────┼────────────────┐
         ▼                ▼                ▼
┌────────────────┐ ┌────────────┐ ┌────────────────┐
│ html_service.py│ │ Inline     │ │ resume_tailor_ │
│ (section       │ │ text       │ │ engine/        │
│  parser)       │ │ parser     │ │ (5-phase DOCX) │
└────────────────┘ └────────────┘ └────────────────┘
```

### Three Key Input Formats

| Format | How it's created | Used by path |
|--------|-----------------|-------------|
| **HTML** | DOCX→mammoth→HTML, or PDF→PyMuPDF→elements→HTML | Path A (primary), Path C (fallback) |
| **Plain text** | Direct extraction from PDF/DOCX | Path B |
| **Structured JSON** | Parsed by Groq LLM during upload | Path D |
| **Raw DOCX bytes** | Original file stored on Cloudinary | Path E (not yet in API) |

### Two Independent LLM Providers

| Provider | Config key | Used by |
|----------|-----------|---------|
| **Ollama** (local) | `LLM_PROVIDER=ollama`, `MODEL_NAME=...` | Default, used for section-level calls |
| **Groq** (cloud) | `LLM_PROVIDER=groq`, `GROQ_API_KEY=...` | Alternative, used when configured |

Both are accessed through the unified `call_llm()` function in `backend/app/core/llm.py`.

---

## 3. Understanding the Resume Data Model

When a resume is uploaded, MongoDB stores a document like this:

```javascript
{
  "_id": ObjectId("..."),
  "resume_id": "a1b2c3d4...",        // UUID hex
  "cloudinary_url": "https://...",    // Original file URL
  "cloudinary_public_id": "resumes/...",
  "filename": "resume.docx",
  "content_type": "application/vnd.openxmlformats...",
  "file_size": 123456,
  "extracted_text": "John Doe\njohn@email.com\n...",  // Raw text
  "extracted_text_length": 5000,
  "resume_html": "<!DOCTYPE html>\n<html>...",        // ← THIS IS KEY
  "parsed_data": {                                     // Groq-parsed structure
    "name": "John Doe",
    "email": "john@email.com",
    "education": [{"institution": "MIT", "degree": "BS CS", "year": 2020}],
    "experience": [{"company": "Acme", ...}],
    "skills": ["Python", "React"],
    "languages": ["English"],
    "certifications": []
  },
  "processing_status": "completed",
  "schema_version": 3,
  "created_at": ISODate("..."),
  "updated_at": ISODate("...")
}
```

**Critical field: `resume_html`** — This is what Path A uses. If it's empty/falsy, the code falls to Path B (text tailoring).

The `resume_html` is created by:
- **DOCX uploads:** `mammoth.convert_to_html()` → preserves bold, italic, headings, links
- **PDF uploads:** `PyMuPDF` extracts structured elements → `elements_to_html()` converts to HTML

---

## 4. Flow 0: Resume Upload (POST /upload)

**File:** `backend/app/api/v1/resumes.py` → `upload_resume()`

### Step-by-step

1. **Validate** file type (PDF, DOC, DOCX allowed) and size (max 10 MB)
2. **Extract text** from the file:
   - PDF: `extract_text_from_pdf()` (PyMuPDF)
   - DOCX: `extract_text_from_docx()` (python-docx)
3. **Convert to HTML** for formatting preservation:
   - PDF: `extract_structured_from_pdf()` → `elements_to_html()` 
   - DOCX: `docx_to_html()` via mammoth
   - If either fails: `plain_text_to_html()` as basic fallback
4. **Upload** original file to Cloudinary storage
5. **Parse** extracted text with Groq LLM → structured JSON (`parse_resume_text()`)
6. **Sanitize** parsed data (`_sanitize_parsed_data()`) for MongoDB schema compliance
7. **Save** everything to MongoDB

> **Key debugging note:** The `resume_html` field in MongoDB is what drives which tailoring path is chosen. If it's empty, you get text tailoring (Path B) instead of HTML tailoring (Path A).

---

## 5. Flow 1: Resume Tailor (POST /tailor) — Main Entry Point

**File:** `backend/app/api/v1/resumes.py` → `tailor_resume()`

### Step-by-step

```
Client sends { resume_id, job_id }
              │
              ▼
    Fetch resume from MongoDB (get_resume_by_id)
    Fetch job from MongoDB (get_job_by_id)
              │
              ▼
    Does resume have resume_html?
              │
     ┌────────┴────────┐
     ▼                  ▼
    YES                 NO
     │                   │
     ▼                   ▼
 tailor_resume_      tailor_resume_
 html(resume_html,    text(extracted_
      job)               text, job)
     │                   │
     │                   │
     └─────────┬─────────┘
               ▼
     Extract plain text from tailored HTML
     (extract_text_from_html)
               │
               ▼
     Generate cover letter
     (generate_cover_letter)
               │
               ▼
     Generate DOCX + PDF files
     Upload to Cloudinary
               │
               ▼
     Save tailor session to MongoDB
     Return { tailored_text, cover_letter, download_urls }
```

### Key decision point (line ~180 in resumes.py):

```python
if resume_html:
    # New-style resume with HTML — Path A
    tailored_html = await tailor_resume_html(resume_html, job)
else:
    # Legacy resume without HTML — Path B
    tailored_text = await tailor_resume_text(resume_text, job)
    tailored_html = plain_text_to_html(tailored_text)
```

After both paths:
```python
tailored_text = extract_text_from_html(tailored_html)  # Extract plain text for response
```

### Output format

The endpoint returns `ResumeTailorResponse`:
```python
{
    "resume_id": "...",
    "job_id": "...",
    "tailored_text": "John Doe\n...",          # Plain text version
    "cover_letter": "Dear Hiring Manager...",   # Generated cover letter
    "download_urls": {
        "pdf": "https://res.cloudinary.com/...resume_pdf.pdf",
        "docx": "https://res.cloudinary.com/...resume_docx",
        "cover_letter_pdf": "https://res.cloudinary.com/...cover_letter.pdf"
    }
}
```

---

## 6. Path A: HTML Tailoring (tailor_resume_html)

**File:** `backend/app/services/resume_tailor.py` — function `tailor_resume_html()`

This is the **primary path**. It is called when the resume has HTML stored in MongoDB.

### How it works

```
Input: resume_html (full HTML document), job (MongoDB document)
                │
                ▼
    parse_html_into_sections(resume_html)  ← html_service.py
                │
      ┌─────────┴─────────┐
      ▼                   ▼
  Success              Failed/Empty
      │                   │
      ▼                   ▼
  Process each         _fallback_html_
  section INDIVIDUALLY   tailor()  ← Path C
      │
      ▼
  For each section:
  ┌─────────────────────────────────────┐
  │ 1. Check if editable               │
  │    section_type in                  │
  │    _NON_EDITABLE_SECTION_TYPES?     │
  │    → YES: skip (keep original)     │
  │    → NO: continue                  │
  │                                     │
  │ 2. Build prompt with XML tags:     │
  │    <job_title>...</job_title>      │
  │    <job_description>...</>         │
  │    <required_skills>...</>         │
  │    <resume_section>...</>          │
  │                                     │
  │ 3. call_llm(prompt)                │
  │                                     │
  │ 4. Log raw LLM output (debug)      │
  │                                     │
  │ 5. validate_html()                 │
  │    (strips ```html fences,         │
  │     parses with BeautifulSoup)     │
  │                                     │
  │ 6. _extract_body_html()            │
  │    (gets <body> inner HTML)        │
  │                                     │
  │ 7. Store in section["body_html"]   │
  └─────────────────────────────────────┘
                │
                ▼
    reassemble_html(sections)
    (concatenates body_html, wraps in full HTML)
                │
                ▼
    Output: tailored full HTML document
```

### Detailed Loop Logic

```python
for section in sections:
    section_type = section.get("type", "unknown")
    
    # ── CRITICAL: Non-editable section check ──
    if section_type in _NON_EDITABLE_SECTION_TYPES:
        log.debug("Skipping non-editable section '%s'", section_type)
        continue  # ← LLM NEVER sees this section
    
    # ── Build prompt ──
    prompt = SECTION_HTML_PROMPT.format(
        section_html=truncated_body,
        section_type=section_type,
        section_name=section_name,
        job_title=job_title,
        job_description=job_description[:10000],
        job_skills=job_skills or "Not specified",
    )
    
    # ── Call LLM ──
    tailored = call_llm(prompt, json_format=False, max_tokens=4096)
    log.debug("Raw LLM output for section '%s': %r", section_type, tailored[:300])
    
    # ── Validate ──
    validated = validate_html(tailored.strip())
    if validated and len(validated) > 10:
        section["body_html"] = _extract_body_html(validated) or validated
```

### Failure Isolation

Each section is processed independently. If one section's LLM call fails (exception, empty response, or validation error), ONLY that section keeps its original content. All other sections are unaffected.

```
Summary: ✓ tailored
Experience: ✓ tailored
Skills: ✗ failed → keeps original
Education: skipped (non-editable)
```

---

## 7. Path B: Plain Text Tailoring (tailor_resume_text)

**File:** `backend/app/services/resume_tailor.py` — function `tailor_resume_text()`

Used when the resume has NO HTML stored (legacy uploads).

### How it works

```
Input: resume_text (plain text), job (MongoDB document)
                │
                ▼
    _split_text_into_sections(resume_text)
    (detects heading lines dynamically)
                │
                ▼
    For each section:
    ┌─────────────────────────────────────┐
    │ 1. Check if editable               │
    │    section_type in                  │
    │    _NON_EDITABLE_SECTION_TYPES?     │
    │    → YES: skip (keep original)     │
    │    → NO: continue                  │
    │                                     │
    │ 2. Build TEXT prompt with XML tags │
    │    <resume_section>...</>           │
    │                                     │
    │ 3. call_llm(prompt)                │
    │                                     │
    │ 4. If heading was dropped:         │
    │    prepend original heading        │
    │                                     │
    │ 5. Store in section["content"]     │
    └─────────────────────────────────────┘
                │
                ▼
    Reassemble with blank-line spacing
                │
                ▼
    Output: tailored plain text
```

### Section Splitting Logic

The `_split_text_into_sections()` function uses two rules to detect section headings:

1. **Blank-line requirement:** A heading line must be preceded by a blank line (or be the first line). This prevents short capitalized lines inside bullet content from being misidentified.
2. **Word matching:** The line must contain or start with a recognized section word (e.g., "experience", "education", "skills").

Lines that don't match become content within the current section.

---

## 8. Path C: Fallback HTML Tailor (_fallback_html_tailor)

**File:** `backend/app/services/resume_tailor.py` — function `_fallback_html_tailor()`

This is a **safety net** activated when `parse_html_into_sections()` either:
- Raises an exception
- Returns an empty list

### Why it exists

Some resumes have HTML that BeautifulSoup can't parse into clean sections:
- Malformed HTML (unclosed tags)
- No `<body>` tag
- BeautifulSoup not installed (`HAS_BS4 = False`)
- Completely flat HTML (no heading elements at all)

### How it differs from Path A

| Aspect | Path A (section-by-section) | Path C (fallback) |
|--------|---------------------------|-------------------|
| Number of LLM calls | One per section | **One for entire resume** |
| Section skipping | Code-level (`continue`) | **Prompt-level only** |
| Content inflation guard | N/A (each section is small) | **No built-in guard** |
| Prompt | `SECTION_HTML_PROMPT` | `FALLBACK_HTML_PROMPT` (different) |

### The Fallback Prompt

The fallback uses a dedicated `FALLBACK_HTML_PROMPT` that explicitly lists sections to preserve:

```
IMPORTANT — PRESERVE THESE SECTIONS EXACTLY AS WRITTEN:
- EDUCATION (or "Academic Background", "Academic History"): ...
- CERTIFICATIONS (or "Certifications & Licenses"): ...
- LANGUAGES: ...
- PUBLICATIONS (or "Publications & Awards"): ...

Instructions:
1. Rewrite only the work experience, skills, summary/profile sections...
```

**This is prompt-level protection only** — unlike Path A's code-level skip, the fallback relies on the LLM following instructions. If the LLM ignores them, education content can be corrupted.

### When to suspect you're hitting Path C

Check server logs for:
```
WARNING: HTML section parsing failed (...), falling back to whole-document tailoring
```
or
```
WARNING: No sections found in resume HTML, falling back to whole-document tailoring
```

---

## 9. Path D: Structured Element Tailoring (tailor_resume_structured)

**File:** `backend/app/services/resume_tailor.py` — function `tailor_resume_structured()`

This is a **legacy path** that operates on JSON arrays of `ResumeElement` objects. It is NOT called from the main API endpoint — it exists for backward compatibility.

### Input format

```python
# Each element has:
{
    "text": "Led development of...",
    "type": "bullet",           # heading / subheading / bullet / normal
    "bold": False,
    "links": [{"text": "View", "url": "https://..."}]
}
```

### How it works

1. Serializes all elements to JSON
2. Sends entire element list + JD to LLM in ONE call
3. LLM returns JSON with rewritten `text` fields
4. Elements with malformed fields are skipped
5. If any element fails validation, original is kept

**Limitations:**
- One LLM call for the entire resume (no failure isolation)
- No non-editable section filter (all elements are sent)
- JSON-based, so not used in the primary API path

---

## 10. Path E: DOCX v2 Engine (tailor_resume_docx_v2)

**File:** `backend/app/services/resume_tailor.py` → bridge to `resume_tailor_engine/`

This is a **formatting-preserving engine** that operates directly on `.docx` files. It is available via `tailor_resume_docx_v2()` but is NOT currently wired into the main API.

The engine is a 5-phase pipeline in the `resume_tailor_engine/` package:

```
┌──────────────────────────────────────────────────────────────────┐
│                      DOCX v2 Pipeline                            │
│                                                                   │
│  Phase 1: PARSER (parser.py)                                     │
│  Walk .docx paragraph-by-paragraph → Content Map                 │
│  Each span has: id, tier, paragraph_index, run_index, text,      │
│                 char_budget, section, needs_manual_review         │
│                                                                   │
│  Phase 2: LLM CLIENT (llm_client.py)                             │
│  Send spans in batches of 8 to Ollama (gemma4:e2b)              │
│  Receives structured JSON: {"rewrites": [{"id", "new_text"}]}    │
│                                                                   │
│  Phase 2b: VALIDATOR (validator.py)                              │
│  - Char budget check                                              │
│  - Banned pattern check                                           │
│  - Fabrication detection (new dates, percentages, dollar amounts) │
│  - Retry loop for over-budget fields (max 2 retries)             │
│                                                                   │
│  Phase 3: REINJECTOR (reinjector.py)                             │
│  Open ORIGINAL docx, set run.text only (never paragraph.text)    │
│  Preserves all formatting (fonts, sizes, colors, bold, italic)   │
│  - Single run: run[0].text = new_text                            │
│  - Multiple uniform runs: text in run[0], clear run[1:]          │
│  - Mixed formatting: skip (no automatic rewrite)                 │
│  - Typography post-process: straight → curly quotes              │
│                                                                   │
│  Phase 4: VERIFIER (verifier.py)                                 │
│  Convert both to PDF via LibreOffice headless                    │
│  Compare page counts                                              │
│  Optional: render side-by-side image diff                        │
└──────────────────────────────────────────────────────────────────┘
```

### Tier System (DOCX engine only)

| Tier | Content | Edit behavior |
|------|---------|---------------|
| 1 | Bullets under experience | 25% character slack, freely rewrite |
| 2 | Summary/Objective | 20% slack, freely rewrite |
| 3 | Skills list | 10% slack, reorder/drop/add if plausible |
| 4 | Headers, names, titles, dates, companies | **Never sent to LLM** |

### Calibration Tool

The engine includes `print_content_map()` for debugging:
```python
from app.services.resume_tailor_engine import print_content_map
print_content_map("path/to/resume.docx")
```
This prints every detected span with its tier, budget, section, and text — so you can verify section detection is working before running the full pipeline.

### Comparison: HTML Path vs DOCX Engine

| Feature | HTML Path (A) | DOCX Engine (E) |
|---------|---------------|-----------------|
| Input format | HTML string | .docx file on disk |
| Formatting preservation | HTML tags only | Full OOXML (fonts, sizes, colors, spacing) |
| LLM calls | One per section | Batched (8 spans per call) |
| Non-editable sections | Code-level skip | Tier 4 exclusion |
| In use? | ✅ Yes (API) | ❌ Not yet wired |
| Fabrication detection | Prompt-level only | Code-level (validator.py) |

---

## 11. The Non-Editable Sections System

**This is the most important defense against JD content bleed.**

### How it works

```python
# In resume_tailor.py — defined at module level
_NON_EDITABLE_SECTION_TYPES = frozenset({
    "education",
    "certifications",
    "languages",
    "publications",
})
```

Both `tailor_resume_html()` and `tailor_resume_text()` check each section BEFORE calling the LLM:

```python
if section_type in _NON_EDITABLE_SECTION_TYPES:
    log.debug("Skipping non-editable section '%s' (%s)", section_type, section_name)
    continue  # ← LLM never sees this section
```

### What sections are excluded

| Section type | Reason | Content examples |
|-------------|--------|-----------------|
| `"education"` | Purely factual | Institutions, degrees, dates, GPAs |
| `"certifications"` | Purely factual | License names, issuing bodies |
| `"languages"` | Purely factual | Language names, proficiency levels |
| `"publications"` | Purely factual | Paper titles, journals, dates |

### What sections ARE editable

| Section type | Why it's safe to edit |
|-------------|----------------------|
| `"summary"` | Descriptive text, benefits from rewording |
| `"experience"` | Bullet points, benefits from JD alignment |
| `"skills"` | Can be reordered/re-emphasized |
| `"projects"` | Descriptive text, benefits from rewording |
| `"preamble"` | N/A (content before first heading, often contact info — factual) |
| `"other"` | Unrecognized heading — varies |

### Why this doesn't apply to Path C (fallback)

The fallback sends the ENTIRE resume in one LLM call. The `_NON_EDITABLE_SECTION_TYPES` check only works in the section-by-section loop. The fallback uses prompt-level instructions instead (see the `FALLBACK_HTML_PROMPT`).

If you're seeing education corruption, check whether Path C is being triggered.

---

## 12. HTML Section Parser (html_service.py)

**File:** `backend/app/services/html_service.py`

### `parse_html_into_sections(full_html) → list[dict]`

This is the function that splits resume HTML into sections for individual LLM processing.

### Input → Output

```python
# Input: Full HTML document
# Output:
[
    {
        "type": "summary",
        "editable": True,
        "body_html": "<h2>Professional Summary</h2><p>Experienced...</p>",
        "html": "<!DOCTYPE html><html>...<body>...</body></html>",
        "section_name": "professional summary",
    },
    {
        "type": "experience",
        "body_html": "<h2>Experience</h2><h3>Company 1</h3>...",
        ...
    },
]
```

### How sections are detected

The function iterates over `<body>` children and calls `_is_heading_like(element)` on each one:

1. **Tag-name check:** `<h1>`, `<h2>`, `<h3>`, `<h4>` → always a heading
2. **ALL-CAPS paragraph check:** If text is uppercase AND contains a recognized section word → heading
3. **Bold child check:** If first child is `<strong>` or `<b>` → heading
4. **Short line check:** If < 40 chars, no period, starts with section word → heading

When a heading is found, all elements since the last heading are saved as one section. The heading element starts a new section.

### Section type classification

`_classify_section(heading_text) → str` maps heading text to a type:

| Heading contains | Type |
|----------------|------|
| "summary", "profile", "objective" | `"summary"` |
| "experience", "employment", "history", "work" | `"experience"` |
| "skill", "technolog", "competenc", "expertise" | `"skills"` |
| "education", "academic" | `"education"` |
| "project" | `"projects"` |
| "certification", "license" | `"certifications"` |
| "publication", "award", "honor" | `"publications"` |
| "language" | `"languages"` |
| "volunteer" | `"volunteer"` |
| None of the above | `"other"` |

### `validate_html(raw) → str`

Called on each LLM response. Does three things:
1. **Strips code fences**: Removes ```html ... ``` if present
2. **Parses with BeautifulSoup**: Ensures valid HTML
3. **Removes scripts/styles**: Decomposes `<script>` and `<style>` tags

The fence stripping is UNCONDITIONAL (no `startswith` check) — regex runs on all input as a no-op if no fences present.

### `reassemble_html(sections) → str`

Concatenates all sections' `body_html` in order, wraps in a full HTML document with CSS.

### `_extract_body_html(html) → str`

Extracts just the inner HTML of `<body>` tag. Used to strip the `<html>/<head>/<style>` wrapper that the LLM might produce.

---

## 13. Plain Text Section Parser (inline in resume_tailor.py)

### `_is_text_heading_line(stripped, *, prev_line_empty=True) → bool`

Detects section headings in plain text using these rules:

1. **Blank-line requirement** (most important): The line must be preceded by an empty line (or be the first line). This prevents:
   - Short capitalized lines inside bullet content (e.g., a project name in all-caps)
   - Skill names that happen to match section words
   
2. **ALL-CAPS check**: Text must be uppercase, ≥ 3 chars, ≤ 60 chars, AND contain a recognized section word

3. **Title-case check**: Text must be < 40 chars AND equal or start-with a recognized section word

### `_split_text_into_sections(text) → list[dict]`

```python
[
    {
        "type": "summary",
        "heading": "Professional Summary",
        "content": "Professional Summary\nExperienced developer..."
    },
    {
        "type": "education",
        "heading": "Education",
        "content": "Education\nBSc in CS, XYZ University, 2022"
    },
]
```

---

## 14. LLM Prompts Reference

### SECTION_HTML_PROMPT (Path A — each section)

```
You are a professional resume writer. You are tailoring ONE section...

<job_title>{job_title}</job_title>

<job_description>
{job_description}
</job_description>

<required_skills>{job_skills}</required_skills>

<resume_section type="{section_type}" name="{section_name}">
{section_html}
</resume_section>

Instructions:
1. Only rewrite the content inside <resume_section>...</resume_section>
2. <job_description> is reference material only — never copy its text
3. Rewrite to align with top skills. Keep same facts, same entities
4. CRITICAL: PRESERVE ALL HTML TAGS. Only change text between tags
5. Do NOT change names, titles, companies, dates, or section headings
6. Do NOT fabricate experience, metrics, or qualifications
7. If already a strong match, return unchanged
8. Return ONLY the modified HTML — no commentary, no fences
```

### SECTION_TEXT_PROMPT (Path B — each section)

Same structure as HTML prompt but without HTML preservation instructions.

### FALLBACK_HTML_PROMPT (Path C — entire resume)

```
...Same XML tags...

IMPORTANT — PRESERVE THESE SECTIONS EXACTLY AS WRITTEN:
- EDUCATION (or "Academic Background", "Academic History"): ...
- CERTIFICATIONS (or "Certifications & Licenses"): ...
- LANGUAGES: ...
- PUBLICATIONS (or "Publications & Awards"): ...

Instructions:
1. Rewrite only work experience, skills, summary/profile sections
2. <job_description> is reference material only
3. Rewrite TEXT CONTENT to align with top skills
4. CRITICAL: PRESERVE ALL HTML TAGS
5. Do NOT change names, titles, companies, dates, headings
6. Do NOT fabricate
7. If already a strong match, return unchanged
8. Return ONLY the modified HTML — no commentary, no fences
```

### DOCX Engine System Prompt (llm_client.py)

```
You are a professional resume tailor...

Rules:
- Receive text spans with id, char_budget, tier
- Return ONLY JSON: {"rewrites": [{"id": "...", "new_text": "..."}]}
- Do NOT invent job titles, employers, dates, degrees, or metrics
- Stay within char_budget
- If span is already a strong match, return unchanged
```

### COVER_LETTER_PROMPT (cover_letter.py)

Separate prompt used for generating the cover letter. Not related to resume tailoring directly.

---

## 15. Defensive Guards Against JD Content Bleed

The system has multiple layers of defense to prevent the LLM from copying job description content into the resume:

### Layer 1: Code-level section skipping (most reliable)

```python
# resume_tailor.py — Path A and Path B
if section_type in _NON_EDITABLE_SECTION_TYPES:
    continue  # LLM never sees these sections
```

### Layer 2: XML tag delimiters in prompts

All prompts use `<job_description>...</job_description>` and `<resume_section>...</resume_section>` tags to clearly separate JD content from resume content. Instructions explicitly say:
```
Everything inside <job_description> is reference material only — 
never copy its headings, structure, sentences, or boilerplate into your output.
```

### Layer 3: Fence stripping in validate_html()

```python
# html_service.py — runs BEFORE BeautifulSoup parsing
raw = re.sub(r"^```[a-zA-Z]*\n?", "", raw)
raw = re.sub(r"\n?```$", "", raw)
```

### Layer 4: Content inflation heuristic (inflation guard)

> **Note:** The inflation guard was proposed but may not be in the current code. Check if the following exists in your version:

```python
if original_len > 50 and tailored_len > original_len * 2:
    # Content likely inflated with JD text — keep original
    section["body_html"] = original_body
    continue
```

### Layer 5: Debug logging

Raw LLM output is logged at debug level for every section:
```python
log.debug("Raw LLM output for section '%s': %r", section_type, tailored[:300])
```

### Layer 6: DOCX engine validation (validator.py)

The DOCX engine has a `_introduces_fabrication()` check that detects:
- New dates not in the original
- New percentage metrics not in the original
- New dollar amounts not in the original

---

## 16. Output Pipeline: DOCX & PDF Generation

After the resume is tailored, the API generates downloadable files.

### DOCX Generation

```python
docx_bytes = html_to_docx(tailored_html)
```

Uses `htmldocx` library to convert the tailored HTML to DOCX format. The process:
1. Strips the full HTML wrapper (extracts `<body>` inner HTML)
2. Uses `HtmlToDocx` parser to add HTML to a python-docx `Document`
3. Saves to `BytesIO` → bytes

**Known limitation:** htmldocx doesn't handle all CSS. Complex layouts may not convert perfectly.

### PDF Generation

```python
pdf_bytes = await html_to_pdf_async(tailored_html)
```

Uses Playwright (headless Chromium) to render the HTML with full CSS fidelity:
1. Saves HTML to temp file
2. Opens with headless Chromium
3. Calls `page.pdf()` with Letter format + margins + `print_background=True`
4. Falls back to reportlab-based PDF if Playwright unavailable

### Cloudinary Upload

Both files are uploaded to Cloudinary alongside a cover letter PDF:
- Tailored PDF → `tailored/{session_id}/resume_pdf`
- Tailored DOCX → `tailored/{session_id}/resume_docx`
- Cover letter → `tailored/{session_id}/cover_letter`

---

## 17. Cover Letter Generation

**File:** `backend/app/services/cover_letter.py` — `generate_cover_letter()`

Called after tailoring. Uses a separate LLM call with:
- Candidate name
- Candidate skills (comma-separated)
- Candidate experience (formatted text)
- Job title
- Company name
- Job description

Prompt instructs the model to write a 3-4 paragraph professional cover letter. Returns plain text.

---

## 18. Debugging Checklist

Use this checklist when you see unexpected behavior (like education section being modified):

### Step 1: Check which path is running

Look at server logs:
```
INFO: Resume has N sections: ['summary', 'experience', 'skills', 'education']
```
vs
```
WARNING: HTML section parsing failed (...), falling back to...
```

If you see the INFO with section list → Path A is running (section-by-section)
If you see the WARNING → Path C is running (fallback)

### Step 2: Check non-editable section skipping

Look for:
```
DEBUG: Skipping non-editable section 'education' (education)
DEBUG: Skipping non-editable text section 'education' (Education)
```

If you DON'T see this for the education section, the section type isn't being classified as "education".

### Step 3: Check raw LLM output

Look for:
```
DEBUG: Raw LLM output for section 'education': ...
```

If you see this for "education" type → the non-editable skip is NOT working.

### Step 4: Check section classification

If the education section has type "other" or "unknown" instead of "education":
- The heading text might not contain the word "education"
- Check `_classify_section()` in `html_service.py` (HTML path)
- Check `_classify_text_section()` in `resume_tailor.py` (text path)

### Step 5: Check for JD content in raw output

If the raw LLM output for a section contains phrases from the JD that weren't in the original resume:
- The prompt instructions about "reference only" are being ignored
- Consider strengthening the prompt or adding code-level guards
- Check if the inflation guard is triggered

### Step 6: Verify resume_html exists in MongoDB

Run this against your database:
```javascript
db.resumes.findOne({_id: ObjectId("your_resume_id")}, {resume_html: 1})
```

If `resume_html` is empty or missing, the code falls to Path B (text tailoring).

---

## 19. Common Issues & Solutions

### Issue: Education section contains JD content

**Symptoms:** Education section has fabricated degrees, institutions, or descriptions that match the JD.

**Root causes (in order of likelihood):**

1. **Server running old code** — Python modules stay in memory. Restart the server.
2. **Path C (fallback) is being triggered** — Check logs for "falling back". The fallback uses prompt-level protection only.
3. **Section type isn't "education"** — The heading text doesn't contain the word "education". Check `_classify_section()`.
4. **Already-corrupted data in MongoDB** — Previous runs corrupted the stored `resume_html`. Re-upload the original resume.

**Fix:**
- Restart the server
- Verify `resume_html` exists and is well-formed HTML
- Re-upload the original resume if data is corrupted

### Issue: JD content appears in other sections

**Symptoms:** Experience or Skills sections contain verbatim text from the job description.

**Root causes:**
1. **Prompt instructions not strong enough** — The LLM treats JD as source material, not reference
2. **Small model can't follow complex instructions** — Gemma 4 E2B may struggle with long prompts

**Fixes applied in current code:**
- XML tag delimiters (`<job_description>`, `<resume_section>`) to clearly separate boundaries
- "CRITICAL DO NOT" instructions against copying JD text
- "Reference only" language throughout prompts

### Issue: Sections are created from JD content

**Symptoms:** New sections like "B.Tech", "12th", "10th" appear in the output that weren't in the original resume.

**Root cause:** The LLM generates fabricated content that looks like resume sections. The section-by-section approach should prevent this since only ORIGINAL sections are processed.

**Fix:** Ensure Path A is running (section-by-section). If Path C is running, the entire resume is in one LLM call and the model can fabricate new structures.

### Issue: Section parser doesn't detect all headings

**Symptoms:** The resume has 5 sections but the parser only finds 3.

**Root causes:**
1. Heading doesn't contain a recognized section word
2. Heading isn't preceded by a blank line (text path)
3. HTML heading isn't using `<h1>`-`<h4>` and doesn't match other heuristics

**Fix:** Add the heading word to `_COMMON_SECTION_WORDS` in `html_service.py` (and `_SECTION_HEADING_WORDS` in `resume_tailor.py`).

### Issue: "No sections found" / Falling back

**Symptoms:**
```
WARNING: HTML section parsing failed (...), falling back...
```

**Root causes:**
1. `HAS_BS4` is False (BeautifulSoup not installed)
2. HTML has no `<body>` tag
3. Exception during parsing

**Fix:** 
- Install BeautifulSoup: `pip install beautifulsoup4`
- Check the stored `resume_html` for proper structure
- The fallback will work but has weaker protection

### Issue: HTML tags in LLM output

**Symptoms:** Raw LLM output contains ```html``` fences or broken HTML.

**Root causes:**
1. Small model ignores "no markdown formatting" instruction
2. Model wraps response in ```html ... ``` fences

**Fix:** `validate_html()` strips fences before BeautifulSoup parsing. If fences still appear, check the fence-stripping regex.

---

## 20. How to Run & Test Locally

### Prerequisites

```bash
# Python 3.10+
# MongoDB running on localhost:27017
# Ollama running on localhost:11434 (or Groq API key)

pip install -r requirements.txt
```

### Configuration (backend/.env)

```
LLM_PROVIDER=ollama
MODEL_NAME=gemma4:e2b
MODEL_TEMPERATURE=0.7

# OR:
LLM_PROVIDER=groq
GROQ_API_KEY=gsk_...
GROQ_MODEL_NAME=llama3-70b-8192
```

### Running the server

```bash
cd backend
uvicorn app.main:app --reload --port 8000
```

The `--reload` flag ensures code changes are picked up automatically.

### Testing the tailor endpoint

```python
import requests

# 1. Upload a resume
with open("resume.docx", "rb") as f:
    upload_resp = requests.post(
        "http://localhost:8000/api/v1/resumes/upload",
        files={"file": f}
    )
resume_id = upload_resp.json()["resume_id"]

# 2. Create a job (or use existing)
# ...

# 3. Tailor
tailor_resp = requests.post(
    "http://localhost:8000/api/v1/resumes/tailor",
    json={"resume_id": resume_id, "job_id": job_id}
)
print(tailor_resp.json()["tailored_text"][:1000])
```

### Checking logs

The system logs at INFO level for section counts and WARNING for fallbacks:
```bash
# Look for these patterns:
# "Resume has N sections: [...]" — Path A
# "Skipping non-editable section 'education'" — Education bypassed
# "Raw LLM output for section 'education': ..." — Debug raw output
# "falling back to whole-document tailoring" — Path C triggered
```

---

## 21. File Inventory

### Core Tailoring

| File | Purpose |
|------|---------|
| `backend/app/services/resume_tailor.py` | Main orchestrator. All 5 tailoring paths, prompts, text parser, heading preservation |
| `backend/app/services/html_service.py` | HTML section parser, validate_html, reassembly, DOCX/PDF conversion |
| `backend/app/services/cover_letter.py` | Cover letter generation |
| `backend/app/services/resume_parser.py` | LLM-based resume parsing during upload |
| `backend/app/services/db_service.py` | MongoDB CRUD operations |

### DOCX Engine (not yet in API)

| File | Purpose |
|------|---------|
| `backend/app/services/resume_tailor_engine/__init__.py` | Orchestrator + `TailorResult` |
| `backend/app/services/resume_tailor_engine/parser.py` | Content map builder from .docx |
| `backend/app/services/resume_tailor_engine/llm_client.py` | Ollama client with JSON mode + batching |
| `backend/app/services/resume_tailor_engine/validator.py` | Budget check, fabrication detection, retry loop |
| `backend/app/services/resume_tailor_engine/reinjector.py` | Run-level write-back (NEVER paragraph.text) |
| `backend/app/services/resume_tailor_engine/verifier.py` | Page count verification via LibreOffice |

### API & Models

| File | Purpose |
|------|---------|
| `backend/app/api/v1/resumes.py` | POST /upload, POST /tailor, POST /download-from-url |
| `backend/app/core/llm.py` | Unified call_llm() with Ollama/Groq/Gemini support |
| `backend/app/core/config.py` | Settings from .env |
| `backend/app/models/resume.py` | Pydantic models for API requests/responses |
| `backend/app/models/resume_elements.py` | ResumeElement model (structured elements) |

### Documentation

| File | Purpose |
|------|---------|
| `backend/docs/RESUME_TAILORING_ENGINE_ARCHITECTURE.md` | Previous architecture doc (v1) |
| `backend/docs/TEMPLATE_PRESERVING_RESUME_ARCHITECTURE.md` | Template-based approach (not current) |
| `backend/docs/resume-tailoring-implementation-plan.md` | Original implementation plan |
| `backend/docs/RESUME_TAILOR_WHOLE_FLOW.md` | **You are here (v2, current)** |
