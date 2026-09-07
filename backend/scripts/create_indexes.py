#!/usr/bin/env python3
"""
Index Creation Script for jobapp Database
Creates all 40+ indexes for optimal query performance.

Usage:
    python scripts/create_indexes.py --uri "mongodb+srv://..." --db jobapp
"""

import asyncio
import sys
from datetime import datetime

try:
    from motor.motor_asyncio import AsyncIOMotorClient
    from pymongo.errors import PyMongoError
except ImportError:
    print("Error: Required packages not installed.")
    print("Run: pip install pymongo motor")
    sys.exit(1)


# Index definitions - each tuple is (index_spec, index_name, options)
INDEXES = {
    # NOTE: the legacy "jobs" collection was retired (migration
    # 015_retire_jobs_collection.py) — job/posting data now lives in
    # "postings" and its indexes come from migrations 012 and 015
    # (idx_postings_first_seen_at, idx_postings_dedupe_key,
    # idx_postings_provider_org, idx_postings_judged_first_seen,
    # idx_postings_prefiltered_first_seen, idx_postings_posted_at).
    # Deliberately not listed here — calling create_index on a dropped
    # collection name would silently recreate it.

    "resumes": [
        ([("resume_id", 1)], "idx_resume_resume_id", {"unique": True}),
        ([("user_id", 1), ("updated_at", -1)], "idx_resume_user_updated", {}),
        ([("parsed_data.skills", "text")], "idx_resume_skills_text", {}),
        ([("processing_status", 1), ("created_at", 1)], "idx_resume_processing_status", {}),
        ([("extracted_text", "text")], "idx_resume_text_search", {"default_language": "english"}),
    ],

    "users": [
        ([("email", 1)], "idx_users_email", {"unique": True}),
        ([("username", 1)], "idx_users_username", {"unique": True}),
        ([("user_id", 1)], "idx_users_user_id", {"unique": True}),
        ([
            ("profile.first_name", "text"),
            ("profile.last_name", "text"),
            ("profile.bio", "text")
         ], "idx_users_profile_search", {"default_language": "english"}),
        ([("role", 1), ("is_active", 1)], "idx_users_role_active", {}),
        ([("email_verified", 1), ("is_active", 1)], "idx_users_email_verified", {}),
    ],

    "applications": [
        ([("user_id", 1), ("job_id", 1)], "idx_applications_user_job_unique",
         {"unique": True, "partialFilterExpression": {"is_deleted": False}}),
        ([("user_id", 1), ("updated_at", -1)], "idx_applications_user_updated", {}),
        ([("user_id", 1), ("status", 1), ("applied_at", -1)], "idx_applications_user_status", {}),
        ([("follow_up_date", 1), ("user_id", 1)], "idx_applications_followup", {}),
        ([("job_id", 1), ("applied_at", -1)], "idx_applications_job_applied", {}),
        # TTL for deleted applications (7 years)
        ([("is_deleted", 1), ("deleted_at", 1)], "idx_applications_deleted_ttl",
         {"expireAfterSeconds": 7 * 365 * 24 * 60 * 60}),
    ],

    "companies": [
        ([("name_normalized", 1)], "idx_companies_name_normalized",
         {"unique": True, "collation": {"locale": "en", "strength": 2}}),
        ([("domain", 1)], "idx_companies_domain",
         {"unique": True, "sparse": True}),
        ([("industry", 1), ("size", 1)], "idx_companies_industry_size", {}),
        ([("headquarters", 1)], "idx_companies_headquarters", {}),
        ([("last_job_posted", -1)], "idx_companies_last_job", {}),
    ],

    "skills": [
        ([("name_normalized", 1)], "idx_skills_normalized", {"unique": True}),
        ([("category", 1), ("popularity", -1)], "idx_skills_category_popular", {}),
        ([("name", "text"), ("synonyms", "text")], "idx_skills_text_search", {}),
        ([("is_active", 1), ("popularity", -1)], "idx_skills_active_popular", {}),
    ],

    "searchHistory": [
        ([("user_id", 1), ("created_at", -1)], "idx_search_history_user_recent", {}),
        # TTL (1 year)
        ([("created_at", 1)], "idx_search_history_user_ttl",
         {"expireAfterSeconds": 365 * 24 * 60 * 60}),
        ([("query", 1), ("created_at", -1)], "idx_search_history_query_recent", {}),
        ([("user_id", 1), ("session_id", 1), ("created_at", -1)], "idx_search_history_session", {}),
        ([("ip_address", 1), ("created_at", -1)], "idx_search_history_ip_rate_limit", {}),
    ],

    "jobMatches": [
        ([("user_id", 1), ("created_at", -1)], "idx_job_matches_user_recent", {}),
        ([("job_id", 1), ("match_score", -1)], "idx_job_matches_job_score", {}),
        ([("user_id", 1), ("job_id", 1)], "idx_job_matches_user_job",
         {"unique": True, "partialFilterExpression": {"expires_at": {"$gt": datetime.utcnow()}}}),
        # TTL
        ([("expires_at", 1)], "idx_job_matches_expiry_ttl", {}),
        ([("user_id", 1), ("match_score", -1), ("created_at", -1)], "idx_job_matches_user_high_score", {}),
    ],

    "change_stream_checkpoints": [
        ([("_id", 1)], "idx_cs_checkpoint_id", {"unique": True}),
    ],

    "change_stream_configs": [
        ([("name", 1)], "idx_cs_config_name", {"unique": True}),
        ([("is_active", 1), ("name", 1)], "idx_cs_config_active", {}),
    ],
}


async def create_all_indexes(db):
    """Create all indexes defined in INDEXES dict."""
    print("\n╔════════════════════════════════════════════════════════════════╗")
    print("║  Creating All Database Indexes                                ║")
    print("╚════════════════════════════════════════════════════════════════╝\n")

    start_time = datetime.utcnow()
    total_created = 0
    skipped = 0
    errors = 0

    for collection_name, index_list in INDEXES.items():
        print(f"\n[{collection_name}]")

        for index_spec, index_name, options in index_list:
            try:
                # Check if index exists
                existing_indexes = await db[collection_name].index_information()
                if index_name in existing_indexes:
                    print(f"  ⚡ {index_name} already exists")
                    skipped += 1
                    continue

                await db[collection_name].create_index(index_spec, name=index_name, **options)
                print(f"  ✓ {index_name}")
                total_created += 1

            except PyMongoError as e:
                if e.code == 85:  # IndexOptionsConflict
                    print(f"  ⚡ {index_name} exists with different options")
                    skipped += 1
                else:
                    print(f"  ✗ {index_name}: {e}")
                    errors += 1

    duration = (datetime.utcnow() - start_time).total_seconds()

    print("\n" + "=" * 60)
    print("INDEX CREATION COMPLETE")
    print("=" * 60)
    print(f"  Total indexes created: {total_created}")
    print(f"  Skipped (already exist): {skipped}")
    print(f"  Errors: {errors}")
    print(f"  Time taken: {duration:.1f}s")

    # Show summary
    print("\nCollection Index Counts:")
    for collection_name in INDEXES.keys():
        try:
            indexes = await db[collection_name].index_information()
            print(f"  {collection_name:<30} {len(indexes)} indexes")
        except:
            print(f"  {collection_name:<30} N/A")


async def run(uri: str, db_name: str = "jobapp"):
    """Run index creation."""
    client = AsyncIOMotorClient(uri)
    db = client[db_name]

    try:
        await create_all_indexes(db)
    finally:
        client.close()


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Create all indexes for jobapp database")
    parser.add_argument("--uri", required=True, help="MongoDB connection URI")
    parser.add_argument("--db", default="jobapp", help="Database name")

    args = parser.parse_args()
    asyncio.run(run(args.uri, args.db))
