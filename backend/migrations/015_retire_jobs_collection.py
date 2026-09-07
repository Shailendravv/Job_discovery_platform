#!/usr/bin/env python3
"""
Migration 015: Retire the legacy 'jobs' collection + add postings.posted_at index

Part of the cutover from the old "Deep Search Discovery" pipeline
(SearXNG/LinkedIn/browser scraping -> app/services/db_service.save_jobs ->
'jobs') to the ATS ingest pipeline (app/ingest/runner.run_ingest ->
'postings'). See PLAN.md and document/Claude_web_plan.md.

'jobs' is the collection whose $jsonSchema source enum (migration 010)
never grew to include 'workable'/'smartrecruiters'/'recruitee' (milestone
5) -- every document from those three providers was silently rejected at
write time, and app/services/db_service.py's exception handling reported
"0 saved" even when other documents in the same batch succeeded. The old
pipeline (app/agents/job_workflow.py, ats_workflow.py, search_provider.py,
the MCP search/browse servers) is being deleted in the same branch, so
nothing will read or write 'jobs' after this migration.

The 20 documents in 'jobs' at migration time are stale scrape output from
a single run (2026-09-07T05:40:15Z) with no lasting value -- see
scratchpad/jobs_collection_backup.json (outside the repo) for a full dump
taken immediately before this migration ran, kept only as a safety net.

Also adds the postings.posted_at index needed by the new
GET /api/v1/postings endpoint ("200 latest" query, sorted posted_at desc)
-- migration 012 indexed first_seen_at but not posted_at.

Run with:
    python -m migrations.015_retire_jobs_collection --uri "..." --db jobapp
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


class Migration015:
    """Drop the legacy 'jobs' collection; index postings.posted_at."""
    name = "015_retire_jobs_collection"
    version = 15

    async def run(self, db):
        print("\n" + "=" * 68)
        print("  Migration 015: Retire 'jobs' collection + index posted_at")
        print("=" * 68 + "\n")

        # Step 1: Drop 'jobs' (and its validator) if present.
        existing = await db.list_collection_names(filter={"name": "jobs"})
        if existing:
            count = await db.jobs.count_documents({})
            print(f"Step 1: Dropping 'jobs' collection ({count} documents)...")
            try:
                await db.drop_collection("jobs")
                print("  \u2713 Dropped collection: jobs")
            except PyMongoError as e:
                print(f"  \u2717 Failed to drop jobs: {e}")
                raise
        else:
            print("Step 1: 'jobs' collection does not exist -- nothing to drop.")

        # Step 2: Index postings.posted_at (descending) for the
        # "200 latest" GET /api/v1/postings query.
        print("\nStep 2: Creating index on postings.posted_at...")
        try:
            await db.postings.create_index(
                [("posted_at", -1)], name="idx_postings_posted_at", background=True
            )
            print("  \u2713 Created index: idx_postings_posted_at")
        except PyMongoError as e:
            if e.code == 85:  # IndexOptionsConflict
                print("  \u26a1 Index already exists: idx_postings_posted_at")
            else:
                print(f"  \u2717 Error creating idx_postings_posted_at: {e}")
                raise

        await self.record_migration(db)

        print("\n" + "=" * 68)
        print("  Migration 015 Complete")
        print("=" * 68)
        print("\nSummary:")
        print("  \u2705 Dropped legacy 'jobs' collection")
        print("  \u2705 Indexed postings.posted_at (desc)")

    async def record_migration(self, db):
        now = datetime.utcnow()
        try:
            await db["_migrations"].insert_one({
                "migration": self.name,
                "version": self.version,
                "applied_at": now,
                "checksum": "COMPUTED_DURING_DEPLOYMENT",
            })
        except PyMongoError as e:
            if e.code != 11000:
                raise


async def run(uri: str, db_name: str = "jobapp"):
    client = AsyncIOMotorClient(uri)
    db = client[db_name]
    try:
        migration = Migration015()
        await migration.run(db)
    finally:
        client.close()


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Migration 015: Retire 'jobs' collection + index postings.posted_at"
    )
    parser.add_argument("--uri", required=True, help="MongoDB connection URI")
    parser.add_argument("--db", default="jobapp", help="Database name")

    args = parser.parse_args()
    asyncio.run(run(args.uri, args.db))
