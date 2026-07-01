#!/usr/bin/env python3
"""
Migration 007: Add Job Search Indexes

Creates indexes needed for job persistence and retrieval:
- Unique index on url for upsert operations
- Compound text index for full-text search

Run with:
    python -m migrations.007_add_job_search_indexes --uri "..." --db jobapp
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


class Migration007:
    """Add search indexes to jobs collection."""
    name = "007_add_job_search_indexes"
    version = 7

    async def run(self, db):
        print(f"\n╔════════════════════════════════════════════════════════════════╗")
        print(f"║  Migration 007: Add Job Search Indexes                        ║")
        print(f"╚════════════════════════════════════════════════════════════════╝\n")

        # 1. Create unique index on url
        print("Step 1: Creating unique index on 'url'...")
        try:
            await db.jobs.create_index(
                "url",
                unique=True,
                name="idx_jobs_url_unique",
                background=True  # Non-blocking for existing data
            )
            print("  ✓ Created unique index on url")
        except PyMongoError as e:
            if e.code == 85:  # IndexOptionsConflict (already exists)
                print("  ⚡ Index already exists: idx_jobs_url_unique")
            else:
                print(f"  ✗ Error: {e}")
                raise

        # 2. Create compound text index
        print("\nStep 2: Creating compound text index...")
        try:
            await db.jobs.create_index(
                [("title", "text"), ("description", "text"), ("skills", "text")],
                name="idx_jobs_text_search",
                default_language="english",
                background=True
            )
            print("  ✓ Created text index on title, description, skills")
        except PyMongoError as e:
            if e.code == 85:
                print("  ⚡ Index already exists: idx_jobs_text_search")
            else:
                print(f"  ✗ Error: {e}")
                raise

        # Record migration
        await self.record_migration(db)

        print(f"\n╔════════════════════════════════════════════════════════════════╗")
        print(f"║  Migration 007 Complete                                       ║")
        print(f"╚════════════════════════════════════════════════════════════════╝\n")

    async def record_migration(self, db):
        """Record this migration."""
        now = datetime.utcnow()
        try:
            await db["_migrations"].insert_one({
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
        migration = Migration007()
        await migration.run(db)
    finally:
        client.close()


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Migration 007: Add Job Search Indexes")
    parser.add_argument("--uri", required=True, help="MongoDB connection URI")
    parser.add_argument("--db", default="jobapp", help="Database name")

    args = parser.parse_args()
    asyncio.run(run(args.uri, args.db))
