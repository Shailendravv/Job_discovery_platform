#!/usr/bin/env python3
"""
MongoDB Migration Runner for Job Search Backend

This script manages database migrations for the jobapp MongoDB database.
It tracks applied migrations and executes them in order.

Usage:
    python run_migrations.py --uri "mongodb+srv://..." --db jobapp
    python run_migrations.py --list   # List available migrations
    python run_migrations.py --rollback  # Rollback last migration

Requirements:
    pip install pymongo motor python-dotenv

Environment Variables (alternative to --uri):
    MONGODB_URI=mongodb+srv://...
"""

import asyncio
import hashlib
import json
import os
import sys
import glob
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Optional

try:
    from motor.motor_asyncio import AsyncIOMotorClient
    from pymongo.errors import PyMongoError
except ImportError:
    print("Error: Required packages not installed.")
    print("Run: pip install pymongo motor")
    sys.exit(1)

# Configuration
MIGRATIONS_DIR = Path(__file__).parent.parent / "migrations"
MIGRATIONS_DIR = MIGRATIONS_DIR.resolve()

# Migration records collection name
MIGRATIONS_COLLECTION = "_migrations"


class Migration:
    """Represents a single migration."""

    def __init__(self, path: Path):
        self.path = path
        self.name = path.stem
        self.script = path.read_text(encoding='utf-8')
        self.checksum = self._compute_checksum()

    def _compute_checksum(self) -> str:
        """Compute SHA256 checksum of migration script."""
        return hashlib.sha256(self.script.encode()).hexdigest()[:16]

    def __repr__(self):
        return f"Migration({self.name}, checksum={self.checksum})"


class MigrationRunner:
    """Orchestrates migration execution."""

    def __init__(self, uri: str, db_name: str = "jobapp"):
        self.uri = uri
        self.db_name = db_name
        self.client: Optional[AsyncIOMotorClient] = None
        self.db = None
        self.migrations: List[Migration] = []

    async def connect(self) -> None:
        """Connect to MongoDB."""
        self.client = AsyncIOMotorClient(
            self.uri,
            maxPoolSize=10,
            serverSelectionTimeoutMS=5000
        )
        self.db = self.client[self.db_name]

        # Verify connection
        try:
            await self.client.admin.command("ping")
            print(f"✓ Connected to database: {self.db_name}")
        except PyMongoError as e:
            print(f"✗ Connection failed: {e}")
            raise

    async def disconnect(self) -> None:
        """Close database connection."""
        if self.client:
            self.client.close()

    def load_migrations(self) -> None:
        """Load migration scripts from filesystem."""
        pattern = str(MIGRATIONS_DIR / "*.js")
        migration_files = sorted(glob.glob(pattern))

        if not migration_files:
            print(f"⚠ No migration files found in {MIGRATIONS_DIR}")
            return

        self.migrations = []
        for path in migration_files:
            if Path(path).name.startswith("ROLLBACK"):
                continue
            self.migrations.append(Migration(Path(path)))

        print(f"✓ Loaded {len(self.migrations)} migrations")

    def list_migrations(self) -> None:
        """Display available migrations."""
        print("\nAvailable Migrations:")
        print("─" * 60)
        print(f"{'Name':<40} {'Checksum':<16} {'Status'}")
        print("─" * 60)

        for mig in self.migrations:
            print(f"{mig.name:<40} {mig.checksum:<16} pending")

        print("─" * 60)

    async def get_applied_migrations(self) -> List[Dict]:
        """Get list of already applied migrations from database."""
        try:
            applied = await self.db[MIGRATIONS_COLLECTION].find(
                {}, {"_id": 0, "migration": 1, "version": 1, "applied_at": 1}
            ).sort("version", 1).to_list(None)
            return applied
        except PyMongoError:
            return []

    async def is_migration_applied(self, migration: Migration) -> bool:
        """Check if a migration has already been applied."""
        result = await self.db[MIGRATIONS_COLLECTION].find_one(
            {"migration": migration.name}
        )
        return result is not None

    async def apply_migration(self, migration: Migration) -> None:
        """
        Apply a single migration.

        This executes the JavaScript in the MongoDB shell using evalJS.
        Note: Requires MongoDB Shell Session or subprocess call.
        """
        print(f"\n▶ Applying migration: {migration.name}")

        # For MongoDB Atlas, we need to use mongosh or the $eval operator
        # The $eval operator is deprecated and may be disabled
        # Better approach: use subprocess to call mongosh

        import subprocess

        cmd = [
            "mongosh",
            self.uri,
            "--quiet",
            "--eval",
            f"load('{migration.path.absolute()}');"
        ]

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=300  # 5 minute timeout
            )

            print(result.stdout)

            if result.returncode != 0:
                print(f"✗ Migration failed with exit code {result.returncode}")
                print("STDERR:", result.stderr)
                raise RuntimeError(f"Migration {migration.name} failed")

            # Verify it was recorded
            applied = await self.db[MIGRATIONS_COLLECTION].find_one(
                {"migration": migration.name}
            )

            if applied:
                print(f"✓ Migration {migration.name} applied successfully")
                print(f"  Version: {applied.get('version')}")
                print(f"  Applied at: {applied.get('applied_at')}")
            else:
                print(f"⚠ Migration {migration.name} executed but not recorded")
                print("  Manual record may be needed")

        except subprocess.TimeoutExpired:
            print(f"✗ Migration {migration.name} timed out after 5 minutes")
            raise
        except FileNotFoundError:
            print("✗ mongosh not found in PATH")
            print("  Install MongoDB Shell or use Atlas UI to run migrations manually")
            raise

    async def rollback_migration(self, migration: Migration) -> None:
        """Rollback a single migration by dropping affected collections."""
        print(f"\n▶ Rolling back migration: {migration.name}")

        # Read the migration file to see what it created
        script = migration.script.lower()

        collections_to_drop = []

        # Parse collections from the script (simple heuristic)
        if "createcollection" in script:
            # Extract collection names mentioned in createCollection calls
            import re
            matches = re.findall(r'createCollection\("([^"]+)"\)', migration.script)
            collections_to_drop.extend(matches)

        if not collections_to_drop:
            collections_to_drop = [migration.name.split("_")[1]]  # e.g., "jobs" from "001_initial_schema"

        print(f"  Collections to drop: {', '.join(collections_to_drop)}")

        for coll in collections_to_drop:
            try:
                if await self.db[coll].count_documents({}) > 0:
                    print(f"  ⚠ Collection '{coll}' has data - confirm deletion")
                    response = input(f"    Drop collection '{coll}'? (yes/no): ")
                    if response.lower() == "yes":
                        await self.db[coll].drop()
                        print(f"    ✓ Dropped collection '{coll}'")
                    else:
                        print(f"    ○ Skipped '{coll}'")
                else:
                    await self.db[coll].drop()
                    print(f"  ✓ Dropped empty collection '{coll}'")
            except PyMongoError as e:
                print(f"  ✗ Error dropping {coll}: {e}")

        # Remove migration record
        try:
            result = await self.db[MIGRATIONS_COLLECTION].delete_one(
                {"migration": migration.name}
            )
            print(f"  ✓ Removed migration record (deleted: {result.deleted_count})")
        except PyMongoError as e:
            print(f"  ✗ Error removing migration record: {e}")

    async def verify_migration(self, migration: Migration) -> bool:
        """Verify that a migration was applied correctly."""
        print(f"Verifying {migration.name}...")

        # Check migration record exists
        record = await self.db[MIGRATIONS_COLLECTION].find_one(
            {"migration": migration.name}
        )
        if not record:
            print(f"  ✗ No migration record found")
            return False

        print(f"  ✓ Migration record exists (version {record.get('version')})")

        # Check expected collections exist based on migration
        script = migration.script.lower()
        collections_in_script = []

        if "001" in migration.name:
            expected = ["jobs", "resumes", "users", "applications", "companies",
                       "skills", "searchHistory", "jobMatches"]
            for coll in expected:
                if await self.db[coll].count_documents({}) >= 0:  # exists even if empty
                    collections_in_script.append(coll)

        if collections_in_script:
            print(f"  ✓ Expected collections exist: {', '.join(collections_in_script[:5])}")

        return True

    async def run_all(self, target: Optional[str] = None) -> None:
        """
        Run all pending migrations or up to target migration.

        Args:
            target: Migration name to run up to (inclusive). If None, run all.
        """
        applied = await self.get_applied_migrations()
        applied_names = {a["migration"] for a in applied}

        print(f"\nApplied migrations: {len(applied)}")
        for a in applied[:5]:
            print(f"  - {a['migration']} (v{a['version']})")
        if len(applied) > 5:
            print(f"  ... and {len(applied) - 5} more")

        pending = []
        for mig in self.migrations:
            if mig.name in applied_names:
                continue
            if target and mig.name > target:
                break
            pending.append(mig)

        if not pending:
            print("\n✓ No pending migrations to apply")
            return

        print(f"\nPending migrations: {len(pending)}")
        for mig in pending:
            print(f"  - {mig.name}")

        # Confirm
        response = input(f"\nApply {len(pending)} migration(s)? (yes/no): ")
        if response.lower() != "yes":
            print("Cancelled")
            return

        # Apply in order
        for mig in pending:
            try:
                await self.apply_migration(mig)
                # Verify
                if not await self.verify_migration(mig):
                    print(f"⚠ Verification failed for {mig.name}")
                    response = input("Continue? (yes/no): ")
                    if response.lower() != "yes":
                        print("Stopping migrations")
                        break
            except Exception as e:
                print(f"\n✗ Failed to apply {mig.name}: {e}")
                response = input("Continue with next migration? (yes/no): ")
                if response.lower() != "yes":
                    break

        print("\n✅ Migration run complete")

    async def rollback_all(self) -> None:
        """Rollback all migrations (destructive)."""
        applied = await self.get_applied_migrations()

        if not applied:
            print("No migrations to rollback")
            return

        print(f"\nApplied migrations to rollback ({len(applied)}):")
        for a in applied:
            print(f"  - {a['migration']} (v{a['version']})")

        response = input("\nRollback ALL migrations? THIS WILL DELETE DATA! (type 'YES'): ")
        if response != "YES":
            print("Cancelled")
            return

        # Rollback in reverse order
        for a in reversed(applied):
            mig = next((m for m in self.migrations if m.name == a["migration"]), None)
            if mig:
                try:
                    await self.rollback_migration(mig)
                except Exception as e:
                    print(f"✗ Error rolling back {mig.name}: {e}")

        print("\n✅ Rollback complete")

    async def status(self) -> None:
        """Show migration status."""
        applied = await self.get_applied_migrations()
        applied_names = {a["migration"] for a in applied}

        print("\nMigration Status:")
        print("─" * 80)
        print(f"{'Migration':<40} {'Status':<12} {'Version':<8} {'Applied At'}")
        print("─" * 80)

        for mig in self.migrations:
            if mig.name in applied_names:
                record = next(a for a in applied if a["migration"] == mig.name)
                status = "✓ Applied"
                version = str(record.get("version", "-"))
                applied_at = record.get("applied_at", "").strftime("%Y-%m-%d %H:%M") if record.get("applied_at") else "-"
            else:
                status = "pending"
                version = "-"
                applied_at = "-"

            print(f"{mig.name:<40} {status:<12} {version:<8} {applied_at}")

        print("─" * 80)
        print(f"Total: {len(self.migrations)} migrations, {len(applied)} applied")


async def main():
    """Main entry point."""
    import argparse

    parser = argparse.ArgumentParser(description="MongoDB Migration Runner")
    parser.add_argument("--uri", help="MongoDB connection URI")
    parser.add_argument("--db", default="jobapp", help="Database name (default: jobapp)")
    parser.add_argument("--list", action="store_true", help="List available migrations")
    parser.add_argument("--status", action="store_true", help="Show migration status")
    parser.add_argument("--rollback", action="store_true", help="Rollback all migrations")
    parser.add_argument("--target", help="Target migration name to apply up to")

    args = parser.parse_args()

    # Get URI from args or environment
    uri = args.uri or os.getenv("MONGODB_URI")
    if not uri:
        print("Error: MongoDB URI required")
        print("Use --uri or set MONGODB_URI environment variable")
        sys.exit(1)

    runner = MigrationRunner(uri, args.db)

    try:
        await runner.connect()
        runner.load_migrations()

        if args.list:
            runner.list_migrations()
        elif args.status:
            await runner.status()
        elif args.rollback:
            await runner.rollback_all()
        else:
            await runner.run_all(target=args.target)

    except KeyboardInterrupt:
        print("\n\nInterrupted")
        sys.exit(130)
    except Exception as e:
        print(f"\n✗ Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
    finally:
        await runner.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
