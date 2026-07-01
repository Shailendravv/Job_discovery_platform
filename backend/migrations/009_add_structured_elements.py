#!/usr/bin/env python3
"""
Migration 009: Add structured_elements to resumes Schema

Updates the resumes collection JSON schema validator to accept the new
optional `structured_elements` array field. This field stores structured
resume elements (with bold/type/link metadata) alongside the existing
flat-text `extracted_text` field.

The field is OPTIONAL so that:
- Legacy resumes uploaded before this migration continue to work
- Resumes where structured extraction fails gracefully degrade

Run with:
    python -m migrations.009_add_structured_elements --uri "..." --db jobapp
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


STRUCTURED_ELEMENT_SCHEMA = {
    "bsonType": "object",
    "properties": {
        "text": {"bsonType": "string"},
        "type": {
            "enum": ["heading", "subheading", "bullet", "normal"]
        },
        "bold": {"bsonType": "bool"},
        "links": {
            "bsonType": "array",
            "items": {
                "bsonType": "object",
                "properties": {
                    "text": {"bsonType": "string"},
                    "url": {"bsonType": "string"}
                }
            }
        },
        "font_size_pt": {
            "bsonType": ["double", "null"]
        }
    }
}


class Migration009:
    """Add structured_elements to resumes schema."""
    name = "009_add_structured_elements"
    version = 9

    async def run(self, db):
        print(f"\n╔════════════════════════════════════════════════════════════════╗")
        print(f"║  Migration 009: Add structured_elements to resumes Schema     ║")
        print(f"╚════════════════════════════════════════════════════════════════╝\n")

        # Step 1: Get current validator
        print("Step 1: Fetching current resumes collection validator...")
        try:
            cmd_result = await db.command({"listCollections": 1, "filter": {"name": "resumes"}})
            cursor = cmd_result.get("cursor", {})
            collections = cursor.get("firstBatch", [])
            if not collections:
                print("  ✗ Resumes collection not found!")
                return
            resumes_info = collections[0]
            current_options = resumes_info.get("options", {})
            current_validator = current_options.get("validator", {})
            print("  ✓ Current validator retrieved")
        except Exception as e:
            print(f"  ✗ Failed to get collection info: {e}")
            return

        # Step 2: Update validator to add structured_elements
        print("\nStep 2: Adding structured_elements field to validator...")
        updated_validator = current_validator.copy()

        # Ensure the $jsonSchema exists
        if "$jsonSchema" not in updated_validator:
            print("  ✗ Current validator doesn't have $jsonSchema — unexpected!")
            return

        schema = updated_validator["$jsonSchema"]

        # Add structured_elements to the properties (adjust existing schema)
        if "properties" not in schema:
            schema["properties"] = {}

        schema["properties"]["structured_elements"] = {
            "bsonType": ["array", "null"],
            "items": STRUCTURED_ELEMENT_SCHEMA,
            "description": "Structured resume elements preserving bold/type/link metadata"
        }

        # Update schema_version to make it less restrictive
        if "properties" in schema and "schema_version" in schema["properties"]:
            schema["properties"]["schema_version"]["bsonType"] = ["int", "null"]

        # Apply the updated validator
        try:
            await db.command({
                "collMod": "resumes",
                "validator": updated_validator,
                "validationLevel": "moderate",
                "validationAction": "error"
            })
            print("  ✓ Validator updated successfully with structured_elements field")
        except Exception as e:
            print(f"  ✗ Failed to update validator: {e}")
            return

        # Step 3: Update existing documents that don't have structured_elements
        print("\nStep 3: Updating existing resume documents (adding fallback structured_elements)...")
        try:
            result = await db.resumes.update_many(
                {"structured_elements": {"$exists": False}},
                {
                    "$set": {
                        "structured_elements": None,
                        "schema_version": 1,
                    }
                }
            )
            print(f"  ✓ Updated {result.modified_count} legacy resume documents")
        except Exception as e:
            print(f"  ⚠ Could not update legacy documents: {e}")
            print("    (This is non-critical — legacy fallback handling is in the code)")

        # Record migration
        await self.record_migration(db)

        print(f"\n╔════════════════════════════════════════════════════════════════╗")
        print(f"║  Migration 009 Complete                                       ║")
        print(f"╚════════════════════════════════════════════════════════════════╝\n")
        print("Summary:")
        print("  ✅ Added optional structured_elements field to resumes schema")
        print("  ✅ Existing resumes updated with null structured_elements")

    async def record_migration(self, db):
        """Record this migration."""
        now = datetime.utcnow()
        try:
            await db["_migrations"].insert_one({
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
        print(f"\n╔════════════════════════════════════════════════════════════════╗")
        print(f"║  Migration 009: Add structured_elements to resumes Schema     ║")
        print(f"╚════════════════════════════════════════════════════════════════╝\n")
        print(f"Database: {db_name}\n")

        migration = Migration009()
        await migration.run(db)

    finally:
        client.close()


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Migration 009: Add structured_elements to resumes Schema")
    parser.add_argument("--uri", required=True, help="MongoDB connection URI")
    parser.add_argument("--db", default="jobapp", help="Database name")

    args = parser.parse_args()
    asyncio.run(run(args.uri, args.db))
