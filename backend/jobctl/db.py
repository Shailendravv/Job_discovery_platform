"""Short-lived DB connection for a single jobctl invocation.

Reuses ``app.core.database`` / ``app.core.config`` rather than duplicating
connection logic — jobctl and the FastAPI app share one MongoDB.
"""

from contextlib import asynccontextmanager

from motor.motor_asyncio import AsyncIOMotorDatabase

from app.core.database import close_db, connect_db, get_database


@asynccontextmanager
async def db_session():
    await connect_db()
    try:
        db: AsyncIOMotorDatabase = get_database()
        yield db
    finally:
        await close_db()
