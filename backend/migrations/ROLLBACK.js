#!/usr/bin/env mongosh
// MongoDB Migration ROLLBACK: Complete rollback script
// WARNING: This DELETES ALL DATA!
// Run with: mongosh "mongodb+srv://..." migrations/ROLLBACK.js

"use strict";

const dbName = context ? context.getArgs()[0] : "jobapp";
const db = db.getSiblingDB(dbName);

print(`\n╔════════════════════════════════════════════════════════════════╗`);
print(`║  ⚠️  ROLLBACK - DESTRUCTIVE OPERATION                         ║`);
print(`║  This will DELETE all application collections                  ║`);
print(`╠════════════════════════════════════════════════════════════════╣`);
print(`║  Collections to be dropped:                                   ║`);
print(`║    - jobMatches                                              ║`);
print(`║    - searchHistory                                           ║`);
print(`║    - skills                                                  ║`);
print(`║    - companies                                               ║`);
print(`║    - applications                                            ║`);
print(`║    - users                                                   ║`);
print(`║    - resumes                                                 ║`);
print(`║    - jobs                                                    ║`);
print(`║    - jobs_company_summary                                    ║`);
print(`║    - change_stream_checkpoints                              ║`);
print(`║    - change_stream_configs                                  ║`);
print(`║    - _migrations                                             ║`);
print(`╚════════════════════════════════════════════════════════════════╝\n`);

// Confirmation
const confirm = prompt ||
  (function() {
    print("\nType 'YES' to confirm rollback: ");
    return "YES"; // auto in script, but warn in prompt mode
  })();

if (confirm !== "YES") {
  print("\n❌ Rollback cancelled. You must type 'YES' to proceed.");
  print("   Run with: mongosh ... --eval 'confirm=\"YES\"' migrations/ROLLBACK.js");
  quit(1);
}

print("\n⏳ Starting rollback in 3 seconds...");
sleep(3000);

const collectionsToDrop = [
  "jobMatches",
  "searchHistory",
  "skills",
  "companies",
  "applications",
  "users",
  "resumes",
  "jobs",
  "jobs_company_summary",
  "change_stream_checkpoints",
  "change_stream_configs",
  "_migrations"
];

let droppedCount = 0;
let errorCount = 0;

// Drop collections
for (const coll of collectionsToDrop) {
  try {
    if (db.getCollectionNames().includes(coll)) {
      db[coll].drop();
      print(`  ✓ Dropped: ${coll}`);
      droppedCount++;
    } else {
      print(`  ○ Not found: ${coll}`);
    }
  } catch (e) {
    print(`  ✗ Error dropping ${coll}: ${e.message}`);
    errorCount++;
  }
}

// Optional: Drop entire database
const dropDatabase = false; // Set to true to drop the entire jobapp DB
if (dropDatabase) {
  print("\n⚠ Dropping entire jobapp database...");
  sleep(1000);
  db.getMongo().getDB(dbName).dropDatabase();
  print("  ✓ Database dropped");
}

print(`\n╔════════════════════════════════════════════════════════════════╗`);
print(`║  Rollback Complete                                            ║`);
print(`╠════════════════════════════════════════════════════════════════╣`);
print(`║  Collections dropped: ${droppedCount}                                    ║`);
print(`║  Errors: ${errorCount}                                               ║`);
print(`╚════════════════════════════════════════════════════════════════╝\n`);

print("To recreate the database, run migration 001:");
print("  mongosh 'mongodb+srv://...' jobapp migrations/001_initial_schema.js\n");
