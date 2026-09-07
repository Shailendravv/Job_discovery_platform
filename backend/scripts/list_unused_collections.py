#!/usr/bin/env python3
"""
Preview script: List collections that could be safely removed.

This script does NOT drop anything - it just shows what would be dropped
by migration 006_cleanup_unused_collections.

Usage:
    python scripts/list_unused_collections.py --uri "mongodb://..." --db jobapp
"""

import asyncio
import sys

try:
    from motor.motor_asyncio import AsyncIOMotorClient
except ImportError:
    print("Error: Required packages not installed.")
    print("Run: pip install pymongo motor")
    sys.exit(1)


# Collections that are NOT used by current application
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
    # Retired by migration 015_retire_jobs_collection.py — replaced by
    # "postings" (app/ingest/models.py Posting), a different schema.
    "jobs",
]

# Collections that are actively used
USED_COLLECTIONS = [
    "postings",
    "verdicts",
    "prefilter_runs",
    "ingest_runs",
    "resumes",
    "tailor_sessions",
    "_migrations",
]


async def list_collections(uri: str, db_name: str):
    """List all collections and mark which are used/unused."""
    client = AsyncIOMotorClient(uri)
    db = client[db_name]

    try:
        all_collections = await db.list_collection_names()

        print(f"\n╔════════════════════════════════════════════════════════════════╗")
        print(f"║  Collections Analysis - Database: {db_name:<25} ║")
        print(f"╚════════════════════════════════════════════════════════════════╝\n")

        print("USED COLLECTIONS (keep these):")
        print("  (These are actively referenced by application code)\n")
        for coll in sorted(USED_COLLECTIONS):
            status = "✓ EXISTS" if coll in all_collections else "⚠ MISSING"
            print(f"  {status:12} {coll}")

        print("\nUNUSED COLLECTIONS (safe to drop):")
        print("  (These are NOT referenced by current application code)\n")
        for coll in sorted(UNUSED_COLLECTIONS):
            status = "🗑️  EXISTS" if coll in all_collections else "⊘ absent"
            print(f"  {status:12} {coll}")

        print("\nOTHER COLLECTIONS (unknown - review manually):")
        unknown = [c for c in all_collections if c not in USED_COLLECTIONS + UNUSED_COLLECTIONS]
        if unknown:
            for coll in sorted(unknown):
                print(f"  ? {coll}")
        else:
            print("  (none)")

        # Summary
        used_existing = [c for c in USED_COLLECTIONS if c in all_collections]
        unused_existing = [c for c in UNUSED_COLLECTIONS if c in all_collections]

        print(f"\n═══════════════════════════════════════════════════════════════")
        print(f"Summary:")
        print(f"  Total collections: {len(all_collections)}")
        print(f"  Used (keep): {len(used_existing)}")
        print(f"  Unused (drop): {len(unused_existing)}")
        print(f"═══════════════════════════════════════════════════════════════")

        if unused_existing:
            print("\nTo drop unused collections, run:")
            print("  python migrations/006_cleanup_unused_collections.py --uri <your-uri> --db jobapp")

    finally:
        client.close()


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="List collections that could be removed")
    parser.add_argument("--uri", required=True, help="MongoDB connection URI")
    parser.add_argument("--db", default="jobapp", help="Database name")

    args = parser.parse_args()
    asyncio.run(list_collections(args.uri, args.db))
