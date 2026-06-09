#!/usr/bin/env python3
"""
Migration 003: Skills Taxonomy Population

Populates the skills collection with:
- Initial taxonomy of 50+ common skills
- Skills extracted from existing job postings
- Bulk upsert with category assignments

Run with:
    python -m migrations.003_skills_taxonomy --uri "..." --db jobapp
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


# Skills taxonomy - 50+ commonly used skills
SKILLS_TAXONOMY = [
    # Programming Languages
    {"name": "python", "category": "programming_language", "synonyms": ["py", "python3"]},
    {"name": "javascript", "category": "programming_language", "synonyms": ["js", "es6", "node.js"]},
    {"name": "typescript", "category": "programming_language", "synonyms": ["ts"]},
    {"name": "java", "category": "programming_language", "synonyms": ["jdk", "spring"]},
    {"name": "csharp", "category": "programming_language", "synonyms": ["c#", "dotnet", ".net"]},
    {"name": "go", "category": "programming_language", "synonyms": ["golang"]},
    {"name": "rust", "category": "programming_language"},
    {"name": "ruby", "category": "programming_language", "synonyms": ["rails"]},
    {"name": "php", "category": "programming_language", "synonyms": ["laravel"]},
    {"name": "swift", "category": "programming_language", "synonyms": ["ios", "objective-c"]},
    {"name": "kotlin", "category": "programming_language", "synonyms": ["android"]},
    {"name": "scala", "category": "programming_language"},
    {"name": "r", "category": "data_science"},

    # Frontend
    {"name": "react", "category": "frontend", "synonyms": ["react.js", "reactjs"]},
    {"name": "vue", "category": "frontend", "synonyms": ["vue.js", "vuejs"]},
    {"name": "angular", "category": "frontend", "synonyms": ["angularjs", "angular.js"]},
    {"name": "nextjs", "category": "frontend", "synonyms": ["next.js"]},
    {"name": "svelte", "category": "frontend"},
    {"name": "html", "category": "frontend"},
    {"name": "css", "category": "frontend"},
    {"name": "sass", "category": "frontend"},
    {"name": "webpack", "category": "frontend"},
    {"name": "babel", "category": "frontend"},

    # Backend
    {"name": "nodejs", "category": "backend", "synonyms": ["node.js", "node"]},
    {"name": "express", "category": "backend", "synonyms": ["express.js"]},
    {"name": "django", "category": "backend"},
    {"name": "fastapi", "category": "backend"},
    {"name": "flask", "category": "backend"},
    {"name": "spring", "category": "backend", "synonyms": ["spring boot"]},
    {"name": "spring boot", "category": "backend"},
    {"name": "laravel", "category": "backend"},
    {"name": "asp.net", "category": "backend", "synonyms": [".net"]},

    # Databases
    {"name": "postgresql", "category": "database", "synonyms": ["postgres"]},
    {"name": "mongodb", "category": "database"},
    {"name": "mysql", "category": "database"},
    {"name": "redis", "category": "database"},
    {"name": "elasticsearch", "category": "database"},
    {"name": "cassandra", "category": "database"},
    {"name": "dynamodb", "category": "database"},
    {"name": "sqlite", "category": "database"},
    {"name": "oracle", "category": "database"},
    {"name": "mariadb", "category": "database"},
    {"name": "neo4j", "category": "database"},
    {"name": "firebase", "category": "database"},

    # Cloud
    {"name": "aws", "category": "cloud", "synonyms": ["amazon web services"]},
    {"name": "azure", "category": "cloud", "synonyms": ["microsoft azure"]},
    {"name": "gcp", "category": "cloud", "synonyms": ["google cloud"]},
    {"name": "terraform", "category": "cloud"},
    {"name": "kubernetes", "category": "cloud", "synonyms": ["k8s"]},
    {"name": "docker", "category": "cloud"},
    {"name": "serverless", "category": "cloud"},
    {"name": "lambda", "category": "cloud"},
    {"name": "s3", "category": "cloud"},
    {"name": "ec2", "category": "cloud"},
    {"name": "cloudformation", "category": "cloud"},

    # DevOps
    {"name": "ci/cd", "category": "devops"},
    {"name": "jenkins", "category": "devops"},
    {"name": "gitlab ci", "category": "devops"},
    {"name": "github actions", "category": "devops"},
    {"name": "ansible", "category": "devops"},
    {"name": "chef", "category": "devops"},
    {"name": "puppet", "category": "devops"},
    {"name": "circleci", "category": "devops"},
    {"name": "prometheus", "category": "devops"},
    {"name": "grafana", "category": "devops"},

    # Data Science
    {"name": "pandas", "category": "data_science"},
    {"name": "numpy", "category": "data_science"},
    {"name": "tensorflow", "category": "data_science"},
    {"name": "pytorch", "category": "data_science"},
    {"name": "scikit-learn", "category": "data_science"},
    {"name": "jupyter", "category": "data_science"},
    {"name": "apache spark", "category": "data_science"},
    {"name": "hadoop", "category": "data_science"},
    {"name": "kafka", "category": "data_science"},
    {"name": "airflow", "category": "data_science"},
    {"name": "databricks", "category": "data_science"},

    # Project Management
    {"name": "agile", "category": "project_management", "synonyms": ["scrum"]},
    {"name": "scrum", "category": "project_management"},
    {"name": "kanban", "category": "project_management"},
    {"name": "jira", "category": "project_management"},
    {"name": "trello", "category": "project_management"},
    {"name": "asana", "category": "project_management"},

    # Mobile
    {"name": "ios", "category": "mobile"},
    {"name": "android", "category": "mobile"},
    {"name": "react native", "category": "mobile"},
    {"name": "flutter", "category": "mobile"},

    # Testing
    {"name": "jest", "category": "testing"},
    {"name": "pytest", "category": "testing"},
    {"name": "selenium", "category": "testing"},
    {"name": "cypress", "category": "testing"},
    {"name": "mocha", "category": "testing"},
    {"name": "junit", "category": "testing"},

    # Tools
    {"name": "git", "category": "tool"},
    {"name": "github", "category": "tool"},
    {"name": "gitlab", "category": "tool"},
    {"name": "bitbucket", "category": "tool"},
    {"name": "vs code", "category": "tool"},
    {"name": "intellij", "category": "tool"},

    # Design
    {"name": "figma", "category": "design"},
    {"name": "sketch", "category": "design"},
    {"name": "adobe xd", "category": "design"},
    {"name": "photoshop", "category": "design"},

    # Soft Skills
    {"name": "communication", "category": "soft_skill"},
    {"name": "leadership", "category": "soft_skill"},
    {"name": "problem-solving", "category": "soft_skill"},
    {"name": "teamwork", "category": "soft_skill"},
    {"name": "time-management", "category": "soft_skill"},
    {"name": "critical thinking", "category": "soft_skill"},
    {"name": "adaptability", "category": "soft_skill"},
    {"name": "collaboration", "category": "soft_skill"},
]


class Migration003:
    """Skills taxonomy population."""
    name = "003_skills_taxonomy"
    version = 3

    def normalize_name(self, name: str) -> str:
        """Normalize skill name for unique indexing."""
        return name.lower().replace(/[^a-z0-9]/g, '')

    async def run(self, db):
        print(f"\n╔════════════════════════════════════════════════════════════════╗")
        print(f"║  Migration 003: Skills Taxonomy Population                   ║")
        print(f"╚════════════════════════════════════════════════════════════════╝\n")

        now = datetime.utcnow()

        # Step 1: Insert/update taxonomy
        print("Step 1: Inserting initial skills taxonomy...")
        bulk_ops = []

        for skill in SKILLS_TAXONOMY:
            name_normalized = skill["name"].lower().strip()
            bulk_ops.append({
                "update_one": {
                    "filter": {"name_normalized": name_normalized},
                    "update": {
                        "$setOnInsert": {
                            "name": skill["name"],
                            "name_normalized": name_normalized,
                            "category": skill["category"],
                            "subcategory": None,
                            "synonyms": skill.get("synonyms", []),
                            "is_active": True,
                            "created_at": now
                        },
                        "$set": {"updated_at": now}
                    },
                    "upsert": True
                }
            })

        if bulk_ops:
            result = await db.skills.bulk_write(bulk_ops, ordered=False)
            print(f"  ✓ Taxonomy: {result.upserted_count} inserted, {result.modified_count} updated")

        # Verify taxonomy count
        taxonomy_count = await db.skills.count_documents({"is_active": True})
        print(f"  ℹ Total skills in taxonomy: {taxonomy_count}")

        # Step 2: Extract skills from existing jobs
        print("\nStep 2: Extracting skills from existing job postings...")

        try:
            # Get skills from jobs (unwind skills array)
            job_skills_cursor = db.jobs.aggregate([
                {"$unwind": "$skills"},
                {"$group": {"_id": {"$toLower": "$skills"}, "count": {"$sum": 1}}},
                {"$sort": {"count": -1}},
                {"$limit": 500}
            ])

            job_skills = await job_skills_cursor.to_list(None)
            print(f"  ℹ Found {len(job_skills)} unique skills in existing jobs")

            # Bulk upsert
            additional_ops = []
            now2 = datetime.utcnow()
            batch_size = 1000
            processed = 0

            for skill_doc in job_skills:
                skill_name = skill_doc["_id"]
                if not skill_name or len(skill_name) > 100:
                    continue

                name_normalized = skill_name.replace(/[^a-z0-9]/g, '')
                if not name_normalized:
                    continue

                additional_ops.append({
                    "update_one": {
                        "filter": {"name_normalized": name_normalized},
                        "update": {
                            "$setOnInsert": {
                                "name": skill_name,
                                "name_normalized": name_normalized,
                                "category": "tool",
                                "is_active": True,
                                "created_at": now2
                            },
                            "$set": {
                                "updated_at": now2,
                                "popularity": skill_doc["count"]
                            }
                        },
                        "upsert": True
                    }
                })

                if len(additional_ops) >= batch_size:
                    await db.skills.bulk_write(additional_ops, ordered=False)
                    processed += len(additional_ops)
                    additional_ops = []
                    print(f"    ... processed {processed} skills")

            if additional_ops:
                await db.skills.bulk_write(additional_ops, ordered=False)
                processed += len(additional_ops)

            print(f"  ✓ Extracted {processed} additional skills from jobs")

        except Exception as e:
            print(f"  ⚠ Could not extract skills from jobs: {e}")
            print("    (This is OK if no jobs exist yet)")

        # Step 3: Create indexes
        print("\nStep 3: Creating skills indexes...")

        try:
            await db.skills.create_index(
                "name_normalized",
                unique=True,
                name="idx_skills_normalized"
            )
            print("  ✓ Created unique index on name_normalized")
        except PyMongoError as e:
            if e.code != 85:  # IndexOptionsConflict (already exists)
                print(f"  ⚠ Index error: {e}")

        try:
            await db.skills.create_index(
                [("category", 1), ("popularity", -1)],
                name="idx_skills_category_popular"
            )
            print("  ✓ Created category/popularity index")
        except PyMongoError:
            pass

        # Statistics
        total_skills = await db.skills.count_documents({})
        active_skills = await db.skills.count_documents({"is_active": True})

        print(f"\nSkills Collection Stats:")
        print(f"  Total skills: {total_skills}")
        print(f"  Active skills: {active_skills}")
        print(f"  Category breakdown:")

        categories = await db.skills.aggregate([
            {"$match": {"is_active": True}},
            {"$group": {"_id": "$category", "count": {"$sum": 1}}},
            {"$sort": {"count": -1}}
        ]).to_list(None)

        for cat in categories[:10]:  # Top 10
            print(f"    {cat['_id']}: {cat['count']}")

        # Record migration
        await self.record_migration(db)

        print(f"\n╔════════════════════════════════════════════════════════════════╗")
        print(f"║  Migration 003 Complete                                       ║")
        print(f"╚════════════════════════════════════════════════════════════════╝\n")
        print("Next steps:")
        print("  1. Run migration 004 for company materialized view")

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
        migration = Migration003()
        await migration.run(db)
    finally:
        client.close()


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Migration 003: Skills Taxonomy")
    parser.add_argument("--uri", required=True, help="MongoDB connection URI")
    parser.add_argument("--db", default="jobapp", help="Database name")

    args = parser.parse_args()
    asyncio.run(run(args.uri, args.db))
