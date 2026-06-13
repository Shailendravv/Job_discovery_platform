#!/usr/bin/env python3
"""
Clear all data from the `jobs` and `resumes` collections.

This preserves the collections and their indexes — only documents are removed.
Useful for testing or resetting the database between search runs.

Usage:
    python scripts/clear_data.py --uri "mongodb://localhost:27017" --db jobapp

Dry-run (preview only, no deletion):
    python scripts/clear_data.py --uri "mongodb://localhost:27017" --db jobapp --dry-run

Skip confirmation:
    python scripts/clear_data.py --uri "mongodb://localhost:27017" --db jobapp --force
"""

import asyncio
import sys

try:
    from motor.motor_asyncio import AsyncIOMotorClient
except ImportError:
    print("Error: Required packages not installed.")
    print("Run: pip install pymongo motor")
    sys.exit(1)


async def count_documents(db, collection_name: str) -> int:
    """Count documents in a collection."""
    return await db[collection_name].count_documents({})


async def clear_collection(db, collection_name: str, dry_run: bool = False) -> int:
    """Delete all documents from a collection. Returns the count of deleted docs."""
    count = await count_documents(db, collection_name)

    if count == 0:
        print(f"  ℹ️  {collection_name}: already empty (0 documents)")
        return 0

    if dry_run:
        print(f"  🗑️  {collection_name}: would delete {count} document(s) (skipped — dry run)")
        return count

    result = await db[collection_name].delete_many({})
    deleted = result.deleted_count
    print(f"  ✅ {collection_name}: deleted {deleted} document(s)")
    return deleted


async def clear_all(uri: str, db_name: str, dry_run: bool = False, force: bool = False):
    """Clear jobs and resumes collections."""
    client = AsyncIOMotorClient(uri)
    db = client[db_name]

    try:
        print(f"\n{'=' * 56}")
        print(f"  Clear Data — Database: {db_name}")
        print(f"{'=' * 56}\n")

        if dry_run:
            print("🔍 DRY RUN MODE — no data will be deleted\n")

        # Count current documents
        jobs_count = await count_documents(db, "jobs")
        resumes_count = await count_documents(db, "resumes")

        print(f"Current document counts:")
        print(f"  jobs:    {jobs_count}")
        print(f"  resumes: {resumes_count}")
        print()

        if jobs_count == 0 and resumes_count == 0:
            print("Both collections are already empty. Nothing to do.\n")
            return

        # Confirm unless --force
        if not dry_run and not force:
            print(f"This will permanently delete ALL {jobs_count + resumes_count} document(s)")
            print(f"from the 'jobs' and 'resumes' collections in '{db_name}'.")
            print("Collections and indexes will be preserved.")
            print()
            response = input("Are you sure? Type 'yes' to continue: ").strip().lower()
            if response != "yes":
                print("\n❌ Aborted by user.\n")
                return
            print()

        # Clear collections
        total = 0
        total += await clear_collection(db, "jobs", dry_run)
        total += await clear_collection(db, "resumes", dry_run)

        print(f"\n{'─' * 56}")
        if dry_run:
            print(f"🔍 Dry run complete — would delete {total} document(s) total.")
            print("   Run without --dry-run to actually delete.")
        else:
            print(f"✅ Done! Deleted {total} document(s) across both collections.")
            print("   Collections and indexes are intact.")
        print()

    finally:
        client.close()


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Clear all documents from jobs and resumes collections",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--uri", required=True, help="MongoDB connection URI")
    parser.add_argument("--db", default="jobapp", help="Database name (default: jobapp)")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be deleted without actually deleting",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Skip confirmation prompt",
    )

    args = parser.parse_args()
    asyncio.run(clear_all(args.uri, args.db, dry_run=args.dry_run, force=args.force))
