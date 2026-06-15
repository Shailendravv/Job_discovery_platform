#!/usr/bin/env python3
"""
Migration 008: Add tailor_sessions Collection

Creates the tailor_sessions collection with JSON schema validation
and indexes for efficient querying by resume_id + job_id.

The tailor_sessions collection stores:
- Tailored resumes generated per job application
- Cover letters generated per job application
- Cloudinary download URLs for generated PDF/DOCX files

Indexes created:
- Compound unique index on (resume_id, job_id) — prevents duplicate tailoring
- Compound index on (resume_id, created_at) — fast listing of all sessions for a resume

Run with:
    python -m migrations.008_add_tailor_sessions --uri "..." --db jobapp
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


TAILOR_SESSIONS_SCHEMA = {
    "$jsonSchema": {
        "bsonType": "object",
        "required": ["resume_id", "job_id", "tailored_text", "created_at"],
        "properties": {
            "resume_id": {
                "bsonType": "string",
                "description": "Reference to resumes._id (ObjectId as string)"
            },
            "job_id": {
                "bsonType": "string",
                "description": "Reference to jobs._id (ObjectId as string)"
            },
            "original_text_preview": {
                "bsonType": "string",
                "description": "First 500 chars of the base resume text for audit"
            },
            "tailored_text": {
                "bsonType": "string",
                "minLength": 1,
                "description": "Full tailored resume text"
            },
            "cover_letter": {
                "bsonType": "string",
                "description": "Full generated cover letter text"
            },
            "cloudinary_pdf_url": {
                "bsonType": "string",
                "description": "Cloudinary URL for tailored resume PDF"
            },
            "cloudinary_docx_url": {
                "bsonType": "string",
                "description": "Cloudinary URL for tailored resume DOCX"
            },
            "cloudinary_cover_letter_url": {
                "bsonType": "string",
                "description": "Cloudinary URL for cover letter PDF"
            },
            "created_at": {
                "bsonType": "date",
                "description": "Timestamp when the tailor session was created"
            },
            "updated_at": {
                "bsonType": "date",
                "description": "Timestamp when the tailor session was last updated"
            }
        }
    }
}


class Migration008:
    """Add tailor_sessions collection and indexes."""
    name = "008_add_tailor_sessions"
    version = 8

    async def run(self, db):
        print(f"\n╔════════════════════════════════════════════════════════════════╗")
        print(f"║  Migration 008: Add tailor_sessions Collection                 ║")
        print(f"╚════════════════════════════════════════════════════════════════╝\n")

        # Step 1: Create tailor_sessions collection with schema validation
        print("Step 1: Creating tailor_sessions collection...")
        try:
            await db.create_collection(
                "tailor_sessions",
                validator=TAILOR_SESSIONS_SCHEMA,
                validationLevel="moderate",
                validationAction="error"
            )
            print("  ✓ Created collection: tailor_sessions with schema validation")
        except PyMongoError as e:
            if e.code == 48:  # NamespaceExists
                print("  ⚡ Collection already exists: tailor_sessions")
            else:
                print(f"  ✗ Error: {e}")
                raise

        # Step 2: Create compound unique index on (resume_id, job_id)
        print("\nStep 2: Creating unique compound index on (resume_id, job_id)...")
        try:
            await db.tailor_sessions.create_index(
                [("resume_id", 1), ("job_id", 1)],
                unique=True,
                name="idx_tailor_resume_job",
                background=True
            )
            print("  ✓ Created unique index: idx_tailor_resume_job")
        except PyMongoError as e:
            if e.code == 85:  # IndexOptionsConflict
                print("  ⚡ Index already exists: idx_tailor_resume_job")
            else:
                print(f"  ✗ Error: {e}")
                raise

        # Step 3: Create compound index on (resume_id, created_at)
        print("\nStep 3: Creating index on (resume_id, created_at)...")
        try:
            await db.tailor_sessions.create_index(
                [("resume_id", 1), ("created_at", -1)],
                name="idx_tailor_resume_sessions",
                background=True
            )
            print("  ✓ Created index: idx_tailor_resume_sessions")
        except PyMongoError as e:
            if e.code == 85:
                print("  ⚡ Index already exists: idx_tailor_resume_sessions")
            else:
                print(f"  ✗ Error: {e}")
                raise

        # Record migration
        await self.record_migration(db)

        print(f"\n╔════════════════════════════════════════════════════════════════╗")
        print(f"║  Migration 008 Complete                                       ║")
        print(f"╚════════════════════════════════════════════════════════════════╝\n")
        print("Summary:")
        print("  ✅ Created collection: tailor_sessions (with schema validation)")
        print("  ✅ Created index: idx_tailor_resume_job (unique on resume_id + job_id)")
        print("  ✅ Created index: idx_tailor_resume_sessions (on resume_id + created_at)")

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
        print(f"║  Migration 008: Add tailor_sessions Collection                 ║")
        print(f"╚════════════════════════════════════════════════════════════════╝\n")
        print(f"Database: {db_name}\n")

        migration = Migration008()
        await migration.run(db)

    finally:
        client.close()


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Migration 008: Add tailor_sessions Collection")
    parser.add_argument("--uri", required=True, help="MongoDB connection URI")
    parser.add_argument("--db", default="jobapp", help="Database name")

    args = parser.parse_args()
    asyncio.run(run(args.uri, args.db))
