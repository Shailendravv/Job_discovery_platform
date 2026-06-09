#!/usr/bin/env python3
"""
Migration 002: Job Denormalization & Computed Fields

Adds computed fields and backfills existing data:
- company_normalized (lowercase company)
- dedup_hash (SHA256 hash for deduplication)
- posted_date_parsed (ISO date from posted_date string)
- extracted_text_length for resumes

Run with:
    python -m migrations.002_job_denormalization --uri "..." --db jobapp
"""

import asyncio
import hashlib
import re
from datetime import datetime, timedelta
from typing import Optional

try:
    from motor.motor_asyncio import AsyncIOMotorClient
    from pymongo.errors import PyMongoError
except ImportError:
    print("Error: Required packages not installed.")
    print("Run: pip install pymongo motor")
    exit(1)


class Migration002:
    """Denormalization and computed fields migration."""
    name = "002_job_denormalization"
    version = 2

    async def run(self, db):
        print(f"\n╔════════════════════════════════════════════════════════════════╗")
        print(f"║  Migration 002: Job Denormalization & Computed Fields        ║")
        print(f"╚════════════════════════════════════════════════════════════════╝\n")

        # Step 1: Add company_normalized
        print("Step 1: Adding company_normalized field...")
        result1 = await db.jobs.update_many(
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
        print(f"  ✓ Updated {result1.modified_count} jobs with company_normalized")

        # Step 2: Add dedup_hash
        print("\nStep 2: Adding dedup_hash field...")

        # Process in batches for large datasets
        batch_size = 1000
        total_updated = 0
        cursor = db.jobs.find({"dedup_hash": {"$exists": False}}, {"_id": 1, "company": 1, "title": 1, "location": 1})

        async for doc in cursor:
            company = doc.get("company", "")
            title = doc.get("title", "")
            location = doc.get("location", "")

            dedup_key = f"{company}|{title}|{location}"
            dedup_hash = hashlib.sha256(dedup_key.encode()).hexdigest()

            await db.jobs.update_one(
                {"_id": doc["_id"]},
                {"$set": {"dedup_hash": dedup_hash, "updated_at": datetime.utcnow()}}
            )
            total_updated += 1

            if total_updated % batch_size == 0:
                print(f"  ... processed {total_updated} jobs")

        print(f"  ✓ Updated {total_updated} jobs with dedup_hash")

        # Step 3: Add extracted_text_length to resumes
        print("\nStep 3: Adding extracted_text_length to resumes...")
        result3 = await db.resumes.update_many(
            {"extracted_text_length": {"$exists": False}},
            [{
                "$set": {
                    "extracted_text_length": {"$strLenCP": "$extracted_text"},
                    "updated_at": datetime.utcnow()
                }
            }]
        )
        print(f"  ✓ Updated {result3.modified_count} resumes with extracted_text_length")

        # Step 4: Parse posted_date to ISO date
        print("\nStep 4: Parsing posted_date to posted_date_parsed...")
        date_pattern = re.compile(r'^\d{4}-\d{2}-\d{2}')

        # Process in batches
        parsed_count = 0
        cursor = db.jobs.find({"posted_date_parsed": {"$exists": False}}, {"_id": 1, "posted_date": 1})

        async for doc in cursor:
            posted_date_str = doc.get("posted_date")
            if not posted_date_str:
                continue

            parsed_date = None
            if date_pattern.match(str(posted_date_str)):
                try:
                    parsed_date = datetime.strptime(str(posted_date_str), "%Y-%m-%d")
                except ValueError:
                    pass

            if parsed_date:
                await db.jobs.update_one(
                    {"_id": doc["_id"]},
                    {"$set": {"posted_date_parsed": parsed_date, "updated_at": datetime.utcnow()}}
                )
                parsed_count += 1

        print(f"  ✓ Parsed {parsed_count} jobs with valid dates")

        # Step 5: Create company summary view
        print("\nStep 5: Computing company statistics...")

        # Build aggregation
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

        print("  Executing aggregation...")
        start_time = datetime.utcnow()

        try:
            results = await db.jobs.aggregate(pipeline).to_list(None)
            duration = (datetime.utcnow() - start_time).total_seconds()
            print(f"  ✓ Aggregation completed in {duration:.1f}s")
            print(f"  ℹ Generated {len(results)} company summaries")

            # Create or replace summary collection
            await db.jobs_company_summary.drop()
            if results:
                await db.jobs_company_summary.insert_many(results)
                print(f"  ✓ Created jobs_company_summary with {len(results)} records")

                # Create index
                await db.jobs_company_summary.create_index(
                    "name_normalized",
                    unique=True,
                    name="idx_jobs_company_summary_normalized"
                )
                print("  ✓ Created index on jobs_company_summary.name_normalized")

                # Show top 5
                print("\n  Top 5 Companies by Job Count:")
                for i, comp in enumerate(results[:5], 1):
                    print(f"    {i}. {comp['name']} ({comp['job_count']} jobs)")

        except PyMongoError as e:
            print(f"  ✗ Error during aggregation: {e}")
            raise

        # Step 6: Data quality report
        print("\nStep 6: Data quality analysis...")
        try:
            stats = await db.jobs.aggregate([
                {
                    "$facet": {
                        "total": [{"$count": "count"}],
                        "with_url": [
                            {"$match": {"url": {"$exists": True, "$ne": None}}},
                            {"$count": "count"}
                        ],
                        "with_apply_url": [
                            {"$match": {"apply_url": {"$exists": True, "$ne": None}}},
                            {"$count": "count"}
                        ],
                        "with_salary": [
                            {"$match": {"salary": {"$exists": True, "$ne": None}}},
                            {"$count": "count"}
                        ],
                        "with_location": [
                            {"$match": {"location": {"$exists": True, "$ne": None}}},
                            {"$count": "count"}
                        ],
                        "with_skills": [
                            {"$match": {"skills": {"$exists": True, "$ne": []}}},
                            {"$count": "count"}
                        ],
                        "avg_skills": [
                            {"$project": {"skill_count": {"$size": {"$ifNull": ["$skills", []]}}}},
                            {"$group": {"_id": None, "avg": {"$avg": "$skill_count"}}}
                        ]
                    }
                }
            ]).to_list(1)

            if stats and stats[0]:
                s = stats[0]
                total = s["total"][0]["count"] if s["total"] else 0
                print(f"  Data Quality Report:")
                print(f"    Total jobs: {total}")
                print(f"    With URL: {s['with_url'][0]['count'] if s['with_url'] else 0} "
                      f"({(s['with_url'][0]['count'] / total * 100):.1f}%)")
                print(f"    With apply_url: {s['with_apply_url'][0]['count'] if s['with_apply_url'] else 0}")
                print(f"    With salary: {s['with_salary'][0]['count'] if s['with_salary'] else 0}")
                print(f"    With location: {s['with_location'][0]['count'] if s['with_location'] else 0}")
                print(f"    With skills: {s['with_skills'][0]['count'] if s['with_skills'] else 0}")
                print(f"    Avg skills per job: {s['avg_skills'][0]['avg']:.1f}" if s['avg_skills'] else "    Avg skills per job: N/A")

        except Exception as e:
            print(f"  ⚠ Could not compute stats: {e}")

        # Record migration
        await self.record_migration(db)

        print(f"\n╔════════════════════════════════════════════════════════════════╗")
        print(f"║  Migration 002 Complete                                       ║")
        print(f"╚════════════════════════════════════════════════════════════════╝\n")
        print("Next steps:")
        print("  1. Verify denormalized fields with sample queries")
        print("  2. Run migration 003 to populate skills taxonomy")

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
            if e.code != 11000:  # Not duplicate
                raise


async def run(uri: str, db_name: str = "jobapp"):
    """Run this migration."""
    client = AsyncIOMotorClient(uri)
    db = client[db_name]

    try:
        migration = Migration002()
        await migration.run(db)
    finally:
        client.close()


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Migration 002: Job Denormalization")
    parser.add_argument("--uri", required=True, help="MongoDB connection URI")
    parser.add_argument("--db", default="jobapp", help="Database name")

    args = parser.parse_args()
    asyncio.run(run(args.uri, args.db))
