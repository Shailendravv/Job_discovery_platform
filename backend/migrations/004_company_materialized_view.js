#!/usr/bin/env mongosh
// MongoDB Migration: 004_company_materialized_view.js
// Creates jobs_company_summary materialized view

"use strict";

const dbName = context ? context.getArgs()[0] : "jobapp";
const db = db.getSiblingDB(dbName);

print(`\n╔════════════════════════════════════════════════════════════════╗`);
print(`║  Migration 004: Company Materialized View                    ║`);
print(`╚════════════════════════════════════════════════════════════════╝\n`);

// Ensure company_normalized is populated
const missingNormalized = db.jobs.countDocuments({ company_normalized: { $exists: false } });
if (missingNormalized > 0) {
  print(`⚠ Warning: ${missingNormalized} jobs missing company_normalized`);
  print("  Running backfill...");
  db.jobs.updateMany(
    { company_normalized: { $exists: false } },
    [{
      $set: {
        company_normalized: {
          $trim: {
            input: { $toLower: "$company" }
          }
        },
        updated_at: "$$NOW"
      }
    }]
  );
}

// Build aggregation pipeline for company summary
print("Building company aggregation pipeline...");

const companySummaryPipeline = [
  {
    $match: {
      company: { $exists: true, $ne: "", $ne: null }
    }
  },
  {
    $group: {
      _id: {
        name: "$company",
        normalized: "$company_normalized"
      },
      job_count: { $sum: 1 },
      unique_locations: { $addToSet: "$location" },
      job_types: { $addToSet: "$job_type" },
      sources: { $addToSet: "$source" },
      first_job: { $min: "$created_at" },
      last_job: { $max: "$created_at" },
      avg_match_score: { $avg: "$match_score" },
      has_salary_info: { $sum: { $cond: [{ $ne: ["$salary", null] }, 1, 0] } }
    }
  },
  {
    $project: {
      _id: 0,
      name_normalized: "$_id.normalized",
      name: "$_id.name",
      job_count: 1,
      unique_locations: {
        $size: { $ifNull: ["$unique_locations", []] }
      },
      job_type_count: {
        $size: { $ifNull: ["$job_types", []] }
      },
      sources: 1,
      first_job: 1,
      last_job: 1,
      avg_match_score: { $round: ["$avg_match_score", 2] },
      salary_info_count: "$has_salary_info",
      location_distribution: "$unique_locations"
    }
  },
  {
    $sort: { job_count: -1 }
  }
];

print("Executing aggregation (this may take a moment)...");
const startTime = new Date();

try {
  const results = db.jobs.aggregate(companySummaryPipeline).toArray();
  const duration = (new Date() - startTime) / 1000;

  print(`  ✓ Aggregation completed in ${duration.toFixed(1)}s`);
  print(`  ℹ Generated ${results.length} company summaries`);

  // Create or replace summary collection
  print("\nCreating jobs_company_summary collection...");
  db.jobs_company_summary.drop().catch(() => {});

  if (results.length > 0) {
    db.jobs_company_summary.insertMany(results);
    print(`  ✓ Inserted ${results.length} company summary records`);
  }

  // Create indexes
  print("\nCreating summary collection indexes...");

  db.jobs_company_summary.createIndex(
    { name_normalized: 1 },
    { name: "idx_jobs_company_summary_normalized", unique: true }
  );
  print("  ✓ Created unique index on name_normalized");

  db.jobs_company_summary.createIndex(
    { job_count: -1 },
    { name: "idx_jobs_company_summary_job_count" }
  );
  print("  ✓ Created index on job_count");

  db.jobs_company_summary.createIndex(
    { last_job: -1 },
    { name: "idx_jobs_company_summary_last_job" }
  );
  print("  ✓ Created index on last_job");

  // Verify
  const summaryCount = db.jobs_company_summary.countDocuments();
  print(`\nSummary collection verified: ${summaryCount} documents`);

  // Show top 10 companies
  if (results.length > 0) {
    print("\nTop 10 Companies by Job Count:");
    const top10 = results.slice(0, 10);
    for (let i = 0; i < top10.length; i++) {
      const c = top10[i];
      print(`  ${i + 1}. ${c.name} (${c.job_count} jobs)`);
    }
  }

} catch (e) {
  print(`✗ Error during aggregation: ${e.message}`);
  throw e;
}

// Record migration
try {
  db._migrations.insertOne({
    migration: "004_company_materialized_view",
    version: 4,
    applied_at: new Date(),
    checksum: "COMPUTED_DURING_DEPLOYMENT"
  });
} catch (e) {
  // Migration record might already exist
}

print(`\n╔════════════════════════════════════════════════════════════════╗`);
print(`║  Migration 004 Complete                                       ║`);
print(`╚════════════════════════════════════════════════════════════════╝\n`);

print("Next steps:");
print("  1. Create all indexes from MONGODB_SCHEMAS_ATLAS.md");
print("  2. Configure Atlas Search for full-text search");
print("");
