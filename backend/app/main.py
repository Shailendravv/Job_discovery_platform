import logging
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.core.database import connect_db, close_db
from app.api.v1 import postings, resumes
from app.core.config import settings
from app.services.cloudinary_service import configure_cloudinary

log_level = getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO)
logging.basicConfig(
    level=log_level,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

app = FastAPI(title="Job App API")

# CORS – allow the frontend dev server to call the API
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",  # Vite default
        "http://localhost:3000",
        "http://127.0.0.1:5173",
        "http://127.0.0.1:3000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(postings.router, prefix="/api/v1/postings", tags=["postings"])
app.include_router(resumes.router, prefix="/api/v1/resumes", tags=["resumes"])


@app.on_event("startup")
async def startup():
    await connect_db()

    log = logging.getLogger("startup")

    # Configure Cloudinary
    if (
        settings.CLOUDINARY_CLOUD_NAME
        and settings.CLOUDINARY_API_KEY
        and settings.CLOUDINARY_API_SECRET
    ):
        try:
            configure_cloudinary()
            log.info("  CLOUDINARY                  : configured")
        except Exception as e:
            log.warning("  CLOUDINARY                  : configuration failed — %s", e)
    else:
        log.warning(
            "  CLOUDINARY                  : not configured (set CLOUDINARY_* env vars)"
        )

    # Log LLM Provider Config — fixed Claude (Haiku) -> Ollama chain
    log.info("=== LLM Provider Config ===")
    log.info("  LLM_PROVIDER               : %s", settings.LLM_PROVIDER)
    log.info("  CLAUDE_MODEL                : %s", settings.CLAUDE_MODEL)
    log.info("  OLLAMA_BASE_URL            : %s (fallback)", settings.OLLAMA_BASE_URL)
    log.info("  OLLAMA_MODEL               : %s", settings.OLLAMA_MODEL)
    log.info("============================")


@app.on_event("shutdown")
async def shutdown():
    await close_db()


@app.get("/health")
async def health():
    return {"status": "ok"}
