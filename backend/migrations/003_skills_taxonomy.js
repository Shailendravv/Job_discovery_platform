#!/usr/bin/env mongosh
// MongoDB Migration: 003_skills_taxonomy.js
// Populates skills collection with taxonomy and extracts from existing jobs

"use strict";

const dbName = context ? context.getArgs()[0] : "jobapp";
const db = db.getSiblingDB(dbName);

print(`\n╔════════════════════════════════════════════════════════════════╗`);
print(`║  Migration 003: Skills Taxonomy Population                   ║`);
print(`╚════════════════════════════════════════════════════════════════╝\n`);

// Skills taxonomy
const skillsTaxonomy = [
  // Programming Languages
  { name: "python", category: "programming_language", synonyms: ["py", "python3"] },
  { name: "javascript", category: "programming_language", synonyms: ["js", "es6", "node.js"] },
  { name: "typescript", category: "programming_language", synonyms: ["ts"] },
  { name: "java", category: "programming_language", synonyms: ["jdk", "spring"] },
  { name: "csharp", category: "programming_language", synonyms: ["c#", "dotnet", ".net"] },
  { name: "go", category: "programming_language", synonyms: ["golang"] },
  { name: "rust", category: "programming_language" },
  { name: "ruby", category: "programming_language", synonyms: ["rails"] },
  { name: "php", category: "programming_language", synonyms: ["laravel"] },
  { name: "swift", category: "programming_language", synonyms: ["ios", "objective-c"] },
  { name: "kotlin", category: "programming_language", synonyms: ["android"] },
  { name: "scala", category: "programming_language" },
  { name: "perl", category: "programming_language" },
  { name: "r", category: "data_science" },

  // Frontend
  { name: "react", category: "frontend", synonyms: ["react.js", "reactjs"] },
  { name: "vue", category: "frontend", synonyms: ["vue.js", "vuejs"] },
  { name: "angular", category: "frontend", synonyms: ["angularjs", "angular.js"] },
  { name: "nextjs", category: "frontend", synonyms: ["next.js"] },
  { name: "svelte", category: "frontend" },
  { name: "html", category: "frontend" },
  { name: "css", category: "frontend" },
  { name: "sass", category: "frontend" },
  { name: "webpack", category: "frontend" },
  { name: "babel", category: "frontend" },

  // Backend
  { name: "nodejs", category: "backend", synonyms: ["node.js", "node"] },
  { name: "express", category: "backend", synonyms: ["express.js"] },
  { name: "django", category: "backend" },
  { name: "fastapi", category: "backend" },
  { name: "flask", category: "backend" },
  { name: "spring", category: "backend", synonyms: ["spring boot"] },
  { name: "spring boot", category: "backend" },
  { name: "laravel", category: "backend" },
  { name: "asp.net", category: "backend", synonyms: [".net"] },
  { name: "flask", category: "backend" },

  // Databases
  { name: "postgresql", category: "database", synonyms: ["postgres"] },
  { name: "mongodb", category: "database" },
  { name: "mysql", category: "database" },
  { name: "redis", category: "database" },
  { name: "elasticsearch", category: "database" },
  { name: "cassandra", category: "database" },
  { name: "dynamodb", category: "database" },
  { name: "sqlite", category: "database" },
  { name: "oracle", category: "database" },
  { name: "mariadb", category: "database" },
  { name: "couchdb", category: "database" },
  { name: "neo4j", category: "database" },
  { name: "firebase", category: "database" },

  // Cloud
  { name: "aws", category: "cloud", synonyms: ["amazon web services"] },
  { name: "azure", category: "cloud", synonyms: ["microsoft azure"] },
  { name: "gcp", category: "cloud", synonyms: ["google cloud"] },
  { name: "terraform", category: "cloud" },
  { name: "kubernetes", category: "cloud", synonyms: ["k8s"] },
  { name: "docker", category: "cloud" },
  { name: "serverless", category: "cloud" },
  { name: "lambda", category: "cloud" },
  { name: "s3", category: "cloud" },
  { name: "ec2", category: "cloud" },
  { name: "cloudformation", category: "cloud" },

  // DevOps
  { name: "ci/cd", category: "devops" },
  { name: "jenkins", category: "devops" },
  { name: "gitlab ci", category: "devops" },
  { name: "github actions", category: "devops" },
  { name: "ansible", category: "devops" },
  { name: "chef", category: "devops" },
  { name: "puppet", category: "devops" },
  { name: "circleci", category: "devops" },
  { name: "travis ci", category: "devops" },
  { name: "prometheus", category: "devops" },
  { name: "grafana", category: "devops" },
  { name: "nagios", category: "devops" },

  // Data Science
  { name: "pandas", category: "data_science" },
  { name: "numpy", category: "data_science" },
  { name: "tensorflow", category: "data_science" },
  { name: "pytorch", category: "data_science" },
  { name: "scikit-learn", category: "data_science" },
  { name: "jupyter", category: "data_science" },
  { name: "jupyter notebook", category: "data_science" },
  { name: "apache spark", category: "data_science" },
  { name: "hadoop", category: "data_science" },
  { name: "kafka", category: "data_science" },
  { name: "airflow", category: "data_science" },
  { name: "databricks", category: "data_science" },

  // Project Management
  { name: "agile", category: "project_management", synonyms: ["scrum"] },
  { name: "scrum", category: "project_management" },
  { name: "kanban", category: "project_management" },
  { name: "jira", category: "project_management" },
  { name: "trello", category: "project_management" },
  { name: "asana", category: "project_management" },

  // Mobile
  { name: "ios", category: "mobile" },
  { name: "android", category: "mobile" },
  { name: "react native", category: "mobile" },
  { name: "flutter", category: "mobile" },
  { name: "xamarin", category: "mobile" },

  // Testing
  { name: "jest", category: "testing" },
  { name: "pytest", category: "testing" },
  { name: "selenium", category: "testing" },
  { name: "cypress", category: "testing" },
  { name: "mocha", category: "testing" },
  { name: "chai", category: "testing" },
  { name: "junit", category: "testing" },
  { name: "testng", category: "testing" },
  { name: "puppeteer", category: "testing" },

  // CI/CD
  { name: "git", category: "tool" },
  { name: "github", category: "tool" },
  { name: "gitlab", category: "tool" },
  { name: "bitbucket", category: "tool" },
  { name: "vs code", category: "tool" },
  { name: "intellij", category: "tool" },

  // Design
  { name: "figma", category: "design" },
  { name: "sketch", category: "design" },
  { name: "adobe xd", category: "design" },
  { name: "photoshop", category: "design" },
  { name: "illustrator", category: "design" },

  // Soft Skills
  { name: "communication", category: "soft_skill" },
  { name: "leadership", category: "soft_skill" },
  { name: "problem-solving", category: "soft_skill" },
  { name: "teamwork", category: "soft_skill" },
  { name: "time-management", category: "soft_skill" },
  { name: "critical thinking", category: "soft_skill" },
  { name: "adaptability", category: "soft_skill" },
  { name: "creativity", category: "soft_skill" },
  { name: "collaboration", category: "soft_skill" },
];

const now = new Date();
let bulkOps = [];

print("Preparing taxonomy upsert operations...");

for (const skill of skillsTaxonomy) {
  const nameNormalized = skill.name.toLowerCase().replace(/[^a-z0-9]/g, '');
  if (!nameNormalized) continue;

  bulkOps.push({
    updateOne: {
      filter: { name_normalized: nameNormalized },
      update: {
        $setOnInsert: {
          name: skill.name,
          name_normalized: nameNormalized,
          category: skill.category,
          subcategory: null,
          synonyms: skill.synonyms || [],
          is_active: true,
          created_at: now
        },
        $set: {
          updated_at: now
        }
      },
      upsert: true
    }
  });
}

if (bulkOps.length > 0) {
  const result = db.skills.bulkWrite(bulkOps, { ordered: false });
  print(`✓ Inserted/updated ${result.upsertedCount + result.modifiedCount} taxonomy skills`);
  print(`  (upserted: ${result.upsertedCount}, modified: ${result.modifiedCount})`);
}

// Extract additional skills from existing jobs
print("\nExtracting skills from existing job postings...");

const jobSkillsPipeline = [
  { $unwind: "$skills" },
  { $group: { _id: { $toLower: "$skills" }, count: { $sum: 1 } } },
  { $sort: { count: -1 } },
  { $limit: 500 }
];

try {
  const jobSkills = db.jobs.aggregate(jobSkillsPipeline).toArray();
  print(`  ℹ Found ${jobSkills.length} unique skills in existing jobs`);

  const additionalBulkOps = [];
  const now2 = new Date();
  let batchCount = 0;

  for (const skillDoc of jobSkills) {
    const skillName = skillDoc._id;
    if (!skillName || skillName.length > 100) continue;

    const normalized = skillName.replace(/[^a-z0-9]/g, '');
    if (!normalized) continue;

    additionalBulkOps.push({
      updateOne: {
        filter: { name_normalized: normalized },
        update: {
          $setOnInsert: {
            name: skillName,
            name_normalized: normalized,
            category: "tool",
            is_active: true,
            created_at: now2
          },
          $set: {
            updated_at: now2,
            popularity: skillDoc.count,
            synonyms: []
          }
        },
        upsert: true
      }
    });

    // Execute in batches
    if (additionalBulkOps.length >= 1000) {
      db.skills.bulkWrite(additionalBulkOps, { ordered: false });
      batchCount += additionalBulkOps.length;
      additionalBulkOps.length = 0;
    }
  }

  if (additionalBulkOps.length > 0) {
    db.skills.bulkWrite(additionalBulkOps, { ordered: false });
    batchCount += additionalBulkOps.length;
  }

  print(`✓ Extracted ${batchCount} additional skills into taxonomy`);
} catch (e) {
  print(`⚠ Error extracting skills from jobs: ${e.message}`);
}

// Create index on normalized name
print("\nCreating skills indexes...");
try {
  db.skills.createIndex(
    { name_normalized: 1 },
    { name: "idx_skills_normalized", unique: true }
  );
  print("✓ Created unique index on name_normalized");
} catch (e) {
  print(`  Index may exist: ${e.message}`);
}

try {
  db.skills.createIndex(
    { category: 1, popularity: -1 },
    { name: "idx_skills_category_popular" }
  );
  print("✓ Created category/popularity index");
} catch (e) {
  print(`  Index may exist: ${e.message}`);
}

// Statistics
const totalSkills = db.skills.countDocuments();
const activeSkills = db.skills.countDocuments({ is_active: true });
print(`\nSkills Collection Stats:`);
print(`  Total skills: ${totalSkills}`);
print(`  Active skills: ${activeSkills}`);
print(`  Category breakdown:`);

const categories = db.skills.aggregate([
  { $match: { is_active: true } },
  { $group: { _id: "$category", count: { $sum: 1 } } },
  { $sort: { count: -1 } }
]).toArray();

for (const cat of categories) {
  print(`    ${cat._id}: ${cat.count}`);
}

// Record migration
try {
  db._migrations.insertOne({
    migration: "003_skills_taxonomy",
    version: 3,
    applied_at: new Date(),
    checksum: "COMPUTED_DURING_DEPLOYMENT"
  });
} catch (e) {
  // Migration record might already exist
}

print(`\n╔════════════════════════════════════════════════════════════════╗`);
print(`║  Migration 003 Complete                                       ║`);
print(`╚════════════════════════════════════════════════════════════════╝\n`);

print("Next steps:");
print("  1. Review skill categories for correctness");
print("  2. Run migration 004 for company materialized view");
print("");
