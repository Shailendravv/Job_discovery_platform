#!/usr/bin/env mongosh
// MongoDB Migration: 002_job_denormalization.js
// Adds computed fields and backfills existing data

"use strict";

const dbName = context ? context.getArgs()[0] : "jobapp";
const db = db.getSiblingDB(dbName);

print(`\n╔════════════════════════════════════════════════════════════════╗`);
print(`║  Migration 002: Job Denormalization & Computed Fields        ║`);
print(`╚════════════════════════════════════════════════════════════════╝\n`);

// 1. Add company_normalized field to all jobs
print("Step 1: Adding company_normalized field...");
const result1 = db.jobs.updateMany(
  { company_normalized: { $exists: false } },
  [{
    $set: {
      company_normalized: {
        $trim: {
          input: {
            $toLower: "$company"
          }
        }
      },
      updated_at: "$$NOW"
    }
  }]
);
print(`  ✓ Updated ${result1.modifiedCount} jobs with company_normalized`);

// 2. Add dedup_hash field
print("\nStep 2: Adding dedup_hash field...");
const result2 = db.jobs.updateMany(
  { dedup_hash: { $exists: false } },
  [{
    $set: {
      dedup_hash: {
        $function: {
          body: function(company, title, location) {
            const crypto = require('crypto');
            const key = `${company || ''}|${title || ''}|${location || ''}`;
            return crypto.createHash('sha256').update(key).digest('hex');
          },
          args: ["$company", "$title", "$location"],
          returns: "string"
        }
      },
      updated_at: "$$NOW"
    }
  }]
);
print(`  ✓ Updated ${result2.modifiedCount} jobs with dedup_hash`);

// 3. Add extracted_text_length to resumes
print("\nStep 3: Adding extracted_text_length to resumes...");
const result3 = db.resumes.updateMany(
  { extracted_text_length: { $exists: false } },
  [{
    $set: {
      extracted_text_length: { $strLenCP: "$extracted_text" },
      updated_at: "$$NOW"
    }
  }]
);
print(`  ✓ Updated ${result3.modifiedCount} resumes with extracted_text_length`);

// 4. Populate posted_date_parsed from posted_date string
print("\nStep 4: Parsing posted_date to ISO date...");
const dateParseResult = db.jobs.updateMany(
  { posted_date_parsed: { $exists: false } },
  [{
    $set: {
      posted_date_parsed: {
        $cond: {
          if: {
            $regexMatch: {
              input: "$posted_date",
              regex: /^\d{4}-\d{2}-\d{2}/
            }
          },
          then: {
            $dateFromString: {
              dateString: "$posted_date",
              format: "%Y-%m-%d"
            }
          },
          else: {
            $dateFromParts: {
              year: 2024,
              month: 1,
              day: 1
            }
          }
        }
      },
      updated_at: "$$NOW"
    }
  }]
);
print(`  ✓ Updated ${dateParseResult.modifiedCount} jobs with posted_date_parsed`);

// 5. Create company statistics aggregation
print("\nStep 5: Computing company statistics...");
const companyStats = db.jobs.aggregate([
  {
    $group: {
      _id: "$company_normalized",
      company: { $first: "$company" },
      job_count: { $sum: 1 },
      first_job: { $min: "$created_at" },
      last_job: { $max: "$created_at" },
      job_types: { $addToSet: "$job_type" },
      locations: { $addToSet: "$location" },
      sources: { $addToSet: "$source" }
    }
  },
  {
    $project: {
      _id: 0,
      name_normalized: "$_id",
      name: "$company",
      job_count: 1,
      first_job: 1,
      last_job: 1,
      job_type_count: { $size: { $ifNull: ["$job_types", []] } },
      location_count: { $size: { $ifNull: ["$locations", []] } },
      sources: 1
    }
  }
]).toArray();

print(`  ℹ Computed stats for ${companyStats.length} unique companies`);

// Save to jobs_company_summary collection
db.jobs_company_summary.drop().catch(() => {});
if (companyStats.length > 0) {
  db.jobs_company_summary.insertMany(companyStats);
  db.jobs_company_summary.createIndex(
    { name_normalized: 1 },
    { name: "idx_jobs_company_summary_normalized", unique: true }
  );
  print(`  ✓ Created jobs_company_summary collection with ${companyStats.length} records`);
}

// 6. Analyze data quality
print("\nStep 6: Data quality analysis...");
const stats = db.jobs.aggregate([
  {
    $facet: {
      total: [{ $count: "count" }],
      with_url: [
        { $match: { url: { $exists: true, $ne: null } } },
        { $count: "count" }
      ],
      with_apply_url: [
        { $match: { apply_url: { $exists: true, $ne: null } } },
        { $count: "count" }
      ],
      with_salary: [
        { $match: { salary: { $exists: true, $ne: null } } },
        { $count: "count" }
      ],
      with_location: [
        { $match: { location: { $exists: true, $ne: null } } },
        { $count: "count" }
      ],
      with_skills: [
        { $match: { skills: { $exists: true, $ne: [] } } },
        { $count: "count" }
      ],
      avg_skills: [
        {
          $project: { skill_count: { $size: { $ifNull: ["$skills", []] } } }
        },
        { $group: { _id: null, avg: { $avg: "$skill_count" } } }
      ]
    }
  }
]).toArray();

if (stats.length > 0) {
  const s = stats[0];
  print(`  Data Quality Report:`);
  print(`    Total jobs: ${s.total[0]?.count || 0}`);
  print(`    With URL: ${s.with_url[0]?.count || 0} (${((s.with_url[0]?.count || 0) / (s.total[0]?.count || 1) * 100).toFixed(1)}%)`);
  print(`    With apply_url: ${s.with_apply_url[0]?.count || 0}`);
  print(`    With salary: ${s.with_salary[0]?.count || 0}`);
  print(`    With location: ${s.with_location[0]?.count || 0}`);
  print(`    With skills: ${s.with_skills[0]?.count || 0}`);
  print(`    Avg skills per job: ${s.avg_skills[0]?.avg?.toFixed(1) || 0}`);
}

// Record migration
try {
  db._migrations.insertOne({
    migration: "002_job_denormalization",
    version: 2,
    applied_at: new Date(),
    checksum: "COMPUTED_DURING_DEPLOYMENT"
  });
} catch (e) {
  // Migration record might already exist from previous run
  print(`  Migration record: ${e.code === 11000 ? 'already exists' : e.message}`);
}

print(`\n╔════════════════════════════════════════════════════════════════╗`);
print(`║  Migration 002 Complete                                       ║`);
print(`╚════════════════════════════════════════════════════════════════╝\n`);

print("Next steps:");
print("  1. Verify denormalized fields with a few sample queries");
print("  2. Run migration 003 to populate skills taxonomy");
print("");
