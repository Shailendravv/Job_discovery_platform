from fastapi import APIRouter, Depends, UploadFile, File
from app.models.resume import ResumeUploadResponse, ResumeTailorRequest, ResumeTailorResponse
from app.api.deps import get_db

router = APIRouter()

@router.post("/upload", response_model=ResumeUploadResponse)
async def upload_resume(file: UploadFile = File(...), db=Depends(get_db)):
    # TODO: extract text via PDF_service, store in MongoDB
    return ResumeUploadResponse(resume_id="placeholder", extracted_text="")

@router.post("/tailor", response_model=ResumeTailorResponse)
async def tailor_resume(request: ResumeTailorRequest, db=Depends(get_db)):
    # TODO: invoke LangGraph tailor_resume node
    return ResumeTailorResponse(resume_id=request.resume_id, tailored_text="")
