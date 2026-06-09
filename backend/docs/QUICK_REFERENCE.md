# MongoDB Atlas Setup - Quick Reference

## One-Line Setup Commands

```bash
# 1. Create database and collections with validation
mongosh "mongodb+srv://..." jobapp migrations/001_initial_schema.js

# 2. Apply all migrations
python scripts/run_migrations.py --uri "mongodb+srv://..." --db jobapp

# 3. Create all indexes
mongosh "mongodb+srv://..." scripts/create_indexes.js

# 4. Generate test data
python scripts/generate_test_data.py --uri "mongodb+srv://..." --db jobapp --jobs 1000 --users 50

# 5. Rollback everything (DESTRUCTIVE)
mongosh "mongodb+srv://..." migrations/ROLLBACK.js --eval 'confirm="YES"'
```

---

## Production Deployment Checklist

- [ ] Set `MONGODB_URI` in `.env` with Atlas connection string
- [ ] Create Atlas database user with `readWrite` on `jobapp`
- [ ] Whitelist production IPs in Atlas Network Access
- [ ] Enable backup (daily snapshots, 14-day retention)
- [ ] Configure cluster tier based on expected load (M10 for dev, M20+ for production)
- [ ] Run all migrations in Atlas UI or via runner
- [ ] Create Atlas Search index for `jobs` collection
- [ ] Configure alerts (CPU > 80%, Memory > 85%, Disk < 20GB free)
- [ ] Enable Performance Advisor
- [ ] Test connection from app startup

---

## Atlas Search Index JSON

Import this in Atlas UI → Collections → Search Indexes → Create Search Index:

```json
{
  "mappings": {
    "dynamic": false,
    "fields": {
      "title": {
        "type": "string",
        "analyzer": "lucene.english"
      },
      "company": { "type": "string" },
      "description": {
        "type": "string",
        "analyzer": "lucene.english"
      },
      "skills": { "type": "string" },
      "location": { "type": "string" },
      "job_type": { "type": "string" }
    }
  }
}
```

---

## Python Integration Example

```python
# backend/app/core/database.py (updated)

from motor.motor_asyncio import AsyncIOMotorClient
from pymongo.write_concern import WriteConcern
from pymongo.read_concern import ReadConcern
import os

class Database:
    client: AsyncIOMotorClient = None
    db = None

    @classmethod
    async def connect(cls, uri: str = None, db_name: str = "jobapp"):
        uri = uri or os.getenv("MONGODB_URI")
        if not uri:
            raise ValueError("MONGODB_URI environment variable required")

        cls.client = AsyncIOMotorClient(
            uri,
            maxPoolSize=100,
            minPoolSize=10,
            maxIdleTimeMS=30000,
            waitQueueTimeoutMS=5000,
            retryWrites=True,
            w="majority",
            readConcernLevel="majority"
        )

        cls.db = cls.client[db_name]

        # Verify connection
        await cls.client.admin.command("ping")
        print(f"Connected to MongoDB: {db_name}")

        # Ensure indexes exist (call on startup)
        await cls.create_indexes()

        return cls.db

    @classmethod
    async def create_indexes(cls):
        """Create all required indexes if they don't exist."""
        db = cls.db

        # Jobs indexes
        await db.jobs.create_index([("company_normalized", 1)], unique=True,
                                    partialFilterExpression={"is_deleted": {"$exists": False}})
        await db.jobs.create_index([("created_at", -1)])
        await db.jobs.create_index([("location", 1), ("job_type", 1), ("created_at", -1)])
        await db.jobs.create_index([("skills", 1)])
        await db.jobs.create_index([("match_score", -1)])

        # Users indexes
        await db.users.create_index([("email", 1)], unique=True)
        await db.users.create_index([("user_id", 1)], unique=True)

        # Applications indexes
        await db.applications.create_index([("user_id", 1), ("job_id", 1)], unique=True,
                                           partialFilterExpression={"is_deleted": False})
        await db.applications.create_index([("user_id", 1), ("status", 1), ("applied_at", -1)])

        print("All indexes ensured")

    @classmethod
    async def close(cls):
        if cls.client:
            cls.client.close()
```

Add to `main.py`:

```python
from app.core.database import Database

@app.on_event("startup")
async def startup_db():
    Database.connect()

@app.on_event("shutdown")
async def shutdown_db():
    await Database.close()

# Dependency
async def get_db():
    return Database.db
```

---

## Schema Changes Summary

| Collection | Status | Size Estimate | Retention |
|------------|--------|---------------|-----------|
| `jobs` | **Production Ready** | 10K - 100K | 90 days (TTL) |
| `resumes` | **Production Ready** | 100 - 10K | Permanent |
| `users` | Ready for Auth | 100 - 10K | Permanent |
| `applications` | Ready for Feature | 100 - 100K | 7 years (archive) |
| `companies` | Ready for Feature | 1K - 10K | Permanent |
| `skills` | Ready for Feature | 1K - 5K | Permanent |
| `searchHistory` | Ready for Analytics | 100K - 1M | 1 year (TTL) |
| `jobMatches` | Ready for Feature | 1K - 100K | 30 days (TTL) |

---

## Troubleshooting

**Index build time too long on large collections?**
```javascript
// Build indexes in background
db.collection.createIndex({ field: 1 }, { background: true });
```

**Change streams not working?**
- Ensure replica set enabled (Atlas provides this)
- Check fullDocument: "updateLookup" requires readConcern majority
- Add clusterMonitor role to database user

**TTL indexes not deleting?**
- Ensure field is a Date type, not string
- TTL task runs every 60 seconds
- Documents are deleted within 48 hours of expiration

**Atlas Search not returning results?**
- Wait 5-10 minutes after index creation
- Check index status in Atlas UI (should be "READY")
- Use `$search` aggregation stage, not text index

---

## Files Reference

```
backend/
├── migrations/
│   ├── 001_initial_schema.js      # Create all 8 collections with validation
│   ├── 002_job_denormalization.js # Add computed fields
│   ├── 003_skills_taxonomy.js     # Populate skills taxonomy
│   ├── 004_company_materialized_view.js  # Build company summaries
│   ├── 005_change_streams.js      # Document change stream setup
│   └── ROLLBACK.js                # Full rollback script
├── scripts/
│   ├── run_migrations.py          # Python migration runner
│   ├── generate_test_data.py      # Test data generator
│   ├── create_indexes.js          # Index creation utility
│   └── create_atlas_search_index.json  # Atlas Search config
└── docs/
    ├── MONGODB_SCHEMAS_ATLAS.md   # Full documentation
    └── QUICK_REFERENCE.md         # This file
```

---

## Monitoring Queries

Check slow operations (last 24h):
```javascript
db.system.profile.find({
  "ts": { $gte: new Date(Date.now() - 24 * 60 * 60 * 1000) },
  "millis": { $gt: 100 }
}).sort({ millis: -1 }).pretty();
```

Index usage stats:
```javascript
db.jobs.aggregate([{ $indexStats: {} }]).pretty();
```

Unused indexes to drop:
```javascript
db.jobs.aggregate([
  { $indexStats: {} },
  { $match: { accessCount: { $eq: 0 } } }
]).forEach(idx => print(`Consider dropping: ${idx.name}`));
```
