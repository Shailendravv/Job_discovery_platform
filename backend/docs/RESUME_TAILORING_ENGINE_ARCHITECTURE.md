# Resume Tailoring Engine — Architecture & Implementation Guide

**Version:** 1.0
**Last updated:** June 21, 2026

This document describes the complete resume tailoring system — from the HTML/text section-by-section pipeline in the main API, to the formatting-preserving DOCX engine. Use this as a reference to understand, modify, or extend any part of the system.

---

## Table of Contents

1. [System Overview](#1-system-overview)
2. [Tailoring Pipeline (Main API)](#2-tailoring-pipeline-main-api)
3. [HTML Section Parser (`html_service.py`)](#3-html-section-parser)
4. [Plain Text Section Parser](#4-plain-text-section-parser)
5. [LLM Prompts & JD Prioritization](#5-llm-prompts--jd-prioritization)
6. [Formatting-Preserving DOCX Engine](#6-formatting-preserving-docx-engine)
7. [Integration Points](#7-integration-points)
8. [How to Extend & Modify](#8-how-to-extend--modify)

---

## 1. System Overview

```
┌─────────────────────────────────────────────────────────────┐
│                        API Endpoint                         │
│              POST /api/v1/resumes/tailor                    │
│         (resumes.py → calls resume_tailor.py)              │
└──────────────────────┬──────────────────────────────────────┘
                       │
            ┌──────────▼──────────┐
            │  resume_tailor.py    │
            │  - tailor_resume_html()  → HTML path           │
            │  - tailor_resume_text()  → Text path           │
            │  - tailor_resume_docx_v2() → DOCX engine path  │
            └──────────┬──────────┘
                       │
        ┌──────────────┼──────────────┐
        ▼              ▼              ▼
┌──────────────┐ ┌──────────┐ ┌──────────────┐
│ html_service │ │ Inline   │ │ resume_tailor│
│ .py          │ │ text     │ │ _engine/     │
│ Section      │ │ parser   │ │ (DOCX only)  │
│ parser       │ │          │ │              │
└──────────────┘ └──────────┘ └──────────────┘
```

There are **three independent tailoring paths**:

| Path | Input | Key File(s) | Uses LLM? | Preserves Formatting? |
|------|-------|-------------|-----------|----------------------|
| **HTML** | Full HTML resume | `resume_tailor.py`, `html_service.py` | Yes (section-level) | Yes (preserves HTML tags) |
| **Plain Text** | Extracted text | `resume_tailor.py` (inline parser) | Yes (section-level) | No (plain text only) |
| **DOCX v2** | Raw `.docx` bytes | `resume_tailor_engine/*` | Yes (span-level, batched) | Yes (run-level write-back) |

---

## 2. Tailoring Pipeline (Main API)

**File:** `backend/app/services/resume_tailor.py`

### 2.1 `tailor_resume_html(resume_html, job) → str`

The primary path. Used when the resume has HTML stored (from mammoth DOCX→HTML conversion).

**Flow:**
1. Parse the full HTML into sections via `parse_html_into_sections()`
2. For each section, call the LLM independently with:
   - Just that section's HTML content
   - The full job description (for context)
   - Instructions to preserve tags and emphasize JD keywords
3. Validate the LLM response
4. Reassemble all sections back into full HTML via `reassemble_html()`

**Failure isolation:** If one section's LLM call fails, only that section keeps its original content — the rest are unaffected.

### 2.2 `tailor_resume_text(resume_text, job) → str`

Fallback path for resumes without HTML. Uses an inline text section parser.

**Flow:**
1. Split text into sections via `_split_text_into_sections()`
2. For each section, call the LLM independently
3. Preserve section headings if the LLM drops them
4. Reassemble with spacing between sections

### 2.3 `_fallback_html_tailor(resume_html, job) → str`

Safety net. Used only if `parse_html_into_sections()` raises an exception or returns no sections. Sends the entire resume in one LLM call.

### 2.4 `tailor_resume_structured(elements, job) → list[ResumeElement]`

Legacy path for structured element arrays (JSON-based). Uses a single LLM call with the full element list.

### 2.5 `tailor_resume_docx_v2(docx_bytes, job) → dict`

Integration bridge to the new formatting-preserving DOCX engine. Saves bytes to a temp file, runs the full pipeline, returns tailored DOCX/PDF bytes.

---

## 3. HTML Section Parser

**File:** `backend/app/services/html_service.py`

### 3.1 `_is_heading_like(element) → bool`

Detects if an HTML element looks like a section heading. This is the core of dynamic section detection.

**Detection rules (in order):**
1. **Tag check:** `<h1>`, `<h2>`, `<h3>`, `<h4>` → always a heading
2. **Non-paragraph check:** Only `<p>` and `<div>` are checked further — everything else is ignored
3. **Empty/long check:** Text must exist and be ≤ 60 characters
4. **ALL-CAPS check:** If text is uppercase: must contain at least one recognized section word (from `_COMMON_SECTION_WORDS`) — this filters out dates like "JANUARY 2020" or data lines like "PHONE 555-0100"
5. **Bold child check:** If the first child element is `<strong>` or `<b>` → heading
6. **Short line check:** If text is < 40 chars, doesn't end with ".", and starts with a recognized section word → heading

### 3.2 `_COMMON_SECTION_WORDS`

The shared list of recognized section heading words. Used by both the HTML and text parsers:

```python
["summary", "profile", "objective", "experience", "employment", "history",
 "work", "education", "academic", "skill", "technolog", "competenc",
 "expertise", "project", "certification", "publication", "award", "honor",
 "language", "interest", "reference", "volunteer", "leadership",
 "professional", "qualification", "training", "affiliation", "activity",
 "internship", "research", "achievement", "background", "core",
 "additional", "development"]
```

**To add a new section word:** Add it to `_COMMON_SECTION_WORDS` in `html_service.py`. Both parsers will automatically pick it up.

### 3.3 `parse_html_into_sections(full_html) → list[dict]`

Parses full resume HTML into sections. Returns:

```python
[
    {
        "type": "summary",       # Dynamically classified type
        "editable": True,         # Always True — LLM decides
        "html": "<!DOCTYPE...>",  # Full HTML with CSS wrapper
        "body_html": "<h2>...</h2><p>...</p>",  # Body content only
        "section_name": "professional summary",  # Normalized heading
    },
    # ... more sections
]
```

**How splitting works:**
1. Iterates over `<body>` children
2. When a heading-like element is found (via `_is_heading_like`), the previous group of nodes is saved as a section
3. The heading element starts a new section
4. Everything after it (until the next heading) belongs to that section

**Edge case — content before first heading:** Gets classified as "preamble" type. This handles resumes that start with a name/contact line before any section heading.

### 3.4 `reassemble_html(sections) → str`

Concatenates all sections' `body_html` values and wraps in a full HTML document with CSS. Used after tailoring to rebuild the complete HTML.

### 3.5 `_classify_section(heading_text) → str`

Returns a human-readable type for logging: `"summary"`, `"experience"`, `"skills"`, `"education"`, `"projects"`, `"certifications"`, `"publications"`, `"languages"`, `"volunteer"`, `"preamble"`, or `"other"`.

Used only for logging/debugging — does NOT affect whether the section is sent to the LLM (all sections are sent).

---

## 4. Plain Text Section Parser

**File:** `backend/app/services/resume_tailor.py` (inline functions)

### 4.1 `_is_text_heading_line(stripped) → bool`

Detects heading lines in plain text. Uses the same `_SECTION_HEADING_WORDS` list (should match `_COMMON_SECTION_WORDS` in `html_service.py`).

**Detection rules:**
1. **ALL-CAPS:** Must be ≥ 3 chars and ≤ 60 chars, AND contain a recognized section word
2. **Title-case/sentence-case:** Must be < 40 chars, AND equal or start-with a recognized section word

### 4.2 `_split_text_into_sections(text) → list[dict]`

```python
[
    {
        "type": "summary",
        "heading": "PROFESSIONAL SUMMARY",
        "content": "PROFESSIONAL SUMMARY\nExperienced developer..."
    },
    # ...
]
```

All sections are editable — no filtering occurs.

---

## 5. LLM Prompts & JD Prioritization

### 5.1 HTML Section Prompt (`SECTION_HTML_PROMPT`)

**File:** `resume_tailor.py`

```python
SECTION_HTML_PROMPT = """You are a professional resume writer...
Instructions:
1. Analyze the job description and identify the TOP 3-5 most important skills
2. Rewrite the TEXT CONTENT to STRONGLY EMPHASIZE those top skills
3. For skills less relevant to THIS specific job: de-emphasize them
4. Reorder bullet/paragraph content to put the most relevant points first
5. CRITICAL: PRESERVE ALL HTML TAGS AND STRUCTURE EXACTLY as they are
6. CRITICAL: Do NOT change names, job titles, company names, dates, headings
7. Keep all factual information accurate — do NOT fabricate
8. If already a strong match, return unchanged
9. Return ONLY the modified HTML
"""
```

**Template placeholders:** `{section_html}`, `{section_type}`, `{section_name}`, `{job_title}`, `{job_description}`, `{job_skills}`

### 5.2 Text Section Prompt (`SECTION_TEXT_PROMPT`)

Same structure as the HTML prompt but for plain text. No HTML preservation instruction.

### 5.3 New Engine Prompt (`llm_client.py`)

Uses structured JSON mode (`format="json"`) for deterministic parsing:

- **System prompt** instructs the model to return `{"rewrites": [{"id": "...", "new_text": "..."}]}`
- Each span has a `char_budget` limit
- Skills are ranked by JD relevance

### 5.4 How to Modify Prompts

To change what the LLM emphasizes, edit the prompt templates in:
- `resume_tailor.py`: `SECTION_HTML_PROMPT`, `SECTION_TEXT_PROMPT`
- `resume_tailor_engine/llm_client.py`: `SYSTEM_PROMPT`

Key instructions to maintain:
- "TOP 3-5 most important skills" — forces JD prioritization
- "Do NOT change names, job titles, companies, dates" — fabrication guard
- "Preserve ALL HTML tags" — formatting preservation

---

## 6. Formatting-Preserving DOCX Engine

**Package:** `backend/app/services/resume_tailor_engine/`

A complete 5-phase pipeline that operates on the actual `.docx` file, preserving all fonts, sizes, colors, bold, italic, spacing, and layout.

### 6.1 Phase 1 — Parser (`parser.py`)

**Function:** `build_content_map(docx_path) → (content_map, section_map)`

Walks the DOCX paragraph-by-paragraph, building a content map with:

```python
{
    "id": "p42",                   # Stable ID: "p{para_index}"
    "tier": 1,                     # 1=bullet, 2=summary, 3=skills, 4=header
    "paragraph_index": 42,
    "run_count": 3,
    "run_index": 0,
    "text": "Led development of...",
    "char_budget": 125,            # len(text) * 1.25 + 1 for tier 1
    "section": "experience",
    "needs_manual_review": False,  # True if mixed formatting detected
}
```

**Tier system:**
| Tier | Content | Editable? |
|------|---------|-----------|
| 1 | Bullets under experience | ✅ Freely rewrite |
| 2 | Summary/Objective | ✅ Freely rewrite |
| 3 | Skills list | ✅ Reorder/re-emphasize |
| 4 | Headers, names, titles, dates, companies | 🚫 Never edit |

**Section detection** mirrors the HTML parser: checks heading styles, ALL-CAPS lines, and bold short lines.

**`_is_bullet(para)`:** Detects bullet paragraphs by style name or `numPr` XML element (numbering properties).

**`_check_uniform(para)`:** Checks if all runs in a paragraph share identical bold/italic/underline/font/size/color. Non-uniform paragraphs are flagged for manual review.

**Budget calculation:**
- Tier 1 (bullets): `len(text) * 1.25 + 1` (25% slack)
- Tier 2 (summary): `len(text) * 1.20 + 1` (20% slack)
- Tier 3 (skills): `len(text) * 1.10 + 1` (10% slack)

### 6.2 Phase 2 — LLM Client (`llm_client.py`)

**Function:** `tailor_spans_batched(spans, ...) → list[{"id", "new_text"}]`

Sends spans to Ollama in small batches (default 8) to keep the model focused. Each batch is processed independently — failure of one batch doesn't affect others.

Uses `format="json"` in the Ollama API request for structured output.

**`_call_ollama_structured()`:** Calls Ollama with `format: "json"` and the `REWRITE_SCHEMA` in the system prompt.

### 6.3 Phase 2b — Validator (`validator.py`)

**Function:** `validate_and_apply_budget(rewrites, content_map_by_id) → dict[str, str]`

Checks each rewrite against:
1. **Span exists** — no hallucinated IDs
2. **Not empty** — fall back to original if empty
3. **Char budget** — reject if over budget (retry loop handles it)
4. **Banned patterns** — no `[Placeholder]` patterns
5. **Fabrication detection** — no new dates, percentages, or dollar amounts that weren't in the original

**`retry_over_budget()`:** For over-budget fields, re-prompts the model with a "shorten" instruction. Max 2 retries per field, then falls back to original text.

### 6.4 Phase 3 — Reinjector (`reinjector.py`)

**Function:** `apply_rewrites(original_path, content_map, rewrites, output_path)`

The **most critical rule**: NEVER calls `paragraph.text = ...` or `cell.text = ...`. Only sets `run.text = ...` on the specific run.

**How it works:**
1. Opens the ORIGINAL docx
2. For each span with a rewrite:
   - Single run: `para.runs[0].text = new_text`
   - Multiple uniform runs: put text in run[0], clear runs[1:]
   - Mixed formatting: skip (no automatic rewrite)
3. Table cells use the same run-level approach
4. Typography post-processing: converts straight quotes to curly quotes

### 6.5 Phase 4 — Verifier (`verifier.py`)

**Function:** `verify_page_count(original_path, tailored_path) → bool | None`

Converts both to PDF via LibreOffice headless and compares page counts. Returns None if LibreOffice is not installed.

### 6.6 Orchestrator (`__init__.py`)

**Function:** `tailor_resume(docx_path, job_description, ...) → TailorResult`

The main entry point. Runs all 5 phases in sequence. Also provides `print_content_map()` for calibration debugging.

---

## 7. Integration Points

### 7.1 API Endpoint

**File:** `backend/app/api/v1/resumes.py`

The `POST /tailor` endpoint currently uses the HTML tailoring path. To use the DOCX engine instead, replace:

```python
# Current (line ~185):
tailored_html = await tailor_resume_html(resume_html, job)

# With:
from app.services.resume_tailor import tailor_resume_docx_v2
result = await tailor_resume_docx_v2(docx_bytes, job, output_format="both")
```

### 7.2 New Engine Bridge

**File:** `backend/app/services/resume_tailor.py :: tailor_resume_docx_v2()`

Wraps the 5-phase DOCX engine for use from async API code. Takes `docx_bytes`, saves to temp file, runs pipeline, returns bytes.

### 7.3 LLM Provider

**File:** `backend/app/core/llm.py`

Centralized LLM call function with provider selection:
- `call_llm(prompt, json_format, max_tokens)` — Supports `ollama`, `groq`, `gemini`
- Default `max_tokens=4096` — adequate for section-level calls (each section is small)
- For the DOCX engine, Ollama is used directly (bypasses this)

---

## 8. How to Extend & Modify

### 8.1 Add a New Section Type (e.g., "Publications")

The system is fully dynamic — you don't need to add anything. The LLM prompt already handles all section types. If you want improved type labels in logs:

1. **HTML path:** Add to `_classify_section()` in `html_service.py`
2. **Text path:** Add to `_classify_text_section()` in `resume_tailor.py`

### 8.2 Add a New Section Heading Word (e.g., "milestones")

Add to `_COMMON_SECTION_WORDS` in `html_service.py`. The text parser has a separate `_SECTION_HEADING_WORDS` in `resume_tailor.py` that should be updated to match.

**Recommended:** Import from a shared location instead of duplicating (see Section 8.6).

### 8.3 Change the LLM Prompt to Prioritize Different Skills

Edit the prompt templates in:
- `resume_tailor.py`: `SECTION_HTML_PROMPT`, `SECTION_TEXT_PROMPT`
- `resume_tailor_engine/llm_client.py`: `SYSTEM_PROMPT`

Key areas to customize:
- The "TOP 3-5" number
- Which skills to emphasize/de-emphasize
- The fabrication guard wording
- Output format instructions

### 8.4 Adjust Character Budgets

If the LLM keeps exceeding budgets:
- In `parser.py`: Change `slack_map` values in `_compute_budget()`
- In `validator.py`: Change `max_retries` parameter

### 8.5 Add the DOCX Engine to the API

To make the API use the formatting-preserving engine for DOCX uploads:

```python
# In resumes.py :: tailor_resume()
from app.services.resume_tailor import tailor_resume_docx_v2

# Instead of HTML tailoring, use DOCX v2:
if resume.get("content_type") == "application/vnd.openxmlformats-officedocument.wordprocessingml.document":
    # Fetch original docx bytes from Cloudinary or storage
    docx_bytes = await fetch_original_docx(resume)
    result = await tailor_resume_docx_v2(docx_bytes, job, output_format="both")
    tailored_text = extract_text_from_docx(result["docx_bytes"])
    # ... upload to Cloudinary ...
```

### 8.6 Deduplicate Section Word Lists

The HTML parser (`html_service.py`) and text parser (`resume_tailor.py`) each have their own copy of the section word list. To deduplicate:

```python
# In resume_tailor.py imports:
from app.services.html_service import _get_section_words

# Replace _SECTION_HEADING_WORDS with:
_SECTION_HEADING_WORDS = _get_section_words()
```

### 8.7 Add Debug/Calibration Endpoint

The `print_content_map()` function in `__init__.py` shows how the DOCX engine parses the resume. To add a debug API endpoint:

```python
# In resumes.py:
from app.services.resume_tailor_engine import print_content_map

@router.post("/debug/content-map")
async def debug_content_map(file: UploadFile = File(...)):
    raw_bytes = await file.read()
    with tempfile.NamedTemporaryFile(suffix=".docx") as f:
        f.write(raw_bytes)
        f.flush()
        print_content_map(f.name)
    return {"status": "printed to console"}
```

