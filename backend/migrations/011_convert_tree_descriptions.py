#!/usr/bin/env python3
"""
Migration 011: Convert accessibility tree descriptions to HTML

Existing job descriptions may contain raw accessibility-tree snapshots
(e.g. "- main:\n  - heading 'title' [level=1]\n  ...") stored as plain text.

This migration converts any description that looks like a tree format
into clean HTML using the tree_to_html converter.

Run with:
    python -m migrations.011_convert_tree_descriptions --uri "..." --db jobapp
"""

import asyncio
import re
import sys
from datetime import datetime

try:
    from motor.motor_asyncio import AsyncIOMotorClient
    from pymongo.errors import PyMongoError
except ImportError:
    print("Error: Required packages not installed.")
    print("Run: pip install pymongo motor")
    sys.exit(1)

sys.path.insert(0, ".")


def _looks_like_tree(text: str) -> bool:
    """Check if text is an accessibility tree snapshot."""
    if not text or not isinstance(text, str):
        return False
    lines = [l for l in text.split("\n") if l.strip()]
    if not lines:
        return False
    first = lines[0].lstrip(" ")
    return first.startswith("- ")


class Migration011:
    """Convert accessibility tree descriptions to HTML."""
    name = "011_convert_tree_descriptions"
    version = 11

    async def run(self, db):
        print(f"\n╔════════════════════════════════════════════════════════════════╗")
        print(f"║  Migration 011: Convert tree descriptions to HTML             ║")
        print(f"╚════════════════════════════════════════════════════════════════╝\n")

        # Import the converter
        try:
            from app.utils.accessibility_tree_to_html import tree_to_html
            print("  ✓ Converter imported")
        except ImportError as e:
            print(f"  ✗ Failed to import converter: {e}")
            print("  Make sure you are running from the backend/ directory")
            return

        # Find all jobs with tree-format descriptions
        print("\nStep 1: Finding jobs with tree-format descriptions...")
        cursor = db.jobs.find(
            {"description": {"$regex": r"^\s*- ", "$options": "m"}},
            {"_id": 1, "description": 1},
        )
        jobs = await cursor.to_list(length=None)
        total = len(jobs)
        print(f"  Found {total} jobs with tree-format descriptions")

        if total == 0:
            print("\n✓ No jobs need conversion — all descriptions are clean.")
            await self.record_migration(db)
            return

        # Convert descriptions
        print(f"\nStep 2: Converting {total} descriptions...")
        updated = 0
        errors = 0
        batch = []
        BATCH_SIZE = 50

        for job in jobs:
            try:
                original = job.get("description", "")
                converted = tree_to_html(original)
                if converted != original:
                    batch.append(converted)
                    # Update in place
                    result = await db.jobs.update_one(
                        {"_id": job["_id"]},
                        {"$set": {"description": converted}}
                    )
                    if result.modified_count > 0:
                        updated += 1
            except Exception as e:
                print(f"  ✗ Error converting job {job['_id']}: {e}")
                errors += 1

            if len(batch) >= BATCH_SIZE:
                print(f"  ... {updated} converted so far")
                batch = []

        # Flush remaining
        if batch:
            pass

        print(f"\n  ✓ Converted: {updated}")
        if errors:
            print(f"  ✗ Errors: {errors}")

        # Record migration
        await self.record_migration(db)

        print(f"\n╔════════════════════════════════════════════════════════════════╗")
        print(f"║  Migration 011 Complete                                       ║")
        print(f"╚════════════════════════════════════════════════════════════════╝\n")
        print("Summary:")
        print(f"  ✅ {updated} job descriptions converted from tree format to HTML")
        if errors:
            print(f"  ⚠  {errors} jobs had errors (check logs above)")

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
        print(f"║  Migration 011: Convert tree descriptions to HTML             ║")
        print(f"╚════════════════════════════════════════════════════════════════╝\n")
        print(f"Database: {db_name}\n")

        migration = Migration011()
        await migration.run(db)

    finally:
        client.close()


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Migration 011: Convert tree descriptions to HTML"
    )
    parser.add_argument("--uri", required=True, help="MongoDB connection URI")
    parser.add_argument("--db", default="jobapp", help="Database name")

    args = parser.parse_args()
    asyncio.run(run(args.uri, args.db))
