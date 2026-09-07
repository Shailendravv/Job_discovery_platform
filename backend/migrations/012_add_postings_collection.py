#!/usr/bin/env python3
"""
Migration 012: Add 'postings' + 'ingest_runs' collections (ATS ingest layer)

Creates the normalized posting store used by ``backend/app/ingest/`` and
``jobctl`` (JobSphere v2 / PLAN.md milestone 1). Distinct from the existing
``jobs`` collection, which backs the legacy dashboard search — that
collection and its validator are untouched.

Indexes:
- unique on nothing extra (``_id`` is already the deterministic
  sha256(provider, org, provider_job_id) — see app/ingest/models.py)
- ``first_seen_at`` — powers "what's new since yesterday" queries
- ``(org, title_normalized, location_normalized)`` — near-dup lookups
- ``(provider, org)`` — per-source stats / doctor
- ``(judged, first_seen_at)`` — milestone 2's `jobctl list --new --unjudged`

Run with:
    python -m migrations.012_add_postings_collection --uri "..." --db jobapp
"""

import asyncio
from datetime import datetime

try:
    from motor.motor_asyncio import AsyncIOMotorClient
    from pymongo.errors import CollectionInvalid, PyMongoError
except ImportError:
    print("Error: Required packages not installed.")
    print("Run: pip install pymongo motor")
    exit(1)


POSTINGS_SCHEMA = {
    "$jsonSchema": {
        "bsonType": "object",
        "required": ["provider", "org", "company_name", "title", "url"],
        "properties": {
            "provider": {"bsonType": "string", "minLength": 1},
            "org": {"bsonType": "string", "minLength": 1},
            "company_name": {"bsonType": "string", "minLength": 1, "maxLength": 200},
            "title": {"bsonType": "string", "minLength": 1, "maxLength": 300},
            "title_normalized": {"bsonType": "string"},
            "location": {"bsonType": ["string", "null"], "maxLength": 500},
            "location_normalized": {"bsonType": "string"},
            "remote_flag": {"bsonType": ["bool", "null"]},
            "employment_type": {"bsonType": ["string", "null"]},
            "description_text": {"bsonType": "string"},
            "salary": {"bsonType": ["string", "null"]},
            "url": {"bsonType": "string", "pattern": "^https?://"},
            "apply_url": {"bsonType": ["string", "null"]},
            "posted_at": {"bsonType": ["date", "null"]},
            "first_seen_at": {"bsonType": "date"},
            "last_seen_at": {"bsonType": "date"},
            "duplicate_of": {"bsonType": ["string", "null"]},
            "tags": {"bsonType": "array", "items": {"bsonType": "string"}},
            "raw": {"bsonType": "object"},
            "judged": {"bsonType": "bool"},
            "verdict": {"bsonType": ["string", "null"], "enum": ["apply", "maybe", "skip", None]},
            "ingest_run_ids": {"bsonType": "array", "items": {"bsonType": "string"}},
            "created_at": {"bsonType": "date"},
            "updated_at": {"bsonType": "date"},
        },
    }
}

INGEST_RUNS_SCHEMA = {
    "$jsonSchema": {
        "bsonType": "object",
        "required": ["started_at"],
        "properties": {
            "started_at": {"bsonType": "date"},
            "finished_at": {"bsonType": ["date", "null"]},
            "sources_total": {"bsonType": ["int", "null"]},
            "sources_ok": {"bsonType": ["int", "null"]},
            "sources_error": {"bsonType": ["int", "null"]},
            "sources_skipped": {"bsonType": ["int", "null"]},
            "postings_fetched": {"bsonType": ["int", "null"]},
            "postings_normalized": {"bsonType": ["int", "null"]},
            "duplicates_marked": {"bsonType": ["int", "null"]},
            "inserted": {"bsonType": ["int", "null"]},
            "updated": {"bsonType": ["int", "null"]},
            "errors": {"bsonType": ["array", "null"]},
        },
    }
}


class Migration012:
    """Add postings + ingest_runs collections for the ATS ingest layer."""
    name = "012_add_postings_collection"
    version = 12

    async def run(self, db):
        print("\n╔════════════════════════════════════════════════════════════════╗")
        print("║  Migration 012: Add postings + ingest_runs collections          ║")
        print("╚════════════════════════════════════════════════════════════════╝\n")

        await self._create_collection(db, "postings", POSTINGS_SCHEMA)
        await self._create_collection(db, "ingest_runs", INGEST_RUNS_SCHEMA)

        print("\nCreating indexes on 'postings'...")
        index_specs = [
            (["first_seen_at"], "idx_postings_first_seen_at"),
            ([("org", 1), ("title_normalized", 1), ("location_normalized", 1)], "idx_postings_dedupe_key"),
            ([("provider", 1), ("org", 1)], "idx_postings_provider_org"),
            ([("judged", 1), ("first_seen_at", 1)], "idx_postings_judged_first_seen"),
        ]
        for spec, name in index_specs:
            await self._create_index(db.postings, spec, name)

        await self.record_migration(db)

        print("\n╔════════════════════════════════════════════════════════════════╗")
        print("║  Migration 012 Complete                                          ║")
        print("╚════════════════════════════════════════════════════════════════╝\n")

    async def _create_collection(self, db, name: str, schema: dict) -> None:
        try:
            await db.create_collection(
                name,
                validator=schema,
                validationLevel="moderate",
                validationAction="error",
            )
            print(f"  ✓ Created collection: {name}")
        except CollectionInvalid:
            print(f"  ⚡ Collection already exists: {name}")
        except PyMongoError as e:
            print(f"  ✗ Failed to create {name}: {e}")
            raise

    async def _create_index(self, collection, spec, name: str) -> None:
        try:
            await collection.create_index(spec, name=name, background=True)
            print(f"  ✓ Created index: {name}")
        except PyMongoError as e:
            if e.code == 85:  # IndexOptionsConflict
                print(f"  ⚡ Index already exists: {name}")
            else:
                print(f"  ✗ Error creating {name}: {e}")
                raise

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
    """Run this migration."""
    client = AsyncIOMotorClient(uri)
    db = client[db_name]
    try:
        migration = Migration012()
        await migration.run(db)
    finally:
        client.close()


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Migration 012: Add postings + ingest_runs collections")
    parser.add_argument("--uri", required=True, help="MongoDB connection URI")
    parser.add_argument("--db", default="jobapp", help="Database name")

    args = parser.parse_args()
    asyncio.run(run(args.uri, args.db))
