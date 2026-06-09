#!/usr/bin/env mongosh
// Index Creation Script for jobapp Database
// Run this after migrations to create all indexes

"use strict";

const dbName = context ? context.getArgs()[0] : "jobapp";
const db = db.getSiblingDB(dbName);

print(`\n╔════════════════════════════════════════════════════════════════╗`);
print(`║  Creating All Database Indexes                                ║`);
print(`╚════════════════════════════════════════════════════════════════╝\n`);

const startTime = new Date();
let totalCreated = 0;
let skipped = 0;
let errors = 0;

// Helper function to create index safely
function createIndex(collection, indexSpec, name, options = {}) {
  try {
    // Check if index already exists
    const existing = collection.getIndexes().find(idx => idx.name === name);
    if (existing) {
      print(`  ⚡ ${collection.name}.${name} already exists`);
      skipped++;
      return false;
    }

    collection.createIndex(indexSpec, { name, ...options });
    print(`  ✓ ${collection.name}.${name}`);
    totalCreated++;
    return true;
  } catch (e) {
    if (e.code === 85) { // IndexOptionsConflict
      print(`  ⚡ ${collection.name}.${name} exists with different options`);
      skipped++;
    } else {
      print(`  ✗ ${collection.name}.${name}: ${e.message}`);
      errors++;
    }
    return false;
  }
}

// JOBS COLLECTION INDEXES
print("\n[1/8] Jobs collection indexes\n");

createIndex(db.jobs, { _id: 1 }, "idx_job_id");  // Auto-created, just check

createIndex(db.jobs, { company: 1, title: 1, location: 1 }, "idx_job_dedup_unique", {
  unique: true,
  partialFilterExpression: { is_deleted: { $exists: false } }
});

createIndex(db.jobs, { title: "text", company: "text", description: "text", skills: "text" },
  "idx_job_text_search", {
    weights: { title: 10, company: 3, skills: 5, description: 1 },
    default_language: "english"
  }
);

createIndex(db.jobs, { source: 1, created_at: -1 }, "idx_job_source_created");
createIndex(db.jobs, { location: 1, job_type: 1, created_at: -1 }, "idx_job_location_type");
createIndex(db.jobs, { job_type: 1, posted_date_parsed: -1 }, "idx_job_type_posted");
createIndex(db.jobs, { skills: 1 }, "idx_job_skills", { background: true });
createIndex(db.jobs, { match_score: -1, created_at: -1 }, "idx_job_match_score");
createIndex(db.jobs, { user_id: 1, is_saved: 1 }, "idx_job_user_saved");
createIndex(db.jobs, { company: 1, created_at: -1 }, "idx_job_company_created");
createIndex(db.jobs, { dedup_hash: 1 }, "idx_job_dedup_hash", {
  unique: true,
  partialFilterExpression: { dedup_hash: { $exists: true } }
});

// TTL index for jobs (90 days)
try {
  db.jobs.createIndex(
    { created_at: 1 },
    { name: "idx_job_created_ttl", expireAfterSeconds: 90 * 24 * 60 * 60 }
  );
  print("  ✓ jobs.idx_job_created_ttl (TTL: 90 days)");
  totalCreated++;
} catch (e) {
  print(`  ✗ jobs.idx_job_created_ttl: ${e.message}`);
  errors++;
}

// RESUMES COLLECTION INDEXES
print("\n[2/8] Resumes collection indexes\n");

createIndex(db.resumes, { resume_id: 1 }, "idx_resume_resume_id", { unique: true });
createIndex(db.resumes, { user_id: 1, updated_at: -1 }, "idx_resume_user_updated");
createIndex(db.resumes, { "parsed_data.skills": "text" }, "idx_resume_skills_text");
createIndex(db.resumes, { processing_status: 1, created_at: 1 }, "idx_resume_processing_status");
createIndex(db.resumes, { extracted_text: "text" }, "idx_resume_text_search", {
  weights: { extracted_text: 1 },
  default_language: "english"
});

// USERS COLLECTION INDEXES
print("\n[3/8] Users collection indexes\n");

createIndex(db.users, { email: 1 }, "idx_users_email", { unique: true });
createIndex(db.users, { username: 1 }, "idx_users_username", { unique: true });
createIndex(db.users, { user_id: 1 }, "idx_users_user_id", { unique: true });
createIndex(db.users, {
  "profile.first_name": "text",
  "profile.last_name": "text",
  "profile.bio": "text"
}, "idx_users_profile_search");
createIndex(db.users, { role: 1, is_active: 1 }, "idx_users_role_active");
createIndex(db.users, { email_verified: 1, is_active: 1 }, "idx_users_email_verified");

// APPLICATIONS COLLECTION INDEXES
print("\n[4/8] Applications collection indexes\n");

createIndex(db.applications, { user_id: 1, job_id: 1 }, "idx_applications_user_job_unique", {
  unique: true,
  partialFilterExpression: { is_deleted: false }
});
createIndex(db.applications, { user_id: 1, updated_at: -1 }, "idx_applications_user_updated");
createIndex(db.applications, { user_id: 1, status: 1, applied_at: -1 }, "idx_applications_user_status");
createIndex(db.applications, { follow_up_date: 1, user_id: 1 }, "idx_applications_followup");
createIndex(db.applications, { job_id: 1, applied_at: -1 }, "idx_applications_job_applied");

// TTL for deleted applications (7 years)
try {
  db.applications.createIndex(
    { is_deleted: 1, deleted_at: 1 },
    { name: "idx_applications_deleted_ttl", expireAfterSeconds: 7 * 365 * 24 * 60 * 60 }
  );
  print("  ✓ applications.idx_applications_deleted_ttl (TTL: 7 years)");
  totalCreated++;
} catch (e) {
  print(`  ⚡ applications.idx_applications_deleted_ttl may exist: ${e.message}`);
}

// COMPANIES COLLECTION INDEXES
print("\n[5/8] Companies collection indexes\n");

createIndex(db.companies, { name_normalized: 1 }, "idx_companies_name_normalized", {
  unique: true,
  collation: { locale: "en", strength: 2 }
});
createIndex(db.companies, { domain: 1 }, "idx_companies_domain", {
  unique: true,
  sparse: true
});
createIndex(db.companies, { industry: 1, size: 1 }, "idx_companies_industry_size");
createIndex(db.companies, { headquarters: 1 }, "idx_companies_headquarters");
createIndex(db.companies, { last_job_posted: -1 }, "idx_companies_last_job");

// SKILLS COLLECTION INDEXES
print("\n[6/8] Skills collection indexes\n");

createIndex(db.skills, { name_normalized: 1 }, "idx_skills_normalized", { unique: true });
createIndex(db.skills, { category: 1, popularity: -1 }, "idx_skills_category_popular");
createIndex(db.skills, { name: "text", synonyms: "text" }, "idx_skills_text_search");
createIndex(db.skills, { is_active: 1, popularity: -1 }, "idx_skills_active_popular");

// SEARCH HISTORY INDEXES
print("\n[7/8] SearchHistory collection indexes\n");

createIndex(db.searchHistory, { user_id: 1, created_at: -1 }, "idx_search_history_user_recent");

// TTL index for search history (1 year)
try {
  db.searchHistory.createIndex(
    { created_at: 1 },
    { name: "idx_search_history_user_ttl", expireAfterSeconds: 365 * 24 * 60 * 60 }
  );
  print("  ✓ searchHistory.idx_search_history_user_ttl (TTL: 1 year)");
  totalCreated++;
} catch (e) {
  print(`  ⚡ searchHistory.idx_search_history_user_ttl may exist: ${e.message}`);
}

createIndex(db.searchHistory, { query: 1, created_at: -1 }, "idx_search_history_query_recent");
createIndex(db.searchHistory, { user_id: 1, session_id: 1, created_at: -1 }, "idx_search_history_session");
createIndex(db.searchHistory, { ip_address: 1, created_at: -1 }, "idx_search_history_ip_rate_limit");

// JOB MATCHES INDEXES
print("\n[8/8] JobMatches collection indexes\n");

createIndex(db.jobMatches, { user_id: 1, created_at: -1 }, "idx_job_matches_user_recent");
createIndex(db.jobMatches, { job_id: 1, match_score: -1 }, "idx_job_matches_job_score");
createIndex(db.jobMatches, { user_id: 1, job_id: 1 }, "idx_job_matches_user_job", {
  unique: true,
  partialFilterExpression: { expires_at: { $gt: new Date() } }
});

// TTL index for job matches (30 days)
try {
  db.jobMatches.createIndex(
    { expires_at: 1 },
    { name: "idx_job_matches_expiry_ttl" }
  );
  print("  ✓ jobMatches.idx_job_matches_expiry_ttl");
  totalCreated++;
} catch (e) {
  print(`  ⚡ jobMatches.idx_job_matches_expiry_ttl may exist: ${e.message}`);
}

createIndex(db.jobMatches, { user_id: 1, match_score: -1, created_at: -1 }, "idx_job_matches_user_high_score");

// Change Stream Support Indexes
print("\n[*] Change Stream Support Indexes\n");

// Check if change_stream_checkpoints exists
if (db.change_stream_checkpoints) {
  createIndex(db.change_stream_checkpoints, { _id: 1 }, "idx_cs_checkpoint_id", { unique: true });
}

// Summary
const duration = (new Date() - startTime) / 1000;
print("\n" + "=".repeat(60));
print("INDEX CREATION COMPLETE");
print("=".repeat(60));
print(`  Total indexes created: ${totalCreated}`);
print(`  Skipped (already exist): ${skipped}`);
print(`  Errors: ${errors}`);
print(`  Time taken: ${duration.toFixed(1)}s`);
print("\nVerification:");

// List all indexes
const collections = ["jobs", "resumes", "users", "applications", "companies",
                     "skills", "searchHistory", "jobMatches"];
for (const collName of collections) {
  const coll = db[collName];
  if (coll) {
    const indexes = coll.getIndexes();
    print(`  ${collName}: ${indexes.length} indexes`);
  }
}

print("\n" + "=".repeat(60));
print("Next steps:");
print("  1. Verify index usage with db.collection.explain().find()");
print("  2. Configure Atlas Search index for full-text search");
print("  3. Set up MongoDB Atlas alerts and backups");
print("");
