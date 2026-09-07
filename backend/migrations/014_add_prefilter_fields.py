#!/usr/bin/env python3
"""
Migration 014: Add prefilter fields to 'postings' + new 'prefilter_runs'
collection (PLAN.md §4 "Phase 3 — prefilter before the agent sees anything",
milestone 3)

Extends migration 012's ``postings`` validator (via ``collMod``, same
pattern as migration 010's jobs.source enum update) with three fields
written by ``app.ingest.prefilter.run_prefilter``:

    prefiltered       bool    — has this posting been classified yet
    prefilter_status  string  — "passed" | "hard_filter" | "keyword_floor" |
                                 "embedding", null until prefiltered
    prefilter_reason  string  — human-readable reason for a reject, null on
                                 pass or until prefiltered

These are additive only — every field migration 012 already validates stays
untouched, so existing documents and code keep working unchanged (same
approach as migration 013's separate ``verdicts`` collection).

``prefilter_runs`` mirrors ``ingest_runs``: one document per
``run_prefilter`` call with the per-stage counts — this is what makes the
"log counts at each stage" acceptance requirement (PLAN.md §4) inspectable
after the fact, not just in that run's stdout.

Run with:
    python -m migrations.014_add_prefilter_fields --uri "..." --db jobapp
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


PREFILTER_RUNS_SCHEMA = {
    "$jsonSchema": {
        "bsonType": "object",
        "required": ["run_at", "input"],
        "properties": {
            "run_at": {"bsonType": "date"},
            "input": {"bsonType": "int"},
            "hard_filter_rejected": {"bsonType": "int"},
            "keyword_floor_rejected": {"bsonType": "int"},
            "embedding_rejected": {"bsonType": "int"},
            "embedding_skipped": {"bsonType": "int"},
            "passed": {"bsonType": "int"},
        },
    }
}


class Migration014:
    """Add prefilter fields to postings + the prefilter_runs collection."""
    name = "014_add_prefilter_fields"
    version = 14

    async def run(self, db):
        print("\n╔════════════════════════════════════════════════════════════════╗")
        print("║  Migration 014: Add prefilter fields + prefilter_runs            ║")
        print("╚════════════════════════════════════════════════════════════════╝\n")

        await self._extend_postings_validator(db)
        await self._create_collection(db, "prefilter_runs", PREFILTER_RUNS_SCHEMA)

        print("\nCreating indexes...")
        await self._create_index(
            db.postings, [("prefiltered", 1), ("first_seen_at", 1)], "idx_postings_prefiltered_first_seen"
        )
        await self._create_index(db.prefilter_runs, [("run_at", -1)], "idx_prefilter_runs_run_at")

        await self.record_migration(db)

        print("\n╔════════════════════════════════════════════════════════════════╗")
        print("║  Migration 014 Complete                                          ║")
        print("╚════════════════════════════════════════════════════════════════╝\n")

    async def _extend_postings_validator(self, db) -> None:
        print("Step 1: Fetching current postings collection validator...")
        try:
            cmd_result = await db.command({"listCollections": 1, "filter": {"name": "postings"}})
            collections = cmd_result.get("cursor", {}).get("firstBatch", [])
            if not collections:
                print("  ✗ postings collection not found — run migration 012 first!")
                return
            current_validator = collections[0].get("options", {}).get("validator", {})
            print("  ✓ Current validator retrieved")
        except Exception as e:
            print(f"  ✗ Failed to get collection info: {e}")
            return

        print("\nStep 2: Adding prefiltered/prefilter_status/prefilter_reason...")
        updated_validator = current_validator.copy()
        schema = updated_validator.setdefault("$jsonSchema", {})
        properties = schema.setdefault("properties", {})
        properties["prefiltered"] = {"bsonType": "bool"}
        properties["prefilter_status"] = {
            "bsonType": ["string", "null"],
            "enum": ["passed", "hard_filter", "keyword_floor", "embedding", None],
        }
        properties["prefilter_reason"] = {"bsonType": ["string", "null"]}

        try:
            await db.command({
                "collMod": "postings",
                "validator": updated_validator,
                "validationLevel": "moderate",
                "validationAction": "error",
            })
            print("  ✓ postings validator updated with prefilter fields")
        except PyMongoError as e:
            print(f"  ✗ Failed to update validator: {e}")
            raise

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
        migration = Migration014()
        await migration.run(db)
    finally:
        client.close()


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Migration 014: Add prefilter fields + prefilter_runs collection")
    parser.add_argument("--uri", required=True, help="MongoDB connection URI")
    parser.add_argument("--db", default="jobapp", help="Database name")

    args = parser.parse_args()
    asyncio.run(run(args.uri, args.db))
