---
covers:
  - backend/app/api/v1/resumes.py
  - backend/app/services/structured_tailor.py
  - backend/app/services/pii_service.py
  - backend/app/services/llm/
  - backend/app/services/cover_letter.py
  - backend/app/services/html_service.py
  - backend/app/services/cloudinary_service.py
  - backend/app/services/db_service.py
  - backend/app/models/resume.py
status: needs_review
last_verified: 2026-06-28
prompt_version: 4
---

# Structured Resume Tailoring — Data Flow & Architecture

## Purpose

This document traces the complete data flow through the `POST /tailor-structured` endpoint, from request to response. It documents every file involved, the role it plays, and known issues discovered during analysis.

---

## Endpoint Overview

**Route:** `POST /tailor-structured`
**Request:** `{ resume_id: str, job_id: str }`
**Response:** `StructuredTailorResponse` (200) or `StructuredTailorErrorResponse` (200)

The endpoint takes a previously uploaded resume and a saved job posting, strips Personally Identifiable Information (PII), sends structured resume data + job description to an LLM with an ATS optimization prompt, re-injects PII, generates downloadable files (PDF, DOCX, cover letter), uploads them to Cloudinary, and returns the tailored result.

---

## Complete File Inventory

### Layer 1: API Route (orchestrator)

| File | Role |
|------|------|
| `backend/app/api/v1/resumes.py` | Route handler — validates IDs, calls the pipeline, handles errors, generates files, returns response |

### Layer 2: Pydantic Models

| File | Role |
|------|------|
| `backend/app/models/resume.py` | Defines request/response models: `StructuredTailorRequest`, `StructuredTailorResponse`, `StructuredTailorErrorResponse`, `TailoredResumeData`, `StructuredTailorDownloadUrls` |

### Layer 3: Core Services

| File | Role |
|------|------|
| `backend/app/services/structured_tailor.py` | **Core pipeline** — PII separation, editable vs preserved data, chunking, LLM calls, merging, HTML generation |
| `backend/app/services/pii_service.py` | Extracts and re-injects name/email/phone using parsed data + regex fallback |
| `backend/app/services/cover_letter.py` | Generates cover letter via Groq LLM (separate call) |
| `backend/app/services/db_service.py` | MongoDB CRUD: `get_resume_by_id()`, `get_job_by_id()`, `save_tailor_session()` |

### Layer 4: LLM Provider Chain

| File | Role |
|------|------|
| `backend/app/services/llm/__init__.py` | Re-exports `get_llm_provider()` |
| `backend/app/services/llm/factory.py` | Resolves provider name → instance; caches singleton per provider |
| `backend/app/services/llm/multi_provider.py` | `MultiProvider` — tries providers in chain: groq → cerebras → sambanova → nvidia → openrouter |
| `backend/app/services/llm/openrouter_provider.py` | `OpenRouterProvider` — calls OpenRouter API; delegates model-level fallback to `FallbackManager` |
| `backend/app/services/llm/fallback_manager.py` | `FallbackManager` — retries 8+ models with exponential backoff + jitter |
| `backend/app/services/llm/base.py` | `LLMProvider` abstract base + `LLMResult` data class |
| `backend/app/services/llm/groq_provider.py` | Groq provider (used by cover_letter.py via legacy path) |
| `backend/app/services/llm/cerebras_provider.py` | Cerebras provider |
| `backend/app/services/llm/sambanova_provider.py` | SambaNova provider |
| `backend/app/services/llm/nvidia_provider.py` | NVIDIA provider |
| `backend/app/services/llm/ollama_provider.py` | Ollama provider (local, rarely used in production) |
| `backend/app/core/llm.py` | Legacy dispatch — `call_llm_async()` used by `resume_parser.py` and `cover_letter.py` |
| `backend/app/core/config.py` | Settings: API keys, model names, base URLs |

### Layer 5: File Generation

| File | Role |
|------|------|
| `backend/app/services/html_service.py` | HTML→DOCX (htmldocx), HTML→PDF (Playwright), text extraction from HTML |
| `backend/app/services/PDF_service.py` | PDF text extraction (PyMuPDF), PDF generation (reportlab fallback) |
| `backend/app/services/cloudinary_service.py` | File upload, download URL generation, streaming, URL parsing |

### Layer 6: Configuration

| File | Role |
|------|------|
| `backend/app/core/config.py` | All env vars: `LLM_PROVIDER`, `LLM_PROVIDER_CHAIN`, `OPENROUTER_API_KEY`, etc. |

### Files NOT Used

The old `backend/app/services/resume_tailor_engine/` directory (`parser.py`, `reinjector.py`, `validator.py`, `verifier.py`, `llm_client.py`) is **not involved** in the `/tailor-structured` endpoint. These are legacy files from a previous section-by-section tailoring approach.

---

## Complete Data Flow (Step-by-Step)

```
┌──────────────────────────────────────────────────────────────────┐
│ POST /tailor-structured → resumes.py:tailor_resume_structured()  │
│ Request Body: { resume_id, job_id }                              │
└─────────────────────────┬────────────────────────────────────────┘
                          │
                          ▼
┌──────────────────────────────────────────────────────────────────┐
│ STEP 1: Fetch from MongoDB (db_service.py)                       │
│                                                                  │
│ resume = get_resume_by_id(db, resume_id)                         │
│   → Extracts: resume["extracted_text"] (raw text)                │
│               resume["parsed_data"]  (structured JSON)           │
│                                                                  │
│ job = get_job_by_id(db, job_id)                                  │
│   → Extracts: job["title"], job["description"], job["skills"]    │
│                                                                  │
│ ❌ If resume not found → 404                                     │
│ ❌ If job not found → 404                                        │
│ ❌ If resume has no extracted_text → StructuredTailorErrorResponse│
└─────────────────────────┬────────────────────────────────────────┘
                          │
                          ▼
┌──────────────────────────────────────────────────────────────────┐
│ STEP 2: Call run_structured_tailor()                             │
│         (structured_tailor.py:tailor_resume_structured)          │
│                                                                  │
│ Arguments: resume_text (str), parsed_data (dict), job (dict)     │
└─────────────────────────┬────────────────────────────────────────┘
                          │
                          ▼
┌──────────────────────────────────────────────────────────────────┐
│ STEP 3: Extract PII (pii_service.extract_pii())                  │
│                                                                  │
│ Fields stripped: name, email, phone                              │
│ Strategy:                                                        │
│   1. Try parsed_data first (LLM-extracted fields)                │
│   2. Fall back to regex on resume_text:                          │
│      - Email:  EMAIL_RE pattern                                  │
│      - Phone:  PHONE_RE pattern                                  │
│      - Name:   heuristic (first capitalized 2-4 word line)       │
│                                                                  │
│ PII is NEVER sent to the external LLM                            │
└─────────────────────────┬────────────────────────────────────────┘
                          │
                          ▼
┌──────────────────────────────────────────────────────────────────┐
│ STEP 4: Build Editable vs Preserved JSON                         │
│         (_build_editable_and_preserved())                         │
│                                                                  │
│ Editable (sent to LLM):       Preserved (kept server-side):      │
│ ┌──────────────────────┐      ┌────────────────────────┐         │
│ │ summary              │      │ education              │         │
│ │ skills               │      │ certifications         │         │
│ │ experience           │      └────────────────────────┘         │
│ │ projects             │                                         │
│ └──────────────────────┘                                         │
│                                                                  │
│ If parsed_data fields are empty, heuristic fallbacks extract      │
│ from resume_text:                                                 │
│   - _extract_summary_from_text()    → first few descriptive lines│
│   - _extract_skills_from_text()     → items under "skills" header│
│   - _extract_experience_from_text() → entries under "experience" │
│   - _extract_projects_from_text()   → entries under "projects"   │
│   - _extract_education_from_text()  → entries under "education"  │
└─────────────────────────┬────────────────────────────────────────┘
                          │
                          ▼
┌──────────────────────────────────────────────────────────────────┐
│ STEP 5: Try Single LLM Call with Retry                           │
│         (_try_single_with_retry())                                │
│                                                                  │
│ Sends FULL editable payload in one call (no proactive chunking)  │
│                                                                  │
│ Provider resolution (get_llm_provider()):                        │
│                                                                  │
│   factory.py ──→ reads settings.LLM_PROVIDER                     │
│                    ↓                                              │
│   "multi" ────→ MultiProvider(["groq","cerebras",               │
│                                 "sambanova","nvidia",            │
│                                 "openrouter"])                   │
│                    ↓                                              │
│   Each provider tried in order until one succeeds                │
│                    ↓                                              │
│   OpenRouter → FallbackManager tries 8+ models:                  │
│     - openai/gpt-oss-120b:free                                   │
│     - nvidia/nemotron-3-ultra-550b-a55b:free                     │
│     - meta-llama/llama-3.3-70b-instruct:free                     │
│     - nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free         │
│     - google/gemma-4-26b-a4b-it:free                             │
│     - poolside/laguna-xs.2:free                                  │
│     - nvidia/nemotron-nano-12b-v2-vl:free                        │
│     - cognitivecomputations/dolphin-mistral-24b-venice-edition   │
│                                                                  │
│ System Prompt (SYSTEM_PROMPT_TEMPLATE): same structure as below  │
│ max_tokens=16384 (doubled from 8192 to avoid truncation)         │
│ timeout=180                                                      │
│                                                                  │
│ ┌─ Retry Strategy (only on rate-limit 429) ─────────────────┐   │
│ │ 1st retry: wait 10s                                       │   │
│ │ 2nd retry: wait 20s (cumulative 30s)                      │   │
│ │ 3rd retry: wait 30s (cumulative 60s)                      │   │
│ │ Non-rate-limit errors skip retry (MultiProvider already    │   │
│ │ exhausted all providers) → fall through to chunking       │   │
│ └───────────────────────────────────────────────────────────┘   │
│                                                                  │
│ On success → run _merge_missing_entries() integrity check         │
│                                                                  │
│ On failure after all retries → fall through to chunking          │
└─────────────────────────┬────────────────────────────────────────┘
                          │
               ┌──────────┴──────────┐
               ▼                     ▼
       SUCCESS                  FAILED (all retries)
          │                         │
          │                         ▼
          │        ┌────────────────────────────────────────────────┐
          │        │ STEP 6: Fallback Chunking (_chunk_editable())  │
          │        │                                                │
          │        │ Threshold: MAX_CHUNK_CHARS = 8000 chars        │
          │        │                                                │
          │        │ ≤ 8000 chars  → Single chunk (use original)    │
          │        │ ≤ 16000 chars → 2 chunks                      │
          │        │   Chunk 0: summary, skills[:half], exp[:mid],  │
          │        │            projects                            │
          │        │   Chunk 1: summary, skills[half:], exp[mid:],  │
          │        │            []                                  │
          │        │                                                │
          │        │ > 16000 chars → 3 chunks                      │
          │        │   Chunk 0: summary, skills[:⅔], exp[:⅓]        │
          │        │   Chunk 1: "", skills[⅔:], exp[⅓:⅔], projects │
          │        │   Chunk 2: "", [], exp[⅔:], []                 │
          │        │                                                │
          │        │ Each chunk: _call_llm_for_chunk()              │
          │        │   (same provider chain, max_tokens=16384)      │
          │        │   → _merge_missing_entries() per chunk          │
          │        │   → _merge_chunks_results()                    │
          │        └────────────────────────────────────────────────┘
          │                         │
          └──────────┬──────────────┘
                     ▼
┌──────────────────────────────────────────────────────────────────┐
│ STEP 7: Data Integrity Check (_merge_missing_entries())          │
│                                                                  │
│ Compares LLM output against original data for each section:      │
│                                                                  │
│   - Projects:    match by project name                           │
│   - Experience:  match by (company, title) tuple                 │
│   - Skills:      match by string value                           │
│                                                                  │
│ If the LLM dropped any entries (e.g. returned 3 projects out     │
│ of 9), the missing ones are merged back from original data       │
│ and a warning is logged.                                         │
│                                                                  │
│ This prevents silent data loss when the LLM hits token limits    │
│ or omits entries in its response.                                │
└─────────────────────────┬────────────────────────────────────────┘
                          │
                          ▼
┌──────────────────────────────────────────────────────────────────┐
│ STEP 8: Re-inject Preserved Data + PII                           │
│                                                                  │
│ full_data = {}                                                   │
│ full_data.update(merged_editable)     # summary, skills, exp,    │
│                                       # projects                 │
│ full_data.update(preserved)           # education, certifications │
│ full_data = reinject_pii(full_data)   # name, email, phone       │
└─────────────────────────┬────────────────────────────────────────┘
                          │
                          ▼
┌──────────────────────────────────────────────────────────────────┐
│ STEP 9: Generate HTML (generate_html_from_tailored())            │
│                                                                  │
│ Output sections in order:                                        │
│   1. Header (name + email | phone)                               │
│   2. Professional Summary                                        │
│   3. Skills (comma-separated)                                    │
│   4. Experience (company, title, duration, bullet-point desc)    │
│   5. Projects (name, description)                                │
│   6. Education (institution, degree, year)                       │
│   7. Certifications                                              │
│                                                                  │
│ Uses Calibri/Arial font, print-friendly CSS                      │
└─────────────────────────┬────────────────────────────────────────┘
                          │
                          ▼
┌──────────────────────────────────────────────────────────────────┐
│ STEP 10: Back in resumes.py — Post-Pipeline                      │
│                                                                  │
│ a. Extract plain text from HTML (html_service)                   │
│ b. Generate cover letter (cover_letter.py → Groq LLM)            │
│    Falls back to templated letter on failure                     │
│                                                                  │
│ c. Generate downloadable files:                                  │
│    - DOCX (html_service.html_to_docx → htmldocx)                 │
│    - PDF  (html_service.html_to_pdf_async → Playwright)          │
│    - Cover letter PDF (PDF_service.generate_pdf → reportlab)     │
│                                                                  │
│ d. Upload all three to Cloudinary (cloudinary_service):          │
│    - Tailored PDF  → resource_type="image"                       │
│    - Tailored DOCX → resource_type="raw"                         │
│    - Cover PDF     → resource_type="image"                       │
│                                                                  │
│ e. Generate download URLs from Cloudinary public_ids             │
│                                                                  │
│ f. Save tailor session to MongoDB (db_service.save_tailor_session)│
│    Collection: tailor_sessions                                   │
│    Failure is non-fatal (logged as warning)                      │
│                                                                  │
│ g. Return StructuredTailorResponse or StructuredTailorErrorResponse│
└──────────────────────────────────────────────────────────────────┘
```

---

## System Prompt Architecture (SYSTEM_PROMPT_TEMPLATE)

Located in `backend/app/services/structured_tailor.py`.

### 16 Critical Rules

| # | Rule | Purpose |
|---|------|---------|
| 1 | Never invent experience | Anti-fabrication |
| 2 | Never create fake companies | Anti-fabrication |
| **3** | **Never create fake projects. If the original has N projects, tailored must have exactly N — not fewer, not more.** | **Anti-fabrication** |
| 4 | Never create fake certifications | Anti-fabrication |
| 5 | Never create fake education | Anti-fabrication |
| 6 | Never fabricate years of experience | Anti-fabrication |
| 7 | Never claim ownership of unused technologies | Anti-fabrication |
| 8 | Preserve all factual information | Accuracy |
| 9 | Improve wording, impact, ATS compatibility | Optimization |
| 10 | Optimize for ATS parsing | Optimization |
| **11** | **Never copy JD text into the summary** | **Anti-contamination** |
| **12** | **Every summary claim must be verifiable from candidate data** | **Provenance** |
| **13** | **Preserve original format/structure of each section** (paragraph→paragraph, bullets→bullets) (exception: Skills may be regrouped) | **Format preservation** |
| **14** | **Do not expand content beyond what is in the original resume. Do not copy Experience/Projects content into the summary.** | **Content boundaries** |
| **15** | **Do not add new sub-headings, category labels, or meta-descriptions** | **Structure preservation** |
| **16** | **Never add LinkedIn URLs, GitHub URLs, or social media profiles not in original resume** | **Anti-fabrication** |

### Per-Section Constraints

#### Professional Summary

**Original problematic instructions (v1):**
```
* Add relevant keywords
* Improve ATS matching
```
→ This encouraged JD text injection into the summary

**Current constraints (v4):**
- Preserve the original summary's format EXACTLY: paragraph→paragraph, bullets→bullets
- Do NOT add bullet points to a paragraph-formatted summary
- Do NOT extract part of the summary as a separate heading or title line
- Do NOT copy any text from the JD into the summary
- Do NOT inject keywords just for ATS scoring
- Only rephrase what already exists — do NOT add new claims
- Every claim must be directly quoted or closely paraphrased from experience/skills/projects
- No new content expansion
- ATS alignment handled in Skills/Experience sections only

#### Skills Section
- May group skills by category (Frontend, Backend, AI/ML, Cloud, Databases, Tools)
- May reorder to prioritize JD-matching skills within each group
- Exception to Rule #13 (this is the only section allowed structural changes)
- May only include skills already present in the resume
- **Do NOT infer assumed skills:** if resume mentions AWS, do not add GCP or Azure

#### Experience Section
- Rewrite bullet points for clarity and impact
- Improve action verbs
- Quantify achievements only if metrics exist in original (do NOT invent metrics)
- Do NOT add new sub-headings, category labels, duration summaries, or meta-descriptions
- Do NOT add new bullet points or achievements not in the original
- Do NOT expand descriptions beyond original level of detail
- **Preserve original description format:** paragraph→paragraph, bullets→bullets. Do NOT convert

#### Projects Section
- Rewrite descriptions — do NOT expand with new details
- **Must include ALL projects from the original** — do not omit any
- Preserve original description length and level of detail (if original was 1-2 sentences, tailored must be too)
- Do NOT add new technologies, features, or outcomes not in the original
- Do NOT add new section labels ("Project Name", "Technologies Used", etc.)

#### Education & Certifications
- Not sent to LLM — preserved exactly server-side
- Re-injected after LLM response

### ATS Optimization Rules

Priority by section:

| Section | Strategy |
|---------|----------|
| **Professional Summary** | Do NOT optimize for keywords. Focus on readability and authenticity. **No new content.** |
| **Skills** | Reorder and group skills to prioritize JD-matching ones |
| **Experience** | Incorporate relevant keywords naturally into existing bullet points. **Do not add new bullets.** |
| **Projects** | Only rephrase existing content. **Do not add new technologies or features.** |

---

## Resolved Issues

### Issue 1: Profile Summary Picking Up JD Content

**Status: FIXED (v2)**

**Root cause:** The original prompt said "Add relevant keywords" and "Improve ATS matching" without any anti-copying constraint, causing the LLM to inject JD text into the summary.

**Fix applied:**
- Added Critical Rule #11: explicit ban on copying JD text into summary
- Added Critical Rule #12: every claim must be verifiable from candidate data
- Replaced "Add relevant keywords" and "Improve ATS matching" with clear rephrasing-only instructions
- Added "Anti-Copying Constraint" block with 4 specific prohibitions
- Updated ATS Optimization Rules to explicitly exclude summary from keyword optimization

### Issue 2: Content Expansion & Format Changes

**Status: FIXED (v3)**

**Root cause:** The prompt allowed rewriting without bounding the scope of changes, causing:
- Summary converted from paragraph to bullet points
- Project descriptions expanded from 1-2 sentences to 3-5 sentence paragraphs with fabricated details
- Experience section gained new sub-headings and duration summaries

**Fix applied:**
- Added Critical Rule #13: preserve original format and structure (paragraph→paragraph, bullets→bullets, with exception for Skills categorization)
- Added Critical Rule #14: do not expand content beyond what exists in original
- Added Critical Rule #15: do not add new sub-headings, labels, or meta-descriptions
- Added explicit "no fabrication" block to Projects section with length preservation
- Added structure preservation constraints to Experience section
- Updated ATS Optimization Rules to prevent keyword injection into Projects

### Issue 3: Fabricated Projects, Skills, LinkedIn URLs

**Status: FIXED (v4)**

**Root cause:** The LLM was inventing projects, inferring skills (GCP, Azure from AWS), and fabricating LinkedIn URLs. The original rules banned "fake projects" but didn't explicitly prohibit inferring skills or adding contact URLs.

**Fix applied:**
- Strengthened Rule #3: "If the original has N projects, tailored must have exactly N — not fewer, not more"
- Added Rule #16: ban on adding LinkedIn URLs, GitHub URLs, or social media profiles not in original
- Added explicit skill inference ban: "if resume only mentions AWS, do not add GCP or Azure"
- Strengthened summary format preservation with negative examples (no extracting title lines)
- Added format preservation to Experience section (paragraph→paragraph, bullets→bullets)

### Issue 4: Proactive Chunking Causing Inconsistent Results

**Status: FIXED (v4)**

**Root cause:** The pipeline proactively split the editable payload into 2-3 chunks based on size (>8K chars), sending different subsets to the LLM. This caused:
- Projects only sent to one chunk — if that chunk's LLM call failed or dropped projects, they were lost
- Inconsistent skill ordering across chunks
- Unnecessary multiple LLM calls for large resumes

**Fix applied:**
- Changed to **single-call-first** strategy: always try the full payload in one call
- Added retry with increasing delays (10s, 20s, 30s) on rate-limit failures
- Chunking now only used as a fallback when single call fails after all retries

### Issue 5: Project Section Truncation (Silent Data Loss)

**Status: FIXED (v4)**

**Root cause:** The LLM's `max_tokens=8192` could cut off responses. If the truncated output was valid JSON (closing brackets present but fewer items), it passed `json.loads()` silently with incomplete data.

**Fix applied:**
- Added `_merge_missing_entries()` — a post-LLM integrity check that compares returned projects/experience/skills against the original and merges back any dropped entries
- Increased `max_tokens` from 8192 to 16384 to give the LLM more headroom
- Matching strategies: projects by name, experience by (company, title), skills by exact string

---

## Error Handling & Edge Cases

| Scenario | Behavior | HTTP Status |
|----------|----------|-------------|
| Resume not found | `404` with detail | 404 |
| Job not found | `404` with detail | 404 |
| Resume has no extracted_text | `StructuredTailorErrorResponse` with `error` field | 200 (not 404) |
| LLM pipeline throws | `StructuredTailorErrorResponse` with `error` + `tailored_text` fallback (first 1000 chars) | 200 |
| LLM call fails (single) | Retry up to 3× with 10s, 20s, 30s delays (rate-limit only). Falls back to chunking if all retries fail | — |
| LLM call fails per chunk | Falls back to original chunk data; logged as warning | — |
| LLM response truncated (missing projects) | `_merge_missing_entries()` detects and merges back dropped entries from original | — |
| Cover letter generation fails | Templated fallback letter used | 200 (non-fatal) |
| HTML→DOCX conversion fails | Empty download_urls; logged as error | 200 (non-fatal) |
| HTML→PDF conversion fails | Falls back to reportlab text-based PDF | — |
| Playwright not installed | Falls back to reportlab for PDF generation | — |
| Cloudinary upload fails | Empty download_urls; logged as error | 200 (non-fatal) |
| Save tailor session fails | Logged as warning only | 200 (non-fatal) |

---

## Model Response Models

### StructuredTailorRequest (input)
```python
{
    resume_id: str,   # MongoDB ObjectId string
    job_id: str,      # MongoDB ObjectId string
}
```

### StructuredTailorResponse (success, 200)
```python
{
    resume_id: str,
    job_id: str,
    tailored_data: TailoredResumeData,
    tailored_text: str,           # Plain text extracted from HTML
    cover_letter: str,            # Plain text cover letter
    download_urls: StructuredTailorDownloadUrls { pdf, docx, cover_letter_pdf },
    ats_keywords_matched: list[str],
    ats_keywords_missing: list[str],
    optimization_notes: list[str],
    llm_model: str,               # e.g. "qwen/qwen3-coder:free"
}
```

### StructuredTailorErrorResponse (partial failure, 200)
```python
{
    resume_id: str | None,
    job_id: str | None,
    error: str,
    tailored_text: str | None,    # Fallback: first 1000 chars of original resume
    cover_letter: str | None,
    ats_keywords_matched: list[str],
    ats_keywords_missing: list[str],
    optimization_notes: list[str],
}
```

### TailoredResumeData (nested inside success response)
```python
{
    summary: str,
    skills: list[str],
    experience: list[ExperienceEntry],  # company, title, duration, description
    projects: list[ProjectEntry],       # name, description
    education: list[EducationEntry],    # institution, degree, year
    certifications: list[str],
}
```

---

## Configuration (Environment Variables)

### Provider Selection
| Variable | Purpose | Values |
|----------|---------|--------|
| `LLM_PROVIDER` | Which provider to use | `"multi"`, `"groq"`, `"openrouter"`, `"ollama"`, etc. |
| `LLM_PROVIDER_CHAIN` | Fallback chain for `multi` | `"groq,cerebras,sambanova,nvidia,openrouter"` |

### API Keys
| Variable | Provider |
|----------|----------|
| `OPENROUTER_API_KEY` | OpenRouter (used by structured_tailor) |
| `GROQ_API_KEY` | Groq (used by resume_parser + cover_letter) |
| `CEREBRAS_API_KEY` | Cerebras |
| `SAMBANOVA_API_KEY` | SambaNova |
| `NVIDIA_API_KEY` | NVIDIA |

### Cloudinary
| Variable | Purpose |
|----------|---------|
| `CLOUDINARY_CLOUD_NAME` | Cloud name |
| `CLOUDINARY_API_KEY` | API key |
| `CLOUDINARY_API_SECRET` | API secret |

---

## Key Design Decisions

1. **PII stripping before LLM** — Name, email, and phone are extracted and re-injected server-side. The external model never sees PII. This is the primary privacy constraint.

2. **Single-call-first with retry (not proactive chunking)** — The first attempt always sends the FULL editable payload. Only on failure after 3 retries (10s, 20s, 30s delays on 429) does chunking kick in as a fallback. This avoids the complexity of merging chunk results and ensures consistent context for all sections.

3. **Rate-limit retries only retry on 429** — Non-rate-limit failures skip retry because the `MultiProvider` chain already exhausted all 5 providers internally. Retrying wouldn't help for auth errors, bad requests, etc.

4. **Post-LLM data integrity check** — `_merge_missing_entries()` validates that the LLM response includes all projects, experience, and skills from the original. Missing entries are merged back with a warning. This catches silent truncation when the LLM hits token limits.

5. **max_tokens=16384** — Doubled from 8192 to give the LLM room for large resumes with many projects and long descriptions.

6. **Multi-provider fallback** — Free-tier LLM providers are unreliable. The `MultiProvider` chain tries 5 providers, and OpenRouter itself tries 8+ models internally, maximizing the chance of a successful call.

7. **Errors return 200** — The endpoint returns 200 with `StructuredTailorErrorResponse` body on partial failures (rather than 4xx/5xx) because partial results (fallback text, cover letter) are still useful to the frontend.

8. **File generation is non-fatal** — If DOCX/PDF generation or Cloudinary upload fails, the response still returns 200 with empty `download_urls`. The tailored text and data are still delivered.

9. **Heuristic fallbacks for parsing** — If the original LLM parser (`resume_parser.py`) failed to extract structured fields, the pipeline falls back to regex/heuristic extraction from raw text for summary, skills, experience, projects, and education.
