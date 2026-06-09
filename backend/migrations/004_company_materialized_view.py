#!/usr/bin/env python3
"""
Migration 004: Company Materialized View

Creates jobs_company_summary collection with pre-aggregated company statistics.

Run with:
    python -m migrations.004_company_materialized_view --uri "..." --db jobapp
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


class Migration004:
    """Company materialized view creation."""
    name = "004_company_materialized_view"
    version = 4

    async def run(self, db):
        print(f"\n╔════════════════════════════════════════════════════════════════╗")
        print(f"║  Migration 004: Company Materialized View                    ║")
        print(f"╚════════════════════════════════════════════════════════════════╝\n")

        # Ensure company_normalized is populated
        print("Checking company_normalized field...")
        missing = await db.jobs.count_documents({"company_normalized": {"$exists": False}})
        if missing > 0:
            print(f"  ⚠ Warning: {missing} jobs missing company_normalized")
            print("  Running backfill...")

            result = await db.jobs.update_many(
                {"company_normalized": {"$exists": False}},
                [{
                    "$set": {
                        "company_normalized": {
                            "$trim": {"input": {"$toLower": "$company"}}
                        },
                        "updated_at": datetime.utcnow()
                    }
                }]
            )
            print(f"  ✓ Backfilled {result.modified_count} jobs")

        # Build aggregation pipeline
        print("\nBuilding company aggregation pipeline...")
        pipeline = [
            {
                "$match": {
                    "company": {"$exists": True, "$ne": "", "$ne": None}
                }
            },
            {
                "$group": {
                    "_id": {
                        "name": "$company",
                        "normalized": "$company_normalized"
                    },
                    "job_count": {"$sum": 1},
                    "unique_locations": {"$addToSet": "$location"},
                    "job_types": {"$addToSet": "$job_type"},
                    "sources": {"$addToSet": "$source"},
                    "first_job": {"$min": "$created_at"},
                    "last_job": {"$max": "$created_at"},
                    "avg_match_score": {"$avg": "$match_score"},
                    "has_salary_info": {"$sum": {"$cond": [{"$ne": ["$salary", None]}, 1, 0]}}
                }
            },
            {
                "$project": {
                    "_id": 0,
                    "name_normalized": "$_id.normalized",
                    "name": "$_id.name",
                    "job_count": 1,
                    "unique_locations": {
                        "$size": {"$ifNull": ["$unique_locations", []]}
                    },
                    "job_type_count": {
                        "$size": {"$ifNull": ["$job_types", []]}
                    },
                    "sources": 1,
                    "first_job": 1,
                    "last_job": 1,
                    "avg_match_score": {"$round": ["$avg_match_score", 2]},
                    "salary_info_count": "$has_salary_info"
                }
            },
            {"$sort": {"job_count": -1}}
        ]

        print("Executing aggregation (this may take a moment)...")
        start_time = datetime.utcnow()

        try:
            results = await db.jobs.aggregate(pipeline).to_list(None)
            duration = (datetime.utcnow() - start_time).total_seconds()
            print(f"  ✓ Aggregation completed in {duration:.1f}s")
            print(f"  ℹ Generated {len(results)} company summaries")

            # Create or replace summary collection
            print("\nCreating jobs_company_summary collection...")
            await db.jobs_company_summary.drop()

            if results:
                await db.jobs_company_summary.insert_many(results)
                print(f"  ✓ Inserted {len(results)} company summary records")

                # Create indexes
                await db.jobs_company_summary.create_index(
                    "name_normalized",
                    unique=True,
                    name="idx_jobs_company_summary_normalized"
                )
                print("  ✓ Created unique index on name_normalized")

                await db.jobs_company_summary.create_index(
                    [("job_count", -1)],
                    name="idx_jobs_company_summary_job_count"
                )
                print("  ✓ Created index on job_count")

                await db.jobs_company_summary.create_index(
                    [("last_job", -1)],
                    name="idx_jobs_company_summary_last"
                )
                print("  ✓ Created index on last_job")

                # Show top 10
                print("\n  Top 10 Companies by Job Count:")
                for i, comp in enumerate(results[:10], 1):
                    print(f"    {i}. {comp['name']} ({comp['job_count']} jobs)")

        except PyMongoError as e:
            print(f"  ✗ Error during aggregation: {e}")
            raise

        # Record migration
        await self.record_migration(db)

        print(f"\n╔════════════════════════════════════════════════════════════════╗")
        print(f"║  Migration 004 Complete                                       ║")
        print(f"╚════════════════════════════════════════════════════════════════╝\n")
        print("Next steps:")
        print("  1. Create all indexes (see MONGODB_SCHEMAS_ATLAS.md)")
        print("  2. Configure Atlas Search for full-text search")

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
        migration = Migration004()
        await migration.run(db)
    finally:
        client.close()


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Migration 004: Company Materialized View")
    parser.add_argument("--uri", required=True, help="MongoDB connection URI")
    parser.add_argument("--db", default="jobapp", help="Database name")

    args = parser.parse_args()
    asyncio.run(run(args.uri, args.db))
