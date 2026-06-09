import logging
from fastapi import FastAPI
from app.core.database import connect_db, close_db
from app.api.v1 import jobs, resumes
from app.core.config import settings

log_level = getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO)
logging.basicConfig(
    level=log_level,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

app = FastAPI(title="Job App API")

app.include_router(jobs.router, prefix="/api/v1/jobs", tags=["jobs"])
app.include_router(resumes.router, prefix="/api/v1/resumes", tags=["resumes"])


@app.on_event("startup")
async def startup():
    await connect_db()
    from app.core.config import settings
    log = logging.getLogger("startup")
    log.info("=== Search Provider Config ===")
    log.info("  SEARXNG_ENABLED            : %r", settings.SEARXNG_ENABLED)
    log.info("  LINKEDIN_GUEST_API_ENABLED : %r", settings.LINKEDIN_GUEST_API_ENABLED)
    log.info("  LINKEDIN_GUEST_API_LOCATION: %r", settings.LINKEDIN_GUEST_API_LOCATION)
    log.info("==============================")


@app.on_event("shutdown")
async def shutdown():
    await close_db()


@app.get("/health")
async def health():
    return {"status": "ok"}
