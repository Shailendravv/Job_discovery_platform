# Template-Preserving Resume Generation Architecture

> **Last updated:** 2026-06-20
> **Scope:** `backend/app/services/template_service.py`, `backend/app/services/resume_tailor.py`,
> `backend/app/services/embedding_service.py`, `backend/app/models/resume_content.py`,
> `backend/app/services/docx_service.py`, `backend/app/api/v1/resumes.py`,
> `backend/app/services/html_service.py`

---

## Table of Contents

1.  [Architecture Overview](#1-architecture-overview)
2.  [Core Concepts](#2-core-concepts)
3.  [Data Flow](#3-data-flow)
4.  [Component Breakdown](#4-component-breakdown)
5.  [Block-Level DOM Subtree Templating](#5-block-level-dom-subtree-templating)
6.  [Content Selection vs. Rewriting](#6-content-selection-vs-rewriting)
7.  [Separate DOCX and PDF Pipelines](#7-separate-docx-and-pdf-pipelines)
8.  [Validation Pipeline](#8-validation-pipeline)
9.  [Section-Specific Prompts](#9-section-specific-prompts)
10. [Models Reference](#10-models-reference)
11. [Troubleshooting](#11-troubleshooting)
12. [Custom Section Fallback — Text-Based Tailoring](#12-custom-section-fallback--text-based-tailoring)
    1. [When It Activates](#121-when-it-activates)
    2. [Markdown Cleanup (`_strip_markdown`)](#122-markdown-cleanup-_strip_markdown)
    3. [Smart Text-to-HTML Conversion (`_text_to_resume_html`)](#123-smart-text-to-html-conversion-_text_to_resume_html)

---

## 1. Architecture Overview

### The Problem

Traditional resume tailoring sends the **entire HTML document** to an LLM and asks it to "preserve all tags while editing text." This approach is fragile:

- LLMs frequently mangle HTML structure (unclosed tags, missing attributes, broken CSS)
- Full-document HTML exceeds context windows of small models (e.g., Qwen 1.5B)
- Even with careful prompting, models often add or remove structural elements
- Variable-length output (more bullets, longer summaries) breaks fixed templates

### The Solution

A **template-preserving architecture** with strict separation of concerns:

```
┌──────────────────────────────────────────────────────────────────┐
│                        FULL HTML RESUME                          │
└─────────────┬──────────────────────────┬────────────────────────┘
              │                          │
              ▼                          ▼
┌──────────────────────────────┐  ┌─────────────────────────────────┐
│   HEADINGS DETECTED          │  │   NO HEADINGS DETECTED          │
│   (<h2>/<h3> tags found)     │  │   (<p><strong> headings only)   │
│                              │  │                                 │
│   Parse into structured      │  │   Fall back to TEXT-BASED       │
│   sections + cloneable       │  │   tailoring (Section 12)        │
│   fragments                  │  │                                 │
└──────────────┬───────────────┘  └──────────────┬──────────────────┘
               │                                  │
               ▼                                  ▼
┌─────────────────────────────────────────────────────────────────────┐
│             1. PARSE (template_service.py)                          │
│                                                                     │
│   Original HTML ──▶  Template Layer (design)                       │
│                   ──▶  Content Layer (editable data)               │
│                                                                     │
│   Template = {section:id:hash} placeholders + cloneable fragments   │
│   Content  = structured JSON (summary, skills, experiences...)      │
└──────────────────────────┬──────────────────────────────────────────┘
                           │
                           ▼
┌──────────────────────────────────────────────────────────────────┐
│             2. TAILOR (resume_tailor.py)                          │
│                                                                   │
│   For EACH section independently:                                │
│     LLM receives: plain text/JSON only (NEVER HTML)              │
│     LLM returns: JSON only (NEVER HTML)                          │
│                                                                   │
│   Summary     ──▶  groq/gemini/ollama  ──▶  JSON                 │
│   Skills      ──▶  groq/gemini/ollama  ──▶  JSON                 │
│   Experience  ──▶  groq/gemini/ollama  ──▶  JSON                 │
│   Projects    ──▶  groq/gemini/ollama  ──▶  JSON                 │
│   Certs       ──▶  groq/gemini/ollama  ──▶  JSON                 │
└──────────────────────────┬───────────────────────────────────────┘
                           │
                           ▼
┌──────────────────────────────────────────────────────────────────┐
│          3. RECONSTRUCT (template_service.py)                     │
│                                                                   │
│   Cloneable fragments cloned N times, filled with tailored content│
│   ▶ Reconstructed HTML (design preserved + new content)           │
│                                                                   │
│   Then validate:                                                  │
│   - Round-trip parse (no unclosed tags)                          │
│   - Structural DOM diff (tag names, attributes, classes)         │
│   - HTML-special character escaping check                        │
│   - Orphaned marker cleanup                                      │
└──────────────────────────┬───────────────────────────────────────┘
                           │
                           ▼
┌──────────────────────────────────────────────────────────────────┐
│             4. RENDER (separate pipelines)                        │
│                                                                   │
│   ┌────────────────────┐     ┌───────────────────────────────┐   │
│   │  PDF               │     │  DOCX                         │   │
│   │                    │     │                               │   │
│   │  Reconstructed     │     │  Structured Resume JSON       │   │
│   │  HTML ──▶ Playwright│    │  ──▶ python-docx              │   │
│   │  (CSS-faithful)    │     │  (structural, no CSS loss)    │   │
│   └────────────────────┘     └───────────────────────────────┘   │
│                                                                   │
│   These are SEPARATE pipelines with different strengths.          │
│   HTML→DOCX conversion (htmldocx) is NOT used for tailored docs. │
└──────────────────────────────────────────────────────────────────┘
```

### Key Design Decisions

| Decision | Rationale |
|---|---|
| **Block-level DOM subtrees** | Cloneable fragments handle variable-length content (more/fewer bullets) without breaking HTML |
| **Never send HTML to LLM** | The model cannot edit what it never sees — enforced structurally, not by instruction |
| **Per-section chunking** | Each section fits within small-context models (Qwen 1.5B's 32K context) |
| **JSON-only responses** | `json_format=True` forces structured output from the model |
| **Embeddings for selection only** | Selection (which content) uses embeddings; rewriting (how it's phrased) uses direct JD conditioning |
| **Separate DOCX/PDF pipelines** | PDF needs CSS fidelity (Playwright); DOCX needs clean OOXML (python-docx). One HTML render can't serve both. |

---

## 2. Core Concepts

### 2.1 Template Layer vs. Content Layer

**Template Layer** = Design (preserved in `ResumeTemplate.template_html`)
- All HTML tags, CSS styles, classes, layout, spacing, icons, colors
- `{section:id:hash}` placeholders where section body content was removed
- `CloneableFragment` HTML with `{field_name}` markers for text content
- Never sent to the LLM; never modified

**Content Layer** = Editable Data (stored as `ResumeContent.sections`)
- Structured Pydantic models per section type (`SummaryContent`, `ExperienceContent`, etc.)
- Only text content (no HTML, no CSS, no styling)
- Sent to LLM for rewriting; returned as JSON

### 2.2 Cloneable Fragments

A **cloneable fragment** is a DOM subtree representing ONE repeatable unit:

- **One experience entry**: `<h3>{heading_text}</h3><p>{paragraph_text}</p><ul><li>{bullet}</li><li>{bullet_0}</li></ul>`
- **One bullet**: `<li>{bullet}</li>`
- **One skill chip**: `<li>{text}</li>` or `<p>{text}</p>`
- **One certification**: `<li>{text}</li>`

When reconstructing, the fragment is cloned N times and each clone is filled with the corresponding content. This naturally handles variable counts.

### 2.3 Placeholder Integrity

Each section placeholder has a SHA-256 hash:
```
{section:experience_0:a1b2c3d4e5f6}
```

The hash validates that replacements don't accidentally mangle content during reconstruction. If a placeholder's hash doesn't match, it's treated as unreplaced and cleaned up.

### 2.4 Orphaned Marker Cleanup

After filling clone templates, any remaining `{field_name}` markers (e.g., `{bullet_2}` if only 2 bullets were provided but the template had 3 slots) are stripped using:

```python
re.sub(r"\{[a-z_]+\d*\}", "", result)
```

This prevents "raw marker" text from appearing in the output.

---

## 3. Data Flow

### 3.1 Resume Upload → Parse → Template + Content

```
Input: Full HTML resume document (from mammoth DOCX→HTML or elements_to_html PDF→HTML)
                │
                ▼
    1. Parse with BeautifulSoup
                │
                ▼
    2. Find all <h2>/<h3> headings → split into SECTIONS
       Each section = heading + all content until next heading
                │
                ▼
    3. For each section body:
       a. Detect repeatable fragment pattern
          - experience/projects: first h3/h4 + following siblings
          - skills/certs/languages: first <li> element
          - summary/custom: no fragment (flat text)
       b. If fragment detected: create CloneableFragment with {field_name} markers
       c. Extract structured content
       d. Replace body HTML with {section:id:hash} placeholder
                │
                ▼
    4. Return:
       ResumeTemplate  = HTML with placeholders + fragment templates
       ResumeContent   = structured JSON per section
```

### 3.2 Tailor → Reconstruct → Validate (Primary: Headings Detected)

```
Input: ResumeTemplate + ResumeContent + Job description
                │
                ▼
    CHECK: Are any sections known type? (summary, skills, experience, etc.)
                │
           ┌────┴────┐
           ▼         ▼
       YES(primary)  NO(fallback)
           │         See §3.4
           │
           ▼
    1. For each section independently:
       a. Extract plain-text content from ResumeContent
       b. Build prompt with: section content + job title + job description + skills
       c. Call LLM with json_format=True
       d. Parse JSON response
       e. If parsing fails: fall back to original content
                │
                ▼
    2. For each section, render tailored content back to HTML:
       a. If CloneableFragment exists: clone N times, fill each clone
       b. If no fragment: use inline rendering (_render_content_body)
                │
                ▼
    3. Replace {section:id:hash} placeholders with rendered HTML
                │
                ▼
    4. Validate:
       a. Round-trip parse (nothing thrown away)
       b. Style/CSS content preserved
       c. Structural DOM diff (tag names, attributes, classes)
       d. HTML-special character escaping check
       e. Orphaned marker cleanup
                │
                ▼
    Output: Reconstructed HTML (design preserved + new content)
```

### 3.3 Fallback: Tailor → Clean → Convert to HTML (No Headings Detected)

When `tailor_resume_via_template()` detects that ALL parsed sections have type
`"custom"` (meaning `<h2>`/`<h3>` heading tags were NOT found in the HTML), it
delegates to `_fallback_text_tailor()` instead of the primary pipeline.

```
Input: Original resume HTML + Job description
                │
                ▼
    1. EXTRACT plain text from HTML (BeautifulSoup get_text)
                │
                ▼
    2. TAILOR via legacy text-only LLM prompt
       (full resume + job description, no JSON format required)
       Prompt says "return plain text, no markdown"
                │
                ▼
    3. CLEAN markdown syntax the small model may have returned
       _strip_markdown() handles: ###, ####, **bold**, *italic*, ```code```
                │
                ▼
    4. CONVERT to structured HTML:
       _text_to_resume_html() detects:
       - Bullet lines (•, -, ·) → grouped into <ul><li> blocks
       - Section headings (2+ words, ≥10 chars) → <p><strong> tags
       - Single-word known headings (Experience, Skills…) → <p><strong> tags
       - Regular paragraphs → <p> tags
                │
                ▼
    Output: Structured HTML (basic CSS, plain text tailored content)
```

### 3.4 DOCX Generation (from JSON, not HTML)

```
Input: Structured Resume JSON (tailored ResumeContent)
                │
                ▼
    1. Create python-docx Document
    2. For each section in document order:
       - Section heading → Heading 2
       - Summary text → Normal paragraphs
       - Skills → comma-separated paragraph
       - Experience → Heading 3 + duration (gray) + List Bullet items
       - Projects → Heading 3 + description + List Bullet items
       - Certifications → List Bullet items
       - Education → institution – degree – year
       - Languages → comma-separated paragraph
    3. Save to BytesIO
                │
                ▼
    Output: DOCX bytes (clean OOXML, no CSS conversion loss)
```

---

## 4. Component Breakdown

### 4.1 `app/services/template_service.py` — The Core Engine

This is the heart of the architecture. It handles:

| Function | Purpose |
|---|---|
| `parse_html_to_template_and_content()` | Full HTML → Template + Content (entry point) |
| `_detect_repeatable_fragment()` | Identify DOM subtree for one repeatable unit |
| `_zero_out_text_content()` | Create clone template with `{field_name}` markers |
| `_build_template_and_content()` | Build template with placeholders + extracted content |
| `_fill_clone_template()` | Fill a clone template's markers with escaped values |
| `_render_via_clone_fragment()` | Clone fragment N times and render |
| `_render_experience_as_clones()` | Clone experience entry fragment per entry |
| `_render_list_items_as_clones()` | Clone <li> fragment per item |
| `_render_content_body()` | Fallback: inline HTML rendering (no fragments) |
| `reconstruct_html()` | Inject tailored content into template placeholders |
| `_validate_reconstructed_html()` | Full validation pipeline |
| `_recursive_structural_diff()` | Recursive DOM comparison (tag names, attrs, classes) |
| `extract_content_from_html()` | High-level API: parse → return template + content |
| `_xml_escape()` | Escape HTML-special characters before injection |

### 4.2 `app/models/resume_content.py` — Data Models

| Model | Purpose |
|---|---|
| `CloneableFragment` | DOM subtree pattern for one repeatable unit |
| `SectionInfo` | Metadata about a detected section (including optional fragment) |
| `SummaryContent` | Professional summary text |
| `SkillItem` | One skill with optional category |
| `SkillsContent` | Skills list |
| `ExperienceBullet` | One bullet point within an experience entry |
| `ExperienceEntry` | One job/role (title, company, duration, bullets) |
| `ExperienceContent` | Full experience section |
| `ProjectEntry` | One project |
| `ProjectsContent` | Full projects section |
| `CertificationEntry` | One certification |
| `CertificationsContent` | Full certifications section |
| `EducationEntry` | One education entry |
| `EducationContent` | Full education section |
| `LanguagesContent` | Languages list |
| `CustomSectionContent` | Unrecognized sections (passthrough) |
| `ResumeContent` | Container for all sections |
| `ResumeTemplate` | HTML template with placeholders + fragment templates |

### 4.3 `app/services/embedding_service.py` — Content Selection

| Function | Purpose |
|---|---|
| `compute_embedding()` | Compute normalized embedding via sentence-transformers |
| `cosine_similarity()` | Cosine similarity between two vectors |
| `select_relevant_items()` | Generic item selection by embedding similarity |
| `select_relevant_entries()` | Entry-level selection with optional bullet trimming |

**Design principle**: Embeddings are for **which** content surfaces, not **how** it's phrased. Rewriting is a separate step conditioned directly on the JD per section.

### 4.4 `app/services/resume_tailor.py` — Section-Level Tailoring

| Function | Purpose |
|---|---|
| `tailor_summary()` | Rewrite summary text (JSON I/O) |
| `tailor_skills()` | Reorder skills (JSON I/O) |
| `tailor_experience()` | Rewrite experience bullets (JSON I/O) |
| `tailor_projects()` | Rewrite project bullets (JSON I/O) |
| `tailor_certifications()` | Reorder certifications (JSON I/O) |
| `tailor_custom()` | Passthrough for unrecognized section types (returns original unchanged) |
| `tailor_all_sections()` | Orchestrate all section tailoring sequentially |
| `tailor_resume_text()` | Legacy: full-text tailoring via plain-text prompt (no JSON format) |
| `tailor_resume_html()` | Entry point for the template-preserving pipeline |
| `tailor_resume_via_template()` | Full pipeline: parse → tailor → reconstruct → validate |
| `_fallback_text_tailor()` | **Fallback** when no heading tags detected (text → LLM → markdown cleanup → HTML) |
| `_text_to_resume_html()` | Convert plain text to structured HTML with `<ul><li>` and `<p><strong>` |
| `_strip_markdown()` | Strip markdown syntax (`###`, `**`, `*`) from small-model LLM output |
| `_xml_escape_for_fallback()` | XML-escape text for the fallback HTML output |

**Critical**: Every section tailor sends ONLY plain text / JSON to the LLM. The model NEVER sees HTML tags, CSS, or markup. Its input and output are pure data values — it has no markup to edit because it never sees any.

### 4.5 `app/services/docx_service.py` — DOCX-from-JSON

| Function | Purpose |
|---|---|
| `generate_docx_from_resume_content()` | Build DOCX from structured Resume JSON (NOT from HTML) |

This uses python-docx directly: `Paragraph`, `Run`, `List Bullet` style, `Heading 2`/`Heading 3` styles, and proper font/color configuration. No CSS-to-OOXML conversion loss.

### 4.6 `app/api/v1/resumes.py` — API Endpoints

The `/tailor` endpoint now:
1. Calls `tailor_resume_html()` → runs the full template-preserving pipeline
2. Generates DOCX from structured Resume JSON via `generate_docx_from_resume_content()`
3. Generates PDF from reconstructed HTML via Playwright's `html_to_pdf_async()`

This is the **separate pipelines** approach: DOCX and PDF come from different sources (content JSON vs. rendered HTML), each using the best tool for the job.

---

## 5. Block-Level DOM Subtree Templating

### 5.1 How It Works

The key innovation: instead of using text-node placeholders (which break when content length varies), we identify **DOM subtrees** that represent one repeatable unit and clone them.

```
Original HTML for experience section:
┌─────────────────────────────────────────────┐
│ <h2>Experience</h2>                         │
│ <h3>Senior Dev at Acme</h3>                 │
│ <p>2020-2024</p>                            │
│ <ul>                                        │
│   <li>Led team of 5</li>                    │
│   <li>Built microservices</li>              │
│ </ul>                                       │
│ <h3>Junior Dev at Beta</h3>                 │
│ <p>2018-2020</p>                            │
│ <ul>                                        │
│   <li>Wrote tests</li>                      │
│ </ul>                                       │
└─────────────────────────────────────────────┘

Step 1: Detect the repeatable fragment (first entry):
┌─────────────────────────────────────────────┐
│ <h3>Senior Dev at Acme</h3>                 │  ← First h3 = entry boundary
│ <p>2020-2024</p>                            │
│ <ul>                                        │
│   <li>Led team of 5</li>                    │
│   <li>Built microservices</li>              │
│ </ul>                                       │
└─────────────────────────────────────────────┘

Step 2: Zero out text → clone template:
┌──────────────────────────────────────────────┐
│ <h3>{heading_text}</h3>                       │
│ <p>{paragraph_text}</p>                       │
│ <ul>                                          │
│   <li>{bullet}</li>                           │
│   <li>{bullet_0}</li>                         │
│ </ul>                                         │
└──────────────────────────────────────────────┘

Step 3: Two entries → clone 2×, fill each:
┌──────────────────────────────────────────────┐
│ <h3>Senior Dev at Acme</h3>                   │  ← Clone 1
│ <p>2020-2024</p>                              │
│ <ul>                                          │
│   <li>Led team of 5...</li>                   │
│   <li>Built microservices...</li>             │
│ </ul>                                         │
│ <h3>Junior Dev at Beta</h3>                   │  ← Clone 2
│ <p>2018-2020</p>                              │
│ <ul>                                          │
│   <li>Wrote tests...</li>                     │
│ </ul>                                         │
└──────────────────────────────────────────────┘
```

### 5.2 Fragment Detection Strategy

| Section Type | Detection Strategy |
|---|---|
| `experience` | First `<h3>`/`<h4>` subheading + following siblings (up to next subheading) |
| `projects` | Same as experience |
| `skills` | First `<li>` element |
| `certifications` | First `<li>` element |
| `languages` | First `<li>` element |
| `summary` | No fragment (flat text) |
| `custom` | No fragment (passthrough) |

### 5.3 Field Zeroing Strategy

The `_zero_out_text_content()` function replaces text in a DOM fragment with `{field_name}` markers:

| Parent Tag | Field Name |
|---|---|
| `<h3>`, `<h4>` | `{heading_text}`, `{heading_text_0}`, ... |
| `<p>` | `{paragraph_text}`, `{paragraph_text_0}`, ... |
| `<li>` | `{bullet}`, `{bullet_0}`, `{bullet_1}`, ... |
| `<strong>`, `<b>` | `{bold_text}`, `{bold_text_0}`, ... |
| Other | `{text}`, `{text_0}`, ... |

### 5.4 Why Not Text-Node Replacement?

The **old approach** (previous iteration of this architecture):
```
Template: <h2>Summary</h2>{section:summary_0:abc123}
Replacement: <h2>Summary</h2><p>Tailored summary text here...</p>
```

Problems:
- If section has no content (LLM returned empty), the section was blanked
- If section had variable-length content, it could overflow containers
- No structural enforcement for variable bullet counts

The **new approach** (current):
```
Template: <h2>Experience</h2>{section:experience_0:def456}
          + CloneableFragment: <h3>{heading_text}</h3><ul><li>{bullet}</li></ul>
Replacement: Clone fragment N times:
  <h3>Role at Company</h3><ul><li>Bullet 1</li></ul>
  <h3>Role2 at Company2</h3><ul><li>Bullet 2</li></ul>
```

Benefits:
- Variable entry count: clone 1 time for 1 entry, 5 times for 5 entries
- Variable bullet count: template has N bullet slots, orphaned markers cleaned up
- HTML structure always valid (the fragment is valid HTML, cloning preserves it)
- CSS/style/layout fully preserved (fragment includes all attributes and classes)

---

## 6. Content Selection vs. Rewriting

### 6.1 Separation of Concerns

```
┌──────────────────────────────────────────────────────────────────┐
│                        SELECTION                                 │
│  (embedding_service.py)                                          │
│                                                                   │
│  Purpose: Pick WHICH content surfaces                            │
│  Method: Embedding similarity (JD vs. bullet text)               │
│  Input:  Master resume with 10+ entries                          │
│  Output: Top-5 most relevant entries                             │
│  Used:   AP pre-filter (optional, before tailoring)              │
└──────────────────────────────────────────────────────────────────┘
                           │
                           ▼
┌──────────────────────────────────────────────────────────────────┐
│                        REWRITING                                 │
│  (resume_tailor.py)                                              │
│                                                                   │
│  Purpose: Change HOW content is phrased                          │
│  Method: Direct JD conditioning (prompt engineering)             │
│  Input:  Selected entries + job description                      │
│  Output: Rewritten entries (JSON)                                │
│  Used:   Every section tailoring call                            │
└──────────────────────────────────────────────────────────────────┘
```

### 6.2 When to Use Selection

Selection is used when the master resume has **more entries/bullets than appropriate** for a given job application:

```python
from app.services.embedding_service import select_relevant_entries

# Before tailoring: reduce 10 entries to top 5 most relevant
selected_entries = select_relevant_entries(
    entries=master_entries,
    query=job_description,
    entry_text_fn=lambda e: f"{e.title} {e.company} {' '.join(b.text for b in e.bullets)}",
    top_k=5,
    bullets_per_entry=6,  # optional: limit bullets per entry
    bullet_text_fn=lambda e: [b.text for b in e.bullets],
)
```

### 6.3 When to Use Rewriting

Rewriting is used in every section tailoring call. The model conditions directly on the JD to optimize phrasing. It does NOT use embeddings — it uses the raw JD text in the prompt.

This separation means:
- **Selection** handles the "too much content" problem
- **Rewriting** handles the "optimize phrasing" problem
- Neither step conflates the other's job

---

## 7. Separate DOCX and PDF Pipelines

### 7.1 Why Separate?

HTML→DOCX conversion (htmldocx) is **lossy** for:
- CSS positioning (margins, padding, floats)
- Custom fonts (icon fonts, non-standard families)
- Precise spacing (letter-spacing, word-spacing)
- Background colors and gradients

PDF from HTML (Playwright) is **lossless** for all of these because the browser renders the HTML/CSS exactly as specified.

Therefore, a single HTML render cannot faithfully serve both formats.

### 7.2 DOCX Pipeline (from JSON)

```
ResumeContent (Pydantic models)
        │
        ▼
generate_docx_from_resume_content()
        │
        ├── Heading 2 for section titles
        ├── Heading 3 for experience/project entries  
        ├── List Bullet for bullet points
        ├── Normal paragraph for descriptions
        ├── Gray (RGB 0x55, 0x55, 0x55) for duration text
        └── BOLD for emphasis
        │
        ▼
    python-docx Document → BytesIO → bytes
```

### 7.3 PDF Pipeline (from HTML)

```
Reconstructed HTML (template_service.py)
        │
        ▼
html_to_pdf_async()
        │
        ├── Playwright (headless Chromium)
        ├── Renders HTML with full CSS fidelity
        ├── page.pdf() with Letter format + margins
        └── print_background=True for colors
        │
        ▼
    PDF bytes
```

### 7.4 API Integration

In `app/api/v1/resumes.py`, the `/tailor` endpoint:

```python
# DOCX: from structured Resume JSON
template, content = parse_html_to_template_and_content(resume_html)
docx_bytes = generate_docx_from_resume_content(content.sections, content.raw_sections)

# PDF: from reconstructed HTML
pdf_bytes = await html_to_pdf_async(tailored_html)
```

---

## 8. Validation Pipeline

After reconstruction, the system runs a multi-step validation:

### 8.1 Round-Trip Parse

```python
recon_soup = BeautifulSoup(reconstructed_html, "html.parser")
re_serialized = str(recon_soup)
# Verify no parse-time errors (BS4 will warn on malformed HTML)
```

### 8.2 HTML-Special Character Check

Scans text nodes for unescaped `&`, `<`, `>` characters:
```python
if "&" in text and "&amp;" not in text and not text.strip().startswith("{"):
    warnings.append(f"Potentially unescaped '&' in text node: '{text[:50]}...'")
```

### 8.3 Style/CSS Preservation

Compares `<style>` block content between original and reconstructed HTML:
```python
if orig_style and recon_style:
    if orig_style.get_text(strip=True) != recon_style.get_text(strip=True):
        warnings.append("CSS/style content differs between original and reconstructed HTML")
```

### 8.4 Structural DOM Diff

Recursive walk comparing every element in the body:

```python
_recursive_structural_diff(orig_body, recon_body, path="body")

# For each element (recursively):
# - Tag name match?
# - Attributes match? (excluding inline style)
# - Class lists match?
# - Child element count match?
```

Any structural difference is reported as a warning. Differences include:
- Tag names: `@{path}: tag 'div' vs 'p'`
- Missing classes: `@{path}: missing classes {'highlight'}`
- Extra classes: `@{path}: extra classes {'new-class'}`
- Attribute mismatch: `@{path}: attributes differ...`
- Child count: `@{path}: child element count 3 vs 2`

### 8.5 Orphaned Marker Cleanup

Any remaining `{field_name}` markers in the final HTML are stripped:
```python
result = re.sub(r"\{[a-z_]+\d*\}", "", result)
```

---

## 9. Section-Specific Prompts

### 9.1 Summary

```
You are an ATS-optimization resume writer.
Given a candidate's Professional Summary and a target job description,
rewrite the summary to best match the job.
Return ONLY valid JSON: {"summary_text": "your rewritten summary here"}

RULES:
- Use strong action verbs and industry keywords from the job description
- Keep factual information accurate — do NOT fabricate experience
- Keep the same length and scope as the original
- Optimize for ATS parsing (use keywords naturally)
- Write in 1-3 concise paragraphs
- Return ONLY the JSON object, no markdown, no code fences, no commentary
```

### 9.2 Skills

```
You are an ATS-optimization resume writer.
Given a candidate's Skills list and a target job description,
reorder and optimize the list.
Return ONLY valid JSON: {"skills": [{"name": "skill name"}]}

RULES:
- Prioritize skills that appear in the job description — move them to the front
- Keep ALL original skills (do not remove any)
- You may add at most 3 new skills that are clearly implied by existing experience
- Do NOT fabricate skills the candidate doesn't have
- Return ONLY the JSON object, no markdown, no code fences, no commentary
```

### 9.3 Experience

```
You are an ATS-optimization resume writer.
Given a list of Experience entries and a target job description,
rewrite the bullet points for each entry to best match the job.
Return ONLY valid JSON: {"entries": [
  {"company": "...", "title": "...", "duration": "...", "bullets": [{"text": "..."}]}
]}

RULES:
- Rewrite bullet text to use stronger action verbs and industry keywords
- Keep the SAME number of bullets per entry as the original
- Keep ALL factual information accurate — do NOT fabricate
- Preserve company, title, and duration exactly as given
- Use quantified achievements where the original supports it
- Return ONLY the JSON object, no markdown, no code fences, no commentary
```

### 9.4 Projects

```
You are an ATS-optimization resume writer.
Given a list of Projects and a target job description,
rewrite the descriptions and bullet points.
Return ONLY valid JSON: {"entries": [
  {"name": "...", "description": "...", "bullets": [{"text": "..."}]}
]}

RULES:
- Rewrite descriptions and bullets to highlight relevance to the target job
- Keep the SAME number of bullets per entry as the original
- Keep ALL factual information accurate — do NOT fabricate
- Preserve project names exactly as given
- Use technical keywords from the job description where applicable
- Return ONLY the JSON object, no markdown, no code fences, no commentary
```

### 9.5 Certifications

```
You are an ATS-optimization resume writer.
Given a list of Certifications and a target job description,
reorder them by relevance.
Return ONLY valid JSON: {"entries": [{"name": "Certification Name"}]}

RULES:
- Keep ALL original certifications
- Reorder so most relevant to the job come first
- Do NOT add certifications the candidate hasn't earned
- Return ONLY the JSON object, no markdown, no code fences, no commentary
```

---

## 10. Models Reference

### 10.1 `CloneableFragment`

```python
class CloneableFragment(BaseModel):
    """
    A DOM subtree pattern representing ONE repeatable unit
    (one experience entry, one bullet, one skill chip).
    The template uses {field_name} placeholders for text content,
    and can be cloned N times to build a list of entries.
    """
    html_template: str  # HTML with {field_name} markers
```

### 10.2 `SectionInfo`

```python
class SectionInfo(BaseModel):
    section_id: str                          # e.g., "experience_0"
    heading_text: str                        # e.g., "Professional Experience"
    heading_tag: str                         # e.g., "h2"
    heading_html: str                        # Full HTML of heading element
    section_type: SECTION_TYPES              # "summary" | "skills" | "experience" | ...
    order: int                               # Position in document (0-based)
    fragment_template: Optional[CloneableFragment]  # Cloneable fragment, if detected
```

### 10.3 `ResumeTemplate`

```python
class ResumeTemplate(BaseModel):
    template_html: str                       # HTML with {section:id:hash} placeholders
    sections: list[SectionInfo]              # Metadata per section
    original_full_html: str                  # Original HTML (for validation)
```

### 10.4 `ResumeContent`

```python
class ResumeContent(BaseModel):
    sections: list[ResumeSectionContent]     # Section content in document order
    raw_sections: list[SectionInfo]          # Parallel: metadata per section
```

### 10.5 Section Content Models

All section content models share a `section_type` field for discriminated union support:

| Model | `section_type` | Key Fields |
|---|---|---|
| `SummaryContent` | `"summary"` | `summary_text: str` |
| `SkillsContent` | `"skills"` | `skills: list[SkillItem]` |
| `ExperienceContent` | `"experience"` | `entries: list[ExperienceEntry]` |
| `ProjectsContent` | `"projects"` | `entries: list[ProjectEntry]` |
| `CertificationsContent` | `"certifications"` | `entries: list[CertificationEntry]` |
| `EducationContent` | `"education"` | `entries: list[EducationEntry]` |
| `LanguagesContent` | `"languages"` | `items: list[str]` |
| `CustomSectionContent` | `"custom"` | `heading: str, content_text: str` |

---

## 11. Troubleshooting

### "No sections detected" / "All sections are custom" warning

The template parser found no `<h2>`/`<h3>` headings in the HTML. Causes:
- The HTML has a non-standard structure (no heading tags)
- The resume uses `<p><strong>Heading</strong></p>` instead of `<h2>`/`<h3>`
- The mammoth/elements_to_html output didn't produce heading tags

**Fix**: The parser falls back to `_handle_no_headings()` which creates a single
custom section. `tailor_resume_via_template()` detects this (all sections type
`"custom"`) and delegates to `_fallback_text_tailor()` — see [Section 12](#12-custom-section-fallback--text-based-tailoring).

If the fallback markdown/heading detection produces poor results, ensure the
uploaded DOCX uses proper Word heading styles (Heading 1, Heading 2) rather than
just bold formatting.

### "Fragment count mismatch" warning

**This is a logged warning, not an error.** The clone template has a different number of entries/bullets than the tailored content. This happens when:
- The LLM returned a different number of entries than expected
- The fragment detection found a different pattern than expected

**Fix**: The orphaned-marker cleanup (`re.sub(r"\{[a-z_]+\d*\}", "", result)`) handles this gracefully by stripping unfilled markers. The prompt instructs the model to keep the same count, so this should be rare.

### "CSS/style content differs" validation warning

The reconstructed HTML's `<style>` block doesn't match the original. This should never happen because the style block is never touched — it's part of the template.

**Fix**: If this warning appears, something went very wrong during template reconstruction. Check that the template parsing correctly preserved the `<head>` section. File a bug.

### "Structural DOM diff" validation warnings

The recursive DOM walk found differences between original and reconstructed HTML structure. Examples:
- `@body/h2[0]: tag 'h2' vs 'h3'` — a heading tag changed type
- `@body/div[2]/ul[0]: child element count 3 vs 2` — a list has different items
- `@body/p[1]: missing classes {'highlight'}` — a class was removed

**Fix**: These indicate the template structure was modified during reconstruction. This should be extremely rare since the model never touches HTML. Check if the fragment cloning or inline rendering produced different structure than expected.

### Orphaned `{field_name}` text visible in output

The `re.sub()` cleanup failed to strip a marker. Possible causes:
- The marker uses non-standard characters (regex only matches `[a-z_]`)
- The marker is inside a script or style block that was preserved separately

**Fix**: Verify the marker format matches `{field_name_N}`. If it does, file a bug with the specific marker text.

### Embedding service returns no results

`compute_embedding()` returned `None`. Causes:
- `sentence-transformers` is not installed (pip package missing)
- The model failed to load (corrupted download, OOM)
- The text is empty or contains only stop words

**Fix**: Install `sentence-transformers`:
```bash
pip install sentence-transformers
```
The function returns `[]` (empty list) as fallback, which means `select_relevant_items` returns the first `top_k` items unsorted.

### Fallback HTML shows raw `###`, `####`, or `**` characters in PDF

The PDF was generated from HTML that contains raw markdown syntax. The small
LLM (e.g., qwen2.5-coder:1.5b on Ollama) ignored the "no markdown" instruction
and returned markdown-formatted text, which was then wrapped in `<p>` tags.

**Fix**: `_strip_markdown()` was added to clean markdown syntax before HTML
conversion (see [Section 12.2](#122-markdown-cleanup-_strip_markdown)).
This runs automatically in the fallback path. If markdown still appears,
the LLM is using non-standard markers not covered by the regex patterns —
check the logs and extend `_strip_markdown()` in `resume_tailor.py`.

### Fallback output has flat `<p>` tags (no bullet lists, all text same weight)

The old `plain_text_to_html()` wrapped every line in a flat `<p>` tag,
losing bullet structure and heading emphasis.

**Fix**: `_text_to_resume_html()` was added as a replacement (see
[Section 12.3](#123-smart-text-to-html-conversion-_text_to_resume_html)).
It detects bullet markers (`•`, `-`, `·`), section heading patterns
(2+ words, ≥10 chars, all-caps, separator chars), and known single-word
headings (`Experience`, `Skills`, …) and renders them with proper
`<ul><li>` and `<p><strong>` tags.

---

## 12. Custom Section Fallback — Text-Based Tailoring

### 12.1 When It Activates

The template-preserving pipeline relies on detecting `<h2>`/`<h3>` heading tags
in the resume HTML. However, many DOCX-to-HTML converters (including mammoth)
output `<p><strong>Heading</strong></p>` instead of `<h2>Heading</h2>` when
the DOCX uses bold formatting rather than proper Word heading styles.

When `tailor_resume_via_template()` parses the HTML and detects that ALL
detected sections have `section_type == "custom"` (none of the known types:
summary, skills, experience, projects, certifications, education, languages),
it concludes the heading detection failed and activates the fallback:

```python
# In tailor_resume_via_template() — resume_tailor.py
known_types = {"summary", "skills", "experience", "projects",
               "certifications", "education", "languages"}
all_custom = all(
    info.section_type not in known_types
    for info in resume_content.raw_sections
)

if all_custom:
    log.warning(
        "No known section types detected (%d sections, all 'custom') — "
        "falling back to text-based tailoring"
    )
    return await _fallback_text_tailor(resume_html, job)
```

The fallback function `_fallback_text_tailor()` does three things:
1. Extracts plain text from the resume HTML via BeautifulSoup
2. Calls the legacy `tailor_resume_text()` which sends the FULL resume text
   (no JSON format, no section parsing) to the LLM with a simple prompt
3. Passes the LLM output through two cleanup stages before wrapping in HTML

### 12.2 Markdown Cleanup (`_strip_markdown`)

The legacy prompt instructs the LLM to "return plain text only, no markdown
formatting." Small models (qwen2.5-coder:1.5b) frequently ignore this and
return markdown anyway. `_strip_markdown()` cleans the output before HTML
conversion:

```python
def _strip_markdown(text: str) -> str:
    """
    Strip common markdown syntax from LLM output before HTML conversion.

    Small models like qwen2.5-coder:1.5b often fail to follow the
    "no markdown formatting" instruction and return markdown anyway.

    Cleans:
    - Heading markers: #, ##, ###, #### at line starts
    - Bold markers: **text** → text
    - Italic markers: *text* → text (but not bullet asterisks)
    - Mismatched markers: *text** → text, **text* → text
    - Trailing asterisks on bold/italic text
    - Triple-backtick code fences
    - Multiple spaces collapsed to single space
    """
```

**Regex order matters**: properly-paired `**text**` is handled first, then
mismatched patterns (`*text**`, `**text*`), then any remaining stray `*` or
`**` are removed entirely. This prevents raw markdown from appearing in the
PDF output while preserving the actual content.

### 12.3 Smart Text-to-HTML Conversion (`_text_to_resume_html`)

After markdown cleanup, the plain text is converted to structured HTML.
This replaces the old `plain_text_to_html()` which wrapped every line in
a flat `<p>` tag, destroying bullet lists and heading structure.

The converter operates line-by-line with three detection rules:

| Detection | Rule | HTML Output |
|---|---|---|
| **Bullet lines** | Starts with `•`, `-`, `·`, or digit (e.g., `1.`) | Consecutive bullets grouped into `<ul><li>` block |
| **Section headings** | 2+ words, ≥10 chars, no period/comma at end | `<p><strong>text</strong></p>` |
| **ALL-CAPS headings** | All uppercase, >3 chars | `<p><strong>TEXT</strong></p>` |
| **Separator headings** | Contains `|`, `–`, `—` | `<p><strong>text</strong></p>` |
| **Known headings** | Single word in `_KNOWN_HEADINGS` set | `<p><strong>text</strong></p>` |
| **Regular text** | Everything else | `<p>text</p>` |

**Known single-word headings** (`_KNOWN_HEADINGS`):
```python
_KNOWN_HEADINGS = {
    "summary", "profile", "objective",
    "experience", "employment", "work",
    "education", "academic",
    "skills", "competencies",
    "projects", "portfolio",
    "certifications", "certificates", "licenses",
    "languages",
    "publications", "awards", "honors",
    "references", "volunteering",
    "additional", "interests",
}
```

This ensures that after `_strip_markdown` removes `###` from `### Experience`,
the remaining word `Experience` is still recognized as a section heading and
rendered with `<strong>` tags.

**Conservative heading detection**: Short fragments like `Full-Stack` (1 word,
9 chars) are deliberately NOT bolded to avoid false positives. The threshold
requires 2+ words AND ≥10 characters for heuristic heading detection.

### 12.4 Limitations of the Fallback Path

| Limitation | Impact |
|---|---|
| **No design preservation** | The fallback generates basic HTML with default CSS, not the original resume layout |
| **No cloneable fragments** | Bullet lists are detected heuristically (consecutive lines starting with `•`) rather than from DOM structure |
| **Markdown leakage** | If the LLM uses unusual markdown not covered by `_strip_markdown`, raw syntax may appear in output |
| **Single-word headings only** | Only recognizes known heading words (Experience, Skills…). Custom section headings like "Open Source" are not bolded |

For best results, use DOCX files with proper Word heading styles so the
primary template-preserving pipeline activates.

---

## Appendix: File Map

```
backend/
├── app/
│   ├── models/
│   │   ├── resume_content.py         # CloneableFragment, SectionInfo, section content models
│   │   └── resume_elements.py        # Legacy: ResumeElement, ResumeLink
│   │
│   ├── services/
│   │   ├── template_service.py       # ⭐ Core: parse/reconstruct/validate/clone
│   │   ├── resume_tailor.py          # Section-level chunked tailoring (NEVER sends HTML to LLM)
│   │   ├── embedding_service.py      # Content selection via embeddings
│   │   ├── html_service.py           # Legacy: HTML round-trip (mammoth, htmldocx, Playwright)
│   │   ├── docx_service.py           # DOCX read/write + DOCX-from-JSON
│   │   ├── PDF_service.py            # PDF read/write
│   │   ├── resume_parser.py          # LLM-based resume parsing
│   │   └── cover_letter.py           # LLM-based cover letter generation
│   │
│   └── api/
│       └── v1/
│           └── resumes.py            # API endpoints (uses DOCX-from-JSON + PDF-from-HTML)
│
└── docs/
    └── TEMPLATE_PRESERVING_RESUME_ARCHITECTURE.md    # ← You are here
```

---

*End of documentation. Last updated: 2026-06-20.*
