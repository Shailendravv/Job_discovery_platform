# Frontend Planning — Resume Tailoring Feature

> **Date:** 2026-06-15  
> **Approach:** Option C — Tailor button on both the jobs table AND job details page  
> **Goal:** Allow users to select an existing resume, tailor it to a specific job, generate a cover letter, and download the results

---

## Table of Contents

1. [Project Overview](#1-project-overview)
2. [Architecture Overview](#2-architecture-overview)
3. [Navigation Structure](#3-navigation-structure)
4. [Backend API Reference](#4-backend-api-reference)
5. [User Flow](#5-user-flow)
6. [Frontend Component Architecture](#6-frontend-component-architecture)
7. [Screen-by-Screen Implementation](#7-screen-by-screen-implementation)
8. [State Management & Data Flow](#8-state-management--data-flow)
9. [API Integration Examples](#9-api-integration-examples)
10. [Error Handling](#10-error-handling)
11. [Suggested Implementation Order](#11-suggested-implementation-order)

---

## 1. Project Overview

This is a **job search and application tool** with a FastAPI Python backend and a React frontend.

### What it does

1. **Searches for jobs** — Aggregate job listings from multiple sources (LinkedIn, SearXNG, etc.)
2. **Stores jobs** — Persists job listings to MongoDB (`jobs` collection)
3. **Uploads resumes** — Accepts PDF/DOCX, extracts text, parses with LLM into structured data
4. **Tailors resumes** — Given a resume + job, rewrites the resume to match the job description
5. **Generates cover letters** — Creates a professional cover letter for each job application
6. **Downloads results** — Generates PDF and DOCX files, uploaded to Cloudinary for download

### Tech Stack

| Layer | Technology |
|---|---|
| Frontend | React (plain or Next.js) — your choice |
| Backend | FastAPI (Python) |
| Database | MongoDB (via Motor async driver) |
| File Storage | Cloudinary |
| LLM | Groq (Llama 3 70B) — for parsing, tailoring, and cover letters |
| File Processing | pypdf (PDF), python-docx (DOCX), reportlab (PDF generation) |

### Key Collections in MongoDB

| Collection | Purpose |
|---|---|
| `jobs` | Stored job listings with title, company, description, skills, etc. |
| `resumes` | Uploaded resumes with extracted text + parsed structured data |
| `tailor_sessions` | Tailored outputs — one document per resume+job pair (added by migration 008) |
| `_migrations` | Tracks which migrations have been applied |

---

## 2. Architecture Overview

```
┌────────────────────────────────────────────────────────────────────────────┐
│                            React Frontend                                   │
│                                                                             │
│  ┌──────────────┐   ┌──────────────────┐   ┌──────────────────────────┐   │
│  │  Navigation   │   │                  │   │                          │   │
│  │  🔍 Jobs     │──▶│   Page Content    │──▶│  Modal / Result Screen   │   │
│  │  📄 Resumes  │   │                  │   │                          │   │
│  └──────────────┘   └──────────────────┘   └──────────────────────────┘   │
│                                                                             │
│  ┌──────────────┐    ┌─────────────────┐    ┌───────────────────┐         │
│  │ Jobs Table    │    │ Job Details      │    │ Tailor Result     │         │
│  │ (list page)   │───▶│ (details page)   │───▶│ (success screen)  │         │
│  └──────┬───────┘    └────────┬────────┘    └───────────────────┘         │
│         │                     │                                             │
│         └──────────┬──────────┘                                             │
│                    ▼                                                        │
│         ┌──────────────────────┐                                           │
│         │ Resume Picker Modal  │  ← Shared across all entry points        │
│         └──────────┬───────────┘                                           │
│                    │                                                        │
│                    ▼                                                        │
│         ┌──────────────────────┐                                           │
│         │  Tailor Confirmation  │  ← "Processing..." state                │
│         └──────────────────────┘                                           │
│                                                                             │
│  ┌──────────────────────────────────────────────────────┐                 │
│  │  Resumes Page (separate menu item)                    │                 │
│  │  ┌──────────────┐  ┌──────────────┐  ┌────────────┐ │                 │
│  │  │ Resume Card 1 │  │ Resume Card 2 │  │ [+ Upload]│ │                 │
│  │  └──────────────┘  └──────────────┘  └────────────┘ │                 │
│  └──────────────────────────────────────────────────────┘                 │
└──────────────────────────┬───────────────────────────────────────────────┘
                           │
                           │ HTTP API calls
                           ▼
┌────────────────────────────────────────────────────────────────────────────┐
│                            FastAPI Backend                                  │
│                                                                             │
│  GET  /api/v1/jobs/jobs        → List stored jobs                         │
│  GET  /api/v1/jobs/job/:id     → Single job details                       │
│  GET  /api/v1/resumes          → List uploaded resumes                    │
│  POST /api/v1/resumes/upload   → Upload new resume                        │
│  POST /api/v1/resumes/tailor   → Tailor resume + generate cover letter    │
│  GET  /api/v1/resumes/sessions → List tailor sessions                     │
└──────────────────────────┬───────────────────────────────────────────────┘
                           │
                           ▼
                   ┌───────────────┐
                   │    MongoDB     │
                   │  jobs, resumes │
                   │ tailor_sessions│
                   └───────────────┘
```

---

## 3. Navigation Structure

The app has **two primary pages**, accessible from a top navigation bar.

### Navigation Bar

```
┌────────────────────────────────────────────────────────────────────────┐
│  🏆 JobApp                     🔍 Jobs      📄 Resumes                │
│  ───────────────────────────────────────────────────────────────────── │
│                                                                         │
│  (Page content here...)                                                 │
└────────────────────────────────────────────────────────────────────────┘
```

### Why Two Menu Items?

| Menu Item | Order | Purpose | When User Wants To... |
|---|---|---|---|
| 🔍 Jobs | **1st** | Main job search & listing | Browse jobs, view details, tailor resumes |
| 📄 Resumes | **2nd** | Resume management | Upload, view, or delete base resumes |

### Resume Upload Has Two Entry Points

| Entry Point | Where | When |
|---|---|---|
| **Resumes page** | Dedicated page (menu item #2) | User wants to manage all resumes |
| **Resume Picker Modal** | Inline in tailor flow | User clicks "Tailor" but has no resumes yet |

This means the user never has to navigate away from the tailoring workflow to upload a resume — if they don't have one, the modal lets them upload immediately.

---

## 4. Backend API Reference

Below are all the API endpoints the frontend will interact with.  
**Base URL:** `http://localhost:8000/api/v1`

---

### 4.1 List Jobs

Fetches stored jobs with pagination, filtering, and sorting.

```
GET /api/v1/jobs/jobs?page=1&limit=20&q=react&sort_by=created_at&sort_order=desc
```

**Query Parameters:**

| Param | Type | Default | Description |
|---|---|---|---|
| `page` | int | 1 | Page number |
| `limit` | int | 20 | Items per page (max 100) |
| `source` | string | — | Filter by source (`linkedin`, `searxng`) |
| `job_type` | string | — | Filter by type (`full-time`, `remote`, etc.) |
| `location` | string | — | Filter by location (partial match) |
| `q` | string | — | Full-text search query |
| `sort_by` | string | `created_at` | Sort field |
| `sort_order` | string | `desc` | Sort direction |

**Response (200):**
```json
{
  "jobs": [
    {
      "_id": "65f1a2b3c4d5e6f7a8b9c0d1",
      "title": "Senior Software Engineer",
      "company": "Acme Corp",
      "location": "Remote",
      "description": "We are looking for...",
      "url": "https://...",
      "apply_url": "https://...",
      "skills": ["Python", "React", "AWS"],
      "job_type": "full-time",
      "posted_date": "2026-06-10",
      "salary": "$150k - $200k",
      "source": "linkedin"
    }
  ],
  "pagination": {
    "page": 1,
    "limit": 20,
    "total": 45,
    "pages": 3
  }
}
```

> **Note:** The `_id` field in each job object is the `job_id` you send to the tailor endpoint.

---

### 4.2 Get Job By ID

Fetches a single job by its MongoDB ObjectId.

```
GET /api/v1/jobs/job/{id}
```

**Response (200):**
```json
{
  "_id": "65f1a2b3c4d5e6f7a8b9c0d1",
  "title": "Senior Software Engineer",
  "company": "Acme Corp",
  "location": "Remote",
  "description": "Full job description text...",
  "skills": ["Python", "React", "AWS"],
  "job_type": "full-time",
  "source": "linkedin",
  "url": "https://...",
  "created_at": "2026-06-10T12:00:00Z"
}
```

> **Note:** This endpoint may not exist yet — you may need to create it.

---

### 4.3 List Resumes

Fetches all uploaded resumes with their parsed data summaries.

```
GET /api/v1/resumes
```

**Response (200):**
```json
{
  "resumes": [
    {
      "_id": "65f1a2b3c4d5e6f7a8b9c0d2",
      "resume_id": "abc123-def456",
      "filename": "john_doe_resume.pdf",
      "content_type": "application/pdf",
      "file_size": 245000,
      "parsed_data": {
        "name": "John Doe",
        "email": "john@example.com",
        "skills": ["Python", "React", "TypeScript", "MongoDB"]
      },
      "cloudinary_url": "https://res.cloudinary.com/.../resume.pdf",
      "processing_status": "completed",
      "created_at": "2026-06-12T10:00:00Z"
    }
  ]
}
```

> **Note:** This endpoint may not exist yet and needs to be created.

---

### 4.4 Upload Resume

Uploads a new resume file (PDF or DOCX).

```
POST /api/v1/resumes/upload
```

**Request:** `multipart/form-data` with a `file` field (PDF or DOCX, max 10MB)

**Response (200):**
```json
{
  "resume_id": "65f1a2b3c4d5e6f7a8b9c0d2",
  "cloudinary_url": "https://res.cloudinary.com/.../resume.pdf",
  "parsed_data": {
    "name": "John Doe",
    "email": "john@example.com",
    "phone": "+1-555-123-4567",
    "education": [
      { "institution": "MIT", "degree": "B.S. Computer Science", "year": 2020 }
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

---

### 4.5 Tailor Resume (THE KEY ENDPOINT)

Tailors a resume to a specific job and generates a cover letter.

```
POST /api/v1/resumes/tailor
```

**Request Body:**
```json
{
  "resume_id": "65f1a2b3c4d5e6f7a8b9c0d2",
  "job_id": "65f1a2b3c4d5e6f7a8b9c0d1"
}
```

**Response (200) — Success:**
```json
{
  "resume_id": "65f1a2b3c4d5e6f7a8b9c0d2",
  "job_id": "65f1a2b3c4d5e6f7a8b9c0d1",
  "tailored_text": "John Doe\njohn@example.com\n\nProfessional Summary\n...",
  "cover_letter": "Dear Hiring Manager,\n\nI am writing to express my interest...",
  "download_urls": {
    "pdf": "https://res.cloudinary.com/.../tailored_resume.pdf",
    "docx": "https://res.cloudinary.com/.../tailored_resume.docx",
    "cover_letter_pdf": "https://res.cloudinary.com/.../cover_letter.pdf"
  }
}
```

**Response (500) — Partial Failure (e.g. file generation failed):**
```json
{
  "resume_id": "65f1a2b3c4d5e6f7a8b9c0d2",
  "job_id": "65f1a2b3c4d5e6f7a8b9c0d1",
  "tailored_text": "The full tailored resume text...",
  "cover_letter": "The full cover letter...",
  "download_urls": { "pdf": "", "docx": "", "cover_letter_pdf": "" }
}
```

**Response (404):**
```json
{
  "detail": "Resume not found: 65f1a2b3c4d5e6f7a8b9c0d2"
}
```

---

### 4.6 List Tailor Sessions

Returns history of all tailoring sessions.

```
GET /api/v1/resumes/sessions?resume_id=65f1a2b3c4d5e6f7a8b9c0d2
```

> **Note:** This endpoint may not exist yet. You can optionally add it.

---

## 5. User Flow

### Flow A: From the Jobs Table (Fast Path)

```
[User sees Jobs Table]
        │
        ▼
[User clicks "✂️ Tailor" on a job row]
        │
        ▼
[Resume Picker Modal opens]
  ├── Shows all uploaded resumes with name + skills preview
  ├── "+ Upload Another Resume" option (inline file picker)
  └── If no resumes exist → "Upload a resume to get started" (full file picker)
        │
        ▼
[User selects a resume → clicks "Tailor & Generate Cover Letter"]
        │
        ▼
[Loading spinner — "Tailoring your resume... Generating cover letter..."]
        │
        ▼
[Result Screen shows]
  ├── Tailored resume preview
  ├── Cover letter preview
  ├── Download buttons: [PDF] [DOCX] [Cover Letter PDF]
  └── "✂️ Tailor Again" or "🗂️ Back to Jobs"
```

### Flow B: From the Job Details Page (Full Context)

```
[User sees Job Details page]
  ├── Full job description, company info, skills
  └── "✂️ Tailor Resume for This Job" button
        │
        ▼
[Same Resume Picker Modal → Same Result Screen]
```

Both flows use **the same modal** and **the same result screen** — only the entry point differs.

### Flow C: From the Resumes Page (Reverse Flow)

```
[User navigates to "📄 Resumes" via menu bar]
        │
        ▼
[Resumes Page shows all uploaded resumes as cards]
  ├── Each card shows: name, filename, skills preview, upload date
  ├── Actions on each card: "✂️ Tailor to Job" and "🗑️ Delete"
  └── [+ Upload New Resume] button at top
        │
        ▼
[User clicks "✂️ Tailor to Job" on a resume card]
        │
        ▼
[Job Picker Modal opens]
  ├── Shows list of stored jobs (title, company, location)
  └── Search/filter to find the right job
        │
        ▼
[User selects a job → clicks "Tailor & Generate"]
        │
        ▼
[Same Result Screen]
```

### Flow D: Upload Then Tailor (Combined Flow)

```
[User clicks "✂️ Tailor" from anywhere]
        │
        ▼
[Resume Picker Modal opens]
        │
        ▼
[No resumes found → Modal shows file upload UI]
        │
        ▼
[User uploads PDF/DOCX → file uploads via POST /upload]
        │
        ▼
[Modal auto-selects the newly uploaded resume]
        │
        ▼
[User clicks "Tailor & Generate Cover Letter"]
        │
        ▼
[Same Result Screen]
```

---

## 6. Frontend Component Architecture

```
src/
├── components/
│   ├── NavBar.jsx               ← Top navigation: 🔍 Jobs | 📄 Resumes
│   │
│   │   ── Jobs Section ──
│   ├── JobsTable.jsx             ← Main table listing all jobs
│   ├── JobRow.jsx                ← Single job row with "View" and "Tailor" actions
│   ├── JobDetails.jsx            ← Full job detail view (page)
│   │
│   │   ── Resumes Section ──
│   ├── ResumesPage.jsx           ← Resume management page with card grid
│   ├── ResumeCard.jsx            ← Single resume card with "Tailor to Job" + "Delete"
│   ├── ResumeUploadForm.jsx      ← Drag-and-drop or file picker for PDF/DOCX
│   │
│   │   ── Tailor Section (Shared) ──
│   ├── ResumePickerModal.jsx     ← ✨ Select which resume to use (shared)
│   ├── JobPickerModal.jsx        ← ✨ Select which job to tailor for (reverse flow)
│   ├── TailorResult.jsx          ← ✨ Show tailored output + downloads
│   │
│   │   ── Common ──
│   └── common/
│       ├── LoadingSpinner.jsx
│       ├── ErrorMessage.jsx
│       └── DownloadButton.jsx
│
├── hooks/
│   ├── useJobs.js                ← Fetch jobs list
│   ├── useResumes.js             ← Fetch resumes list
│   ├── useTailor.js              ← POST to /tailor endpoint
│   └── useUpload.js              ← POST to /upload endpoint + delete
│
├── pages/
│   ├── JobsPage.jsx              ← Page with JobsTable + search
│   ├── JobDetailPage.jsx         ← Page with JobDetails
│   └── ResumesPage.jsx           ← Page with resume management
│
├── api/
│   └── client.js                 ← Axios/fetch wrapper with base URL
│
└── App.jsx                       ← Router setup: /jobs, /jobs/:id, /resumes
```

### Component Responsibilities

| Component | Responsibility |
|---|---|
| `NavBar` | Top navigation bar with "🔍 Jobs" and "📄 Resumes" links, active state highlighting |
| `JobsTable` | Fetches jobs, renders paginated table with columns + actions |
| `JobRow` | Single row with `_id`, title, company, location, skills preview + action buttons |
| `JobDetails` | Shows full job description, company, skills list, salary, apply URL |
| `ResumesPage` | Fetches resumes, renders as card grid, upload button at top |
| `ResumeCard` | Single card with name, filename, skills, upload date + "Tailor to Job" + "Delete" |
| `ResumeUploadForm` | Drag-and-drop or file picker for PDF/DOCX, uploads via POST /upload |
| `ResumePickerModal` | Fetches resumes on mount, shows radio list, inline upload option, confirm button |
| `JobPickerModal` | Reverse flow: shows job list for user to pick which job to tailor for |
| `TailorResult` | Shows tailored text + cover letter (truncated with "show more"), download buttons |

---

## 7. Screen-by-Screen Implementation

### 7.1 Navigation Bar

```
┌────────────────────────────────────────────────────────────────────────┐
│  🏆 JobApp                     🔍 Jobs      📄 Resumes                │
│  ───────────────────────────────────────────────────────────────────── │
│                                    ↑ Active (if on Resumes page)      │
│  (Current page content)                                                │
└────────────────────────────────────────────────────────────────────────┘
```

**Behavior:**
- Clicking "🔍 Jobs" → navigates to `/jobs`
- Clicking "📄 Resumes" → navigates to `/resumes`
- Active page is highlighted
- Logo/name links to `/jobs` (home)

---

### 7.2 Jobs Table Screen

```
┌────────────────────────────────────────────────────────────────────────────┐
│  🏆 JobApp                     🔍 Jobs      📄 Resumes                    │
│  ───────────────────────────────────────────────────────────────────────── │
│                                                                             │
│  🔍 [Search jobs...]                                    [+ New Search]    │
│                                                                             │
│  ┌────┬──────────────────┬──────────┬──────────┬────────────────┬─────────┐│
│  │ #  │ Title            │ Company  │ Location │ Skills         │ Actions ││
│  ├────┼──────────────────┼──────────┼──────────┼────────────────┼─────────┤│
│  │ 1  │ Sr. SWE          │ Acme Corp│ Remote   │ Python,React   │ 👁️ ✂️   ││
│  │ 2  │ Frontend Dev     │ Beta Inc │ NYC      │ React,TS,CSS   │ 👁️ ✂️   ││
│  │ 3  │ Backend Eng      │ Gamma    │ SF       │ Go,Postgres    │ 👁️ ✂️   ││
│  │ 4  │ Data Scientist   │ Delta    │ Remote   │ Python,ML,SQL  │ 👁️ ✂️   ││
│  └────┴──────────────────┴──────────┴──────────┴────────────────┴─────────┘│
│                                                                             │
│  ◀ 1 2 3 ... 5 ▶                                                          │
└────────────────────────────────────────────────────────────────────────────┘
```

**Behavior:**
- **👁️ View** → Navigate to `/jobs/:id` (job details page)
- **✂️ Tailor** → Open `ResumePickerModal` with `jobId` pre-populated
- Table supports pagination, search, and sorting

---

### 7.3 Job Details Page

```
┌────────────────────────────────────────────────────────────────────────────┐
│  🏆 JobApp                     🔍 Jobs      📄 Resumes                    │
│  ───────────────────────────────────────────────────────────────────────── │
│  ← Back to Jobs                                                           │
│                                                                             │
│  ┌──────────────────────────────────────────────────────────────┐          │
│  │  Senior Software Engineer                                      │          │
│  │  Acme Corp  •  Remote  •  Full-time                           │          │
│  │  Posted: 2026-06-10  •  Salary: $150k - $200k                │          │
│  │                                                                │          │
│  │  Skills: Python, React, AWS, Docker, PostgreSQL               │          │
│  │                                                                │          │
│  │  [✂️ Tailor Resume for This Job]  [🌐 Apply Now]             │          │
│  └──────────────────────────────────────────────────────────────┘          │
│                                                                             │
│  ┌──────────────────────────────────────────────────────────────┐          │
│  │  Job Description                                               │          │
│  │  We are looking for an experienced software engineer...       │          │
│  │  ...full description...                                       │          │
│  └──────────────────────────────────────────────────────────────┘          │
└────────────────────────────────────────────────────────────────────────────┘
```

---

### 7.4 Resumes Page (NEW — Menu Item #2)

```
┌────────────────────────────────────────────────────────────────────────────┐
│  🏆 JobApp                     🔍 Jobs      📄 Resumes (active)           │
│  ───────────────────────────────────────────────────────────────────────── │
│                                                                             │
│  My Resumes                                   [+ Upload New Resume]       │
│  ──────────────                                                             │
│                                                                             │
│  ┌────────────────────────────────────────┐  ┌──────────────────────────┐  │
│  │ 📄 Full Stack Resume                   │  │ 📄 Backend Resume         │  │
│  │                                        │  │                          │  │
│  │ John Doe                               │  │ John Doe                 │  │
│  │ john_doe_resume.pdf  (245 KB)          │  │ backend_focused.docx     │  │
│  │ Uploaded: June 12, 2026                │  │ Uploaded: June 10, 2026  │  │
│  │                                        │  │                          │  │
│  │ Skills: Python, React, AWS, Postgres   │  │ Skills: Python, Django,  │  │
│  │          TypeScript                     │  │          Docker, SQL     │  │
│  │                                        │  │                          │  │
│  │ [✂️ Tailor to Job]  [🗑️ Delete]       │  │ [✂️ Tailor to Job]  [🗑️] │  │
│  └────────────────────────────────────────┘  └──────────────────────────┘  │
│                                                                             │
│  ┌────────────────────────────────────────┐                                │
│  │ ⊕ Upload New Resume                    │                                │
│  │                                        │                                │
│  │ Drag & drop your resume here           │                                │
│  │ or click to browse                     │                                │
│  │                                        │                                │
│  │ Supported: PDF, DOCX (max 10 MB)      │                                │
│  └────────────────────────────────────────┘                                │
└────────────────────────────────────────────────────────────────────────────┘
```

**States:**
1. **Loading** → Skeleton cards while fetching
2. **Has resumes** → Card grid layout
3. **No resumes** → Empty state with large upload area and message: "Upload your first resume to get started"
4. **Error** → Error message with retry button
5. **Uploading** → Progress bar on the upload card

**"✂️ Tailor to Job" on Resume Card:**
- Opens `JobPickerModal` (the reverse flow)
- Shows a list of stored jobs to pick from
- User selects a job → calls same `POST /tailor` endpoint → shows same `TailorResult`

---

### 7.5 Resume Picker Modal (Shared — Entry to Tailor Flow)

This is the **central shared component** used when coming from the Jobs Table or Job Details page.

```
┌─────────────────────────────────────────────────────┐
│  ✂️ Tailor Resume for "Senior SWE @ Acme Corp"│
├─────────────────────────────────────────────────────┤
│                                                     │
│  Select a resume to tailor:                         │
│                                                     │
│  ┌──────────────────────────────────────────────┐   │
│  │ ○ John Doe — Full Stack Resume (PDF)         │   │
│  │   Skills: Python, React, TypeScript, AWS     │   │
│  │   Uploaded: 2 days ago                       │   │
│  ├──────────────────────────────────────────────┤   │
│  │ ○ John Doe — Backend Resume (DOCX)           │   │
│  │   Skills: Python, Django, PostgreSQL, Docker │   │
│  │   Uploaded: 1 week ago                       │   │
│  ├──────────────────────────────────────────────┤   │
│  │ ⊕ Upload Another Resume                      │   │
│  │   [Choose File...] (inline)                  │   │
│  └──────────────────────────────────────────────┘   │
│                                                     │
│  [Cancel]  [✂️ Tailor & Generate Cover Letter]      │
└─────────────────────────────────────────────────────┘
```

**States:**
1. **No resumes uploaded** → Show "Upload a new resume" as the only option with a file picker
2. **Loading** → Show spinner while fetching resumes
3. **Error** → Show error message with retry button
4. **Has resumes** → Show radio list with "+ Upload Another" option at bottom
5. **Uploading new resume** → Show upload progress, then auto-select the new resume
6. **Confirming** → Disable button, show "Processing..." state

**State machine for the confirm button:**
```
if (no resume selected)       → disabled
if (uploading new resume)     → disabled + spinner
if (resume selected)          → enabled "Tailor & Generate Cover Letter"
if (tailoring in progress)    → disabled + "Tailoring your resume..."
```

---

### 7.6 Job Picker Modal (Reverse Flow — from Resumes Page)

Used when the user clicks "✂️ Tailor to Job" on a resume card.

```
┌─────────────────────────────────────────────────────┐
│  ✂️ Tailor "John Doe — Full Stack Resume" to a Job  │
├─────────────────────────────────────────────────────┤
│                                                     │
│  Select the job you want to apply for:              │
│                                                     │
│  🔍 [Search jobs...]                                │
│                                                     │
│  ┌──────────────────────────────────────────────┐   │
│  │ ○ Senior Software Engineer @ Acme Corp       │   │
│  │   Remote  •  Full-time  •  $150k-$200k      │   │
│  ├──────────────────────────────────────────────┤   │
│  │ ○ Frontend Developer @ Beta Inc             │   │
│  │   NYC  •  Full-time  •  $120k-$150k         │   │
│  ├──────────────────────────────────────────────┤   │
│  │ ○ Backend Engineer @ Gamma                  │   │
│  │   SF  •  Contract  •  $100k-$130k           │   │
│  └──────────────────────────────────────────────┘   │
│                                                     │
│  [Cancel]  [✂️ Tailor & Generate Cover Letter]      │
└─────────────────────────────────────────────────────┘
```

---

### 7.7 Tailor Result Screen

```
┌──────────────────────────────────────────────────────────────┐
│  ✅ Resume Tailored Successfully!                             │
│                                                               │
│  Job: Senior Software Engineer @ Acme Corp                   │
│  Resume: John Doe — Full Stack Resume                        │
│                                                               │
│  ┌────────────────────────────────────────────────────────┐  │
│  │  Tailored Resume (preview)                             │  │
│  │  ────────────────────────                              │  │
│  │  John Doe                                              │  │
│  │  john@example.com                                      │  │
│  │                                                         │  │
│  │  PROFESSIONAL SUMMARY                                  │  │
│  │  Experienced software engineer with 4+ years...        │  │
│  │  ...                                                    │  │
│  │  [Show Full Text ▼]                                    │  │
│  └────────────────────────────────────────────────────────┘  │
│                                                               │
│  ┌────────────────────────────────────────────────────────┐  │
│  │  Cover Letter (preview)                                │  │
│  │  Dear Hiring Manager,                                  │  │
│  │  I am writing to express my interest...                │  │
│  │  ...                                                    │  │
│  │  [Show Full Text ▼]                                    │  │
│  └────────────────────────────────────────────────────────┘  │
│                                                               │
│  ┌──────────────────────────────────────────────┐            │
│  │  📥 Download                                  │            │
│  │  [📄 Download PDF]  [📄 Download DOCX]        │            │
│  │  [💌 Download Cover Letter (PDF)]           │            │
│  └──────────────────────────────────────────────┘            │
│                                                               │
│  [✂️ Tailor Again]  [🗂️ Back to Jobs]  [🔍 View Job Details]│
└──────────────────────────────────────────────────────────────┘
```

**Behavior:**
- Show truncated preview of tailored_resume + cover letter with "Show Full Text" expand
- Download buttons open Cloudinary URLs in new tab (or trigger download)
- "✂️ Tailor Again" → goes back to Resume Picker Modal (same job)
- All three result states: Success, Partial Success (no downloads), Error

---

## 8. State Management & Data Flow

### 8.1 Flow Diagram for the Tailor Operation

```
Step 1: User clicks "Tailor" (from table, details page, or resume card)
        │
        ▼
Step 2: Open picker modal (ResumePicker or JobPicker depending on entry point)
        │
        ▼
Step 3: User selects the missing piece (resume if coming from job, job if coming from resume)
        │
        ▼
Step 4: Frontend calls POST /api/v1/resumes/tailor
        Body: { resume_id: "...", job_id: "..." }
        │
        ▼
Step 5: Show loading state ("Tailoring your resume... Generating cover letter...")
        │
        ▼
Step 6: Response received
        ├── Success → Show TailorResult with text + download URLs
        ├── Partial → Show TailorResult with text but empty download URLs
        └── Error   → Show error message with retry option
```

### 8.2 Component State Examples

```jsx
// ResumePickerModal state
const [resumes, setResumes] = useState([]);         // Fetched resume list
const [selectedId, setSelectedId] = useState(null);  // Selected resume._id
const [isLoading, setIsLoading] = useState(true);    // Fetching resumes
const [isUploading, setIsUploading] = useState(false); // Uploading new resume
const [isTailoring, setIsTailoring] = useState(false); // Tailoring in progress
const [error, setError] = useState(null);             // Error message
```

```jsx
// TailorResult state
const [result, setResult] = useState(null);          // Response from /tailor
const [isProcessing, setIsProcessing] = useState(false);
const [error, setError] = useState(null);
const [showFullTailored, setShowFullTailored] = useState(false);
const [showFullCover, setShowFullCover] = useState(false);
```

```jsx
// ResumesPage state
const [resumes, setResumes] = useState([]);
const [isLoading, setIsLoading] = useState(true);
const [isUploading, setIsUploading] = useState(false);
const [error, setError] = useState(null);
```

---

## 9. API Integration Examples

### 9.1 API Client

```javascript
// api/client.js
const API_BASE = 'http://localhost:8000/api/v1';

export async function fetchJobs({ page = 1, limit = 20, q = '' } = {}) {
  const params = new URLSearchParams({ page, limit });
  if (q) params.append('q', q);
  const res = await fetch(`${API_BASE}/jobs/jobs?${params}`);
  if (!res.ok) throw new Error(`Failed to fetch jobs: ${res.statusText}`);
  return res.json();
}

export async function fetchJobById(id) {
  const res = await fetch(`${API_BASE}/jobs/job/${id}`);
  if (!res.ok) throw new Error(`Job not found: ${res.statusText}`);
  return res.json();
}

export async function fetchResumes() {
  const res = await fetch(`${API_BASE}/resumes`);
  if (!res.ok) throw new Error(`Failed to fetch resumes: ${res.statusText}`);
  return res.json();
}

export async function tailorResume(resumeId, jobId) {
  const res = await fetch(`${API_BASE}/resumes/tailor`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ resume_id: resumeId, job_id: jobId }),
  });
  if (!res.ok) {
    const err = await res.json();
    throw new Error(err.detail || 'Tailoring failed');
  }
  return res.json();
}

export async function uploadResume(file) {
  const formData = new FormData();
  formData.append('file', file);
  const res = await fetch(`${API_BASE}/resumes/upload`, {
    method: 'POST',
    body: formData,
  });
  if (!res.ok) {
    const err = await res.json();
    throw new Error(err.detail || 'Upload failed');
  }
  return res.json();
}
```

### 9.2 Resume Picker Modal (React Component Sketch)

```jsx
import React, { useState, useEffect } from 'react';
import { fetchResumes, uploadResume, tailorResume } from '../api/client';

function ResumePickerModal({ jobId, jobTitle, companyName, onComplete, onCancel }) {
  const [resumes, setResumes] = useState([]);
  const [selectedId, setSelectedId] = useState(null);
  const [isLoading, setIsLoading] = useState(true);
  const [isTailoring, setIsTailoring] = useState(false);
  const [error, setError] = useState(null);

  useEffect(() => {
    fetchResumes()
      .then(data => { setResumes(data.resumes || []); setIsLoading(false); })
      .catch(err => { setError(err.message); setIsLoading(false); });
  }, []);

  const handleTailor = async () => {
    if (!selectedId) return;
    setIsTailoring(true);
    setError(null);
    try {
      const result = await tailorResume(selectedId, jobId);
      onComplete(result);
    } catch (err) {
      setError(err.message);
      setIsTailoring(false);
    }
  };

  const handleFileUpload = async (event) => {
    const file = event.target.files[0];
    if (!file) return;
    try {
      const result = await uploadResume(file);
      setResumes(prev => [...prev, {
        _id: result.resume_id,
        parsed_data: result.parsed_data,
        filename: file.name,
        created_at: new Date().toISOString(),
      }]);
      setSelectedId(result.resume_id);
    } catch (err) {
      setError(err.message);
    }
  };

  if (isLoading) return <div className="modal">Loading resumes...</div>;

  return (
    <div className="modal-overlay">
      <div className="modal">
        <h2>✂️ Tailor Resume for "{jobTitle} @ {companyName}"</h2>
        {error && <div className="error">{error}</div>}

        {resumes.length === 0 ? (
          <div className="upload-area">
            <p>No resumes uploaded yet. Upload one to get started:</p>
            <input type="file" accept=".pdf,.doc,.docx" onChange={handleFileUpload} />
          </div>
        ) : (
          <div className="resume-list">
            {resumes.map(resume => (
              <label key={resume._id} className="resume-option">
                <input type="radio" name="resume"
                  checked={selectedId === resume._id}
                  onChange={() => setSelectedId(resume._id)}
                />
                <div className="resume-info">
                  <strong>{resume.parsed_data?.name || 'Unknown'}</strong>
                  <span className="filename">— {resume.filename}</span>
                  <div className="skills">
                    Skills: {(resume.parsed_data?.skills || []).join(', ')}
                  </div>
                </div>
              </label>
            ))}
            <div className="upload-option">
              ⊕ Upload Another Resume
              <input type="file" accept=".pdf,.doc,.docx" onChange={handleFileUpload} hidden />
            </div>
          </div>
        )}

        <div className="modal-actions">
          <button onClick={onCancel} disabled={isTailoring}>Cancel</button>
          <button onClick={handleTailor} disabled={!selectedId || isTailoring}>
            {isTailoring ? 'Tailoring your resume...' : '✂️ Tailor & Generate Cover Letter'}
          </button>
        </div>
      </div>
    </div>
  );
}
export default ResumePickerModal;
```

### 9.3 Tailor Result Component (React Sketch)

```jsx
import React, { useState } from 'react';

function TailorResult({ result, jobTitle, companyName, onTailorAgain, onBack }) {
  const { tailored_text, cover_letter, download_urls } = result;
  const [showFullTailored, setShowFullTailored] = useState(false);
  const [showFullCover, setShowFullCover] = useState(false);
  const truncate = (text, maxLen = 800) =>
    !text || text.length <= maxLen ? text : text.slice(0, maxLen) + '...';

  const hasDownloads = download_urls?.pdf || download_urls?.docx;

  return (
    <div className="tailor-result">
      <h1>✅ Resume Tailored Successfully!</h1>
      <p className="subtitle">Job: {jobTitle} @ {companyName}</p>

      {/* Tailored Resume Preview */}
      <div className="section">
        <h3>📄 Tailored Resume</h3>
        <pre className="text-preview">
          {showFullTailored ? tailored_text : truncate(tailored_text)}
        </pre>
        {tailored_text?.length > 800 && (
          <button onClick={() => setShowFullTailored(!showFullTailored)}>
            {showFullTailored ? 'Show Less ▲' : 'Show Full Text ▼'}
          </button>
        )}
      </div>

      {/* Cover Letter Preview */}
      <div className="section">
        <h3>💌 Cover Letter</h3>
        <pre className="text-preview">
          {showFullCover ? cover_letter : truncate(cover_letter)}
        </pre>
        {cover_letter?.length > 800 && (
          <button onClick={() => setShowFullCover(!showFullCover)}>
            {showFullCover ? 'Show Less ▲' : 'Show Full Text ▼'}
          </button>
        )}
      </div>

      {/* Download Buttons */}
      <div className="section">
        <h3>📥 Downloads</h3>
        {hasDownloads ? (
          <div className="download-buttons">
            {download_urls.pdf && <a href={download_urls.pdf} target="_blank" className="btn">📄 Download PDF</a>}
            {download_urls.docx && <a href={download_urls.docx} target="_blank" className="btn">📄 Download DOCX</a>}
            {download_urls.cover_letter_pdf &&
              <a href={download_urls.cover_letter_pdf} target="_blank" className="btn">💌 Download Cover Letter (PDF)</a>}
          </div>
        ) : (
          <p className="warning">⚠️ File generation was unavailable. You can copy the tailored text above.</p>
        )}
      </div>

      {/* Actions */}
      <div className="actions">
        <button onClick={onTailorAgain}>✂️ Tailor Again</button>
        <button onClick={onBack}>🗂️ Back to Jobs</button>
      </div>
    </div>
  );
}
export default TailorResult;
```

---

## 10. Error Handling

| Scenario | User Sees | Backend Returns |
|---|---|---|
| No resumes uploaded | File upload UI in modal; empty state on Resumes page | Empty array from `GET /resumes` |
| Resume/job not found | Error message: "Resume/job not found" | 404 `{ "detail": "..." }` |
| Network error | "Failed to connect. Check your connection." | — |
| LLM tailoring fails | Tailored text = original resume (fallback) | `ResumeTailorErrorResponse` |
| File generation fails | Text results shown, download buttons hidden | Empty URLs in `download_urls` |
| File too large (>10MB) | Error during upload | 400 `{ "detail": "File too large..." }` |
| Invalid file type | Error during upload | 400 `{ "detail": "Invalid file type..." }` |
| Upload fails (Cloudinary) | Error during upload | 500 `{ "detail": "Upload failed..." }` |
| Tailoring in progress | Spinner with "Tailoring your resume..." | — (loading state) |

### Error Handling Strategy in Frontend

```javascript
async function safeApiCall(apiFunction, ...args) {
  try {
    setLoading(true);
    setError(null);
    const result = await apiFunction(...args);
    return result;
  } catch (err) {
    setError(err.message || 'An unexpected error occurred');
    return null;
  } finally {
    setLoading(false);
  }
}
```

---

## 11. Suggested Implementation Order

Build this feature in these phases:

### Phase 1: Backend Prerequisites

| Step | Task | File |
|---|---|---|
| 1 | Create `GET /api/v1/resumes` endpoint to list all resumes | `backend/app/api/v1/resumes.py` |
| 2 | Create `GET /api/v1/jobs/job/{id}` endpoint for single job | `backend/app/api/v1/jobs.py` |
| 3 | Run migration 008 to create `tailor_sessions` collection with indexes | `backend/migrations/008_add_tailor_sessions.py` |

### Phase 2: Frontend Foundation

| Step | Task | File |
|---|---|---|
| 4 | Create React project + router setup (`/jobs`, `/jobs/:id`, `/resumes`) | `App.jsx` |
| 5 | Create `NavBar` with 🔍 Jobs and 📄 Resumes links | `NavBar.jsx` |
| 6 | Create API client wrapper (`api/client.js`) | `api/client.js` |
| 7 | Create `useJobs` and `useResumes` hooks | Frontend |

### Phase 3: Jobs Section

| Step | Task | File |
|---|---|---|
| 8 | Create `JobsTable` + `JobRow` components | Frontend |
| 9 | Create `JobsPage` with search and pagination | Frontend |
| 10 | Create `JobDetailPage` with full job info | Frontend |

### Phase 4: Resume Management (Menu Item #2)

| Step | Task | File |
|---|---|---|
| 11 | Create `ResumesPage` with card grid layout | Frontend |
| 12 | Create `ResumeCard` component with "Tailor to Job" + "Delete" | Frontend |
| 13 | Create `ResumeUploadForm` component (drag-and-drop or file picker) | Frontend |
| 14 | Wire upload flow: user uploads → card appears in grid immediately | Frontend |

### Phase 5: Tailoring Flow

| Step | Task | File |
|---|---|---|
| 15 | Create `ResumePickerModal` (select resume → tailor for a job) | Frontend |
| 16 | Create `JobPickerModal` (reverse flow: select job for a resume) | Frontend |
| 17 | Create `useTailor` hook | Frontend |
| 18 | Create `TailorResult` component with preview + downloads | Frontend |

### Phase 6: Wire Everything Together

| Step | Task |
|---|---|
| 19 | Wire "✂️ Tailor" on JobRow → opens ResumePickerModal → shows TailorResult |
| 20 | Wire "✂️ Tailor Resume for This Job" on JobDetailsPage → same flow |
| 21 | Wire "✂️ Tailor to Job" on ResumeCard → opens JobPickerModal → shows TailorResult |
| 22 | Wire inline upload in modal → auto-selects new resume |

### Phase 7: Polish

| Step | Task |
|---|---|
| 23 | Add loading spinners and transition animations |
| 24 | Add responsive design for mobile |
| 25 | Add error boundaries and retry mechanisms |
| 26 | Add "Already tailored" badge on jobs that have existing sessions |
| 27 | Add confirmation dialog before deleting a resume |

---

## Appendix: Quick Reference Card

```
┌────────────────────────────────────────────────────────────────────────────┐
│                          QUICK REFERENCE CARD                              │
├────────────────────────────────────────────────────────────────────────────┤
│                                                                            │
│  📡 API Endpoints                                                         │
│  ─────────────                                                             │
│  GET  /api/v1/jobs/jobs       → List jobs (paginated)                     │
│  GET  /api/v1/jobs/job/:id    → Single job details                        │
│  GET  /api/v1/resumes         → List uploaded resumes                     │
│  POST /api/v1/resumes/upload  → Upload new resume                         │
│  POST /api/v1/resumes/tailor  → Tailor resume + generate cover letter     │
│                                                                            │
│  🗄️ MongoDB Collections                                                   │
│  ────────────────────                                                      │
│  jobs             → { _id, title, company, description, skills, ... }     │
│  resumes          → { _id, resume_id, parsed_data, extracted_text, ... }  │
│  tailor_sessions  → { _id, resume_id, job_id, tailored_text, ... }       │
│                                                                            │
│  🔑 Key IDs                                                               │
│  ──────────                                                                 │
│  job_id     = MongoDB ObjectId from jobs collection (24-char hex string)   │
│  resume_id  = MongoDB ObjectId from resumes collection (24-char hex string)│
│                                                                            │
│  📦 Tailor Request                                                         │
│  ────────────────                                                          │
│  { "resume_id": "65f1...", "job_id": "65f1..." }                         │
│                                                                            │
│  📦 Tailor Response (success)                                              │
│  ─────────────────────────                                                │
│  {                                                                         │
│    "resume_id": "...",                                                     │
│    "job_id": "...",                                                        │
│    "tailored_text": "...full resume text...",                              │
│    "cover_letter": "...full letter...",                                    │
│    "download_urls": {                                                      │
│      "pdf": "https://cloudinary.com/.../resume.pdf",                      │
│      "docx": "https://cloudinary.com/.../resume.docx",                    │
│      "cover_letter_pdf": "https://cloudinary.com/.../cover.pdf"           │
│    }                                                                       │
│  }                                                                         │
│                                                                            │
│  🧭 Navigation                                                             │
│  ─────────────                                                             │
│  Menu: 🔍 Jobs (1st) | 📄 Resumes (2nd)                                 │
│                                                                            │
│  📄 Resumes Page (menu #2)                                                │
│  ────────────────────────                                                 │
│  Shows all uploaded resumes as cards                                      │
│  Each card: name, filename, skills, upload date                           │
│  Actions: [✂️ Tailor to Job] [🗑️ Delete]                                 │
│  [+ Upload New Resume] button at top                                      │
│                                                                            │
│  ✂️ Resume Picker Modal (from Jobs)                                       │
│  ────────────────────────────────────                                     │
│  Shows all resumes as radio list                                          │
│  "+ Upload Another" inline option at bottom                               │
│  Confirm → POST /tailor → TailorResult                                    │
│                                                                            │
│  ✂️ Job Picker Modal (from Resumes)                                       │
│  ─────────────────────────────────                                        │
│  Shows all jobs as radio list with search                                 │
│  Confirm → POST /tailor → TailorResult                                    │
│                                                                            │
└────────────────────────────────────────────────────────────────────────────┘
```
