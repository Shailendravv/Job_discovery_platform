import logging
from fastapi import FastAPI
from app.core.database import connect_db, close_db
from app.api.v1 import jobs, resumes

logging.basicConfig(
    # level=logging.DEBUG,
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

app = FastAPI(title="Job App API")

app.include_router(jobs.router, prefix="/api/v1/jobs", tags=["jobs"])
app.include_router(resumes.router, prefix="/api/v1/resumes", tags=["resumes"])


@app.on_event("startup")
async def startup():
    await connect_db()


@app.on_event("shutdown")
async def shutdown():
    await close_db()


@app.get("/health")
async def health():
    return {"status": "ok"}
