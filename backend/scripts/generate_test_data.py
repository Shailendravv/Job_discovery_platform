#!/usr/bin/env python3
"""
Test Data Generator for Job Search Backend
Generates realistic test data for MongoDB collections.

Usage:
    python generate_test_data.py --uri "mongodb+srv://..." --db jobapp
    python generate_test_data.py --uri "..." --jobs 1000 --users 50 --applications 200
"""

import asyncio
import random
import uuid
from datetime import datetime, timedelta
from typing import List, Dict
from pathlib import Path

try:
    from motor.motor_asyncio import AsyncIOMotorClient
except ImportError:
    print("Error: Required packages not installed.")
    print("Run: pip install pymongo motor")
    exit(1)


# Test data generators
COMPANIES = [
    "TechCorp Inc", "Innovate Labs", "DataDriven AI", "CloudScale Inc",
    "StartupXYZ", "Enterprise Solutions", "Digital Makers", "Future Tech",
    "Global Systems", "NextGen Software", "Prime Digital", "Apex Technologies",
    "Bright Solutions", "Core Systems", "Dynamic Networks", "Elite IT",
    "First Response Tech", "Genius Labs", "Horizon Tech", "Innovation Co"
]

JOB_TITLES = [
    "Senior Python Developer", "Full Stack Engineer", "Data Scientist",
    "ML Engineer", "Backend Developer", "DevOps Engineer", "Frontend Developer",
    "Software Engineer", "Product Manager", "UX Designer", "Data Engineer",
    "Site Reliability Engineer", "Cloud Architect", "Security Engineer",
    "QA Engineer", "Mobile Developer", "Engineering Manager", "Tech Lead"
]

LOCATIONS = [
    "San Francisco, CA", "New York, NY", "Remote", "Austin, TX",
    "Seattle, WA", "Boston, MA", "Chicago, IL", "Los Angeles, CA",
    "Denver, CO", "Atlanta, GA", "Miami, FL", "Portland, OR"
]

JOB_TYPES = ["full-time", "remote", "contract", "hybrid", "on-site"]
SOURCES = ["linkedin", "searxng", "indeed", "glassdoor", "greenhouse", "lever"]

SKILLS_POOL = [
    "python", "javascript", "typescript", "java", "go", "rust", "ruby", "php",
    "react", "vue", "angular", "nextjs", "nodejs", "express", "django", "fastapi",
    "mongodb", "postgresql", "mysql", "redis", "elasticsearch",
    "aws", "azure", "gcp", "terraform", "kubernetes", "docker",
    "ci/cd", "jenkins", "gitlab ci", "github actions", "ansible",
    "pandas", "numpy", "tensorflow", "pytorch", "scikit-learn", "jupyter",
    "agile", "scrum", "kanban", "jira", "git", "github"
]


class TestDataGenerator:
    """Generates test data for the job search backend."""

    def __init__(self, db, seed: int = None):
        self.db = db
        self.random = random.Random(seed)
        self.now = datetime.utcnow()

    def generate_job(self) -> Dict:
        """Generate a single job document."""
        company = self.random.choice(COMPANIES)
        title = self.random.choice(JOB_TITLES)
        location = self.random.choice(LOCATIONS)
        source = self.random.choice(SOURCES)

        # Generate 3-10 random skills
        num_skills = self.random.randint(3, 10)
        skills = self.random.sample(SKILLS_POOL, num_skills)

        # Random posted date in last 30 days
        days_ago = self.random.randint(0, 30)
        posted_date_str = f"{days_ago} days ago" if days_ago > 0 else "today"
        posted_date = self.now - timedelta(days=days_ago)

        # Random salary range
        salary_base = self.random.choice([80, 100, 120, 150, 180, 200])
        salary_top = salary_base + self.random.randint(20, 100)
        salary = f"${salary_base}k - ${salary_top}k"

        company_normalized = company.lower().strip()
        dedup_key = f"{company}|{title}|{location}"
        import hashlib
        dedup_hash = hashlib.sha256(dedup_key.encode()).hexdigest()

        return {
            "title": title,
            "company": company,
            "company_normalized": company_normalized,
            "location": location,
            "description": (
                f"We are looking for an experienced {title} to join our team at {company}. "
                f"The ideal candidate will have expertise in {', '.join(skills[:3])} "
                f"and related technologies. This is a {self.random.choice(JOB_TYPES)} position "
                f"located in {location}. You will be responsible for developing and maintaining "
                f"scalable solutions, collaborating with cross-functional teams, and driving "
                f"technical innovation."
            ),
            "url": f"https://example.com/jobs/{uuid.uuid4().hex[:8]}",
            "apply_url": f"https://example.com/apply/{uuid.uuid4().hex[:8]}",
            "skills": skills,
            "job_type": self.random.choice(JOB_TYPES),
            "posted_date": posted_date_str,
            "posted_date_parsed": posted_date,
            "salary": salary,
            "source": source,
            "source_id": f"{source}_{uuid.uuid4().hex[:8]}",
            "created_at": self.now - timedelta(days=self.random.randint(0, 30)),
            "updated_at": self.now,
            "dedup_hash": dedup_hash,
            "search_query": self.random.choice([
                "python developer", "react engineer", "data scientist",
                "devops engineer", "full stack developer", None
            ])
        }

    def generate_user(self) -> Dict:
        """Generate a single user document."""
        user_id = f"testuser_{uuid.uuid4().hex[:8]}"
        first_name = self.random.choice([
            "John", "Jane", "Bob", "Alice", "Charlie", "Diana", "Eve", "Frank"
        ])
        last_name = self.random.choice([
            "Smith", "Johnson", "Williams", "Brown", "Jones", "Garcia", "Miller"
        ])

        return {
            "user_id": user_id,
            "email": f"{first_name.lower()}.{last_name.lower()}@example.com",
            "email_verified": True,
            "username": f"{first_name.lower()}{self.random.randint(10, 999)}",
            "password_hash": "$2b$12$" + uuid.uuid4().hex[:53],  # Fake hash
            "profile": {
                "first_name": first_name,
                "last_name": last_name,
                "bio": f"Experienced {self.random.choice(JOB_TITLES).lower()} passionate about {self.random.choice(SKILLS_POOL)}",
                "location": self.random.choice(LOCATIONS).split(",")[0],
                "linkedin_url": f"https://linkedin.com/in/{uuid.uuid4().hex[:8]}",
                "github_url": f"https://github.com/{first_name.lower()}{self.random.randint(1, 99)}"
            },
            "preferences": {
                "notifications_enabled": True,
                "preferred_job_types": self.random.sample(JOB_TYPES, k=self.random.randint(1, 3)),
                "preferred_locations": self.random.sample(LOCATIONS, k=self.random.randint(1, 3)),
                "search_radius_km": self.random.choice([10, 25, 50, 100])
            },
            "role": "user",
            "is_active": True,
            "created_at": self.now - timedelta(days=self.random.randint(0, 90)),
            "updated_at": self.now
        }

    def generate_resume(self, user: Dict) -> Dict:
        """Generate a resume document for a user."""
        # Generate some skills and experience
        user_skills = self.random.sample(SKILLS_POOL, k=self.random.randint(5, 15))
        experiences = []
        for _ in range(self.random.randint(1, 4)):
            company = self.random.choice(COMPANIES)
            title = self.random.choice(JOB_TITLES)
            experiences.append({
                "company": company,
                "title": title,
                "duration": f"{self.random.randint(1, 5)} years",
                "description": f"Worked on {self.random.choice(['web apps', 'data pipelines', 'cloud infrastructure', 'mobile apps'])} using {', '.join(user_skills[:3])}"
            })

        extracted_text = f"""
RESUME
======

Name: {user['profile']['first_name']} {user['profile']['last_name']}
Email: {user['email']}
Location: {user['profile'].get('location', 'N/A')}

SUMMARY
-------
Experienced {self.random.choice(JOB_TITLES)} with expertise in {', '.join(user_skills[:5])}.
Proven track record of delivering scalable solutions.

SKILLS
------
Technical: {', '.join(user_skills)}

EXPERIENCE
----------
""" + "\n".join([
            f"\n{e['title']} at {e['company']} ({e['duration']})\n  - {e['description']}"
            for e in experiences
        ]) + """

EDUCATION
---------
Bachelor's Degree in Computer Science
University of Technology, 2015-2019
"""

        return {
            "resume_id": f"res_{uuid.uuid4().hex[:12]}",
            "user_id": user["user_id"],
            "filename": f"resume_{user['user_id']}.pdf",
            "content_type": "application/pdf",
            "file_size": self.random.randint(10000, 200000),
            "extracted_text": extracted_text.strip(),
            "extracted_text_length": len(extracted_text.strip()),
            "parsed_data": {
                "name": f"{user['profile']['first_name']} {user['profile']['last_name']}",
                "email": user["email"],
                "skills": user_skills,
                "experience": experiences,
                "education": [{
                    "institution": "University of Technology",
                    "degree": "Bachelor's in Computer Science",
                    "year": 2019
                }]
            },
            "processing_status": "completed",
            "schema_version": 1,
            "created_at": self.now,
            "updated_at": self.now
        }

    def generate_application(self, user: Dict, job: Dict, resume: Dict = None) -> Dict:
        """Generate an application record."""
        statuses = ["applied", "emailed", "screening", "interview_scheduled",
                   "interview_completed", "rejected"]
        status = self.random.choice(statuses)

        status_history = [{
            "status": "applied",
            "changed_at": self.now - timedelta(days=30)
        }]

        if status != "applied":
            status_history.append({
                "status": status,
                "changed_at": self.now - timedelta(days=self.random.randint(1, 29))
            })

        return {
            "application_id": str(uuid.uuid4()),
            "user_id": user["user_id"],
            "job_id": job["_id"],
            "resume_id": resume["resume_id"] if resume else None,
            "status": status,
            "notes": self.random.choice([
                "Very interested in this position",
                "Great match for my skills",
                "Looking forward to hearing back",
                None, None
            ]),
            "applied_at": self.now - timedelta(days=30),
            "updated_at": self.now,
            "status_history": status_history,
            "external_application_url": job.get("apply_url"),
            "is_deleted": False
        }

    def generate_search_history(self, user: Dict) -> Dict:
        """Generate a search history record."""
        query = self.random.choice([
            "python developer remote",
            "react Engineer new york",
            "data scientist machine learning",
            "devops engineer aws",
            "full stack node react",
            "product manager startup",
            "ux designer portfolio",
            "security engineer cloud"
        ])

        return {
            "user_id": user["user_id"],
            "query": query,
            "parsed_query": {
                "skills": ["python", "react", "node"][:self.random.randint(0, 3)],
                "location": self.random.choice(["Remote", "San Francisco", "New York", None]),
                "job_types": self.random.sample(JOB_TYPES, k=1)
            },
            "results_count": self.random.randint(5, 50),
            "search_sources": self.random.sample(SOURCES, k=self.random.randint(1, 3)),
            "duration_ms": self.random.randint(500, 5000),
            "user_agent": "Mozilla/5.0 (compatible; JobSearchBot/1.0)",
            "session_id": str(uuid.uuid4()),
            "created_at": self.now - timedelta(
                days=self.random.randint(0, 90),
                hours=self.random.randint(0, 23)
            )
        }

    async def generate_and_insert(
        self,
        num_jobs: int = 1000,
        num_users: int = 50,
        num_applications: int = 200
    ) -> None:
        """Generate and insert all test data."""
        print(f"\nGenerating test data...")
        print(f"  Jobs: {num_jobs}")
        print(f"  Users: {num_users}")
        print(f"  Applications: {num_applications}")

        # Clear existing data (optional)
        confirm = input("\nClear existing collections? (yes/no): ")
        if confirm.lower() == "yes":
            print("Clearing collections...")
            for coll in ["jobs", "users", "resumes", "applications", "searchHistory"]:
                await self.db[coll].delete_many({})
                print(f"  Cleared {coll}")

        # Generate users first
        print("\nGenerating users...")
        users = [self.generate_user() for _ in range(num_users)]
        result = await self.db.users.insert_many(users)
        user_ids = [str(uid) for uid in result.inserted_ids]
        user_objects = [{**u, "_id": uid} for u, uid in zip(users, result.inserted_ids)]
        print(f"  ✓ Inserted {len(user_objects)} users")

        # Generate resumes for each user
        print("\nGenerating resumes...")
        resumes = []
        for user in user_objects:
            resume = self.generate_resume(user)
            resumes.append(resume)
        resume_result = await self.db.resumes.insert_many(resumes)
        print(f"  ✓ Inserted {len(resumes)} resumes")

        # Generate jobs
        print("\nGenerating jobs...")
        jobs = [self.generate_job() for _ in range(num_jobs)]
        job_result = await self.db.jobs.insert_many(jobs)
        job_objects = [{**j, "_id": jid} for j, jid in zip(jobs, job_result.inserted_ids)]
        print(f"  ✓ Inserted {len(job_objects)} jobs")

        # Generate applications
        print("\nGenerating applications...")
        applications = []
        for _ in range(num_applications):
            user = self.random.choice(user_objects)
            job = self.random.choice(job_objects)
            # 70% chance user has a resume
            resume = self.random.choice(resumes) if self.random.random() < 0.7 else None
            applications.append(self.generate_application(user, job, resume))

        app_result = await self.db.applications.insert_many(applications)
        print(f"  ✓ Inserted {len(applications)} applications")

        # Generate search history
        print("\nGenerating search history...")
        searches = []
        for user in user_objects:
            num_searches = self.random.randint(5, 50)
            searches.extend([self.generate_search_history(user) for _ in range(num_searches)])

        search_result = await self.db.searchHistory.insert_many(searches)
        print(f"  ✓ Inserted {len(searches)} search history records")

        # Summary
        print("\n" + "=" * 60)
        print("DATA GENERATION COMPLETE")
        print("=" * 60)
        print(f"  Users: {len(user_objects)}")
        print(f"  Resumes: {len(resumes)}")
        print(f"  Jobs: {len(job_objects)}")
        print(f"  Applications: {len(applications)}")
        print(f"  Search History: {len(searches)}")
        print("\nYou can now run integration tests against this data.")
        print("=" * 60)


async def main():
    import argparse

    parser = argparse.ArgumentParser(description="Generate test data for jobapp database")
    parser.add_argument("--uri", required=True, help="MongoDB connection URI")
    parser.add_argument("--db", default="jobapp", help="Database name")
    parser.add_argument("--jobs", type=int, default=1000, help="Number of jobs to generate")
    parser.add_argument("--users", type=int, default=50, help="Number of users to generate")
    parser.add_argument("--applications", type=int, default=200, help="Number of applications to generate")
    parser.add_argument("--seed", type=int, help="Random seed for reproducibility")

    args = parser.parse_args()

    client = AsyncIOMotorClient(args.uri)
    db = client[args.db]

    generator = TestDataGenerator(db, seed=args.seed)

    try:
        await generator.generate_and_insert(
            num_jobs=args.jobs,
            num_users=args.users,
            num_applications=args.applications
        )
    except Exception as e:
        print(f"\n✗ Error: {e}")
        import traceback
        traceback.print_exc()
    finally:
        client.close()


if __name__ == "__main__":
    asyncio.run(main())
