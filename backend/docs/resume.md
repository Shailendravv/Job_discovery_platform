---
covers: [backend/app/api/v1/resumes.py, backend/app/models/resume.py, backend/app/services/db_service.py]
status: active
last_verified: 2026-07-01
---

# Resume API

## Purpose
Allows users to upload a resume (PDF/DOCX), have it parsed by an LLM into structured fields, store it in MongoDB + Cloudinary, then tailor it against a specific job posting via a PII-safe structured pipeline that produces PDF/DOCX downloads and a cover letter.

## Behavior Specification

### `POST /upload` — Upload & Parse Resume
- **Inputs:** `file: UploadFile` — PDF (`application/pdf`) or DOCX/DOC (`application/msword`, `application/vnd.openxmlformats-officedocument.wordprocessingml.document`), max 10 MB
- **Process:**
  1. Reject unsupported content types with 400.
  2. Reject files exceeding 10 MB with 400.
  3. Extract text: PDFs via `extract_text_from_pdf`; DOCX via `extract_text_from_docx`.
  4. If text extraction fails → 422.
  5. If extracted text is empty/whitespace → 422.
  6. Convert to HTML: PDFs use structured element extraction → `elements_to_html`; DOCX use mammoth → `docx_to_html`. Falls back to `plain_text_to_html` on failure.
  7. Upload original file to Cloudinary (PDF as resource_type `"image"`, DOCX as `"raw"`). Generate a proper download URL via `get_download_url`.
  8. If Cloudinary upload fails → 500.
  9. Send extracted text to Groq LLM (`parse_resume_text`) for structured parsing.
  10. If LLM parsing fails, use empty parsed data and continue (status = `"completed"`).
  11. Sanitise parsed data via `_sanitize_parsed_data` to comply with MongoDB schema (deep-clean nulls, types, empty strings).
  12. Save full document to MongoDB `resumes` collection via `save_resume`.
- **Outputs (200):** `ResumeUploadResponse` with `resume_id`, `cloudinary_url`, `parsed_data`, `extracted_text_preview` (first 500 chars), `processing_status`.
- **Error responses:** 400 (bad type or size), 422 (extraction failure or empty text), 500 (Cloudinary failure).

### `POST /tailor-structured` — Structured Resume Tailoring (PII-safe)
- **Inputs:** `StructuredTailorRequest { resume_id, job_id }`
- **Process:**
  1. Fetch resume document from MongoDB by `resume_id` → 404 if missing.
  2. Fetch job document from MongoDB by `job_id` → 404 if missing.
  3. If resume has no `extracted_text` → return `StructuredTailorErrorResponse` with `error` field (not a 404).
  4. Strip PII (name, email, phone) — never sent to external LLM.
  5. Send structured resume JSON + job to the configured LLM provider (via MultiProvider fallback chain) with ATS system prompt.
  6. Parse tailored JSON response, re-inject PII.
  7. If the LLM pipeline throws → return `StructuredTailorErrorResponse` with `error`, `tailored_text` fallback (first 1000 chars of original resume).
  8. Generate cover letter via `generate_cover_letter`; on failure, fall back to a templated letter.
  9. Generate downloadable files: `html_to_docx`, `html_to_pdf_async` for resume; `generate_pdf` for cover letter.
  10. Upload all three to Cloudinary (PDFs as `resource_type="image"`, DOCX as `"raw"`).
  11. Save tailor session to MongoDB `tailor_sessions` collection.
  12. If file generation/upload fails, return response with no download URLs (not an error).
- **Outputs (200):** `StructuredTailorResponse` or `StructuredTailorErrorResponse` (both are 200; errors use the error response model).
- **Validation:** `resume_id` must be a valid MongoDB ObjectId string (24 hex chars) — `get_resume_by_id` returns `None` and triggers 404 otherwise. `job_id` is a `postings` document `_id` (sha256 hex, from `app/ingest/models.py::posting_id`) — the handler does an inline `db.postings.find_one({"_id": job_id})` and 404s if not found.

### `POST /download-from-url` — Proxy File Download
- **Inputs:** `DownloadFromUrlRequest { url: string }` — a Cloudinary delivery URL.
- **Process:**
  1. Parse the URL via `parse_cloudinary_url` to extract `public_id`, `resource_type`, `file_format`, `filename`.
  2. If URL cannot be parsed → 400 with the parse error message.
  3. Stream the file through the backend as a `StreamingResponse`.
- **Outputs (200):** Binary file stream with `Content-Disposition: attachment` and correct `Content-Type` (PDFs → `application/pdf`, others → `application/octet-stream`).
- **Error responses:** 400 (unparseable URL), 500 (download failure).

### Data Sanitisation (`_sanitize_parsed_data`)
Applies to every parsed resume document before MongoDB insertion:
- `name` → coerced to string, empty if absent.
- `email` → omitted entirely if empty string (MongoDB schema has regex pattern, can't accept empty string).
- `phone` → omitted if empty.
- `education` → each entry's `year` coerced to int (default 0). Entries with no `institution` and no `degree` are dropped.
- `experience` → entries where all fields (company, title, duration, description) are empty are dropped.
- `skills`, `languages`, `certifications` → null/empty items filtered out, all coerced to string.

## Data & Interface Contract
### Request/Response shapes

**`POST /upload`**
- Request: `multipart/form-data` with field `file` (UploadFile)
- Response 200: `ResumeUploadResponse { resume_id: str, cloudinary_url: str, parsed_data: ParsedResumeData, extracted_text_preview: str, processing_status: str }`

**`POST /tailor-structured`**
- Request: `{ resume_id: str, job_id: str }`
- Response 200: `StructuredTailorResponse { resume_id, job_id, tailored_data, tailored_text, cover_letter, download_urls, ats_keywords_matched, ats_keywords_missing, optimization_notes, llm_model, keyword_coverage_pct, paper_format, jd_keywords, competency_keywords, selected_project_count, keyword_distribution }`
  or `StructuredTailorErrorResponse { resume_id, job_id, error, tailored_text?, cover_letter?, ats_keywords_matched, ats_keywords_missing, optimization_notes }`

**`POST /download-from-url`**
- Request: `{ url: str }`
- Response 200: binary file stream

### MongoDB document shapes

**`resumes` collection:**
`resume_id` (uuid hex), `cloudinary_url`, `cloudinary_public_id`, `cloudinary_resource_type`, `filename`, `content_type`, `file_size`, `extracted_text`, `extracted_text_length`, `resume_html`, `parsed_data` (nested object with name, email, phone, education[], experience[], skills[], languages[], certifications[]), `processing_status`, `schema_version` (currently 3), `created_at`, `updated_at`.

**`tailor_sessions` collection:**
`resume_id`, `job_id`, `tailoring_type` (`"structured"`), `llm_model`, `original_text_preview`, `tailored_text`, `cover_letter`, `cloudinary_pdf_url`, `cloudinary_docx_url`, `cloudinary_cover_letter_url`, `ats_keywords_matched[]`, `ats_keywords_missing[]`, `optimization_notes[]`, `created_at`, `updated_at`.

## Example
Trace of `POST /upload` with a real PDF containing `{"name": "Jane Doe", "email": "jane@example.com", "skills": ["Python", "FastAPI"]}`:

1. File (PDF, 500 KB, content-type `application/pdf`) is received.
2. Validation passes (type allowed, size < 10 MB).
3. `extract_text_from_pdf` returns the plain-text content of the resume.
4. Text is non-empty; `extract_structured_from_pdf` returns layout elements, `elements_to_html` builds `<p>` / `<h1>` HTML.
5. Cloudinary upload succeeds; `cloudinary_url` = `"https://res.cloudinary.com/..."`.
6. `parse_resume_text(extracted_text)` returns `{"name": "Jane Doe", "email": "jane@example.com", "skills": ["Python", "FastAPI"]}`.
7. `_sanitize_parsed_data` coerces it into safe types; `email` is kept (non-empty), `phone` is omitted (empty).
8. Document saved to `resumes` collection with `schema_version: 3`, `resume_id` = a UUID hex string.
9. Response: `{ resume_id: "<uuid>", cloudinary_url: "<url>", parsed_data: {name: "Jane Doe", email: "jane@example.com", ...}, extracted_text_preview: "<first 500 chars>", processing_status: "completed" }`

No unit test currently covers this endpoint (`backend/tests/test_db_service.py` covers the analogous `save_jobs` path, and `backend/test/test_integration.py` covers job search — neither touches resume routes).

## Dependencies & Integration Points
- **Cloudinary** — file storage; uses resource_type `"image"` for PDFs, `"raw"` for DOCX; download URLs must be explicitly generated because direct Cloudinary delivery may be blocked on free accounts.
- **Configured LLM provider** via `parse_resume_text` (uses `call_llm_async` from `app.core.llm`, routed through the active `LLM_PROVIDER`) — extracts structured fields from raw text; on failure, empty parsed data is used instead of failing.
- **Configured LLM provider** (via MultiProvider fallback chain, routed through `get_llm_provider()` in `app.services.llm`) — the structured tailoring pipeline with PII stripping; uses free-tier models with automatic fallback across providers.
- **MongoDB** via `motor` — collections `resumes`, `tailor_sessions`.
- **`mammoth`** for DOCX→HTML conversion; **`unstructured`** / `pdfminer` for PDF text extraction; **`weasyprint`** / `pdfkit` for HTML→PDF generation.

## Edge Cases & Known Gotchas
- **LLM parsing failure is non-fatal** — if `parse_resume_text` throws, the upload still succeeds with empty parsed data and `processing_status: "completed"`. There is no "failed" processing status in the upload endpoint.
- **Cover letter generation failure is non-fatal** — on failure a template letter is used; the response still returns 200.
- **File generation/upload failure in tailoring is non-fatal** — if DOCX/PDF generation or Cloudinary upload fails, the `StructuredTailorResponse` is returned with empty `download_urls` (no error). Only a logged warning.
- **Tailor session save failure is a warning only** — logged but does not affect the response.
- **Structured tailoring errors return 200, not 4xx/5xx** — when either the LLM pipeline fails or the resume has no extracted text, the endpoint returns 200 with `StructuredTailorErrorResponse` body. Only missing resume/job IDs return 404.
- **PDF resource_type on Cloudinary** — PDFs must use `resource_type="image"` (not `"raw"` or `"video"`) for the free Cloudinary plan. The public_id must NOT include a file extension.
- **MongoDB schema validation** — `email` defaults to an empty string in the model but the MongoDB schema has a regex pattern that rejects empty strings. `_sanitize_parsed_data` omits `email` entirely when it's empty to work around this.

## Key Files
- `backend/app/api/v1/resumes.py` — router with three endpoints: upload, tailor-structured, download-from-url
- `backend/app/models/resume.py` — Pydantic models for all request/response types
- `backend/app/services/db_service.py` — `save_resume`, `get_resume_by_id`, `save_tailor_session`
- `backend/app/services/resume_parser.py` — `parse_resume_text` (Groq LLM call)
- `backend/app/services/structured_tailor.py` — `tailor_resume_structured` (OpenRouter pipeline)
- `backend/app/services/cover_letter.py` — `generate_cover_letter`
- `backend/app/services/PDF_service.py` — PDF text extraction, PDF generation
- `backend/app/services/docx_service.py` — DOCX text extraction
- `backend/app/services/html_service.py` — HTML conversion (docx→html, html→docx, html→pdf)
- `backend/app/services/cloudinary_service.py` — upload, download URL, stream file, URL parsing
- `backend/tests/test_db_service.py` — only tests the analogous `save_jobs` path, not resume endpoints

## Why (Design Rationale)
- **PII stripping before LLM** — name, email, and phone are extracted from the parsed resume data and re-injected after the OpenRouter call. The external model never sees personally identifying information. This is the primary design constraint of `/tailor-structured`.
- **Error responses as 200 with error body** — the tailoring endpoint returns `StructuredTailorErrorResponse` as a 200 instead of a 4xx/5xx because partial results (e.g. a fallback `tailored_text`) are still useful to the frontend. Only truly missing resources (resume/job not found) return HTTP error codes.
- **`_sanitize_parsed_data` is defensive, not prescriptive** — the LLM output is unpredictable. Rather than failing on malformed data, the sanitizer coerces everything to valid types and drops entries that can't be salvaged.
- **Proxy download** — Cloudinary's direct download may be blocked on free accounts (especially for PDFs). The `/download-from-url` endpoint proxies the file through the backend to work around this without requiring a paid Cloudinary plan.

## Open Issues
- No unit tests exist for any of the three resume endpoints — only the integration test harness and `save_jobs` tests are present.
- `_sanitize_parsed_data` has duplicate logic for experience formatting vs `_format_experience` helper.
