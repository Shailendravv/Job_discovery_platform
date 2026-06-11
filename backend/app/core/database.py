import logging
from motor.motor_asyncio import AsyncIOMotorClient
from app.core.config import settings

client: AsyncIOMotorClient = None
log = logging.getLogger(__name__)

def get_database():
    db_name = settings.MONGODB_URI.rsplit("/", 1)[-1].split("?")[0] or "jobapp"
    return client[db_name]

async def connect_db():
    global client
    log.info("Connecting to MongoDB: %s", settings.MONGODB_URI)
    try:
        client = AsyncIOMotorClient(settings.MONGODB_URI)
        # Verify the connection by pinging the admin database
        await client.admin.command("ping")
        log.info("Successfully connected to MongoDB")
    except Exception as e:
        log.error("Failed to connect to MongoDB: %s", e)
        raise

async def close_db():
    global client
    if client:
        client.close()
        log.info("MongoDB connection closed")
