from motor.motor_asyncio import AsyncIOMotorDatabase
from typing import Optional

async def save_jobs(db: AsyncIOMotorDatabase, jobs: list[dict]) -> None:
    if jobs:
        await db["jobs"].insert_many(jobs)

async def get_job_by_id(db: AsyncIOMotorDatabase, job_id: str) -> Optional[dict]:
    from bson import ObjectId
    return await db["jobs"].find_one({"_id": ObjectId(job_id)})

async def save_resume(db: AsyncIOMotorDatabase, resume: dict) -> str:
    result = await db["resumes"].insert_one(resume)
    return str(result.inserted_id)

async def get_resume_by_id(db: AsyncIOMotorDatabase, resume_id: str) -> Optional[dict]:
    from bson import ObjectId
    return await db["resumes"].find_one({"_id": ObjectId(resume_id)})
