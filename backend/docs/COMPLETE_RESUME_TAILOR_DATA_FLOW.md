# Complete Resume Tailoring Data Flow

**Version:** 3.0
**Last updated:** June 22, 2026
**Scope:** Full end-to-end flow from file upload → all 6 tailoring paths → download

---

## Table of Contents

1. [System Architecture Overview](#1-system-architecture-overview)
2. [Data Flow: Upload + All 6 Tailoring Paths](#2-data-flow-upload--all-6-tailoring-paths)
3. [Flow 0: Resume Upload](#3-flow-0-resume-upload-post-upload)
4. [Legacy Paths A–E (summarized)](#4-legacy-paths-ae-summarized)
5. [Flow 6: Structured Tailoring — PATH F (NEW)](#5-flow-6-structured-tailoring--path-f-new)
6. [PII Service Deep Dive](#6-pii-service-deep-dive)
7. [ATS Optimization Engine Prompt](#7-ats-optimization-engine-prompt)
8. [API Response Comparison](#8-api-response-comparison)
9. [File Inventory — All Tailoring Code](#9-file-inventory--all-tailoring-code)
10. [How to Use the New Endpoint](#10-how-to-use-the-new-endpoint)
11. [Migration Guide: Legacy → Structured](#11-migration-guide-legacy--structured)

---

## 1. System Architecture Overview

```
┌────────────────────────────────────────────────────────────────────────────┐
│                          API Layer (FastAPI)                                │
│                    backend/app/api/v1/resumes.py                            │
│                                                                             │
│  ┌──────────────┐  ┌──────────────────┐  ┌─────────────────────────────┐   │
│  │ POST /upload │  │  POST /tailor    │  │  POST /tailor-structured    │   │
│  │ (Flow 0)     │  │  (Legacy — F1)   │  │  (NEW — Flow 6 — Path F)    │   │
│  └──────┬───────┘  └────────┬─────────┘  └─────────────┬───────────────┘   │
└─────────┼───────────────────┼──────────────────────────┼───────────────────┘
          │                   │                          │
          ▼                   ▼                          ▼
┌─────────────────┐  ┌──────────────────┐  ┌──────────────────────────┐
│  Resume Parser  │  │  resume_tailor   │  │  structured_tailor.py    │
│  (Flow 0)       │  │  (Paths A–E)     │  │  (Path F — NEW)          │
│                 │  │                  │  │                          │
│  parse_         │  │  A. tailor_     │  │  Extract PII → Build     │
│  resume_text()  │  │     resume_     │  │  JSON → Strip PII →      │
│  ↓              │  │     html()      │  │  Call OpenRouter →       │
│  Structured    │  │  B. tailor_     │  │  Parse → Re-inject        │
│  JSON          │  │     resume_     │  │  PII → Generate HTML      │
│                 │  │     text()      │  │                          │
│                 │  │  C. _fallback_  │  │  ┌──────────────┐        │
│                 │  │     html_       │  │  │  pii_service │        │
│                 │  │     tailor()    │  │  │  .py         │        │
│                 │  │  D. tailor_     │  │  │  - extract   │        │
│                 │  │     resume_     │  │  │  - strip     │        │
│                 │  │     structured()│  │  │  - reinject  │        │
│                 │  │  E. tailor_     │  │  └──────────────┘        │
│                 │  │     resume_     │  │                          │
│                 │  │     docx_v2()   │  │                          │
│                 │  │                  │  │                          │
│                 │  └──────────────────┘  └──────────────────────────┘
│                 │           │                         │
│                 │           ▼                         ▼
│                 │  ┌──────────────────┐  ┌──────────────────────────┐
│                 │  │  LLM call via    │  │  LLM call via            │
│                 │  │  call_llm_async()│  │  llm.generate_async()    │
│                 │  │  ↓               │  │  ↓                       │
│                 │  │  call_llm() →    │  │  get_llm_provider()      │
│                 │  │  llm.generate()  │  │  → OpenRouterProvider    │
│                 │  │  → asyncio.run() │  │  (or OllamaProvider)     │
│                 │  └──────────────────┘  └──────────────────────────┘
│                 │           │                         │
│                 │           ▼                         ▼
│                 │  ┌──────────────────┐  ┌──────────────────────────┐
│                 │  │  Output Files    │  │  Output Files             │
│                 │  │  - PDF (PlayW.) │  │  - PDF (Playwright)       │
│                 │  │  - DOCX (ht.    │  │  - DOCX (htmldocx)        │
│                 │  │    docx)        │  │  + ATS metadata in JSON   │
│                 │  │  + Cover Letter │  │  + Cover Letter           │
│                 │  └──────────────────┘  └──────────────────────────┘
```

### Two Independent Tailoring APIs

| Feature | Legacy `POST /tailor` | NEW `POST /tailor-structured` |
|---------|----------------------|-------------------------------|
| Endpoint | `/api/v1/resumes/tailor` | `/api/v1/resumes/tailor-structured` |
| Input format | HTML (preferred) or plain text | Structured JSON from parser |
| PII handling | Sent to LLM (included in text/HTML) | **Stripped before LLM call**, re-injected after |
| LLM provider | Uses `call_llm_async()` → configured provider | Uses `get_llm_provider()` → configured provider directly |
| Section handling | One LLM call per section (many calls) | **One LLM call** for entire resume (JSON→JSON) |
| ATS metadata | Not returned | `ats_keywords_matched`, `ats_keywords_missing`, `optimization_notes` |
| System prompt | Resume section rewrite (HTML/text) | **ATS Optimization Engine** (user-provided) |
| Cover letter | Included | Included |
| Response includes | `tailored_text`, `cover_letter`, `download_urls` | + `tailored_data` (structured JSON), `ats_*`, `llm_model` |

---

## 2. Data Flow: Upload + All 6 Tailoring Paths

```
                         UPLOAD RESUME
                              │
                              ▼
                  ┌──────────────────────┐
                  │  Flow 0: POST/upload  │
                  │                      │
                  │  1. Validate file    │
                  │  2. Extract text     │
                  │  3. Convert to HTML  │
                  │  4. Upload to        │
                  │     Cloudinary       │
                  │  5. Parse with LLM   │
                  │     → JSON           │
                  │  6. Save to MongoDB  │
                  └──────────┬───────────┘
                             │
                             ▼
                  ┌──────────────────────┐
                  │  MongoDB Document    │
                  │                      │
                  │  - extracted_text    │
                  │  - resume_html       │
                  │  - parsed_data {     │
                  │      name, email,    │
                  │      phone,          │
                  │      education[],    │
                  │      experience[],   │
                  │      skills[],       │
                  │      languages[],    │
                  │      certs[]         │
                  │    }                 │
                  └──────────┬───────────┘
                             │
              ┌──────────────┴──────────────┐
              │         TAILOR               │
              │                              │
     ┌────────┴────────┐         ┌───────────┴───────────┐
     │  POST /tailor   │         │  POST /tailor-        │
     │  (Legacy)       │         │  structured (NEW)     │
     └────────┬────────┘         └───────────┬───────────┘
              │                              │
              ▼                              ▼
    ┌──────────────────┐          ┌──────────────────────┐
    │  resume_tailor.py │          │  structured_tailor   │
    │                   │          │  .py (Path F)        │
    │  Has resume_html? │          │                      │
    │    ├─ YES → A     │          │  1. extract_pii()   │
    │    └─ NO  → B     │          │  2. Build input JSON│
    │                   │          │     (no PII fields)  │
    │  A → sections?    │          │  3. Send to LLM     │
    │    ├─ YES → per   │          │     with ATS prompt  │
    │    │     section  │          │  4. Parse response  │
    │    └─ NO  → C     │          │  5. reinject_pii()  │
    │                   │          │  6. Generate HTML   │
    │  D (legacy)       │          │  7. Return ATS meta │
    │  E (DOCX engine)  │          └──────────────────────┘
    └──────────────────┘
              │                              │
              ▼                              ▼
    ┌──────────────────┐          ┌──────────────────────┐
    │  Generate Files   │          │  Generate Files      │
    │  - Cover letter   │          │  - Cover letter      │
    │  - PDF (Playw.)   │          │  - PDF (Playwright)  │
    │  - DOCX (htmldocx)│          │  - DOCX (htmldocx)   │
    │  Upload to        │          │  Upload to           │
    │  Cloudinary       │          │  Cloudinary          │
    └──────────────────┘          └──────────────────────┘
              │                              │
              ▼                              ▼
    ┌──────────────────┐          ┌──────────────────────┐
    │  Response:        │          │  Response:            │
    │  - tailored_text  │          │  - tailored_data     │
    │  - cover_letter   │          │    (structured JSON) │
    │  - download_urls  │          │  - tailored_text     │
    │    { pdf, docx,   │          │  - cover_letter      │
    │      cover_letter │          │  - download_urls     │
    │      _pdf }       │          │  - ats_keywords_     │
    └──────────────────┘          │    matched[]         │
                                   │  - ats_keywords_    │
                                   │    missing[]         │
                                   │  - optimization_     │
                                   │    notes[]           │
                                   │  - llm_model         │
                                   └──────────────────────┘
```

---

## 3. Flow 0: Resume Upload

**File:** `backend/app/api/v1/resumes.py` → `upload_resume()`

### Step-by-step

```
Uploaded File (PDF/DOCX/DOC)
        │
        ▼
1. Validate file type & size (max 10 MB)
        │
        ▼
2. Extract text:
   ├── PDF: extract_text_from_pdf()   (PyMuPDF)
   └── DOCX: extract_text_from_docx() (python-docx)
        │
        ▼
3. Convert to HTML:
   ├── PDF: extract_structured_from_pdf() → elements_to_html()
   ├── DOCX: docx_to_html() via mammoth
   └── Fallback: plain_text_to_html()
        │
        ▼
4. Upload original file to Cloudinary
        │
        ▼
5. Parse with LLM → parse_resume_text(extracted_text)
   Uses call_llm_async(prompt, json_format=True)
        │
        ▼
6. Sanitize parsed data for MongoDB schema
   (_sanitize_parsed_data)
        │
        ▼
7. Save to MongoDB:
   {
     resume_id, cloudinary_url, filename,
     extracted_text, resume_html, parsed_data,
     processing_status: "completed"
   }
```

### MongoDB Document Structure (after upload)

```javascript
{
  "_id": ObjectId("..."),
  "resume_id": "a1b2c3d4...",
  "cloudinary_url": "https://res.cloudinary.com/...",
  "filename": "resume.docx",
  "content_type": "application/vnd.openxmlformats...",
  "file_size": 123456,
  "extracted_text": "John Doe\njohn@email.com\n...",          // Raw text
  "resume_html": "<!DOCTYPE html><html>...",                   // ← KEY for legacy path
  "parsed_data": {                                             // ← KEY for structured path
    "name": "John Doe",
    "email": "john@email.com",
    "phone": "+1-555-0100",
    "education": [{"institution": "MIT", "degree": "BS CS", "year": 2020}],
    "experience": [{"company": "Acme Corp", "title": "Dev", ...}],
    "skills": ["Python", "React", "TypeScript"],
    "languages": ["English"],
    "certifications": ["AWS Certified"]
  },
  "schema_version": 3
}
```

**Critical fields:**
- `resume_html` → used by legacy `/tailor` (Paths A/C)
- `parsed_data` → used by new `/tailor-structured` (Path F)
- `extracted_text` → used by both (Path B + summary/project extraction for Path F)

---

## 4. Legacy Paths A–E (summarized)

These paths are documented in detail in `RESUME_TAILOR_WHOLE_FLOW.md`. Here's a quick summary:

### Path A: HTML Tailoring (`tailor_resume_html`)
- **Input:** `resume_html` (full HTML document) + `job`
- **Process:** Parse into sections → one LLM call per section → reassemble
- **LLM calls:** N (one per editable section)
- **Non-editable sections:** Skipped at code level
- **Used when:** `resume_html` exists in MongoDB

### Path B: Plain Text Tailoring (`tailor_resume_text`)
- **Input:** `extracted_text` (plain text) + `job`
- **Process:** Detect section headings → one LLM call per section → reassemble
- **LLM calls:** N (one per editable section)
- **Used when:** No `resume_html` in MongoDB

### Path C: Fallback HTML Tailor (`_fallback_html_tailor`)
- **Input:** `resume_html` (full HTML) + `job`
- **Process:** Single LLM call with full resume
- **LLM calls:** 1
- **Used when:** Section parsing fails or returns nothing

### Path D: Structured Element Tailoring (`tailor_resume_structured` in resume_tailor.py)
- **Input:** `list[ResumeElement]` + `job`
- **Process:** Single LLM call with JSON → parse JSON response
- **LLM calls:** 1
- **Note:** Legacy path, not called from API

### Path E: DOCX v2 Engine (`tailor_resume_docx_v2`)
- **Input:** Raw `.docx` bytes + `job`
- **Process:** 5-phase pipeline (parse → LLM → validate → reinject → verify)
- **LLM calls:** Batched (8 spans per call)
- **Note:** Formatting-preserving, not wired into API

---

## 5. Flow 6: Structured Tailoring — PATH F (NEW)

**Files:**
- `backend/app/services/structured_tailor.py` — Main pipeline
- `backend/app/services/pii_service.py` — PII privacy layer
- `backend/app/api/v1/resumes.py` — `POST /tailor-structured` endpoint

### Complete Pipeline Diagram

```
Client sends { resume_id, job_id }
        │
        ▼
┌──────────────────────────────────────────────┐
│  1. Fetch resume + job from MongoDB          │
│     resume = get_resume_by_id(db, resume_id) │
│     job    = get_job_by_id(db, job_id)       │
│                                              │
│     resume = { extracted_text, parsed_data } │
│     job    = { title, description, skills }  │
└──────────────────┬───────────────────────────┘
                   │
                   ▼
┌──────────────────────────────────────────────┐
│  2. Extract PII — NEVER sent to LLM          │
│                                              │
│     pii.py → extract_pii(parsed_data)        │
│                                              │
│     pii = {                                   │
│       "name":  "John Doe",           ← SAVED │
│       "email": "john@email.com",     ← SAVED │
│       "phone": "+1-555-0100"         ← SAVED │
│     }                                        │
└──────────────────┬───────────────────────────┘
                   │
                   ▼
┌──────────────────────────────────────────────┐
│  3. Build resume JSON for LLM (NO PII)       │
│                                              │
│     structured_tailor.py → _build_resume_    │
│     input_json(parsed_data, resume_text)     │
│                                              │
│     resume_json = {                          │
│       "summary":        "Experienced dev...",│
│       "skills":         ["Python","React"],  │
│       "experience":     [{company, title,    │
│                           duration, desc}],  │
│       "projects":       [{name, desc}],      │
│       "education":      [{institution,       │
│                           degree, year}],    │
│       "certifications": ["AWS Certified"]    │
│     }                                        │
│                                              │
│     ↳ Summary extracted from:               │
│         parsed_data.summary OR heuristics    │
│       ↳ Projects extracted from:            │
│         parsed_data.projects OR heuristics   │
│                                              │
│     PII FIELDS (name, email, phone)          │
│     ARE EXCLUDED from this payload           │
└──────────────────┬───────────────────────────┘
                   │
                   ▼
┌──────────────────────────────────────────────┐
│  4. Call LLM (OpenRouter)                    │
│                                              │
│     System Prompt:                           │
│     ┌──────────────────────────────────┐     │
│     │ ATS Optimization Engine          │     │
│     │ (user-provided)                  │     │
│     │                                  │     │
│     │ Includes:                        │     │
│     │ - 10 Critical Rules              │     │
│     │ - Allowed Modifications per      │     │
│     │   section type                   │     │
│     │ - ATS Optimization Rules         │     │
│     │ - Output JSON Schema             │     │
│     │ - Resume JSON (↓)                │     │
│     │ - Job Description (↓)            │     │
│     └──────────────────────────────────┘     │
│                                              │
│     User Message: "Please tailor this        │
│     resume for the following position..."    │
│                                              │
│     llm = get_llm_provider()                 │
│     result = await llm.generate_async(       │
│       prompt=user_prompt,                    │
│       json_format=True,                      │
│       timeout=180,                           │
│       max_tokens=8192,                       │
│       system_prompt=full_system_prompt,      │
│     )                                        │
│                                              │
│     ── PROVIDER CHAIN ──                     │
│     get_llm_provider()                       │
│       → LLM_PROVIDER env var                 │
│       → OpenRouterProvider (preferred)       │
│         → tries qwen/qwen3-coder:free       │
│         → fallback chain (12 models)        │
│       → OR OllamaProvider                    │
│                                              │
│     ── FREE MODEL FALLBACK CHAIN ──          │
│     1. qwen/qwen3-coder:free (128k ctx)     │
│     2. nvidia/nemotron-3-ultra-550b:free    │
│     3. google/gemma-4-26b-a4b-it:free       │
│     4. meta-llama/llama-3.3-70b:free        │
│     ... (12 models total)                   │
└──────────────────┬───────────────────────────┘
                   │
                   ▼
┌──────────────────────────────────────────────┐
│  5. LLM Returns Tailored JSON               │
│                                              │
│     {                                         │
│       "summary": "Experienced full-stack...",│
│       "skills": ["React","TypeScript",...],  │
│       "experience": [...],                   │
│       "projects": [...],                     │
│       "education": [...],                    │
│       "certifications": [...],              │
│       "ats_keywords_matched": [              │
│         "React", "TypeScript", "AWS"         │
│       ],                                     │
│       "ats_keywords_missing": [              │
│         "Kubernetes", "GraphQL"             │
│       ],                                     │
│       "optimization_notes": [               │
│         "Emphasized React experience",       │
│         "Reordered skills by JD priority"   │
│       ]                                      │
│     }                                         │
└──────────────────┬───────────────────────────┘
                   │
                   ▼
┌──────────────────────────────────────────────┐
│  6. Parse & Validate Response                │
│                                              │
│     try: json.loads(raw_content)             │
│     ↓                                        │
│     Fall back to original data if:           │
│     - JSON parse fails                       │
│     - LLM failure_reason is set              │
│     - Fields missing (use original values)   │
│                                              │
│     Security: validate list types            │
│     for ats_keywords_matched etc.            │
└──────────────────┬───────────────────────────┘
                   │
                   ▼
┌──────────────────────────────────────────────┐
│  7. Re-inject PII                            │
│                                              │
│     pii_service.py → reinject_pii(           │
│       tailored_output,                       │
│       pii                                    │
│     )                                        │
│                                              │
│     full_data = {                            │
│       ...tailored_output,         ← no PII   │
│       "name":  "John Doe",        ← BACK     │
│       "email": "john@email.com",  ← BACK     │
│       "phone": "+1-555-0100"      ← BACK     │
│     }                                        │
└──────────────────┬───────────────────────────┘
                   │
                   ▼
┌──────────────────────────────────────────────┐
│  8. Generate HTML resume                     │
│                                              │
│     structured_tailor.py → generate_html_    │
│     from_tailored(tailored_output, pii)      │
│                                              │
│     Produces:                                │
│     <!DOCTYPE html>                          │
│     <html>                                   │
│       <h1>John Doe</h1>                      │
│       <p>email | phone</p>                   │
│       <h2>Professional Summary</h2>          │
│       <h2>Skills</h2>                        │
│       <h2>Experience</h2>                    │
│         ...                                  │
│       <h2>Projects</h2>                      │
│       <h2>Education</h2>                     │
│       <h2>Certifications</h2>               │
│     </html>                                  │
│                                              │
│     NOTE: ATS metadata is NOT embedded       │
│     in the HTML — it's returned separately   │
│     in the API JSON response.                │
└──────────────────┬───────────────────────────┘
                   │
                   ▼
┌──────────────────────────────────────────────┐
│  9. Generate output files                    │
│                                              │
│     DOCX: html_to_docx(tailored_html)        │
│     PDF:  html_to_pdf_async(tailored_html)   │
│     Cover: generate_cover_letter(...)        │
│                                              │
│     Upload all to Cloudinary                 │
│     Save tailor session to MongoDB           │
└──────────────────┬───────────────────────────┘
                   │
                   ▼
┌──────────────────────────────────────────────┐
│  10. Return StructuredTailorResponse         │
│                                               │
│     {                                         │
│       "resume_id": "...",                    │
│       "job_id": "...",                       │
│       "tailored_data": {                     │
│         "summary": "...",                    │
│         "skills": [...],                     │
│         "experience": [...],                 │
│         "projects": [...],                   │
│         "education": [...],                  │
│         "certifications": [...]              │
│       },                                      │
│       "tailored_text": "...",                │
│       "cover_letter": "...",                 │
│       "download_urls": {                     │
│         "pdf": "https://...",               │
│         "docx": "https://...",              │
│         "cover_letter_pdf": "https://..."   │
│       },                                      │
│       "ats_keywords_matched": [...],         │
│       "ats_keywords_missing": [...],         │
│       "optimization_notes": [...],           │
│       "llm_model": "nvidia/nemotron-..."    │
│     }                                         │
└──────────────────────────────────────────────┘
```

### JSON Schema Mapping (Parsed → LLM Input → Tailored Output)

```
┌──────────────────────┐     ┌──────────────────────┐     ┌──────────────────────┐
│  MongoDB parsed_data  │     │  LLM Input (no PII)  │     │  Tailored Output      │
│                      │     │                      │     │                      │
│  name        ────────┤     │                      │     │                      │
│  email       ────────┤ PII │                      │     │                      │
│  phone       ────────┤     │                      │     │                      │
│                      │     │  summary              │────▶│  summary             │
│                      │     │  skills               │────▶│  skills              │
│  experience  ────────┤────▶│  experience           │────▶│  experience          │
│                      │     │  projects             │────▶│  projects            │
│  education   ────────┤────▶│  education            │────▶│  education           │
│  languages   ────────┤     │  certifications       │────▶│  certifications      │
│  certifications ─────┤     │                      │     │                      │
│                      │     │                      │     │  ats_keywords_       │
│  summary (optional)  │     │                      │     │  matched             │
│  projects (optional) │     │                      │     │  ats_keywords_       │
│                      │     │                      │     │  missing             │
│                      │     │                      │     │  optimization_notes  │
│                      │     │                      │     │                      │
│                      │     │                      │     │  ← reinject PII:     │
│                      │     │                      │     │  name, email, phone  │
└──────────────────────┘     └──────────────────────┘     └──────────────────────┘
```

### Summary & Projects Extraction (Fallback Heuristics)

If `parsed_data` doesn't contain `summary` or `projects`, the system extracts them from raw text:

```
extracted_text: "John Doe\njohn@email.com\nExperienced full-stack developer with 5+ years...\nSKILLS\nPython, React\nEXPERIENCE\nSenior Dev at Acme Corp..."

_extract_summary_from_text():
  ↓
  "Experienced full-stack developer with 5+ years..."
  (Takes first substantial paragraph before section heading)

_extract_projects_from_text():
  ↓
  [{"name": "Project Alpha", "description": "Built microservice..."}]
  (Looks for "Projects" section heading and parses entries)
```

These heuristics are logged at DEBUG level for monitoring accuracy.

---

## 6. PII Service Deep Dive

**File:** `backend/app/services/pii_service.py`

### Three Functions

```
extract_pii(parsed_data)
    ↓
  { "name": "John Doe",
    "email": "john@email.com",
    "phone": "+1-555-0100" }

strip_pii(parsed_data)
    ↓
  { "education": [...],
    "experience": [...],
    "skills": [...],
    ... }
  (name, email, phone removed)

reinject_pii(tailored_data, pii)
    ↓
  { "summary": "...",
    "skills": [...],
    "experience": [...],
    "name": "John Doe",     ← BACK
    "email": "john@email.com", ← BACK
    "phone": "+1-555-0100"   ← BACK
  }
```

### Security Guarantee

The `_build_resume_input_json()` function in `structured_tailor.py` only maps specific non-PII keys:

```python
return {
    "summary": ...,
    "skills": ...,
    "experience": ...,
    "projects": ...,
    "education": ...,
    "certifications": ...,
}
```

Even if `parsed_data` contains extra fields, **only these 6 keys** go into the LLM payload. `name`, `email`, `phone` are never included.

---

## 7. ATS Optimization Engine Prompt

The full system prompt (provided by the user) is in `structured_tailor.py` as `SYSTEM_PROMPT_TEMPLATE`. It uses Python `.format()` with two variables:

| Placeholder | Filled with |
|------------|-------------|
| `{resume_json}` | Indented JSON string of resume (6 fields, no PII) |
| `{job_description}` | Raw job description text from MongoDB |

### Prompt Structure Summary

```
# System Role
You are an expert ATS Resume Optimization Engine.

## Critical Rules (10 rules)
- Never invent experience, companies, projects, certifications, education
- Never fabricate years, technologies, or metrics
- Preserve all factual information

## Input
- Candidate Resume JSON (PII removed)
- Job Description

## Allowed Modifications per Section
- Summary: Rewrite, add keywords, improve ATS matching
- Skills: Reorder, group, prioritize JD-matching skills (only existing skills)
- Experience: Rewrite bullets, improve action verbs, quantify achievements
- Projects: Rewrite descriptions, emphasize relevant tech
- Education: Preserve exactly
- Certifications: Preserve exactly

## ATS Optimization Rules
Target: ATS Friendly, Keyword Rich, Human Readable, Professional Tone
Priority: 1. Required Skills → 2. Responsibilities → 3. Keywords → 4. Preferred

## Gap Handling
If JD mentions skills NOT in resume: DO NOT add them.
Instead: emphasize related existing skills.

## Output Requirements
Return ONLY valid JSON. Same schema as input.
No markdown, no explanations, no comments, no additional text.

## JSON Schema
{
  "summary": "",
  "skills": [],
  "experience": [],
  "projects": [],
  "education": [],
  "certifications": [],
  "ats_keywords_matched": [],
  "ats_keywords_missing": [],
  "optimization_notes": []
}
```

### Template Filling

```python
full_system_prompt = SYSTEM_PROMPT_TEMPLATE.format(
    resume_json=json.dumps(resume_input, ensure_ascii=False, indent=2),
    job_description=job_description,
)
```

This is passed as `system_prompt` to `llm.generate_async()`.

---

## 8. API Response Comparison

### Legacy `/tailor` Response

```json
{
  "resume_id": "abc123",
  "job_id": "def456",
  "tailored_text": "John Doe\njohn@email.com\nProfessional Summary...",
  "cover_letter": "Dear Hiring Manager,\n\nI am writing...",
  "download_urls": {
    "pdf": "https://res.cloudinary.com/...",
    "docx": "https://res.cloudinary.com/...",
    "cover_letter_pdf": "https://res.cloudinary.com/..."
  }
}
```

### New `/tailor-structured` Response

```json
{
  "resume_id": "abc123",
  "job_id": "def456",
  "tailored_data": {
    "summary": "Experienced full-stack developer...",
    "skills": ["React", "TypeScript", "Python"],
    "experience": [
      {
        "company": "Acme Corp",
        "title": "Senior Developer",
        "duration": "2020-2024",
        "description": "Led development of..."
      }
    ],
    "projects": [
      {
        "name": "E-commerce Platform",
        "description": "Built with React..."
      }
    ],
    "education": [
      {
        "institution": "MIT",
        "degree": "BS Computer Science",
        "year": 2020
      }
    ],
    "certifications": ["AWS Certified Developer"]
  },
  "tailored_text": "John Doe\njohn@email.com\nExperienced...",
  "cover_letter": "Dear Hiring Manager,\n\nI am writing...",
  "download_urls": {
    "pdf": "https://res.cloudinary.com/...",
    "docx": "https://res.cloudinary.com/...",
    "cover_letter_pdf": "https://res.cloudinary.com/..."
  },
  "ats_keywords_matched": ["React", "TypeScript", "AWS"],
  "ats_keywords_missing": ["Kubernetes", "GraphQL"],
  "optimization_notes": [
    "Emphasized React experience and TypeScript usage",
    "Reordered skills list to prioritize JD requirements",
    "Education and certifications preserved exactly as requested"
  ],
  "llm_model": "nvidia/nemotron-3-ultra-550b-a55b:free"
}
```

---

## 9. File Inventory — All Tailoring Code

### New Implementation (Path F)

| File | Purpose |
|------|---------|
| `backend/app/services/structured_tailor.py` | Main pipeline: PII-safe JSON→OpenRouter→JSON→HTML |
| `backend/app/services/pii_service.py` | Extract/strip/reinject PII |

### Legacy Implementation (Paths A–E)

| File | Purpose |
|------|---------|
| `backend/app/services/resume_tailor.py` | All 5 legacy paths, prompts, text parser |
| `backend/app/services/html_service.py` | HTML section parser, validation, reassembly |
| `backend/app/services/resume_parser.py` | LLM-based resume parsing during upload |
| `backend/app/services/cover_letter.py` | Cover letter generation |
| `backend/app/services/resume_tailor_engine/__init__.py` | DOCX engine orchestrator |
| `backend/app/services/resume_tailor_engine/parser.py` | DOCX content map builder |
| `backend/app/services/resume_tailor_engine/llm_client.py` | Ollama client for DOCX engine |
| `backend/app/services/resume_tailor_engine/validator.py` | Budget/fabrication validation |
| `backend/app/services/resume_tailor_engine/reinjector.py` | Run-level DOCX write-back |
| `backend/app/services/resume_tailor_engine/verifier.py` | Page count verification |

### Shared Infrastructure

| File | Purpose |
|------|---------|
| `backend/app/core/llm.py` | `call_llm()`, `call_llm_async()` — legacy dispatch |
| `backend/app/services/llm/__init__.py` | `get_llm_provider()` |
| `backend/app/services/llm/base.py` | `LLMProvider` ABC, `LLMResult`, `generate()` sync wrapper |
| `backend/app/services/llm/factory.py` | Provider singleton cache |
| `backend/app/services/llm/openrouter_provider.py` | OpenRouter provider with 12-model fallback |
| `backend/app/services/llm/ollama_provider.py` | Local Ollama provider |
| `backend/app/services/llm/fallback_manager.py` | Automatic model fallback with backoff |
| `backend/app/services/pdf_service.py` | PDF text extraction + generation |
| `backend/app/services/docx_service.py` | DOCX text extraction + generation |
| `backend/app/services/cloudinary_service.py` | Upload/download to Cloudinary |

### API & Models

| File | Purpose |
|------|---------|
| `backend/app/api/v1/resumes.py` | `POST /upload`, `POST /tailor`, `POST /tailor-structured`, `POST /download-from-url` |
| `backend/app/models/resume.py` | All Pydantic models (legacy + structured) |
| `backend/app/models/resume_elements.py` | `ResumeElement`, `ResumeLink` |

---

## 10. How to Use the New Endpoint

### Prerequisites

```bash
# 1. Set environment to use OpenRouter
export LLM_PROVIDER=openrouter
export OPENROUTER_API_KEY=sk-or-v1-...
export OPENROUTER_MODEL=qwen/qwen3-coder:free
```

### Upload a Resume

```bash
curl -X POST http://localhost:8000/api/v1/resumes/upload \
  -F "file=@resume.pdf"
# → Get resume_id from response
```

### Tailor Using the New Structured Pipeline

```bash
curl -X POST http://localhost:8000/api/v1/resumes/tailor-structured \
  -H "Content-Type: application/json" \
  -d '{
    "resume_id": "<resume_id_from_upload>",
    "job_id": "<job_id>"
  }'
```

### Python Example

```python
import requests

# Upload
with open("resume.docx", "rb") as f:
    upload_resp = requests.post(
        "http://localhost:8000/api/v1/resumes/upload",
        files={"file": f}
    )
resume_id = upload_resp.json()["resume_id"]

# Tailor (structured)
tailor_resp = requests.post(
    "http://localhost:8000/api/v1/resumes/tailor-structured",
    json={"resume_id": resume_id, "job_id": job_id}
)
result = tailor_resp.json()

# Access structured data
print(result["tailored_data"]["summary"])
print(result["tailored_data"]["skills"])
print(result["ats_keywords_matched"])
print(result["llm_model"])

# Download URLs
pdf_url = result["download_urls"]["pdf"]
docx_url = result["download_urls"]["docx"]
```

### Logs to Watch

| Log Message | What it means |
|-------------|---------------|
| `Extracted PII — name=John Doe email=... phone=...` | PII captured, will be excluded from LLM |
| `Building input resume JSON with N skills, M experience, K projects` | Input constructed (no PII) |
| `Sending structured tailoring request to openrouter` | LLM call in progress |
| `LLM response received — model=... chars=N` | Successful LLM response |
| `Tailored resume: N skills, M experience, K projects, X matched keywords` | Successful parse |
| `Structured tailoring LLM call failed: ...` | LLM failure → fallback to original |
| `Failed to parse LLM response as JSON` | Bad JSON → fallback to original |

---

## 11. Migration Guide: Legacy → Structured

### When to use which endpoint

| Scenario | Use |
|----------|-----|
| You need ATS keyword analysis | **`/tailor-structured`** |
| You need privacy (PII never leaves) | **`/tailor-structured`** |
| You want structured JSON output | **`/tailor-structured`** |
| You rely on formatting preservation | `/tailor` (HTML section-by-section) |
| You have very large resumes (>15k chars) | `/tailor` (section-by-section avoids context limits) |
| You want the fastest path | `/tailor` (one section per call starts immediately) |

### Frontend Migration

If you're currently using `/tailor` in your frontend, here's how to switch to `/tailor-structured`:

```typescript
// OLD: /tailor
const resp = await fetch('/api/v1/resumes/tailor', {
  method: 'POST',
  body: JSON.stringify({ resume_id, job_id })
});
const data = await resp.json();
// data.tailored_text — plain text only

// NEW: /tailor-structured
const resp = await fetch('/api/v1/resumes/tailor-structured', {
  method: 'POST',
  body: JSON.stringify({ resume_id, job_id })
});
const data = await resp.json();
// data.tailored_data — structured JSON
// data.tailored_data.summary — Professional Summary
// data.tailored_data.skills — Skills array
// data.tailored_data.experience — Experience array
// data.ats_keywords_matched — ATS-matched keywords
// data.ats_keywords_missing — ATS-missing keywords
// data.optimization_notes — Optimization notes
```

### Model Differences

| Aspect | Legacy `ResumeTailorResponse` | New `StructuredTailorResponse` |
|--------|------------------------------|-------------------------------|
| Tailored content | `tailored_text` (string) | `tailored_data` (object) + `tailored_text` (string) |
| ATS keywords | Not available | `ats_keywords_matched`, `ats_keywords_missing` |
| Optimization notes | Not available | `optimization_notes` |
| LLM info | Not available | `llm_model` |
| Download URLs | `download_urls` (same shape) | `download_urls` (same shape) |
| Cover letter | `cover_letter` | `cover_letter` |
| Error fallback | `ResumeTailorErrorResponse` | `StructuredTailorErrorResponse` |

---

*End of documentation. Last updated: 2026-06-22.*
