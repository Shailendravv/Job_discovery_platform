"""Resume and tailor-session persistence.

Job/posting persistence lives in app/ingest/store.py (upsert_postings) and
app/ingest/query.py (list_postings, shortlist_postings) — this module no
longer touches job data directly. See app/api/v1/postings.py for the
posting-fetch-plus-tailoring-status pattern this module supports.
"""

import logging
from motor.motor_asyncio import AsyncIOMotorDatabase
from typing import Optional
from datetime import datetime, timezone
from bson import ObjectId

log = logging.getLogger(__name__)

async def save_resume(db: AsyncIOMotorDatabase, resume: dict) -> str:
    """Insert a new resume document. Returns the string ObjectId."""
    now = datetime.now(timezone.utc)
    resume["created_at"] = now
    resume["updated_at"] = now
    result = await db["resumes"].insert_one(resume)
    return str(result.inserted_id)


async def get_resume_by_id(db: AsyncIOMotorDatabase, resume_id: str) -> Optional[dict]:
    """Fetch a resume document by its ObjectId string."""
    try:
        oid = ObjectId(resume_id)
    except Exception:
        return None
    return await db["resumes"].find_one({"_id": oid})


async def update_resume_status(
    db: AsyncIOMotorDatabase, resume_id: str, status: str, error: Optional[str] = None
) -> bool:
    """Update processing status of a resume."""
    try:
        oid = ObjectId(resume_id)
    except Exception:
        return False
    update = {"$set": {"processing_status": status, "updated_at": datetime.now(timezone.utc)}}
    if error:
        update["$set"]["processing_error"] = error
    result = await db["resumes"].update_one({"_id": oid}, update)
    return result.modified_count > 0


async def save_tailor_session(db: AsyncIOMotorDatabase, session: dict) -> str:
    """Save a tailor session record. Returns the string ObjectId."""
    now = datetime.now(timezone.utc)
    session["created_at"] = now
    session["updated_at"] = now
    result = await db["tailor_sessions"].insert_one(session)
    return str(result.inserted_id)


async def get_latest_resume(db: AsyncIOMotorDatabase) -> Optional[dict]:
    """Fetch the most recently uploaded resume."""
    cursor = db["resumes"].find().sort("created_at", -1).limit(1)
    results = await cursor.to_list(1)
    return results[0] if results else None


async def get_tailor_session_for_job(db: AsyncIOMotorDatabase, job_id: str) -> Optional[dict]:
    """Fetch the latest tailor session for the given job_id."""
    cursor = db["tailor_sessions"].find({"job_id": job_id}).sort("created_at", -1).limit(1)
    results = await cursor.to_list(1)
    return results[0] if results else None