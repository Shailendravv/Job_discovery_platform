#!/usr/bin/env python3
"""
Migration 013: Add 'verdicts' collection (jobctl judge, milestone 2)

Stores the full verdict payload (score, reasons, concerns, matched/missing
requirements) written by ``jobctl judge --apply`` (PLAN.md §3). Separate
from ``postings.judged``/``postings.verdict`` (already added by migration
012) — those two fields stay on the posting for cheap list/next filtering,
this collection holds the detail ``jobctl show <id>`` and later milestones
(shortlist, funnel stats) read.

``_id`` on a verdict document is the resolved posting's full id, so a
verdict is a 1:1 lookup by posting id, never a separate query.

Run with:
    python -m migrations.013_add_verdicts_collection --uri "..." --db jobapp
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


VERDICTS_SCHEMA = {
    "$jsonSchema": {
        "bsonType": "object",
        "required": ["verdict", "score", "judged_by", "judged_at"],
        "properties": {
            "verdict": {"bsonType": "string", "enum": ["apply", "maybe", "skip"]},
            "score": {"bsonType": "int", "minimum": 1, "maximum": 10},
            "reasons": {"bsonType": "array", "items": {"bsonType": "string"}},
            "concerns": {"bsonType": "array", "items": {"bsonType": "string"}},
            "matched_requirements": {"bsonType": "array", "items": {"bsonType": "string"}},
            "missing_requirements": {"bsonType": "array", "items": {"bsonType": "string"}},
            "judged_by": {"bsonType": "string"},
            "judged_at": {"bsonType": "date"},
            "applied_at": {"bsonType": ["date", "null"]},
        },
    }
}


class Migration013:
    """Add the 'verdicts' collection for jobctl judge (milestone 2)."""
    name = "013_add_verdicts_collection"
    version = 13

    async def run(self, db):
        print("\n╔════════════════════════════════════════════════════════════════╗")
        print("║  Migration 013: Add verdicts collection                          ║")
        print("╚════════════════════════════════════════════════════════════════╝\n")

        await self._create_collection(db, "verdicts", VERDICTS_SCHEMA)

        print("\nCreating indexes on 'verdicts'...")
        index_specs = [
            ([("verdict", 1), ("judged_at", 1)], "idx_verdicts_verdict_judged_at"),
        ]
        for spec, name in index_specs:
            await self._create_index(db.verdicts, spec, name)

        await self.record_migration(db)

        print("\n╔════════════════════════════════════════════════════════════════╗")
        print("║  Migration 013 Complete                                          ║")
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
        migration = Migration013()
        await migration.run(db)
    finally:
        client.close()


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Migration 013: Add verdicts collection")
    parser.add_argument("--uri", required=True, help="MongoDB connection URI")
    parser.add_argument("--db", default="jobapp", help="Database name")

    args = parser.parse_args()
    asyncio.run(run(args.uri, args.db))
