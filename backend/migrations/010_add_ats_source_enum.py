#!/usr/bin/env python3
"""
Migration 010: Add 'ashby' and 'workday' to jobs.source enum

Updates the jobs collection JSON schema validator to include the new
ATS provider source values 'ashby' and 'workday' in the source enum.

The enum currently allows:
    searxng, linkedin, indeed, glassdoor, greenhouse, lever, unknown

The Ashby and Workday providers were added after the initial schema was
created, but their source values were never added to the DB validator,
causing every job from those providers to fail with:
    Document failed validation (value was not found in enum)

Run with:
    python -m migrations.010_add_ats_source_enum --uri "..." --db jobapp
"""

import asyncio
from datetime import datetime
from typing import Any

try:
    from motor.motor_asyncio import AsyncIOMotorClient
    from pymongo.errors import PyMongoError
except ImportError:
    print("Error: Required packages not installed.")
    print("Run: pip install pymongo motor")
    exit(1)


UPDATED_SOURCE_ENUM = [
    "searxng", "linkedin", "indeed", "glassdoor",
    "greenhouse", "lever", "ashby", "workday", "unknown",
]


class Migration010:
    """Add ashby and workday to jobs.source enum."""
    name = "010_add_ats_source_enum"
    version = 10

    async def run(self, db):
        print(f"\n╔════════════════════════════════════════════════════════════════╗")
        print(f"║  Migration 010: Add ashby & workday to jobs.source enum       ║")
        print(f"╚════════════════════════════════════════════════════════════════╝\n")

        # Step 1: Get current validator
        print("Step 1: Fetching current jobs collection validator...")
        try:
            cmd_result = await db.command({"listCollections": 1, "filter": {"name": "jobs"}})
            cursor = cmd_result.get("cursor", {})
            collections = cursor.get("firstBatch", [])
            if not collections:
                print("  ✗ Jobs collection not found!")
                return
            jobs_info = collections[0]
            current_options = jobs_info.get("options", {})
            current_validator = current_options.get("validator", {})
            print("  ✓ Current validator retrieved")
        except Exception as e:
            print(f"  ✗ Failed to get collection info: {e}")
            return

        # Step 2: Update validator to add new source enum values
        print("\nStep 2: Adding ashby and workday to source enum...")
        updated_validator = current_validator.copy()

        if "$jsonSchema" not in updated_validator:
            print("  ✗ Current validator doesn't have $jsonSchema — unexpected!")
            return

        schema = updated_validator["$jsonSchema"]
        if "properties" not in schema or "source" not in schema["properties"]:
            print("  ✗ Current validator missing source property — unexpected!")
            return

        source_prop = schema["properties"]["source"]
        if "enum" not in source_prop:
            print("  ✗ Current source property has no enum — unexpected!")
            return

        old_enum = source_prop["enum"]
        print(f"    Old enum: {old_enum}")
        source_prop["enum"] = UPDATED_SOURCE_ENUM
        print(f"    New enum: {UPDATED_SOURCE_ENUM}")

        # Step 3: Apply the updated validator
        try:
            await db.command({
                "collMod": "jobs",
                "validator": updated_validator,
                "validationLevel": "moderate",
                "validationAction": "error"
            })
            print("  ✓ Validator updated successfully with ashby and workday")
        except Exception as e:
            print(f"  ✗ Failed to update validator: {e}")
            return

        # Record migration
        await self.record_migration(db)

        print(f"\n╔════════════════════════════════════════════════════════════════╗")
        print(f"║  Migration 010 Complete                                       ║")
        print(f"╚════════════════════════════════════════════════════════════════╝\n")
        print("Summary:")
        print("  ✅ Added 'ashby' and 'workday' to jobs.source enum")

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
        print(f"\n╔════════════════════════════════════════════════════════════════╗")
        print(f"║  Migration 010: Add ashby & workday to jobs.source enum       ║")
        print(f"╚════════════════════════════════════════════════════════════════╝\n")
        print(f"Database: {db_name}\n")

        migration = Migration010()
        await migration.run(db)

    finally:
        client.close()


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Migration 010: Add ashby & workday to jobs.source enum")
    parser.add_argument("--uri", required=True, help="MongoDB connection URI")
    parser.add_argument("--db", default="jobapp", help="Database name")

    args = parser.parse_args()
    asyncio.run(run(args.uri, args.db))
