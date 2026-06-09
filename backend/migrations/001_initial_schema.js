#!/usr/bin/env mongosh
// MongoDB Migration: 001_initial_schema.js
// Run with: mongosh "mongodb+srv://..." jobapp migrations/001_initial_schema.js
// Or: python migrations/run_migration.py 001

"use strict";

// Get database from context or use 'jobapp'
const dbName = context ? context.getArgs()[0] : "jobapp";
const db = db.getSiblingDB(dbName);

print(`\n╔════════════════════════════════════════════════════════════════╗`);
print(`║  Migration 001: Initial Schema Setup                          ║`);
print(`╚════════════════════════════════════════════════════════════════╝\n`);

// Enable profiling during development
try {
  db.setProfilingLevel(1, { slowms: 100 });
  print("✓ Enabled query profiling (slowms: 100ms)");
} catch (e) {
  print(`⚠ Profiling setup: ${e.message}`);
}

// JSON Schema definitions
const jobsSchema = {
  $jsonSchema: {
    bsonType: "object",
    required: ["title", "company", "description"],
    properties: {
      _id: { bsonType: "objectId" },
      title: {
        bsonType: "string",
        minLength: 1,
        maxLength: 300
      },
      company: {
        bsonType: "string",
        minLength: 1,
        maxLength: 200
      },
      company_normalized: {
        bsonType: "string",
        description: "Normalized company name for deduplication"
      },
      location: { bsonType: "string", maxLength: 500 },
      description: { bsonType: "string", minLength: 1 },
      url: {
        bsonType: ["string", "null"],
        pattern: "^https?://"
      },
      apply_url: {
        bsonType: ["string", "null"],
        pattern: "^https?://"
      },
      skills: {
        bsonType: "array",
        items: {
          bsonType: "string",
          minLength: 1,
          maxLength: 100
        }
      },
      job_type: {
        enum: ["full-time", "part-time", "contract", "internship", "freelance",
               "remote", "on-site", "hybrid", "unknown"]
      },
      posted_date: { bsonType: ["string", "null"] },
      posted_date_parsed: { bsonType: ["date", "null"] },
      salary: { bsonType: "string", maxLength: 200 },
      source: {
        bsonType: "string",
        enum: ["searxng", "linkedin", "indeed", "glassdoor", "greenhouse",
               "lever", "unknown"]
      },
      source_id: { bsonType: "string" },
      user_id: { bsonType: ["string", "null"] },
      is_saved: { bsonType: "bool", default: false },
      match_score: {
        bsonType: ["int", "null"],
        minimum: 0,
        maximum: 100
      },
      matched_skills: { bsonType: ["array", "null"] },
      missing_skills: { bsonType: ["array", "null"] },
      dedup_hash: { bsonType: "string" },
      search_query: { bsonType: "string" },
      created_at: { bsonType: "date" },
      updated_at: { bsonType: "date" }
    }
  }
};

const resumesSchema = {
  $jsonSchema: {
    bsonType: "object",
    required: ["resume_id", "extracted_text"],
    properties: {
      _id: { bsonType: "objectId" },
      resume_id: {
        bsonType: "string",
        minLength: 1,
        maxLength: 100
      },
      user_id: {
        bsonType: "string",
        minLength: 1,
        maxLength: 100
      },
      filename: { bsonType: "string", maxLength: 500 },
      content_type: {
        bsonType: "string",
        enum: ["application/pdf", "text/plain",
               "application/msword",
               "application/vnd.openxmlformats-officedocument.wordprocessingml.document"]
      },
      file_size: {
        bsonType: "int",
        minimum: 0,
        maximum: 10485760
      },
      extracted_text: { bsonType: "string" },
      extracted_text_length: { bsonType: "int", minimum: 0 },
      parsed_data: {
        bsonType: "object",
        properties: {
          name: { bsonType: "string" },
          email: {
            bsonType: "string",
            pattern: "^[^@]+@[^@]+\\.[^@]+$"
          },
          phone: { bsonType: "string" },
          education: {
            bsonType: "array",
            items: {
              bsonType: "object",
              properties: {
                institution: { bsonType: "string" },
                degree: { bsonType: "string" },
                year: { bsonType: "int" }
              }
            }
          },
          experience: {
            bsonType: "array",
            items: {
              bsonType: "object",
              properties: {
                company: { bsonType: "string" },
                title: { bsonType: "string" },
                duration: { bsonType: "string" },
                description: { bsonType: "string" }
              }
            }
          },
          skills: { bsonType: "array", items: { bsonType: "string" } },
          languages: { bsonType: "array", items: { bsonType: "string" } },
          certifications: { bsonType: "array", items: { bsonType: "string" } }
        }
      },
      processing_status: {
        enum: ["pending", "processing", "completed", "failed"],
        default: "pending"
      },
      processing_error: { bsonType: "string" },
      schema_version: { bsonType: "int", default: 1 },
      created_at: { bsonType: "date" },
      updated_at: { bsonType: "date" }
    }
  }
};

const usersSchema = {
  $jsonSchema: {
    bsonType: "object",
    required: ["email", "username", "password_hash"],
    properties: {
      _id: { bsonType: "objectId" },
      user_id: {
        bsonType: "string",
        minLength: 1,
        maxLength: 100
      },
      email: {
        bsonType: "string",
        pattern: "^[^@]+@[^@]+\\.[^@]+$"
      },
      email_verified: { bsonType: "bool", default: false },
      username: {
        bsonType: "string",
        minLength: 3,
        maxLength: 50,
        pattern: "^[a-zA-Z0-9_]+$"
      },
      password_hash: {
        bsonType: "string",
        minLength: 60
      },
      profile: {
        bsonType: "object",
        properties: {
          first_name: { bsonType: "string", maxLength: 100 },
          last_name: { bsonType: "string", maxLength: 100 },
          bio: { bsonType: "string", maxLength: 1000 },
          avatar_url: { bsonType: "string", pattern: "^https?://" },
          location: { bsonType: "string", maxLength: 200 },
          linkedin_url: {
            bsonType: "string",
            pattern: "^https?://(www\\.)?linkedin\\.com"
          },
          github_url: {
            bsonType: "string",
            pattern: "^https?://(www\\.)?github\\.com"
          },
          website: { bsonType: "string", pattern: "^https?://" }
        }
      },
      preferences: {
        bsonType: "object",
        properties: {
          notifications_enabled: { bsonType: "bool", default: true },
          preferred_job_types: {
            bsonType: "array",
            items: {
              enum: ["full-time", "part-time", "contract", "internship",
                     "freelance", "remote"]
            }
          },
          preferred_locations: { bsonType: "array", items: { bsonType: "string" } },
          search_radius_km: {
            bsonType: "int",
            minimum: 0,
            maximum: 500
          }
        }
      },
      role: {
        enum: ["user", "admin", "moderator"],
        default: "user"
      },
      is_active: { bsonType: "bool", default: true },
      last_login_at: { bsonType: ["date", "null"] },
      created_at: { bsonType: "date" },
      updated_at: { bsonType: "date" }
    }
  }
};

const applicationsSchema = {
  $jsonSchema: {
    bsonType: "object",
    required: ["user_id", "job_id", "status"],
    properties: {
      _id: { bsonType: "objectId" },
      application_id: {
        bsonType: "string",
        minLength: 1,
        maxLength: 100
      },
      user_id: {
        bsonType: "string",
        minLength: 1,
        maxLength: 100
      },
      job_id: { bsonType: "objectId" },
      resume_id: { bsonType: "string" },
      status: {
        enum: [
          "applied", "emailed", "called", "screening", "interview_scheduled",
          "interview_completed", "offer_extended", "offer_accepted",
          "offer_declined", "rejected", "withdrawn", "archived"
        ]
      },
      notes: { bsonType: "string", maxLength: 5000 },
      applied_at: { bsonType: "date" },
      updated_at: { bsonType: "date" },
      external_application_url: {
        bsonType: "string",
        pattern: "^https?://"
      },
      follow_up_date: { bsonType: ["date", "null"] },
      status_history: {
        bsonType: "array",
        items: {
          bsonType: "object",
          properties: {
            status: { bsonType: "string" },
            changed_at: { bsonType: "date" },
            notes: { bsonType: "string" }
          }
        }
      },
      is_deleted: { bsonType: "bool", default: false },
      deleted_at: { bsonType: ["date", "null"] }
    }
  }
};

const companiesSchema = {
  $jsonSchema: {
    bsonType: "object",
    required: ["name"],
    properties: {
      _id: { bsonType: "objectId" },
      name: {
        bsonType: "string",
        minLength: 1,
        maxLength: 200
      },
      name_normalized: { bsonType: "string" },
      domain: {
        bsonType: "string",
        pattern: "^[a-z0-9][a-z0-9-]*\\.[a-z]{2,}$"
      },
      careers_url: { bsonType: "string", pattern: "^https?://" },
      logo_url: { bsonType: "string", pattern: "^https?://" },
      description: { bsonType: "string", maxLength: 5000 },
      industry: { bsonType: "string", maxLength: 200 },
      size: {
        enum: ["1-10", "11-50", "51-200", "201-1000", "1001-5000",
               "5001-10000", "10000+"]
      },
      headquarters: { bsonType: "string", maxLength: 200 },
      founded_year: {
        bsonType: "int",
        minimum: 1800,
        maximum: 2025
      },
      linkedin_company_id: { bsonType: "string" },
      job_count: { bsonType: "int", minimum: 0, default: 0 },
      last_job_posted: { bsonType: ["date", "null"] },
      created_at: { bsonType: "date" },
      updated_at: { bsonType: "date" }
    }
  }
};

const skillsSchema = {
  $jsonSchema: {
    bsonType: "object",
    required: ["name", "category"],
    properties: {
      _id: { bsonType: "objectId" },
      name: {
        bsonType: "string",
        minLength: 1,
        maxLength: 100
      },
      name_normalized: {
        bsonType: "string"
      },
      category: {
        enum: [
          "programming_language", "framework", "database", "cloud", "devops",
          "frontend", "backend", "mobile", "data_science", "design",
          "project_management", "soft_skill", "tool", "platform",
          "methodology", "certification"
        ]
      },
      subcategory: { bsonType: "string", maxLength: 100 },
      synonyms: { bsonType: "array", items: { bsonType: "string" } },
      popularity: { bsonType: "int", minimum: 0 },
      is_active: { bsonType: "bool", default: true },
      created_at: { bsonType: "date" },
      updated_at: { bsonType: "date" }
    }
  }
};

const searchHistorySchema = {
  $jsonSchema: {
    bsonType: "object",
    required: ["user_id", "query"],
    properties: {
      _id: { bsonType: "objectId" },
      user_id: {
        bsonType: "string",
        minLength: 1,
        maxLength: 100
      },
      query: {
        bsonType: "string",
        minLength: 1,
        maxLength: 1000
      },
      parsed_query: {
        bsonType: "object",
        properties: {
          location: { bsonType: "string" },
          job_types: { bsonType: "array", items: { bsonType: "string" } },
          skills: { bsonType: "array", items: { bsonType: "string" } },
          companies: { bsonType: "array", items: { bsonType: "string" } },
          experience_level: { bsonType: "string" }
        }
      },
      results_count: { bsonType: "int", minimum: 0 },
      search_sources: {
        bsonType: "array",
        items: { bsonType: "string" }
      },
      duration_ms: { bsonType: "int", minimum: 0 },
      user_agent: { bsonType: "string", maxLength: 500 },
      ip_address: {
        bsonType: "string",
        pattern: "^(?:[0-9]{1,3}\\.){3}[0-9]{1,3}$"
      },
      session_id: { bsonType: "string" },
      created_at: { bsonType: "date" }
    }
  }
};

const jobMatchesSchema = {
  $jsonSchema: {
    bsonType: "object",
    required: ["user_id", "job_id", "resume_id", "match_score"],
    properties: {
      _id: { bsonType: "objectId" },
      match_id: {
        bsonType: "string",
        minLength: 1,
        maxLength: 100
      },
      user_id: {
        bsonType: "string",
        minLength: 1,
        maxLength: 100
      },
      job_id: { bsonType: "objectId" },
      resume_id: { bsonType: "string" },
      match_score: {
        bsonType: "int",
        minimum: 0,
        maximum: 100
      },
      match_details: {
        bsonType: "object",
        properties: {
          skills_match_percentage: {
            bsonType: "double",
            minimum: 0,
            maximum: 100
          },
          experience_match_score: {
            bsonType: "int",
            minimum: 0,
            maximum: 100
          },
          education_match_score: {
            bsonType: "int",
            minimum: 0,
            maximum: 100
          },
          keyword_relevance: {
            bsonType: "int",
            minimum: 0,
            maximum: 100
          }
        }
      },
      matched_skills: {
        bsonType: "array",
        items: {
          bsonType: "object",
          properties: {
            skill: { bsonType: "string" },
            confidence: { bsonType: "double" },
            job_requirement_level: {
              enum: ["required", "preferred", "nice-to-have"]
            }
          }
        }
      },
      missing_skills: {
        bsonType: "array",
        items: {
          bsonType: "object",
          properties: {
            skill: { bsonType: "string" },
            importance: { enum: ["required", "preferred"] }
          }
        }
      },
      suggested_improvements: {
        bsonType: "array",
        items: { bsonType: "string" }
      },
      tailored_resume_snippet: { bsonType: "string", maxLength: 5000 },
      created_at: { bsonType: "date" },
      expires_at: { bsonType: ["date", "null"] }
    }
  }
};

const migrationsCollectionSchema = {
  $jsonSchema: {
    bsonType: "object",
    required: ["migration", "applied_at", "checksum"],
    properties: {
      _id: { bsonType: "objectId" },
      migration: { bsonType: "string" },
      version: { bsonType: "int" },
      applied_at: { bsonType: "date" },
      checksum: { bsonType: "string" },
      rolled_back: { bsonType: "bool", default: false },
      rolled_back_at: { bsonType: ["date", "null"] }
    }
  }
};

// Collections to create
const collections = [
  { name: "jobs", validator: jobsSchema },
  { name: "resumes", validator: resumesSchema },
  { name: "users", validator: usersSchema },
  { name: "applications", validator: applicationsSchema },
  { name: "companies", validator: companiesSchema },
  { name: "skills", validator: skillsSchema },
  { name: "searchHistory", validator: searchHistorySchema },
  { name: "jobMatches", validator: jobMatchesSchema },
  { name: "_migrations", validator: migrationsCollectionSchema }
];

let totalCreated = 0;

// Create collections with validation
print("Creating collections with validation...\n");

for (const coll of collections) {
  try {
    const options = {
      validator: coll.validator,
      validationLevel: "moderate",
      validationAction: "error"
    };

    // Special case for migrations collection - create with unique index
    if (coll.name === "_migrations") {
      db.createCollection(coll.name, options);
      db._migrations.createIndex(
        { migration: 1 },
        { name: "idx_migrations_name", unique: true }
      );
    } else {
      db.createCollection(coll.name, options);
    }

    print(`✓ Created: ${coll.name}`);
    totalCreated++;
  } catch (e) {
    if (e.code === 48) { // Namespace exists
      print(`⚡ Already exists: ${coll.name} (skipping)`);
    } else {
      print(`✗ Error creating ${coll.name}: ${e.message}`);
      throw e;
    }
  }
}

// Record migration
db._migrations.insertOne({
  migration: "001_initial_schema",
  version: 1,
  applied_at: new Date(),
  checksum: "CHECKSUM_TO_BE_COMPUTED" // In production, compute actual checksum
});

print(`\n╔════════════════════════════════════════════════════════════════╗`);
print(`║  Migration 001 Complete: ${totalCreated} collections created  ║`);
print(`╚════════════════════════════════════════════════════════════════╝\n`);

print("Next steps:");
print("  1. Run migration 002 to add denormalized fields");
print("  2. Create indexes (see MONGODB_SCHEMAS_ATLAS.md)");
print("  3. Configure Atlas Search index for jobs collection");
print("");
