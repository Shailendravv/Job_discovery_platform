---
covers:
  - backend/app/services/ats_keywords.py
  - backend/app/services/ats_scoring.py
  - backend/app/services/ats_location.py
  - backend/app/services/html_renderer.py
  - backend/templates/cv-template.html
  - backend/static/fonts/
status: active
last_verified: 2026-07-01
---

# ATS-Optimised PDF Generation

## Purpose

Improves the existing structured tailoring pipeline (`POST /tailor-structured`) by adding:
1. **Explicit JD keyword extraction** — 15-20 keywords extracted before the LLM call, injected into the LLM prompt for guided optimization
2. **Post-LLM ATS scoring** — project ranking (top 3-4 by relevance), bullet reordering (JD-relevant bullets first), keyword coverage computation
3. **ATS-optimised HTML template** — Space Grotesk + DM Sans fonts, gradient header, competency grid, "6-second recruiter scan" section order
4. **Location-based paper format** — Letter for US/Canada, A4 for rest of world
5. **Frontend ATS metadata display** — keyword coverage %, matched/missing keywords, paper format

These features are **integrated into the existing pipeline**, not built as a separate endpoint. All existing safeguards (PII stripping, MultiProvider fallback, chunking, integrity merge, Cloudinary storage) remain unchanged.

## Behavior Specification

### Keyword Extraction (`ats_keywords.py`)

- **Inputs:** `job_title: str`, `job_description: str`, `job_skills: list[str]`
- **Process:**
  1. Collect explicit `job_skills` (highest priority) — categorize as technical/domain/soft_skills
  2. Extract noun phrases from job title (medium priority)
  3. Extract noun phrases from job description (lower priority) using heuristics
  4. Deduplicate, cap at `max_keywords` (default 20)
- **Outputs:** `{all_keywords, technical, domain, soft_skills, required, preferred}`
- **Used by:** `structured_tailor.py` — keywords are injected into the LLM's user prompt

### ATS Scoring (`ats_scoring.py`)

**Project Ranking:**
- **Inputs:** `projects: list[dict]`, `jd_keywords: list[str]`, `max_projects: int`
- **Process:** Score each project by unique keyword overlaps in name + description, sort descending, keep top N
- **Outputs:** Sliced list (highest relevance first)

**Bullet Reordering:**
- **Inputs:** `experience: list[dict]`, `jd_keywords: list[str]`
- **Process:** Within each experience entry, score each bullet by keyword matches, sort descending
- **Outputs:** Experience list with reordered descriptions (JD-relevant bullets first)

**Keyword Coverage:**
- **Inputs:** `tailored_data: dict` (after LLM), `jd_keywords: list[str]`
- **Process:** Check each keyword's presence across summary, experience, skills, projects sections
- **Outputs:** `{matched, missing, coverage_pct, distribution}`

### Paper Format Detection (`ats_location.py`)

- **Inputs:** `job_location: str | None`, `job_description: str`
- **Process:** Check location string for US/Canada state/province patterns → `"letter"`. Check for non-US country patterns → `"a4"`. Fallback to `"letter"`.
- **Outputs:** `"letter"` or `"a4"`
- **Used by:** `structured_tailor.py` for template page width, `html_service.py` for Playwright PDF format

### HTML Template (`cv-template.html`)

- **Fonts:** Space Grotesk (headings, 600-700) + DM Sans (body, 400-500), self-hosted as WOFF2
- **Design:** 24px bold name, 2px gradient line `(hsl(187,74%,32%) → hsl(270,70%,45%))`, section headers in teal 13px uppercase, company names in purple
- **Section order:**
  1. Header (name + gradient + contact row)
  2. Professional Summary
  3. Core Competencies (flex-grid of tags)
  4. Work Experience (with reordered bullets)
  5. Projects (top 3-4)
  6. Education
  7. Certifications
  8. Skills
- **ATS rules:** Single-column, no images/SVGs, no tables, UTF-8, standard headers
- **Margins:** 0.6in consistent
- **Background:** Pure white

### Template Renderer (`html_renderer.py`)

- **Inputs:** Section HTML strings + metadata (name, contact, etc.)
- **Process:** Loads `cv-template.html`, replaces `{{PLACEHOLDER}}` tokens with rendered HTML. Empty sections produce no heading and no content.
- **Outputs:** Complete HTML document string
- **Builder functions:** `build_contact_items`, `build_competency_tags`, `build_experience_html`, `build_projects_html`, `build_education_html`, `build_certifications_html`

## Data & Interface Contract

### New `StructuredTailorResponse` fields

| Field | Type | Description |
|-------|------|-------------|
| `keyword_coverage_pct` | float | 0-100, percentage of JD keywords found in tailored resume |
| `paper_format` | str | `"letter"` or `"a4"` |
| `jd_keywords` | list[str] | 15-20 keywords extracted from job description |
| `competency_keywords` | list[str] | Top 8 matched keywords shown as competency tags |
| `selected_project_count` | int | Number of projects kept after relevance ranking (max 4) |
| `keyword_distribution` | dict | Keywords grouped by section: summary, experience, skills, projects |

### Key workflow (modified pipeline in `structured_tailor.py`)

```
parsed_data + job
    │
    ├── Extract PII (unchanged)
    ├── Separate editable vs preserved (unchanged)
    ├── EXTRACT JD KEYWORDS ◄── NEW
    ├── Call LLM with keywords injected into prompt ◄── MODIFIED
    ├── RANK PROJECTS by JD relevance ◄── NEW
    ├── REORDER BULLETS by JD relevance ◄── NEW
    ├── COMPUTE KEYWORD COVERAGE ◄── NEW
    ├── DETECT PAPER FORMAT from location ◄── NEW
    ├── Re-inject preserved + PII (unchanged)
    ├── Render ATS-optimised HTML template ◄── REPLACED
    └── Return + generate PDF with correct format
```

## Example

After uploading resume and tailoring for a job titled "Senior Python Engineer" at a San Francisco company:

```json
{
  "keyword_coverage_pct": 73.3,
  "paper_format": "letter",
  "jd_keywords": ["Python", "FastAPI", "Docker", "AWS", "microservices",
                  "REST", "PostgreSQL", "CI/CD", "communication", "leadership"],
  "competency_keywords": ["Python", "FastAPI", "AWS", "Docker",
                          "REST", "PostgreSQL", "microservices", "CI/CD"],
  "selected_project_count": 3,
  "keyword_distribution": {
    "summary": ["Python", "FastAPI"],
    "experience": ["Python", "FastAPI", "Docker", "AWS", "microservices"],
    "skills": ["Python", "FastAPI", "Docker", "AWS", "PostgreSQL"],
    "projects": ["REST", "FastAPI"]
  }
}
```

## Dependencies & Integration Points

- **`structured_tailor.py`** — the pipeline that calls all ATS services; receives `job` dict with `location` field for paper format
- **`html_service.py`** — `html_to_pdf_async` now accepts a `format` parameter (`"Letter"`/`"A4"`)
- **`resumes.py`** — extracts new fields from pipeline result, passes format to PDF generation
- **`resume.py`** (models) — `StructuredTailorResponse` extended with new fields
- **Fonts** — `backend/static/fonts/SpaceGrotesk-Variable.woff2` and `DMSans-Variable.woff2` must be downloaded (see [Font Installation](#font-installation))

### Font Installation

```bash
# Download Space Grotesk (Google Fonts)
# https://fonts.google.com/specimen/Space+Grotesk
# Download variable weight WOFF2 → place in backend/static/fonts/

# Download DM Sans (Google Fonts)
# https://fonts.google.com/specimen/DM+Sans
# Download variable weight WOFF2 → place in backend/static/fonts/

Expected files:
  backend/static/fonts/SpaceGrotesk-Variable.woff2
  backend/static/fonts/DMSans-Variable.woff2
```

**Note:** The template references fonts via relative URL `fonts/`. Since Playwright renders the HTML from a temp directory, the template's `src` paths must be relative to its own location in `backend/templates/`. Currently the template expects fonts at `fonts/...` (relative to itself). For Playwright rendering, fonts should be placed in `backend/templates/fonts/` OR the template should use absolute base64-embedded fonts. For simplicity, the template uses relative paths — copy fonts to `backend/templates/fonts/` if Playwright cannot resolve paths from `static/`.

## Edge Cases & Known Gotchas

- **Keyword extraction with empty JD** returns empty lists gracefully
- **Project ranking with no projects** returns empty list
- **Paper format detection** defaults to `"letter"` when location is indeterminate
- **Template placeholders** for empty sections are replaced with empty string (no heading shown for empty sections)
- **The LLM prompt still works without keywords** — the keyword block is only appended when `jd_keywords_data` is provided
- **Font files are optional** — the template degrades gracefully to system sans-serif if fonts aren't installed
- **Backward compatibility** — all new fields in `StructuredTailorResponse` have defaults (`0.0`, `"letter"`, empty lists), so existing API clients won't break

## Key Files

- `backend/app/services/ats_keywords.py` — JD keyword extraction
- `backend/app/services/ats_scoring.py` — project ranking, bullet reordering, keyword coverage
- `backend/app/services/ats_location.py` — paper format detection
- `backend/app/services/html_renderer.py` — ATS template renderer + section builders
- `backend/templates/cv-template.html` — HTML template

## Why (Design Rationale)

- **Post-LLM scoring** — project ranking and bullet reordering happen AFTER the LLM returns, so we never interfere with the LLM's output coherence. The LLM optimizes content; we optimize structure.
- **Explicit keyword extraction** — rather than relying on the LLM to guess which JD terms matter, we extract them algorithmically and guide the LLM. This gives more predictable ATS keyword placement.
- **Template over inline HTML** — the previous approach built HTML with string concatenation in `generate_html_from_tailored()`. A static template with placeholders is easier to maintain, redesign, and preview.
- **Template-relative font paths** — the template references fonts relative to itself. For Playwright rendering from a temp directory, fonts are placed in `backend/templates/fonts/`. This keeps the template self-contained.

## Open Issues

- Font paths: template expects `fonts/` relative to itself. May need to adjust for different rendering contexts (Playwright temp dir vs direct browser preview).
- Keyword extraction is purely heuristic — no LLM-based extraction fallback yet. For very short or generic JDs, the heuristic may produce fewer than 15 keywords.
- No unit tests exist yet for any of the new ATS service files (only MANUAL_TEST.md).
