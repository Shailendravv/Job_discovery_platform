#!/usr/bin/env python3
"""
Migration 016: Job Discovery — role-search index, freshness index, and the
run/scoring fields the Discovery page reads.

Backs the Job Discovery session (search a role, see only postings from the
last 24 hours, watch the run's stage timings live):

1. ``postings.title_normalized`` — the role search matches a regex against
   this field (app/ingest/role_match.py). Migration 012 indexed it only as
   the *third* component of the (org, title_normalized, location_normalized)
   dedupe key, whose prefix cannot serve a query that doesn't also pin
   ``org``, so a role search was a collection scan.

2. ``postings.(prefilter_status, posted_at)`` — the Discovery results read is
   always "prefilter_status=passed, posted within the window, newest first".
   Migration 015's single-field posted_at index can't satisfy the equality
   and the sort together.

3. ``postings.score`` / ``score_band`` and the extra ``ingest_runs`` fields
   declared in their validators. Both collections' $jsonSchema omit
   ``additionalProperties: false``, so these documents already write
   successfully — this only makes the schema describe reality, which is what
   a future reader will trust.

Idempotent: every index creation tolerates IndexOptionsConflict, and
collMod is a no-op when the validator already matches.

Run with:
    python -m migrations.016_discovery_search_indexes --uri "..." --db jobapp
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


# Additive only. No change to ``required``, and no property is narrowed —
# a validator change that could reject an existing document is exactly the
# failure mode that made migration 010 necessary (an ATS source enum that
# stopped at "workday" while three new connectors were already writing).
POSTINGS_NEW_PROPERTIES = {
    "score": {"bsonType": ["int", "null"]},
    "score_band": {
        "bsonType": ["string", "null"],
        "enum": ["apply", "needs_review", "skip", None],
    },
}

INGEST_RUNS_NEW_PROPERTIES = {
    "status": {
        "bsonType": ["string", "null"],
        "enum": ["running", "completed", "failed", None],
    },
    "role": {"bsonType": ["string", "null"]},
    "window": {"bsonType": ["string", "null"]},
    "postings_fresh": {"bsonType": ["int", "null"]},
    "elapsed_ms": {"bsonType": ["double", "int", "null"]},
    "stages": {"bsonType": ["array", "null"]},
    "write_errors": {"bsonType": ["array", "null"]},
    "prefilter": {"bsonType": ["object", "null"]},
    "score": {"bsonType": ["object", "null"]},
    "error": {"bsonType": ["string", "null"]},
}


class Migration016:
    """Indexes and schema fields for the Job Discovery session."""

    name = "016_discovery_search_indexes"
    version = 16

    async def run(self, db):
        print("\n" + "=" * 68)
        print("  Migration 016: Job Discovery search + run-status fields")
        print("=" * 68 + "\n")

        print("Step 1: Creating indexes on 'postings'...")
        index_specs = [
            ([("title_normalized", 1)], "idx_postings_title_normalized"),
            ([("prefilter_status", 1), ("posted_at", -1)], "idx_postings_prefilter_posted_at"),
        ]
        for spec, name in index_specs:
            await self._create_index(db.postings, spec, name)

        print("\nStep 2: Indexing ingest_runs.started_at (run history reads)...")
        await self._create_index(db.ingest_runs, [("started_at", -1)], "idx_ingest_runs_started_at")

        print("\nStep 3: Extending validators with the new fields...")
        await self._extend_validator(db, "postings", POSTINGS_NEW_PROPERTIES)
        await self._extend_validator(db, "ingest_runs", INGEST_RUNS_NEW_PROPERTIES)

        await self.record_migration(db)

        print("\n" + "=" * 68)
        print("  Migration 016 Complete")
        print("=" * 68)
        print("\nSummary:")
        print("  ✅ Indexed postings.title_normalized (role search)")
        print("  ✅ Indexed postings.(prefilter_status, posted_at) (discovery results)")
        print("  ✅ Indexed ingest_runs.started_at")
        print("  ✅ Declared postings.score / score_band")
        print("  ✅ Declared the ingest_runs run-status fields")

    async def _create_index(self, collection, spec, name: str) -> None:
        try:
            await collection.create_index(spec, name=name, background=True)
            print(f"  ✓ Created index: {name}")
        except PyMongoError as e:
            if getattr(e, "code", None) == 85:  # IndexOptionsConflict
                print(f"  ⚡ Index already exists: {name}")
            else:
                print(f"  ✗ Error creating {name}: {e}")
                raise

    async def _extend_validator(self, db, collection_name: str, new_properties: dict) -> None:
        """Merge ``new_properties`` into the collection's existing
        $jsonSchema, leaving everything else — including ``required`` — alone.

        Reads the current validator rather than restating it, so this cannot
        silently drop a rule some earlier migration added.
        """
        existing = await db.list_collection_names(filter={"name": collection_name})
        if not existing:
            print(f"  ⚡ '{collection_name}' does not exist yet -- skipping validator update")
            return

        options = await db[collection_name].options()
        validator = options.get("validator") or {}
        schema = validator.get("$jsonSchema")
        if not schema:
            print(f"  ⚡ '{collection_name}' has no $jsonSchema -- nothing to extend")
            return

        properties = schema.setdefault("properties", {})
        added = [key for key in new_properties if key not in properties]
        properties.update({k: v for k, v in new_properties.items() if k not in properties})

        if not added:
            print(f"  ⚡ '{collection_name}' validator already declares these fields")
            return

        try:
            await db.command({"collMod": collection_name, "validator": {"$jsonSchema": schema}})
            print(f"  ✓ {collection_name}: declared {', '.join(added)}")
        except PyMongoError as e:
            print(f"  ✗ Error updating {collection_name} validator: {e}")
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
    client = AsyncIOMotorClient(uri)
    db = client[db_name]
    try:
        migration = Migration016()
        await migration.run(db)
    finally:
        client.close()


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Migration 016: Job Discovery search + run-status fields"
    )
    parser.add_argument("--uri", required=True, help="MongoDB connection URI")
    parser.add_argument("--db", default="jobapp", help="Database name")

    args = parser.parse_args()
    asyncio.run(run(args.uri, args.db))
