#!/usr/bin/env mongosh
// MongoDB Migration: 005_change_streams.js
// Documents change stream setup (implementation guidance)

"use strict";

const dbName = context ? context.getArgs()[0] : "jobapp";
const db = db.getSiblingDB(dbName);

print(`\n╔════════════════════════════════════════════════════════════════╗`);
print(`║  Migration 005: Change Streams Documentation                 ║`);
print(`╚════════════════════════════════════════════════════════════════╝\n`);

print("Change streams require a MongoDB replica set.");
print("Atlas provides replica sets automatically.\n");

print("╔════════════════════════════════════════════════════════════════╗");
print(`║  Prerequisites:                                                 ║`);
print("║  1. Enable Change Streams: db.getSiblingDB('admin')           ║");
print("║     .runCommand({ enableSharding: false })                     ║");
print("║  2. Verify replica set: rs.status()                           ║");
print("╚════════════════════════════════════════════════════════════════╝\n");

print("This migration documents the change stream implementations.\n");

// Create a collection for tracking change stream checkpoints
print("1. Creating change_stream_checkpoints collection...");
db.createCollection("change_stream_checkpoints");
db.change_stream_checkpoints.createIndex(
  { _id: 1 },
  { name: "idx_cs_checkpoint_id", unique: true }
);
print("   ✓ Created checkpoint tracking collection\n");

// Document the job creation stream
print("2. Job Creation Stream (Updates skill popularity):");
print(`
   // Python implementation in your background worker:
   async def job_creation_stream():
       async with await db.jobs.watch(
           pipeline=[{"$match": {"operationType": "insert"}}],
           full_document="updateLookup"
       ) as stream:
           async for change in stream:
               job = change["fullDocument"]

               # Update skill popularity in parallel
               skill_updates = []
               for skill in job.get("skills", []):
                   skill_updates.append(
                       db.skills.update_one(
                           {"name_normalized": skill.lower()},
                           {"$inc": {"popularity": 1}},
                           upsert=True
                       )
                   )

               # Update company last_job_posted
               if job.get("company"):
                   await db.companies.update_one(
                       {"name_normalized": job["company"].lower().strip()},
                       {
                           "$set": {
                               "last_job_posted": job["created_at"],
                               "updated_at": datetime.utcnow()
                           }
                       }
                   )

               # Batch skill updates
               if skill_updates:
                   await asyncio.gather(*skill_updates)
`);

// Document the application status stream
print("3. Application Status Change Stream (Notifications):");
print(`
   # Trigger notifications when application status changes
   async def application_status_stream():
       async with await db.applications.watch(
           pipeline=[
               {"$match": {"operationType": "update",
                          "updateDescription.updatedFields.status": {"$exists": true}}}
           ],
           full_document="updateLookup"
       ) as stream:
           async for change in stream:
               application = change["fullDocument"]
               user_id = application["user_id"]
               new_status = application["status"]

               # Send notification based on status
               notifications = {
                   "offer_extended": "Congratulations! You have an offer!",
                   "interview_scheduled": "Interview scheduled - prepare!",
                   "rejected": "Don't give up - keep applying!"
               }

               if new_status in notifications:
                   await send_notification(
                       user_id=user_id,
                       type="application_status",
                       title=new_status.replace("_", " ").title(),
                       message=notifications[new_status],
                       data={"application_id": str(application["_id"])}
                   )
`);

// Document the search history aggregation stream
print("4. Search History Aggregation (Real-time Analytics):");
print(`
   async def search_analytics_stream():
       async with await db.searchHistory.watch(
           full_document="updateLookup"
       ) as stream:
           async for change in stream:
               search = change["fullDocument"]

               # Update Redis cache for trending queries
               query_key = f"trending:{search['query'][:50]}"
               await redis_client.incr(query_key)
               await redis_client.expire(query_key, 3600)  # 1 hour TTL

               # Every 100 searches, update materialized view
               if search["created_at"].minute == 0:
                   await update_trending_queries_view()
`);

// Store stream configurations
print("5. Storing Stream Configurations in Database:");
print(`
   // Store stream checkpoints to resume after restart
   const streamConfigs = [
     {
       name: "job_creation_skills",
       collection: "jobs",
       pipeline: [{"$match": {"operationType": "insert"}}],
       checkpoint_collection: "change_stream_checkpoints"
     },
     {
       name: "application_status",
       collection: "applications",
       pipeline: [{"$match": {"operationType": "update",
                              "updateDescription.updatedFields.status": {"$exists": true}}}],
       checkpoint_collection: "change_stream_checkpoints"
     },
     {
       name: "search_analytics",
       collection: "searchHistory",
       pipeline: [],
       checkpoint_collection: "change_stream_checkpoints"
     }
   ];

   // Insert stream configurations
   db.change_stream_configs.insertMany(streamConfigs);
`);

// Create change stream configs collection
print("\n6. Creating change_stream_configs collection...");
db.createCollection("change_stream_configs");
db.change_stream_configs.createIndex(
  { name: 1 },
  { name: "idx_cs_config_name", unique: true }
);
print("   ✓ Created change_stream_configs collection");

// Insert default configs
const configs = [
  {
    name: "job_creation_skills",
    collection: "jobs",
    pipeline: [
      { $match: { operationType: "insert" } }
    ],
    is_active: true,
    worker_class: "JobCreationSkillsUpdater",
    created_at: new Date()
  },
  {
    name: "application_status",
    collection: "applications",
    pipeline: [
      {
        $match: {
          operationType: "update",
          "updateDescription.updatedFields.status": { $exists: true }
        }
      }
    ],
    is_active: true,
    worker_class: "ApplicationStatusNotifier",
    created_at: new Date()
  },
  {
    name: "company_stats",
    collection: "jobs",
    pipeline: [
      { $match: { operationType: ["insert", "update", "delete"] } }
    ],
    is_active: true,
    worker_class: "CompanyStatsUpdater",
    created_at: new Date()
  }
];

try {
  db.change_stream_configs.insertMany(configs, { ordered: false });
  print(`  ✓ Inserted ${configs.length} stream configurations`);
} catch (e) {
  if (e.code === 11000) {
    print("  ⚡ Stream configurations already exist");
  } else {
    throw e;
  }
}

// Create config index
db.change_stream_configs.createIndex(
  { is_active: 1, name: 1 },
  { name: "idx_cs_config_active" }
);

print("\n7. Change Stream Worker Template (Python):");
print(`
import asyncio
import json
from datetime import datetime
from motor.motor_asyncio import AsyncIOMotorClient

class ChangeStreamWorker:
    def __init__(self, mongodb_uri: str, db_name: str):
        self.client = AsyncIOMotorClient(mongodb_uri)
        self.db = self.client[db_name]

    async def run_stream(self, config: dict):
        '''Run a single change stream based on configuration.'''
        collection = self.db[config["collection"]]
        pipeline = config.get("pipeline", [])

        print(f"Starting change stream: {config['name']}")

        async with collection.watch(
            pipeline=pipeline,
            full_document="updateLookup",
            max_await_time_ms=5000
        ) as stream:
            async for change in stream:
                try:
                    await self.process_change(config["worker_class"], change)
                except Exception as e:
                    print(f"Error processing change: {e}")

    async def process_change(self, worker_class: str, change: dict):
        '''Route to appropriate handler.'''
        handlers = {
            "JobCreationSkillsUpdater": self._handle_job_skills,
            "ApplicationStatusNotifier": self._handle_app_status,
            "CompanyStatsUpdater": self._handle_company_stats
        }

        handler = handlers.get(worker_class)
        if handler:
            await handler(change)
        else:
            print(f"No handler for {worker_class}")

    async def _handle_job_skills(self, change: dict):
        '''Update skill popularity counters.'''
        job = change["fullDocument"]
        skills = job.get("skills", [])

        operations = []
        for skill in skills:
            normalized = skill.lower().strip()
            operations.append(
                self.db.skills.update_one(
                    {"name_normalized": normalized},
                    {"$inc": {"popularity": 1}},
                    upsert=True
                )
            )

        if operations:
            await asyncio.gather(*operations)

    async def _handle_app_status(self, change: dict):
        '''Send notification for status changes.'''
        app = change["fullDocument"]
        user_id = app["user_id"]
        status = app["status"]

        # Send notification (implement based on your notification system)
        await self.send_status_notification(user_id, status, app)

    async def _handle_company_stats(self, change: dict):
        '''Update company stats incrementally.'''
        job = change["fullDocument"]
        company = job.get("company")

        if company:
            normalized = company.lower().strip()
            await self.db.companies.update_one(
                {"name_normalized": normalized},
                {
                    "$inc": {"job_count": 1 if change["operationType"] == "insert" else -1},
                    "$set": {"updated_at": datetime.utcnow()}
                },
                upsert=True
            )

    async def send_status_notification(self, user_id: str, status: str, app: dict):
        '''Placeholder for notification implementation.'''
        pass

    async def run_all(self):
        '''Run all active change streams concurrently.'''
        configs = await self.db.change_stream_configs.find(
            {"is_active": True}
        ).to_list(None)

        tasks = [self.run_stream(config) for config in configs]
        await asyncio.gather(*tasks)

if __name__ == "__main__":
    import sys
    uri = sys.argv[1] if len(sys.argv) > 1 else "mongodb://localhost:27017"
    worker = ChangeStreamWorker(uri, "jobapp")
    asyncio.run(worker.run_all())
`);

// Check if collection exists for sharding
print("\n8. Sharding Information for Chang1 - future>");
print("   If sharding the searchHistory collection, also enable sharding for");
print("   change_stream_checkpoints with same key to ensure locality.");

print(`\n╔════════════════════════════════════════════════════════════════╗`);
print(`║  Migration 005 Complete                                       ║`);
print(`║  Change stream documentation and configs stored              ║`);
print(`╚════════════════════════════════════════════════════════════════╝\n`);

print("Implementation:");
print("  1. Install the ChangeStreamWorker in your FastAPI app");
print("  2. Start it as a background task on application startup");
print("  3. Ensure MongoDB URI has ?directConnection=false&replicaSet=...");
print("  4. Monitor stream health with heartbeat collection");
print("");
