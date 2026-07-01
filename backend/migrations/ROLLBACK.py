#!/usr/bin/env python3
"""
Migration ROLLBACK: Complete rollback script

WARNING: This DELETES ALL DATA in the jobapp database!

Run with:
    python -m migrations.rollback --uri "..." --db jobapp --confirm YES
"""

import asyncio
import sys

try:
    from motor.motor_asyncio import AsyncIOMotorClient
    from pymongo.errors import PyMongoError
except ImportError:
    print("Error: Required packages not installed.")
    print("Run: pip install pymongo motor")
    sys.exit(1)


COLLECTIONS_TO_DROP = [
    "jobMatches",
    "searchHistory",
    "skills",
    "companies",
    "applications",
    "users",
    "resumes",
    "jobs",
    "jobs_company_summary",
    "change_stream_checkpoints",
    "change_stream_configs",
    "_migrations"
]


class Rollback:
    """Rollback all migrations."""

    name = "ROLLBACK"
    confirmation_required = True

    async def run(self, db, confirmed: bool = False):
        print(f"\n╔════════════════════════════════════════════════════════════════╗")
        print(f"║  ⚠️  ROLLBACK - DESTRUCTIVE OPERATION                         ║")
        print(f"║  This will DELETE all application collections                  ║")
        print(f"╠════════════════════════════════════════════════════════════════╣")
        print(f"║  Collections to be dropped:                                   ║")

        for coll in COLLECTIONS_TO_DROP:
            print(f"║    - {coll:<50} ║")

        print(f"╚════════════════════════════════════════════════════════════════╝\n")

        if not confirmed:
            print("⚠ Confirmation required!")
            print("   Run with: python -m migrations.rollback --uri ... --confirm YES")
            return False

        print("⏳ Starting rollback in 3 seconds...")
        await asyncio.sleep(3)

        dropped_count = 0
        error_count = 0

        for coll_name in COLLECTIONS_TO_DROP:
            try:
                # Check if collection exists
                collections = await db.list_collection_names()
                if coll_name not in collections:
                    print(f"  ○ Not found: {coll_name}")
                    continue

                await db[coll_name].drop()
                print(f"  ✓ Dropped: {coll_name}")
                dropped_count += 1
            except PyMongoError as e:
                print(f"  ✗ Error dropping {coll_name}: {e}")
                error_count += 1

        # Optionally drop entire database
        print(f"\n╔════════════════════════════════════════════════════════════════╗")
        print(f"║  Rollback Complete                                            ║")
        print(f"║  Collections dropped: {dropped_count}                                    ║")
        print(f"║  Errors: {error_count}                                               ║")
        print(f"╚════════════════════════════════════════════════════════════════╝\n")

        print("To recreate the database, run migration 001:")
        print("  python -m migrations.001_initial_schema --uri ... --db jobapp\n")

        return True

    async def drop_single_collection(self, db, collection_name: str):
        """Drop just one collection (partial rollback)."""
        try:
            await db[collection_name].drop()
            print(f"  ✓ Dropped collection: {collection_name}")
        except PyMongoError as e:
            if e.code == 26:  # NamespaceNotFound
                print(f"  ○ Collection not found: {collection_name}")
            else:
                raise


async def run(uri: str, db_name: str = "jobapp", confirm: str = None):
    """Run rollback."""
    client = AsyncIOMotorClient(uri)
    db = client[db_name]

    try:
        rollback = Rollback()
        confirmed = confirm == "YES"
        success = await rollback.run(db, confirmed)
        if not success:
            sys.exit(1)
    finally:
        client.close()


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Rollback all migrations")
    parser.add_argument("--uri", required=True, help="MongoDB connection URI")
    parser.add_argument("--db", default="jobapp", help="Database name")
    parser.add_argument("--confirm", help="Type YES to confirm rollback")

    args = parser.parse_args()
    asyncio.run(run(args.uri, args.db, args.confirm))
