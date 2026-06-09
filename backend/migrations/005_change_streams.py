#!/usr/bin/env python3
"""
Migration 005: Change Streams Configuration

Sets up change stream configuration collections and documentation.

Note: Change streams require MongoDB replica set (enabled on Atlas automatically).

Run with:
    python -m migrations.005_change_streams --uri "..." --db jobapp
"""

import asyncio
from datetime import datetime

try:
    from motor.motor_asyncio import AsyncIOMotorClient
    from pymongo.errors import PyMongoError
except ImportError:
    print("Error: Required packages not installed.")
    print("Run: pip install pymongo motor")
    exit(1)


CHANGE_STREAM_CONFIGS = [
    {
        "name": "job_creation_skills",
        "collection": "jobs",
        "pipeline": [{"$match": {"operationType": "insert"}}],
        "is_active": True,
        "worker_class": "JobCreationSkillsUpdater",
        "description": "Updates skill popularity counters when new jobs are inserted",
        "created_at": datetime.utcnow()
    },
    {
        "name": "application_status",
        "collection": "applications",
        "pipeline": [
            {
                "$match": {
                    "operationType": "update",
                    "updateDescription.updatedFields.status": {"$exists": True}
                }
            }
        ],
        "is_active": True,
        "worker_class": "ApplicationStatusNotifier",
        "description": "Sends notifications when application status changes",
        "created_at": datetime.utcnow()
    },
    {
        "name": "company_stats",
        "collection": "jobs",
        "pipeline": [
            {"$match": {"operationType": ["insert", "update", "delete"]}}
        ],
        "is_active": True,
        "worker_class": "CompanyStatsUpdater",
        "description": "Maintains company statistics incrementally",
        "created_at": datetime.utcnow()
    }
]


class Migration005:
    """Change streams configuration."""
    name = "005_change_streams"
    version = 5

    async def run(self, db):
        print(f"\n╔════════════════════════════════════════════════════════════════╗")
        print(f"║  Migration 005: Change Streams Configuration                 ║")
        print(f"╚════════════════════════════════════════════════════════════════╝\n")

        print("Change streams require a MongoDB replica set.")
        print("Atlas provides replica sets automatically.\n")

        # Step 1: Create checkpoint collection
        print("Step 1: Creating change_stream_checkpoints collection...")
        try:
            await db.create_collection("change_stream_checkpoints")
            await db.change_stream_checkpoints.create_index(
                [("_id", 1)],
                unique=True,
                name="idx_cs_checkpoint_id"
            )
            print("  ✓ Created checkpoint collection with index\n")
        except PyMongoError as e:
            if e.code == 48:  # NamespaceExists
                print("  ⚡ Collection already exists")
            else:
                raise

        # Step 2: Create configs collection
        print("Step 2: Creating change_stream_configs collection...")
        try:
            await db.create_collection("change_stream_configs")
            await db.change_stream_configs.create_index(
                [("name", 1)],
                unique=True,
                name="idx_cs_config_name"
            )
            await db.change_stream_configs.create_index(
                [("is_active", 1), ("name", 1)],
                name="idx_cs_config_active"
            )
            print("  ✓ Created configs collection with indexes")
        except PyMongoError as e:
            if e.code == 48:
                print("  ⚡ Collection already exists")
            else:
                raise

        # Step 3: Insert configuration documents
        print("\nStep 3: Inserting change stream configurations...")
        for config in CHANGE_STREAM_CONFIGS:
            try:
                await db.change_stream_configs.insert_one(config)
                print(f"  ✓ Config: {config['name']}")
            except PyMongoError as e:
                if e.code == 11000:  # Duplicate key
                    print(f"  ⚡ Config already exists: {config['name']}")
                else:
                    raise

        # Step 4: Print implementation example
        print("\n" + "="*60)
        print("IMPLEMENTATION GUIDE")
        print("="*60)
        print("""
To implement change stream workers in your FastAPI app:

1. Create a background task module (e.g., app/background/change_streams.py):

```python
import asyncio
import logging
from datetime import datetime
from motor.motor_asyncio import AsyncIOMotorClient

log = logging.getLogger(__name__)

class ChangeStreamWorker:
    def __init__(self, db):
        self.db = db
        self.running = False

    async def start(self):
        \"\"\"Start all active change streams.\"\"\"
        self.running = True
        configs = await self.db.change_stream_configs.find(
            {"is_active": True}
        ).to_list(None)

        tasks = [self._run_stream(config) for config in configs]
        await asyncio.gather(*tasks)

    async def _run_stream(self, config: dict):
        \"\"\"Run a single change stream.\"\"\"
        collection = self.db[config["collection"]]
        pipeline = config.get("pipeline", [])

        log.info(f"Starting change stream: {config['name']}")

        try:
            async with collection.watch(
                pipeline=pipeline,
                full_document="updateLookup",
                max_await_time_ms=5000
            ) as stream:
                async for change in stream:
                    try:
                        await self._handle_change(config["name"], change)
                    except Exception as e:
                        log.error(f"Error in {config['name']}: {e}")
        except Exception as e:
            log.error(f"Change stream {config['name']} failed: {e}")
            if self.running:
                # Reconnect with delay
                await asyncio.sleep(5)
                await self._run_stream(config)

    async def _handle_change(self, stream_name: str, change: dict):
        \"\"\"Route to appropriate handler.\"\"\"
        handlers = {
            "job_creation_skills": self._handle_job_skills,
            "application_status": self._handle_app_status,
            "company_stats": self._handle_company_stats
        }

        handler = handlers.get(stream_name)
        if handler:
            await handler(change)

    async def _handle_job_skills(self, change: dict):
        \"\"\"Update skill popularity when a new job is inserted.\"\"\"
        job = change["fullDocument"]
        skills = job.get("skills", [])

        for skill in skills:
            normalized = skill.lower().strip()
            await self.db.skills.update_one(
                {"name_normalized": normalized},
                {"$inc": {"popularity": 1}},
                upsert=True
            )

    async def _handle_app_status(self, change: dict):
        \"\"\"Send notification on application status change.\"\"\"
        app = change["fullDocument"]
        # Send notification (implement based on your notification system)
        log.info(f"Application {app['_id']} status changed to {app['status']}")

    async def _handle_company_stats(self, change: dict):
        \"\"\"Update company stats incrementally.\"\"\"
        job = change["fullDocument"]
        company = job.get("company")

        if company:
            normalized = company.lower().strip()
            inc = 1 if change["operationType"] == "insert" else -1
            await self.db.companies.update_one(
                {"name_normalized": normalized},
                {
                    "$inc": {"job_count": inc},
                    "$set": {"updated_at": datetime.utcnow()}
                },
                upsert=True
            )

# In your main.py, add:
#
# @app.on_event("startup")
# async def start_change_streams():
#     db = Database.db  # or however you access your db
#     worker = ChangeStreamWorker(db)
#     asyncio.create_task(worker.start())
""")

        print("="*60)

        # Record migration
        await self.record_migration(db)

        print(f"\n╔════════════════════════════════════════════════════════════════╗")
        print(f"║  Migration 005 Complete                                       ║")
        print(f"║  Change stream configs stored. Implement worker class.       ║")
        print(f"╚════════════════════════════════════════════════════════════════╝\n")

    async def record_migration(self, db):
        """Record this migration."""
        now = datetime.utcnow()
        try:
            await db._migrations.insert_one({
                "migration": self.name,
                "version": self.version,
                "applied_at": now,
                "checksum": "COMPUTED_DURING_DEPLOYMENT"
            })
        except PyMongoError as e:
            if e.code != 11000:
                raise


async def run(uri: str, db_name: str = "jobapp"):
    """Run this migration."""
    client = AsyncIOMotorClient(uri)
    db = client[db_name]

    try:
        migration = Migration005()
        await migration.run(db)
    finally:
        client.close()


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Migration 005: Change Streams Config")
    parser.add_argument("--uri", required=True, help="MongoDB connection URI")
    parser.add_argument("--db", default="jobapp", help="Database name")

    args = parser.parse_args()
    asyncio.run(run(args.uri, args.db))
