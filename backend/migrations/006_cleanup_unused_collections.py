#!/usr/bin/env python3
"""
Migration 006: Cleanup Unused Collections

Removes collections that are not currently needed by the application.
This is a destructive migration - make sure you have backups if needed.

Collections removed:
- users (user auth not implemented)
- applications (application tracking not implemented)
- companies (redundant with job data)
- searchHistory (search history tracking not implemented)
- jobMatches (resume matching not implemented)
- skills (taxonomy not currently used - skills stored in jobs)
- change_stream_checkpoints (change streams not implemented)
- change_stream_configs (change streams not implemented)
- jobs_company_summary (materialized view not used)

Run with:
    python -m migrations.006_cleanup_unused_collections --uri "..." --db jobapp
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


# Collections to drop - these are NOT used by current application
UNUSED_COLLECTIONS = [
    "users",
    "applications",
    "companies",
    "searchHistory",
    "jobMatches",
    "skills",
    "change_stream_checkpoints",
    "change_stream_configs",
    "jobs_company_summary",
]

# Collections that SHOULD NOT be dropped (for safety)
PROTECTED_COLLECTIONS = [
    "jobs",
    "resumes",
    "_migrations",
]


class Migration006:
    """Cleanup unused collections."""
    name = "006_cleanup_unused_collections"
    version = 6

    async def run(self, db):
        print(f"\n╔════════════════════════════════════════════════════════════════╗")
        print(f"║  Migration 006: Cleanup Unused Collections                    ║")
        print(f"╚════════════════════════════════════════════════════════════════╝\n")

        print("This migration will DROP the following collections:")
        for coll in UNUSED_COLLECTIONS:
            print(f"  - {coll}")

        print("\nThese collections are NOT currently used by the application.")
        print("If you need them in the future, you'll need to recreate them.\n")

        # List existing collections first
        print("Current collections in database:")
        collections = await db.list_collection_names()
        for coll in sorted(collections):
            marker = "🔒" if coll in PROTECTED_COLLECTIONS else "🗑️" if coll in UNUSED_COLLECTIONS else "  "
            print(f"  {marker} {coll}")

        # Confirm with user if running as script
        if __name__ == "__main__":
            response = input("\n⚠️  WARNING: This will permanently delete data in unused collections.\nDo you want to continue? (yes/no): ")
            if response.lower() not in ["yes", "y"]:
                print("Migration cancelled.")
                return

        # Drop unused collections
        print("\nDropping unused collections...")
        dropped_count = 0
        skipped_count = 0

        for collection_name in UNUSED_COLLECTIONS:
            try:
                # Check if collection exists
                if collection_name in collections:
                    await db[collection_name].drop()
                    print(f"  ✓ Dropped collection: {collection_name}")
                    dropped_count += 1
                else:
                    print(f"  ⊘ Collection does not exist: {collection_name}")
                    skipped_count += 1
            except PyMongoError as e:
                print(f"  ✗ Error dropping {collection_name}: {e}")

        # Show remaining collections
        print("\nRemaining collections:")
        remaining = await db.list_collection_names()
        for coll in sorted(remaining):
            marker = "🔒" if coll in PROTECTED_COLLECTIONS else "  "
            print(f"  {marker} {coll}")

        # Record migration
        await self.record_migration(db, dropped_count, skipped_count)

        print(f"\n╔════════════════════════════════════════════════════════════════╗")
        print(f"║  Migration 006 Complete                                       ║")
        print(f"║  Dropped: {dropped_count} collections                         ║")
        print(f"║  Skipped: {skipped_count} collections (did not exist)        ║")
        print(f"╚════════════════════════════════════════════════════════════════╝\n")

        print("Protected collections (kept):")
        for coll in PROTECTED_COLLECTIONS:
            print(f"  🔒 {coll}")

        print("\nNext steps:")
        print("  1. Consider removing unused migration files (003, 004, 005)")
        print("  2. Update documentation to reflect minimal schema")
        print("  3. If you need any of these collections later, you'll need to recreate them")

    async def record_migration(self, db, dropped_count, skipped_count):
        """Record this migration."""
        now = datetime.utcnow()
        try:
            await db["_migrations"].insert_one({
                "migration": self.name,
                "version": self.version,
                "applied_at": now,
                "checksum": "COMPUTED_DURING_DEPLOYMENT",
                "dropped_count": dropped_count,
                "skipped_count": skipped_count,
                "dropped_collections": UNUSED_COLLECTIONS
            })
        except PyMongoError as e:
            if e.code != 11000:  # Not duplicate
                raise


async def run(uri: str, db_name: str = "jobapp"):
    """Run this migration."""
    client = AsyncIOMotorClient(uri)
    db = client[db_name]

    try:
        print(f"\n╔════════════════════════════════════════════════════════════════╗")
        print(f"║  Migration 006: Cleanup Unused Collections                    ║")
        print(f"╚════════════════════════════════════════════════════════════════╝\n")
        print(f"Database: {db_name}\n")

        migration = Migration006()
        await migration.run(db)

    finally:
        client.close()


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Migration 006: Cleanup Unused Collections")
    parser.add_argument("--uri", required=True, help="MongoDB connection URI")
    parser.add_argument("--db", default="jobapp", help="Database name")

    args = parser.parse_args()
    asyncio.run(run(args.uri, args.db))
