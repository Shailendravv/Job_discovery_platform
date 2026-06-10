#!/usr/bin/env python3
"""
Migration 001: Initial Schema Setup
Creates all collections with JSON schema validation.

Run with:
    python -m migrations.001_initial_schema --uri "mongodb+srv://..." --db jobapp
    or
    python scripts/run_migrations.py --uri "..."
"""

import asyncio
import sys
from pathlib import Path
from datetime import datetime

try:
    from motor.motor_asyncio import AsyncIOMotorClient
    from pymongo.errors import PyMongoError
except ImportError:
    print("Error: Required packages not installed.")
    print("Run: pip install pymongo motor")
    sys.exit(1)


# JSON Schema definitions
JOBS_SCHEMA = {
    "$jsonSchema": {
        "bsonType": "object",
        "required": ["title", "company", "description"],
        "properties": {
            "title": {
                "bsonType": "string",
                "minLength": 1,
                "maxLength": 300
            },
            "company": {
                "bsonType": "string",
                "minLength": 1,
                "maxLength": 200
            },
            "company_normalized": {
                "bsonType": "string",
                "description": "Normalized company name for deduplication"
            },
            "location": {"bsonType": "string", "maxLength": 500},
            "description": {"bsonType": "string", "minLength": 1},
            "url": {
                "bsonType": ["string", "null"],
                "pattern": "^https?://"
            },
            "apply_url": {
                "bsonType": ["string", "null"],
                "pattern": "^https?://"
            },
            "skills": {
                "bsonType": "array",
                "items": {
                    "bsonType": "string",
                    "minLength": 1,
                    "maxLength": 100
                }
            },
            "job_type": {
                "enum": ["full-time", "part-time", "contract", "internship", "freelance",
                        "remote", "on-site", "hybrid", "unknown"]
            },
            "posted_date": {"bsonType": ["string", "null"]},
            "posted_date_parsed": {"bsonType": ["date", "null"]},
            "salary": {"bsonType": "string", "maxLength": 200},
            "source": {
                "bsonType": "string",
                "enum": ["searxng", "linkedin", "indeed", "glassdoor", "greenhouse",
                        "lever", "unknown"]
            },
            "source_id": {"bsonType": "string"},
            "user_id": {"bsonType": ["string", "null"]},
            "is_saved": {"bsonType": "bool"},
            "match_score": {
                "bsonType": ["int", "null"],
                "minimum": 0,
                "maximum": 100
            },
            "matched_skills": {"bsonType": ["array", "null"]},
            "missing_skills": {"bsonType": ["array", "null"]},
            "dedup_hash": {"bsonType": "string"},
            "search_query": {"bsonType": "string"},
            "created_at": {"bsonType": "date"},
            "updated_at": {"bsonType": "date"}
        }
    }
}

RESUMES_SCHEMA = {
    "$jsonSchema": {
        "bsonType": "object",
        "required": ["resume_id", "extracted_text"],
        "properties": {
            "resume_id": {
                "bsonType": "string",
                "minLength": 1,
                "maxLength": 100
            },
            "user_id": {
                "bsonType": "string",
                "minLength": 1,
                "maxLength": 100
            },
            "filename": {"bsonType": "string", "maxLength": 500},
            "content_type": {
                "bsonType": "string",
                "enum": ["application/pdf", "text/plain",
                        "application/msword",
                        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"]
            },
            "file_size": {
                "bsonType": "int",
                "minimum": 0,
                "maximum": 10485760
            },
            "extracted_text": {"bsonType": "string"},
            "extracted_text_length": {"bsonType": "int", "minimum": 0},
            "parsed_data": {
                "bsonType": "object",
                "properties": {
                    "name": {"bsonType": "string"},
                    "email": {
                        "bsonType": "string",
                        "pattern": "^[^@]+@[^@]+\\.[^@]+$"
                    },
                    "phone": {"bsonType": "string"},
                    "education": {
                        "bsonType": "array",
                        "items": {
                            "bsonType": "object",
                            "properties": {
                                "institution": {"bsonType": "string"},
                                "degree": {"bsonType": "string"},
                                "year": {"bsonType": "int"}
                            }
                        }
                    },
                    "experience": {
                        "bsonType": "array",
                        "items": {
                            "bsonType": "object",
                            "properties": {
                                "company": {"bsonType": "string"},
                                "title": {"bsonType": "string"},
                                "duration": {"bsonType": "string"},
                                "description": {"bsonType": "string"}
                            }
                        }
                    },
                    "skills": {"bsonType": "array", "items": {"bsonType": "string"}},
                    "languages": {"bsonType": "array", "items": {"bsonType": "string"}},
                    "certifications": {"bsonType": "array", "items": {"bsonType": "string"}}
                }
            },
            "processing_status": {
                "enum": ["pending", "processing", "completed", "failed"]
            },
            "processing_error": {"bsonType": "string"},
            "schema_version": {"bsonType": "int"},
            "created_at": {"bsonType": "date"},
            "updated_at": {"bsonType": "date"}
        }
    }
}

USERS_SCHEMA = {
    "$jsonSchema": {
        "bsonType": "object",
        "required": ["email", "username", "password_hash"],
        "properties": {
            "user_id": {
                "bsonType": "string",
                "minLength": 1,
                "maxLength": 100
            },
            "email": {
                "bsonType": "string",
                "pattern": "^[^@]+@[^@]+\\.[^@]+$"
            },
            "email_verified": {"bsonType": "bool"},
            "username": {
                "bsonType": "string",
                "minLength": 3,
                "maxLength": 50,
                "pattern": "^[a-zA-Z0-9_]+$"
            },
            "password_hash": {
                "bsonType": "string",
                "minLength": 60
            },
            "profile": {
                "bsonType": "object",
                "properties": {
                    "first_name": {"bsonType": "string", "maxLength": 100},
                    "last_name": {"bsonType": "string", "maxLength": 100},
                    "bio": {"bsonType": "string", "maxLength": 1000},
                    "avatar_url": {"bsonType": "string", "pattern": "^https?://"},
                    "location": {"bsonType": "string", "maxLength": 200},
                    "linkedin_url": {
                        "bsonType": "string",
                        "pattern": "^https?://(www\\.)?linkedin\\.com"
                    },
                    "github_url": {
                        "bsonType": "string",
                        "pattern": "^https?://(www\\.)?github\\.com"
                    },
                    "website": {"bsonType": "string", "pattern": "^https?://"}
                }
            },
            "preferences": {
                "bsonType": "object",
                "properties": {
                    "notifications_enabled": {"bsonType": "bool"},
                    "preferred_job_types": {
                        "bsonType": "array",
                        "items": {
                            "enum": ["full-time", "part-time", "contract", "internship",
                                    "freelance", "remote"]
                        }
                    },
                    "preferred_locations": {"bsonType": "array", "items": {"bsonType": "string"}},
                    "search_radius_km": {
                        "bsonType": "int",
                        "minimum": 0,
                        "maximum": 500
                    }
                }
            },
            "role": {
                "enum": ["user", "admin", "moderator"]
            },
            "is_active": {"bsonType": "bool"},
            "last_login_at": {"bsonType": ["date", "null"]},
            "created_at": {"bsonType": "date"},
            "updated_at": {"bsonType": "date"}
        }
    }
}

APPLICATIONS_SCHEMA = {
    "$jsonSchema": {
        "bsonType": "object",
        "required": ["user_id", "job_id", "status"],
        "properties": {
            "application_id": {
                "bsonType": "string",
                "minLength": 1,
                "maxLength": 100
            },
            "user_id": {
                "bsonType": "string",
                "minLength": 1,
                "maxLength": 100
            },
            "job_id": {"bsonType": "objectId"},
            "resume_id": {"bsonType": "string"},
            "status": {
                "enum": [
                    "applied", "emailed", "called", "screening", "interview_scheduled",
                    "interview_completed", "offer_extended", "offer_accepted",
                    "offer_declined", "rejected", "withdrawn", "archived"
                ]
            },
            "notes": {"bsonType": "string", "maxLength": 5000},
            "applied_at": {"bsonType": "date"},
            "updated_at": {"bsonType": "date"},
            "external_application_url": {
                "bsonType": "string",
                "pattern": "^https?://"
            },
            "follow_up_date": {"bsonType": ["date", "null"]},
            "status_history": {
                "bsonType": "array",
                "items": {
                    "bsonType": "object",
                    "properties": {
                        "status": {"bsonType": "string"},
                        "changed_at": {"bsonType": "date"},
                        "notes": {"bsonType": "string"}
                    }
                }
            },
            "is_deleted": {"bsonType": "bool"},
            "deleted_at": {"bsonType": ["date", "null"]}
        }
    }
}

COMPANIES_SCHEMA = {
    "$jsonSchema": {
        "bsonType": "object",
        "required": ["name"],
        "properties": {
            "name": {
                "bsonType": "string",
                "minLength": 1,
                "maxLength": 200
            },
            "name_normalized": {"bsonType": "string"},
            "domain": {
                "bsonType": "string",
                "pattern": "^[a-z0-9][a-z0-9-]*\\.[a-z]{2,}$"
            },
            "careers_url": {"bsonType": "string", "pattern": "^https?://"},
            "logo_url": {"bsonType": "string", "pattern": "^https?://"},
            "description": {"bsonType": "string", "maxLength": 5000},
            "industry": {"bsonType": "string", "maxLength": 200},
            "size": {
                "enum": ["1-10", "11-50", "51-200", "201-1000", "1001-5000",
                        "5001-10000", "10000+"]
            },
            "headquarters": {"bsonType": "string", "maxLength": 200},
            "founded_year": {
                "bsonType": "int",
                "minimum": 1800,
                "maximum": 2025
            },
            "linkedin_company_id": {"bsonType": "string"},
            "job_count": {"bsonType": "int", "minimum": 0},
            "last_job_posted": {"bsonType": ["date", "null"]},
            "created_at": {"bsonType": "date"},
            "updated_at": {"bsonType": "date"}
        }
    }
}

SKILLS_SCHEMA = {
    "$jsonSchema": {
        "bsonType": "object",
        "required": ["name", "category"],
        "properties": {
            "name": {
                "bsonType": "string",
                "minLength": 1,
                "maxLength": 100
            },
            "name_normalized": {"bsonType": "string"},
            "category": {
                "enum": [
                    "programming_language", "framework", "database", "cloud", "devops",
                    "frontend", "backend", "mobile", "data_science", "design",
                    "project_management", "soft_skill", "tool", "platform",
                    "methodology", "certification", "testing"
                ]
            },
            "subcategory": {"bsonType": ["string", "null"], "maxLength": 100},
            "synonyms": {"bsonType": "array", "items": {"bsonType": "string"}},
            "popularity": {"bsonType": "int", "minimum": 0},
            "is_active": {"bsonType": "bool"},
            "created_at": {"bsonType": "date"},
            "updated_at": {"bsonType": "date"}
        }
    }
}

SEARCH_HISTORY_SCHEMA = {
    "$jsonSchema": {
        "bsonType": "object",
        "required": ["user_id", "query"],
        "properties": {
            "user_id": {
                "bsonType": "string",
                "minLength": 1,
                "maxLength": 100
            },
            "query": {
                "bsonType": "string",
                "minLength": 1,
                "maxLength": 1000
            },
            "parsed_query": {
                "bsonType": "object",
                "properties": {
                    "location": {"bsonType": "string"},
                    "job_types": {"bsonType": "array", "items": {"bsonType": "string"}},
                    "skills": {"bsonType": "array", "items": {"bsonType": "string"}},
                    "companies": {"bsonType": "array", "items": {"bsonType": "string"}},
                    "experience_level": {"bsonType": "string"}
                }
            },
            "results_count": {"bsonType": "int", "minimum": 0},
            "search_sources": {"bsonType": "array", "items": {"bsonType": "string"}},
            "duration_ms": {"bsonType": "int", "minimum": 0},
            "user_agent": {"bsonType": "string", "maxLength": 500},
            "ip_address": {
                "bsonType": "string",
                "pattern": "^(?:[0-9]{1,3}\\.){3}[0-9]{1,3}$"
            },
            "session_id": {"bsonType": "string"},
            "created_at": {"bsonType": "date"}
        }
    }
}

JOB_MATCHES_SCHEMA = {
    "$jsonSchema": {
        "bsonType": "object",
        "required": ["user_id", "job_id", "resume_id", "match_score"],
        "properties": {
            "match_id": {
                "bsonType": "string",
                "minLength": 1,
                "maxLength": 100
            },
            "user_id": {
                "bsonType": "string",
                "minLength": 1,
                "maxLength": 100
            },
            "job_id": {"bsonType": "objectId"},
            "resume_id": {"bsonType": "string"},
            "match_score": {
                "bsonType": "int",
                "minimum": 0,
                "maximum": 100
            },
            "match_details": {
                "bsonType": "object",
                "properties": {
                    "skills_match_percentage": {
                        "bsonType": "double",
                        "minimum": 0,
                        "maximum": 100
                    },
                    "experience_match_score": {
                        "bsonType": "int",
                        "minimum": 0,
                        "maximum": 100
                    },
                    "education_match_score": {
                        "bsonType": "int",
                        "minimum": 0,
                        "maximum": 100
                    },
                    "keyword_relevance": {
                        "bsonType": "int",
                        "minimum": 0,
                        "maximum": 100
                    }
                }
            },
            "matched_skills": {
                "bsonType": "array",
                "items": {
                    "bsonType": "object",
                    "properties": {
                        "skill": {"bsonType": "string"},
                        "confidence": {"bsonType": "double"},
                        "job_requirement_level": {
                            "enum": ["required", "preferred", "nice-to-have"]
                        }
                    }
                }
            },
            "missing_skills": {
                "bsonType": "array",
                "items": {
                    "bsonType": "object",
                    "properties": {
                        "skill": {"bsonType": "string"},
                        "importance": {"enum": ["required", "preferred"]}
                    }
                }
            },
            "suggested_improvements": {"bsonType": "array", "items": {"bsonType": "string"}},
            "tailored_resume_snippet": {"bsonType": "string", "maxLength": 5000},
            "created_at": {"bsonType": "date"},
            "expires_at": {"bsonType": ["date", "null"]}
        }
    }
}

MIGRATIONS_COLLECTION_SCHEMA = {
    "$jsonSchema": {
        "bsonType": "object",
        "required": ["migration", "applied_at", "checksum"],
        "properties": {
            "migration": {"bsonType": "string"},
            "version": {"bsonType": "int"},
            "applied_at": {"bsonType": "date"},
            "checksum": {"bsonType": "string"},
            "rolled_back": {"bsonType": "bool", "description": "Whether this migration was rolled back"},
            "rolled_back_at": {"bsonType": ["date", "null"]}
        }
    }
}


class Migration001:
    """Initial schema setup - creates all collections with validation."""

    name = "001_initial_schema"
    version = 1

    SCHEMAS = {
        "jobs": JOBS_SCHEMA,
        "resumes": RESUMES_SCHEMA,
        "users": USERS_SCHEMA,
        "applications": APPLICATIONS_SCHEMA,
        "companies": COMPANIES_SCHEMA,
        "skills": SKILLS_SCHEMA,
        "searchHistory": SEARCH_HISTORY_SCHEMA,
        "jobMatches": JOB_MATCHES_SCHEMA,
        "_migrations": MIGRATIONS_COLLECTION_SCHEMA,
    }

    async def run(self, db):

        # Enable profiling during development
        try:
            await db.command({"profile": 1, "slowms": 100})
            print("  ✓ Enabled query profiling (slowms: 100ms)")
        except Exception as e:
            print(f"  ⚠ Profiling setup: {e}")

        # Create collections with validation
        print("\nCreating collections with validation...")
        created_count = 0

        for collection_name, validator in self.SCHEMAS.items():
            try:
                options = {
                    "validator": validator,
                    "validationLevel": "moderate",
                    "validationAction": "error"
                }

                # Create the collection
                await db.create_collection(collection_name, **options)
                print(f"  ✓ Created collection: {collection_name}")
                created_count += 1

                # For migrations collection, create unique index
                if collection_name == "_migrations":
                    await db["_migrations"].create_index(
                        "migration",
                        unique=True,
                        name="idx_migrations_name"
                    )
                    print("  ✓ Created index on _migrations.migration")

            except PyMongoError as e:
                if e.code == 48:  # NamespaceExists
                    print(f"  ⚡ Collection already exists: {collection_name}")
                else:
                    print(f"  ✗ Error creating {collection_name}: {e}")
                    raise

        # Record migration
        await self.record_migration(db, created_count)

    async def record_migration(self, db, created_count):
        """Record that this migration was applied."""
        now = datetime.utcnow()
        try:
            await db["_migrations"].insert_one({
                "migration": self.name,
                "version": self.version,
                "applied_at": now,
                "checksum": "COMPUTED_DURING_DEPLOYMENT",
                "rolled_back": False,
                "rolled_back_at": None
            })
            print(f"\n╔════════════════════════════════════════════════════════════════╗")
            print(f"║  Migration 001 Complete: {created_count} collections created  ║")
            print(f"╚════════════════════════════════════════════════════════════════╝")
        except PyMongoError as e:
            if e.code == 11000:  # Duplicate key
                print(f"\n⚠ Migration already recorded")
            else:
                raise

        print("\nNext steps:")
        print("  1. Run migration 002 to add denormalized fields")
        print("  2. Create indexes (see MONGODB_SCHEMAS_ATLAS.md)")


async def run(uri: str, db_name: str = "jobapp"):
    """Run this migration."""
    client = AsyncIOMotorClient(uri)
    db = client[db_name]

    try:
        print(f"\n╔════════════════════════════════════════════════════════════════╗")
        print(f"║  Migration 001: Initial Schema Setup                          ║")
        print(f"╚════════════════════════════════════════════════════════════════╝")
        print(f"\nDatabase: {db_name}")

        migration = Migration001()
        await migration.run(db)

    finally:
        client.close()


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Migration 001: Initial Schema Setup")
    parser.add_argument("--uri", required=True, help="MongoDB connection URI")
    parser.add_argument("--db", default="jobapp", help="Database name")

    args = parser.parse_args()

    asyncio.run(run(args.uri, args.db))
