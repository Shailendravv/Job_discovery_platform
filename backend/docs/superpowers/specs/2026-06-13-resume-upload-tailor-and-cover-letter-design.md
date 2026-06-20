# Design Spec: Resume Upload, Cloudinary Integration, AI Parsing, Tailoring & Cover Letter Generation

**Date:** 2026-06-13
**Status:** Approved — In Implementation
**Author:** Buffy (AI Agent)
**Decisions:** Groq (free tier LLM), MongoDB ObjectId for job identification, Cloudinary URLs for file delivery

---

## 1. Problem Statement

The current system can search and persist job listings, but there is no way for users to:

- Upload their existing resume (PDF or DOCX) for storage and parsing
- Parse resume contents into structured data (name, email, experience, skills, etc.)
- Tailor their resume to match a specific job description
- Generate a professional cover letter for a specific job application
- Download the tailored resume in both PDF and DOCX formats

This prevents users from efficiently applying to jobs with customized application materials.

---

## 2. Objectives

- **Resume Upload**: Accept PDF or DOCX files, store them in Cloudinary, parse their text
- **AI-Powered Parsing**: Extract structured data (name, email, phone, education, experience, skills, languages, certifications) using Groq LLM
- **Resume Tailoring**: Given a resume + job description, rewrite sections to align with the job requirements
- **Cover Letter Generation**: Generate a professional, job-specific cover letter using Groq LLM
- **Multi-Format Download**: Generate tailored resume as both PDF and DOCX, store on Cloudinary
- **Frontend Integration Ready**: All endpoints return structured data + Cloudinary download URLs

---

## 3. Architecture & Data Flow

### 3.1 High-Level System Diagram

```
┌──────────────────────────────────────────────────────────────────────┐
│                          Frontend                                      │
│                                                                        │
│  ┌──────────────────────────────────────────────────────────────────┐ │
│  │ Upload Resume (PDF/DOCX)                                         │ │
│  │  → POST /api/v1/resumes/upload (multipart/form-data)             │ │
│  │  → Response: resume_id + parsed_data + cloudinary_url             │ │
│  └──────────────────────────────────────────────────────────────────┘ │
│                                                                        │
│  ┌──────────────────────────────────────────────────────────────────┐ │
│  │ Tailor Resume + Cover Letter                                     │ │
│  │  → POST /api/v1/resumes/tailor (JSON: resume_id + job_id)        │ │
│  │  → Response: tailored_text + cover_letter + download_urls        │ │
│  └──────────────────────────────────────────────────────────────────┘ │
└──────────────────────────┬───────────────────────────────────────────┘
                           │
┌──────────────────────────▼───────────────────────────────────────────┐
│                       FastAPI Backend                                  │
│                                                                        │
│  ┌──────────────────────────────────────────────────────────────────┐ │
│  │ POST /api/v1/resumes/upload                                       │ │
│  │  ① Receive file (PDF or DOCX)                                    │ │
│  │  ② Upload original to Cloudinary                                 │ │
│  │  ③ Extract text (pypdf for PDF, python-docx for DOCX)            │ │
│  │  ④ Call Groq LLM to parse text → structured JSON                  │ │
│  │  ⑤ Save full record to MongoDB (resumes collection)               │ │
│  │  ⑥ Return resume_id + parsed data + Cloudinary URL               │ │
│  └──────────────────────────────────────────────────────────────────┘ │
│                                                                        │
│  ┌──────────────────────────────────────────────────────────────────┐ │
│  │ POST /api/v1/resumes/tailor                                       │ │
│  │  ① Receive { resume_id, job_id }                                 │ │
│  │  ② Fetch resume from MongoDB (parsed_data + extracted_text)       │ │
│  │  ③ Fetch job from MongoDB (title, description, skills)            │ │
│  │  ④ Call Groq LLM to tailor resume to job description              │ │
│  │  ⑤ Call Groq LLM to generate cover letter                         │ │
│  │  ⑥ Generate PDF + DOCX from tailored text                         │ │
│  │  ⑦ Upload both files to Cloudinary                                │ │
│  │  ⑧ Return tailored_text + cover_letter + download_urls            │ │
│  └──────────────────────────────────────────────────────────────────┘ │
└──────────────────────────┬───────────────────────────────────────────┘
                           │
              ┌────────────┴────────────┐
              ▼                         ▼
     ┌─────────────────┐     ┌───────────────────┐
     │    MongoDB       │     │    Cloudinary      │
     │  (jobs + resumes)│     │  (file storage)    │
     └─────────────────┘     └───────────────────┘
                           │
              ┌────────────┴────────────┐
              ▼                         ▼
     ┌─────────────────┐     ┌───────────────────┐
     │   Groq API       │     │   python-docx /   │
     │ (LLM provider)   │     │     pypdf         │
     └─────────────────┘     └───────────────────┘
```

### 3.2 Upload Flow (Detailed)

```
Client → POST /api/v1/resumes/upload
  Headers: Content-Type: multipart/form-data
  Body: file=<PDF_or_DOCX_binary>

Step 1: Validate file type (application/pdf, application/vnd.openxmlformats-officedocument.wordprocessingml.document)
Step 2: Read file bytes
Step 3: Upload to Cloudinary using cloudinary.uploader.upload()
         - resource_type: "raw" (for document files)
         - public_id: "resumes/{uuid}-{original_filename}"
         - Returns: cloudinary_url, public_id
Step 4: Extract text
         - If PDF: use pypdf.PdfReader
         - If DOCX: use docx.Document (python-docx)
Step 5: LLM Parse — send extracted text to Groq with parse prompt
         → Returns structured JSON: { name, email, phone, education[], experience[], skills[], languages[], certifications[] }
Step 6: Save to MongoDB resumes collection:
         {
           cloudinary_url: "https://res.cloudinary.com/...",
           cloudinary_public_id: "resumes/uuid-file.docx",
           filename: "original_filename.docx",
           content_type: "application/vnd.openxmlformats...",
           file_size: 12345,
           extracted_text: "...",
           extracted_text_length: 5000,
           parsed_data: { ... structured data ... },
           processing_status: "completed",
           created_at: now,
           updated_at: now
         }
Step 7: Return ResumeUploadResponse {
           resume_id: "abc123",
           cloudinary_url: "https://...",
           parsed_data: { ... },
           extracted_text_preview: "First 500 chars..."
         }
```

### 3.3 Tailor Flow (Detailed)

```
Client → POST /api/v1/resumes/tailor
  Body: { "resume_id": "abc123", "job_id": "65f1a2b3c4d5e6f7a8b9c0d1" }

Step 1: Validate both IDs are valid ObjectId format
Step 2: Fetch resume from db.resumes (by resume_id/ObjectId)
Step 3: Fetch job from db.jobs (by job_id/ObjectId)
Step 4: Build tailor prompt:
         - Resume sections: summary, experience, education, skills
         - Job details: title, description, required skills
         - Instructions: rewrite bullets to emphasize matching skills, reorder experience by relevance, tailor summary
Step 5: Call Groq LLM with tailor prompt → returns tailored resume text
Step 6: Build cover letter prompt:
         - Candidate name + skills (from resume)
         - Company name + job title (from job)
         - Job description highlights
Step 7: Call Groq LLM with cover letter prompt → returns cover letter text
Step 8: Generate PDF from tailored text (reportlab)
Step 9: Generate DOCX from tailored text (python-docx)
Step 10: Upload both files to Cloudinary
          → pdf_url, docx_url
Step 11: Optionally save tailor session to MongoDB (for history)
Step 12: Return ResumeTailorResponse {
           resume_id: "abc123",
           job_id: "65f1a2b3...",
           tailored_text: "Tailored resume content...",
           cover_letter: "Cover letter content...",
           download_urls: {
             pdf: "https://res.cloudinary.com/.../tailored_resume.pdf",
             docx: "https://res.cloudinary.com/.../tailored_resume.docx"
           }
         }
```

---

## 4. API Design

### 4.1 POST /api/v1/resumes/upload

Upload a resume file (PDF or DOCX), parse it, and store it.

**Request:**
```
Content-Type: multipart/form-data
Body:
  file: <binary file> (required, PDF or DOCX)
```

**Response (200):**
```json
{
  "resume_id": "65f1a2b3c4d5e6f7a8b9c0d1",
  "cloudinary_url": "https://res.cloudinary.com/.../resume.pdf",
  "parsed_data": {
    "name": "John Doe",
    "email": "john@example.com",
    "phone": "+1-555-123-4567",
    "education": [
      {
        "institution": "University of Technology",
        "degree": "B.S. Computer Science",
        "year": 2020
      }
    ],
    "experience": [
      {
        "company": "Tech Corp",
        "title": "Software Engineer",
        "duration": "2020-2024",
        "description": "Built scalable microservices..."
      }
    ],
    "skills": ["Python", "React", "TypeScript", "MongoDB"],
    "languages": ["English", "Spanish"],
    "certifications": ["AWS Solutions Architect"]
  },
  "extracted_text_preview": "John Doe\njohn@example.com\n...",
  "processing_status": "completed"
}
```

**Error Responses:**
- `400`: Invalid file type (not PDF or DOCX), file too large (>10MB)
- `422`: File parsing failed
- `500`: Cloudinary upload failed, LLM parsing failed

### 4.2 POST /api/v1/resumes/tailor

Tailor a resume to a specific job and generate a cover letter.

**Request:**
```json
{
  "resume_id": "65f1a2b3c4d5e6f7a8b9c0d1",
  "job_id": "65f1a2b3c4d5e6f7a8b9c0d2"
}
```

**Response (200):**
```json
{
  "resume_id": "65f1a2b3c4d5e6f7a8b9c0d1",
  "job_id": "65f1a2b3c4d5e6f7a8b9c0d2",
  "tailored_text": "John Doe\njohn@example.com\n...\n\nProfessional Summary\n...\n\nExperience\n...",
  "cover_letter": "Dear Hiring Manager,\n\nI am writing to express my interest...\n\nSincerely,\nJohn Doe",
  "download_urls": {
    "pdf": "https://res.cloudinary.com/.../tailored_resume_abc123.pdf",
    "docx": "https://res.cloudinary.com/.../tailored_resume_abc123.docx",
    "cover_letter_pdf": "https://res.cloudinary.com/.../cover_letter_abc123.pdf"
  }
}
```

**Error Responses:**
- `404`: Resume or job not found
- `400`: Invalid ObjectId format
- `500`: LLM call failed, file generation failed

---

## 5. Pydantic Response Models

### `backend/app/models/resume.py` (Updated)

```python
class ResumeUploadResponse(BaseModel):
    resume_id: str
    cloudinary_url: str
    parsed_data: ParsedResumeData
    extracted_text_preview: str
    processing_status: str

class ParsedResumeData(BaseModel):
    name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    education: List[EducationEntry] = Field(default_factory=list)
    experience: List[ExperienceEntry] = Field(default_factory=list)
    skills: List[str] = Field(default_factory=list)
    languages: List[str] = Field(default_factory=list)
    certifications: List[str] = Field(default_factory=list)

class EducationEntry(BaseModel):
    institution: Optional[str] = None
    degree: Optional[str] = None
    year: Optional[int] = None

class ExperienceEntry(BaseModel):
    company: Optional[str] = None
    title: Optional[str] = None
    duration: Optional[str] = None
    description: Optional[str] = None

class ResumeTailorRequest(BaseModel):
    resume_id: str = Field(..., description="MongoDB ObjectId of the resume")
    job_id: str = Field(..., description="MongoDB ObjectId of the job")

class DownloadUrls(BaseModel):
    pdf: str
    docx: str
    cover_letter_pdf: Optional[str] = None

class ResumeTailorResponse(BaseModel):
    resume_id: str
    job_id: str
    tailored_text: str
    cover_letter: str
    download_urls: DownloadUrls
```

---

## 6. Database Schema

### 6.1 `resumes` Collection (Existing — Enhanced)

The existing schema from migration 001 already has all the fields we need:

| Field | Type | Description |
|-------|------|-------------|
| `_id` | ObjectId | Auto-generated |
| `resume_id` | string | UUID for external reference |
| `cloudinary_url` | string | URL of uploaded file on Cloudinary |
| `cloudinary_public_id` | string | Cloudinary public ID for management |
| `filename` | string | Original filename |
| `content_type` | string | MIME type (pdf or docx) |
| `file_size` | int | File size in bytes |
| `extracted_text` | string | Raw text extracted from file |
| `extracted_text_length` | int | Length of extracted text |
| `parsed_data` | object | Structured data (name, email, etc.) |
| `processing_status` | string | pending, processing, completed, failed |
| `processing_error` | string | Error message if failed |
| `schema_version` | int | For future migrations |
| `created_at` | date | Timestamp |
| `updated_at` | date | Timestamp |

### 6.2 `tailor_sessions` Collection (New — Optional)

For tracking tailoring history:

| Field | Type | Description |
|-------|------|-------------|
| `_id` | ObjectId | Auto-generated |
| `resume_id` | ObjectId | Reference to resumes collection |
| `job_id` | ObjectId | Reference to jobs collection |
| `original_text` | string | Resume text before tailoring |
| `tailored_text` | string | Tailored resume text |
| `cover_letter` | string | Generated cover letter |
| `cloudinary_pdf_url` | string | Tailored resume PDF URL |
| `cloudinary_docx_url` | string | Tailored resume DOCX URL |
| `cloudinary_cover_letter_url` | string | Cover letter PDF URL |
| `created_at` | date | Timestamp |

---

## 7. Configuration Changes

### `backend/app/core/config.py` (Updated)

```python
# Cloudinary Configuration
CLOUDINARY_CLOUD_NAME: str = ""
CLOUDINARY_API_KEY: str = ""
CLOUDINARY_API_SECRET: str = ""

# Groq LLM
GROQ_API_KEY: str = ""  # Already exists, but now properly used
GROQ_MODEL_NAME: str = "llama3-70b-8192"  # Free tier model
```

### `.env` Additions

```env
# Cloudinary
CLOUDINARY_CLOUD_NAME=your_cloud_name
CLOUDINARY_API_KEY=your_api_key
CLOUDINARY_API_SECRET=your_api_secret

# Groq
GROQ_API_KEY=gsk_your_groq_api_key
GROQ_MODEL_NAME=llama-3.3-70b-versatile
```

---

## 8. Dependencies

### New Python Packages

| Package | Version | Purpose |
|---------|---------|---------|
| `cloudinary` | >=1.40 | Cloudinary file upload/download |
| `python-docx` | >=1.1 | DOCX file read/write |
| `groq` | >=0.13 | Groq LLM API client |

### Updated `requirements.txt`

```txt
fastapi
uvicorn[standard]
python-dotenv
motor
pydantic-settings
python-multipart
httpx
ollama
mcp
pypdf
reportlab
cloudinary          # NEW
python-docx         # NEW
groq                # NEW
```

---

## 9. LLM Prompt Design (Groq)

### 9.1 Resume Parse Prompt

```
You are a resume parser. Extract structured information from the following resume text.
Return ONLY valid JSON with this exact structure:
{
  "name": "Full Name",
  "email": "email@example.com",
  "phone": "phone number",
  "education": [{"institution": "University", "degree": "Degree Name", "year": 2024}],
  "experience": [{"company": "Company", "title": "Job Title", "duration": "2020-2024", "description": "What they did"}],
  "skills": ["Skill1", "Skill2"],
  "languages": ["Language1"],
  "certifications": ["Cert1"]
}

Use null for missing fields. For education year, use integer or null.
For experience duration, use string like "2020-2024" or "3 years".
Do not include markdown formatting or code blocks. Return ONLY the JSON.

RESUME TEXT:
{extracted_text}
```

### 9.2 Resume Tailor Prompt

```
You are a professional resume writer. Given a candidate's resume and a job description,
rewrite the resume to best match the job requirements.

Candidate's Resume:
{resume_text}

Job Title: {job_title}
Job Description: {job_description}
Required Skills: {job_skills}

Instructions:
1. Write a compelling Professional Summary that aligns with the job
2. Reorder and rewrite experience bullets to emphasize relevant skills
3. Tailor the skills section to prioritize skills mentioned in the job description
4. Keep all factual information accurate (don't fabricate experience)
5. Format as a clean, professional resume with clear sections

Return the complete tailored resume as plain text.
```

### 9.3 Cover Letter Prompt

```
You are a professional cover letter writer. Write a compelling cover letter
for a job application.

Candidate Name: {candidate_name}
Candidate Skills: {candidate_skills}
Job Title: {job_title}
Company Name: {company_name}
Job Description: {job_description}

Instructions:
1. Address the letter to "Dear Hiring Manager"
2. Open with enthusiasm for the role and company
3. Connect the candidate's skills and experience to the job requirements
4. Show specific knowledge of the company/industry where possible
5. Close professionally with a call to action
6. Keep it to 3-4 paragraphs
7. Sign with the candidate's name

Return the complete cover letter as plain text.
```

---

## 10. New Service Files

### 10.1 `backend/app/services/cloudinary_service.py`

```python
"""
Cloudinary service for file upload and management.
"""
import cloudinary
import cloudinary.uploader
from app.core.config import settings

def configure_cloudinary():
    cloudinary.config(
        cloud_name=settings.CLOUDINARY_CLOUD_NAME,
        api_key=settings.CLOUDINARY_API_KEY,
        api_secret=settings.CLOUDINARY_API_SECRET,
        secure=True
    )

async def upload_file(file_bytes: bytes, public_id: str) -> dict:
    """Upload a file to Cloudinary. Returns dict with url, public_id, etc."""
    result = cloudinary.uploader.upload(
        file_bytes,
        public_id=public_id,
        resource_type="raw",  # For documents (not images)
        overwrite=True
    )
    return {
        "url": result["secure_url"],
        "public_id": result["public_id"],
        "format": result.get("format", ""),
        "bytes": result.get("bytes", 0)
    }
```

### 10.2 `backend/app/services/docx_service.py`

```python
"""
DOCX file handling service.
"""
from docx import Document
from docx.shared import Pt, Inches
import io

def extract_text_from_docx(file_bytes: bytes) -> str:
    """Extract text from a DOCX file."""
    doc = Document(io.BytesIO(file_bytes))
    return "\n".join(p.text for p in doc.paragraphs)

def generate_docx(text: str) -> bytes:
    """Generate a DOCX file from text."""
    doc = Document()
    # Add styling
    style = doc.styles["Normal"]
    font = style.font
    font.name = "Calibri"
    font.size = Pt(11)
    
    for line in text.split("\n"):
        if line.strip():
            # Section headers (all caps or short lines)
            if line.isupper() or len(line.strip()) < 50:
                p = doc.add_paragraph(line)
                p.style = doc.styles["Heading 2"]
            else:
                doc.add_paragraph(line)
        else:
            doc.add_paragraph("")  # Empty line for spacing
    
    buffer = io.BytesIO()
    doc.save(buffer)
    return buffer.getvalue()
```

### 10.3 `backend/app/services/resume_parser.py`

```python
"""
LLM-powered resume parser service.
Uses Groq to extract structured data from resume text.
"""
import json
import re
from app.core.llm import call_llm

PARSE_PROMPT = """..."""  # As designed in section 9.1

async def parse_resume_text(extracted_text: str) -> dict:
    """Parse resume text into structured data using Groq LLM."""
    prompt = PARSE_PROMPT.format(extracted_text=extracted_text)
    raw_response = call_llm(prompt,   )
    # Clean and parse JSON
    cleaned = re.sub(r"^```(?:json)?\s*", "", raw_response).strip()
    cleaned = re.sub(r"\s*```$", "", cleaned).strip()
    return json.loads(cleaned)
```

### 10.4 `backend/app/services/resume_tailor.py`

```python
"""
Resume tailoring service.
Uses Groq to rewrite resume sections based on job description.
"""
from app.core.llm import call_llm

TAILOR_PROMPT = """..."""  # As designed in section 9.2

async def tailor_resume(resume_text: str, job: dict) -> str:
    """Tailor resume text to match job description."""
    prompt = TAILOR_PROMPT.format(
        resume_text=resume_text,
        job_title=job.get("title", ""),
        job_description=job.get("description", ""),
        job_skills=", ".join(job.get("skills", []))
    )
    return call_llm(prompt)
```

### 10.5 `backend/app/services/cover_letter.py`

```python
"""
Cover letter generation service.
Uses Groq to write a professional cover letter.
"""
from app.core.llm import call_llm

COVER_LETTER_PROMPT = """..."""  # As designed in section 9.3

async def generate_cover_letter(
    candidate_name: str,
    candidate_skills: list,
    job_title: str,
    company_name: str,
    job_description: str
) -> str:
    """Generate a cover letter for a job application."""
    prompt = COVER_LETTER_PROMPT.format(
        candidate_name=candidate_name,
        candidate_skills=", ".join(candidate_skills),
        job_title=job_title,
        company_name=company_name,
        job_description=job_description
    )
    return call_llm(prompt)
```

---

## 11. Implementation Steps

### Phase 1: Foundation
1. ✅ Install packages: `cloudinary`, `python-docx`, `groq`
2. ✅ Update `requirements.txt`
3. ✅ Add Cloudinary + Groq model config to `config.py`
4. ✅ Implement Groq provider in `llm.py`

### Phase 2: Upload & Parse
5. ✅ Create `cloudinary_service.py`
6. ✅ Create `docx_service.py`
7. ✅ Add docx generation to `PDF_service.py`
8. ✅ Create `resume_parser.py`
9. ✅ Update Pydantic models in `resume.py`
10. ✅ Update `db_service.py` if needed
11. ✅ Implement `POST /api/v1/resumes/upload`

### Phase 3: Tailor & Cover Letter
12. ✅ Create `resume_tailor.py`
13. ✅ Create `cover_letter.py`
14. ✅ Implement `POST /api/v1/resumes/tailor`

### Phase 4: Validation
15. ✅ Typecheck the project
16. ✅ Code review

---

## 12. Error Handling

| Scenario | HTTP Code | Handling |
|----------|-----------|----------|
| Invalid file type | 400 | Check MIME type before processing |
| File too large (>10MB) | 400 | Check file size before processing |
| Cloudinary upload fails | 500 | Log error, return 500 with message |
| Text extraction fails | 422 | File may be corrupted or password-protected |
| LLM parse fails (bad JSON) | 500 | Retry once, then fail gracefully |
| Resume not found | 404 | Check ObjectId validity first |
| Job not found | 404 | Return separate error for clarity |
| LLM tailor fails | 500 | Return partial response with original text |
| File generation fails | 500 | Return text-only response without download URLs |

---

## 13. Risks & Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| Cloudinary API key missing | Upload fails | Validate config at startup, clear error message |
| Large files (>10MB) | Slow processing, timeout | Enforce size limit, stream processing |
| LLM hallucinates resume data | Users get inaccurate parsed data | Parse prompt instructs "use null for missing", no fabrication rule in tailor prompt |
| Groq API rate limits | Slow responses | Implement retry with backoff; consider fallback to Ollama |
| DOCX formatting issues | Poor quality downloads | Keep formatting simple (no complex tables); focus on content |
| Concurrent uploads to same resume | Data races | Each upload creates new document; no in-place updates |

---

## 14. Success Criteria

- [ ] `POST /upload` accepts PDF and DOCX files, parses them, returns structured data
- [ ] `POST /upload` stores file on Cloudinary and metadata in MongoDB
- [ ] `POST /tailor` accepts resume_id + job_id, returns tailored text
- [ ] `POST /tailor` returns a professional cover letter
- [ ] `POST /tailor` returns Cloudinary download URLs for PDF and DOCX
- [ ] Groq LLM is properly integrated and used for parsing, tailoring, and cover letters
- [ ] All endpoints handle errors gracefully with appropriate HTTP status codes
- [ ] Configuration validation at startup (Cloudinary + Groq API keys)
- [ ] Invalid file types are rejected with clear error messages

---

## 15. Out of Scope (Future)

- **Batch processing** — Multiple resume uploads in one request
- **User authentication** — No user-specific resume management
- **Resume versioning** — Each upload is a separate document; no version tracking
- **ATS score calculation** — No automated scoring of resume fit
- **Webhook notifications** — No async processing callbacks
- **Resume template library** — No predefined formatting templates
- **Bullet point suggestions** — No ML-powered improvement suggestions beyond tailoring

---

## 16. Open Questions (Resolved)

**Q:** Which LLM provider for parsing, tailoring, and cover letters?  
**A:** **Groq (free tier)** — Llama 3 70B or Mixtral 8x7M via Groq API

**Q:** How to identify the job when tailoring?  
**A:** **MongoDB ObjectId** — Frontend sends `job_id` (string ObjectId), backend fetches from `db.jobs`

**Q:** How to deliver tailored resumes to frontend?  
**A:** **Cloudinary URLs + Content** — Generate PDF + DOCX, upload to Cloudinary, return URLs with text content

---

## 17. Review Checklist

- [x] No placeholder "TBD" sections
- [x] All API endpoints clearly defined with request/response
- [x] Database schema changes documented
- [x] All new service files specified with interfaces
- [x] LLM prompts designed
- [x] Error handling considered for each step
- [x] Configuration changes documented
- [x] Dependencies listed
- [x] Implementation steps ordered
- [x] Risks identified with mitigations
- [x] Success criteria measurable
- [x] Out of scope documented
