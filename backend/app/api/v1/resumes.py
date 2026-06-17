import logging
import uuid
from fastapi import APIRouter, Depends, UploadFile, File, HTTPException
from fastapi.responses import StreamingResponse
from motor.motor_asyncio import AsyncIOMotorDatabase

from app.models.resume import (
    ResumeUploadResponse,
    ResumeTailorRequest,
    ResumeTailorResponse,
    ResumeTailorErrorResponse,
    ParsedResumeData,
    DownloadUrls,
    DownloadFromUrlRequest,
)
from app.api.deps import get_db
from app.services.PDF_service import extract_text_from_pdf, generate_pdf
from app.services.docx_service import extract_text_from_docx, generate_docx
from app.services.cloudinary_service import (
    upload_file,
    get_download_url,
    stream_file,
    parse_cloudinary_url,
)
from app.services.resume_parser import parse_resume_text
from app.services.resume_tailor import tailor_resume_text
from app.services.cover_letter import generate_cover_letter
from app.services.db_service import save_resume, get_resume_by_id, save_tailor_session

router = APIRouter()
log = logging.getLogger(__name__)

MAX_FILE_SIZE = 10 * 1024 * 1024  # 10 MB
ALLOWED_CONTENT_TYPES = {
    "application/pdf",
    "application/msword",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}


@router.post("/upload", response_model=ResumeUploadResponse)
async def upload_resume(file: UploadFile = File(...), db: AsyncIOMotorDatabase = Depends(get_db)):
    """
    Upload a resume file (PDF or DOCX), parse its contents with Groq LLM,
    store on Cloudinary, and save structured data to MongoDB.
    """
    # ── Validate file type ──
    if file.content_type not in ALLOWED_CONTENT_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid file type '{file.content_type}'. Allowed: PDF, DOC, DOCX",
        )

    # ── Read file bytes ──
    raw_bytes = await file.read()
    if len(raw_bytes) > MAX_FILE_SIZE:
        raise HTTPException(
            status_code=400,
            detail=f"File too large ({len(raw_bytes)} bytes). Maximum: {MAX_FILE_SIZE} bytes (10 MB)",
        )

    # ── Extract text ──
    try:
        if file.content_type == "application/pdf":
            extracted_text = extract_text_from_pdf(raw_bytes)
        else:
            extracted_text = extract_text_from_docx(raw_bytes)
    except Exception as e:
        log.error("Text extraction failed: %s", e, exc_info=True)
        raise HTTPException(status_code=422, detail=f"Failed to extract text from file: {str(e)}")

    if not extracted_text.strip():
        raise HTTPException(status_code=422, detail="No text could be extracted from the uploaded file")

    # ── Upload original to Cloudinary ──
    # Determine resource_type: PDFs must use "image", DOCX uses "raw"
    is_pdf = file.content_type == "application/pdf"
    resource_type = "image" if is_pdf else "raw"

    # public_id must NOT include file extension per Cloudinary docs
    base_name = (file.filename or "resume").rsplit(".", 1)[0]
    public_id = f"resumes/{uuid.uuid4().hex}-{base_name}"
    try:
        cloud_result = await upload_file(
            raw_bytes,
            public_id=public_id,
            resource_type=resource_type,
        )
        # Generate a proper download URL (critical for PDFs on free accounts)
        download_url = get_download_url(
            public_id=cloud_result["public_id"],
            resource_type=resource_type,
            file_format="pdf" if is_pdf else None,
        )
    except Exception as e:
        log.error("Cloudinary upload failed: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to upload file to storage: {str(e)}")

    # ── Parse with Groq LLM ──
    resume_uuid = uuid.uuid4().hex
    try:
        parsed_data = await parse_resume_text(extracted_text)
        processing_status = "completed"
    except Exception as e:
        log.error("LLM parsing failed: %s", e, exc_info=True)
        parsed_data = {
            "name": "", "email": "", "phone": "",
            "education": [], "experience": [], "skills": [],
            "languages": [], "certifications": []
        }
        processing_status = "completed"  # Still mark as completed, just with empty parsed data

    # Sanitize parsed_data for MongoDB schema compliance
    safe_parsed = _sanitize_parsed_data(parsed_data)

    # ── Save to MongoDB ──
    resume_doc = {
        "resume_id": resume_uuid,
        "cloudinary_url": download_url,
        "cloudinary_public_id": cloud_result["public_id"],
        "cloudinary_resource_type": resource_type,
        "filename": file.filename or "unknown",
        "content_type": file.content_type,
        "file_size": len(raw_bytes),
        "extracted_text": extracted_text,
        "extracted_text_length": len(extracted_text),
        "parsed_data": safe_parsed,
        "processing_status": processing_status,
        "schema_version": 1,
    }
    resume_id = await save_resume(db, resume_doc)

    # ── Return structured response ──
    return ResumeUploadResponse(
        resume_id=resume_id,
        cloudinary_url=download_url,
        parsed_data=ParsedResumeData(**safe_parsed),
        extracted_text_preview=extracted_text[:500],
        processing_status=processing_status,
    )


@router.post("/tailor", response_model=ResumeTailorResponse | ResumeTailorErrorResponse)
async def tailor_resume(request: ResumeTailorRequest, db: AsyncIOMotorDatabase = Depends(get_db)):
    """
    Tailor a resume to a specific job description and generate a cover letter.
    Accepts resume_id and job_id (MongoDB ObjectIds).
    Returns tailored text + cover letter + Cloudinary download URLs.
    """
    # ── Fetch resume ──
    resume = await get_resume_by_id(db, request.resume_id)
    if not resume:
        raise HTTPException(status_code=404, detail=f"Resume not found: {request.resume_id}")

    # ── Fetch job ──
    from app.services.db_service import get_job_by_id
    job = await get_job_by_id(db, request.job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job not found: {request.job_id}")

    resume_text = resume.get("extracted_text", "")
    parsed = resume.get("parsed_data", {})

    # ── Tailor resume ──
    try:
        tailored_text = await tailor_resume_text(resume_text, job)
    except Exception as e:
        log.error("Resume tailoring failed: %s", e, exc_info=True)
        return ResumeTailorErrorResponse(
            resume_id=request.resume_id,
            job_id=request.job_id,
            error=f"Resume tailoring failed: {str(e)}",
            tailored_text=resume_text,
        )

    # ── Generate cover letter ──
    try:
        cover_letter = await generate_cover_letter(
            candidate_name=parsed.get("name") or "Applicant",
            candidate_skills=parsed.get("skills", []),
            candidate_experience=_format_experience(parsed.get("experience", [])),
            job_title=job.get("title", "Position"),
            company_name=job.get("company", "Company"),
            job_description=job.get("description", ""),
        )
    except Exception as e:
        log.error("Cover letter generation failed: %s", e, exc_info=True)
        cover_letter = f"Dear Hiring Manager,\n\nI am writing to express my interest in the {job.get('title', 'position')} position at {job.get('company', 'your company')}.\n\nSincerely,\n{parsed.get('name') or 'Applicant'}"

    # ── Generate downloadable files ──
    try:
        pdf_bytes = generate_pdf(tailored_text)
        docx_bytes = generate_docx(tailored_text)
        cover_pdf_bytes = generate_pdf(cover_letter)

        session_id = uuid.uuid4().hex

        # Upload tailored resume as PDF (resource_type="image" per Cloudinary docs)
        pdf_result = await upload_file(
            pdf_bytes,
            public_id=f"tailored/{session_id}/resume_pdf",  # No .pdf extension!
            resource_type="image",
        )
        # Upload tailored resume as DOCX (resource_type="raw" for non-PDF)
        docx_result = await upload_file(
            docx_bytes,
            public_id=f"tailored/{session_id}/resume_docx",
            resource_type="raw",
        )
        # Upload cover letter as PDF (resource_type="image" per Cloudinary docs)
        cover_pdf_result = await upload_file(
            cover_pdf_bytes,
            public_id=f"tailored/{session_id}/cover_letter",  # No .pdf extension!
            resource_type="image",
        )

        # Generate proper download URLs for Cloudinary delivery
        pdf_url = get_download_url(
            public_id=pdf_result["public_id"],
            resource_type="image",
            file_format="pdf",
        )
        docx_url = get_download_url(
            public_id=docx_result["public_id"],
            resource_type="raw",
            file_format=None,
        )
        cover_pdf_url = get_download_url(
            public_id=cover_pdf_result["public_id"],
            resource_type="image",
            file_format="pdf",
        )

        download_urls = DownloadUrls(
            pdf=pdf_url,
            docx=docx_url,
            cover_letter_pdf=cover_pdf_url,
        )

        # Save tailor session (fire-and-forget style)
        try:
            await save_tailor_session(db, {
                "resume_id": request.resume_id,
                "job_id": request.job_id,
                "original_text_preview": resume_text[:500],
                "tailored_text": tailored_text,
                "cover_letter": cover_letter,
                "cloudinary_pdf_url": pdf_url,
                "cloudinary_docx_url": docx_url,
                "cloudinary_cover_letter_url": cover_pdf_url,
            })
        except Exception as e:
            log.warning("Failed to save tailor session: %s", e)

    except Exception as e:
        log.error("File generation/upload failed: %s", e, exc_info=True)
        # Return text-only response without download URLs
        download_urls = DownloadUrls(
            pdf="",
            docx="",
            cover_letter_pdf="",
        )

    return ResumeTailorResponse(
        resume_id=request.resume_id,
        job_id=request.job_id,
        tailored_text=tailored_text,
        cover_letter=cover_letter,
        download_urls=download_urls,
    )


def _sanitize_parsed_data(data: dict) -> dict:
    """
    Deeply sanitize LLM-parsed resume data to comply with MongoDB schema validation.

    MongoDB schema requirements:
    - education[].year must be int (not null)
    - certifications[] items must be strings (not null)
    - skills[] items must be strings
    - languages[] items must be strings
    - email must match regex if present (omitted when empty)
    - phone is a plain string (omitted when empty)
    - name is a plain string
    """
    safe: dict = {
        "name": str(data.get("name") or ""),
    }

    # Education: filter out entries with null year, or default year to 0
    raw_education = data.get("education", []) or []
    safe_education = []
    for entry in raw_education:
        if not isinstance(entry, dict):
            continue
        year = entry.get("year")
        # year must be int; default 0 if missing/null, skip bogus values
        if year is not None and not isinstance(year, int):
            try:
                year = int(year)
            except (ValueError, TypeError):
                year = 0
        safe_entry = {
            "institution": str(entry.get("institution") or ""),
            "degree": str(entry.get("degree") or ""),
            "year": year if isinstance(year, int) else 0,
        }
        # Only include if at least one field has meaningful content
        if safe_entry["institution"] or safe_entry["degree"]:
            safe_education.append(safe_entry)
    safe["education"] = safe_education

    # Experience: filter out entries where all fields are empty
    raw_experience = data.get("experience", []) or []
    safe_experience = []
    for entry in raw_experience:
        if not isinstance(entry, dict):
            continue
        safe_entry = {
            "company": str(entry.get("company") or ""),
            "title": str(entry.get("title") or ""),
            "duration": str(entry.get("duration") or ""),
            "description": str(entry.get("description") or ""),
        }
        if any(v for v in safe_entry.values()):
            safe_experience.append(safe_entry)
    safe["experience"] = safe_experience

    # Skills, languages, certifications: filter out null/empty items
    for key in ("skills", "languages", "certifications"):
        raw_list = data.get(key, []) or []
        safe[key] = [str(item) for item in raw_list if item is not None and str(item).strip()]

    # Email: only include if non-empty (MongoDB schema has a regex pattern)
    raw_email = str(data.get("email") or "").strip()
    if raw_email:
        safe["email"] = raw_email

    # Phone: only include if non-empty
    raw_phone = str(data.get("phone") or "").strip()
    if raw_phone:
        safe["phone"] = raw_phone

    return safe


def _format_experience(experience: list) -> str:
    """Format experience list into a readable summary string."""
    if not experience:
        return ""
    parts = []
    for exp in experience:
        company = exp.get("company", "") or ""
        title = exp.get("title", "") or ""
        duration = exp.get("duration", "") or ""
        desc = exp.get("description", "") or ""
        line = f"{title} at {company} ({duration})"
        if desc:
            line += f": {desc}"
        parts.append(line)
    return "\n".join(parts)


@router.post("/download-from-url")
async def download_file_from_url(request: DownloadFromUrlRequest):
    """
    Download a file from Cloudinary by providing its Cloudinary delivery URL.

    The frontend receives Cloudinary URLs from the /tailor endpoint. This endpoint
    accepts one of those URLs in the request body, parses it to extract the
    public_id, resource_type, and format, then streams the file through our
    backend — bypassing the direct Cloudinary delivery (which may be blocked
    for PDFs on free accounts).

    Request body:
        { "url": "https://res.cloudinary.com/.../resume_pdf.pdf" }
    """
    try:
        parsed = parse_cloudinary_url(request.url)
        log.info("Parsed Cloudinary URL: %s", parsed)

        return StreamingResponse(
            stream_file(
                public_id=parsed["public_id"],
                resource_type=parsed["resource_type"],
                file_format=parsed["file_format"],
            ),
            media_type=(
                "application/pdf"
                if parsed["file_format"] == "pdf"
                else "application/octet-stream"
            ),
            headers={
                "Content-Disposition": f'attachment; filename="{parsed["filename"]}"'
            },
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        log.error("Download from URL failed: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Download failed: {str(e)}")
