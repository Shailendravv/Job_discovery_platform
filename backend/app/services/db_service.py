import logging
from motor.motor_asyncio import AsyncIOMotorDatabase
from typing import Optional
from datetime import datetime, timezone
from bson import ObjectId
from pymongo import UpdateOne

log = logging.getLogger(__name__)

async def save_jobs(db: AsyncIOMotorDatabase, jobs: list[dict], search_query: str = None) -> int:
    if not jobs:
        return 0

    now = datetime.now(timezone.utc)
    operations = []

    for job in jobs:
        job_url = job.get("url")
        if job_url:
            filter_ = {"url": job_url}
        else:
            # No URL: skip to avoid duplicates
            continue

        # Sanitize document to satisfy validator
        # Required string fields must be non-empty
        if not job.get("title"):
            job["title"] = "No Title"
        if not job.get("company"):
            job["company"] = "Unknown"
        if not job.get("description"):
            job["description"] = "No description"
        # Skills list should not contain empty strings
        if "skills" in job and isinstance(job["skills"], list):
            job["skills"] = [s for s in job["skills"] if s and isinstance(s, str)]

        update_fields = {
            k: v for k, v in job.items()
            if k not in ["_id"] and v is not None
        }

        update = {
            "$set": update_fields,
            "$setOnInsert": {
                "created_at": now,
            }
        }
        update["$set"]["updated_at"] = now
        if search_query:
            update["$set"]["search_query"] = search_query

        operations.append(UpdateOne(filter_, update, upsert=True))

    if not operations:
        return 0

    try:
        result = await db.jobs.bulk_write(operations, ordered=False)
        return result.upserted_count + result.modified_count
    except Exception as e:
        log.error("Error in save_jobs bulk_write: %s", e, exc_info=True)
        return 0

async def get_jobs(
    db: AsyncIOMotorDatabase,
    page: int = 1,
    limit: int = 20,
    source: str = None,
    job_type: str = None,
    location: str = None,
    q: str = None,
    sort_by: str = "created_at",
    sort_order: int = -1  # -1 = desc, 1 = asc
) -> tuple[list[dict], int]:
    """
    Retrieve stored jobs with optional filters and full-text search.

    Returns:
        (jobs_list, total_count)
    """
    # Build match stage
    match = {}

    if source:
        match["source"] = source
    if job_type:
        match["job_type"] = job_type
    if location:
        match["location"] = {"$regex": location, "$options": "i"}

    # Full-text search overrides some behavior
    text_score_sort = False
    if q:
        match["$text"] = {"$search": q}
        text_score_sort = True

    # Pipeline for data
    pipeline = []

    if match:
        pipeline.append({"$match": match})

    if text_score_sort:
        # Add text score field; sort by score
        pipeline.append({"$addFields": {"score": {"$meta": "textScore"}}})
        sort_field = "score"
        sort_dir = -1  # Higher score first
    else:
        sort_field = sort_by
        sort_dir = sort_order

    pipeline.append({"$sort": {sort_field: sort_dir}})

    # Pagination
    skip = (page - 1) * limit
    pipeline.append({"$skip": skip})
    pipeline.append({"$limit": limit})

    # Execute data query
    jobs = await db.jobs.aggregate(pipeline).to_list(limit)

    # Count query (separate to avoid complexity)
    count_pipeline = []
    if match:
        count_pipeline.append({"$match": match})
    # No $sort or $skip/limit in count
    count_cursor = db.jobs.aggregate(count_pipeline + [{"$count": "total"}])
    count_result = await count_cursor.to_list(1)
    total_count = count_result[0]["total"] if count_result else 0

    return jobs, total_count

async def get_job_by_id(db: AsyncIOMotorDatabase, job_id: str) -> Optional[dict]:
    from bson import ObjectId
    return await db["jobs"].find_one({"_id": ObjectId(job_id)})

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