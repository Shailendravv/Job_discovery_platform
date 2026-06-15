#!/usr/bin/env python3
"""
MongoDB Migration Runner for Job Search Backend

Supports both JavaScript (mongosh) and Python (Motor) migrations.

Usage:
    python scripts/run_migrations.py --uri "mongodb+srv://..." --db jobapp
    python scripts/run_migrations.py --list   # List available migrations
    python scripts/run_migrations.py --status # Show migration status
    python scripts/run_migrations.py --rollback # Rollback all

Environment:
    MONGODB_URI=mongodb+srv://...  # Alternative to --uri
"""

import asyncio
import importlib.util
import inspect
import os
import sys
from pathlib import Path
from typing import List, Dict, Any

try:
    from motor.motor_asyncio import AsyncIOMotorClient
    from pymongo.errors import PyMongoError
except ImportError:
    print("Error: Required packages not installed.")
    print("Run: pip install pymongo motor")
    sys.exit(1)


MIGRATIONS_DIR = Path(__file__).parent.parent / "migrations"
MIGRATIONS_DIR = MIGRATIONS_DIR.resolve()
MIGRATIONS_COLLECTION = "_migrations"


class Migration:
    """Represents a migration (either JS or Python)."""

    def __init__(self, path: Path, migration_type: str):
        self.path = path
        self.name = path.stem
        self.type = migration_type  # 'python' or 'javascript'
        self.checksum = self._compute_checksum()
        self._module = None  # For Python migrations

    def _compute_checksum(self) -> str:
        """Compute SHA256 checksum of migration file."""
        import hashlib
        content = self.path.read_text(encoding='utf-8')
        return hashlib.sha256(content.encode()).hexdigest()[:16]

    def __repr__(self):
        return f"Migration({self.name}, type={self.type}, checksum={self.checksum})"


class MigrationRunner:
    """Orchestrates migration execution."""

    def __init__(self, uri: str, db_name: str = "jobapp"):
        self.uri = uri
        self.db_name = db_name
        self.client = None
        self.db = None
        self.migrations: List[Migration] = []

    async def connect(self):
        """Connect to MongoDB."""
        self.client = AsyncIOMotorClient(
            self.uri,
            maxPoolSize=10,
            serverSelectionTimeoutMS=5000
        )
        self.db = self.client[self.db_name]

        try:
            await self.client.admin.command("ping")
            print(f"✓ Connected to database: {self.db_name}")
        except PyMongoError as e:
            print(f"✗ Connection failed: {e}")
            raise

    async def disconnect(self):
        """Close database connection."""
        if self.client:
            self.client.close()

    def load_migrations(self):
        """Load all migration files (both .js and .py)."""
        self.migrations = []

        # Load Python migrations
        for py_file in sorted(MIGRATIONS_DIR.glob("*.py")):
            if py_file.name.startswith("__"):
                continue
            if py_file.name == "ROLLBACK.py":
                continue
            self.migrations.append(Migration(py_file, "python"))

        # Load JavaScript migrations
        for js_file in sorted(MIGRATIONS_DIR.glob("*.js")):
            if js_file.name.startswith("ROLLBACK"):
                continue
            self.migrations.append(Migration(js_file, "javascript"))

        # Sort by filename (001, 002, etc.)
        self.migrations.sort(key=lambda m: m.name)

        print(f"✓ Loaded {len(self.migrations)} migrations "
              f"({len([m for m in self.migrations if m.type == 'python'])} Python, "
              f"{len([m for m in self.migrations if m.type == 'javascript'])} JavaScript)")

    def list_migrations(self):
        """Display available migrations."""
        print("\nAvailable Migrations:")
        print("─" * 70)
        print(f"{'Name':<40} {'Type':<12} {'Checksum':<16} {'Status'}")
        print("─" * 70)

        for mig in self.migrations:
            print(f"{mig.name:<40} {mig.type:<12} {mig.checksum:<16} pending")

        print("─" * 70)

    async def get_applied_migrations(self) -> List[Dict]:
        """Get list of already applied migrations."""
        try:
            applied = await self.db[MIGRATIONS_COLLECTION].find(
                {}, {"_id": 0, "migration": 1, "version": 1, "applied_at": 1}
            ).sort("version", 1).to_list(None)
            return applied
        except PyMongoError:
            return []

    async def apply_migration(self, migration: Migration) -> bool:
        """Apply a single migration."""
        print(f"\n▶ Applying migration: {migration.name} ({migration.type})")

        if migration.type == "python":
            return await self._apply_python_migration(migration)
        else:
            return await self._apply_javascript_migration(migration)

    async def _apply_python_migration(self, migration: Migration) -> bool:
        """Apply a Python migration by importing and running its Migration class."""
        try:
            # Import the module
            spec = importlib.util.spec_from_file_location(
                f"migrations.{migration.name}",
                migration.path
            )
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)

            # Find a class that has a 'run' method and a 'name' attribute
            migration_class = None
            for name, obj in inspect.getmembers(module, inspect.isclass):
                if hasattr(obj, 'run') and hasattr(obj, 'name'):
                    # Check if this class belongs to this module (not imported from elsewhere)
                    if obj.__module__ == module.__name__:
                        migration_class = obj
                        break

            if not migration_class:
                print(f"✗ Migration {migration.name} has no Migration class with run() method")
                return False

            # Instantiate and run
            instance = migration_class()
            await instance.run(self.db)

            # Verify migration was recorded
            applied = await self.db[MIGRATIONS_COLLECTION].find_one(
                {"migration": migration.name}
            )

            if applied:
                print(f"✓ Migration {migration.name} applied successfully")
                print(f"  Version: {applied.get('version')}")
                print(f"  Applied at: {applied.get('applied_at')}")
                return True
            else:
                print(f"⚠ Migration {migration.name} executed but not recorded")
                return False

        except Exception as e:
            print(f"✗ Failed to apply {migration.name}: {e}")
            import traceback
            traceback.print_exc()
            return False

    async def _apply_javascript_migration(self, migration: Migration) -> bool:
        """Apply a JavaScript migration using mongosh."""
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
                timeout=300
            )

            print(result.stdout)

            if result.returncode != 0:
                print(f"✗ Migration failed with exit code {result.returncode}")
                print("STDERR:", result.stderr)
                return False

            # Verify it was recorded
            applied = await self.db[MIGRATIONS_COLLECTION].find_one(
                {"migration": migration.name}
            )

            if applied:
                print(f"✓ Migration {migration.name} applied successfully")
                return True
            else:
                print(f"⚠ Migration {migration.name} executed but not recorded")
                return False

        except subprocess.TimeoutExpired:
            print(f"✗ Migration {migration.name} timed out after 5 minutes")
            return False
        except FileNotFoundError:
            print("✗ mongosh not found in PATH")
            print("  Install MongoDB Shell or use Python migrations instead")
            return False

    async def rollback_all(self) -> bool:
        """Rollback all migrations (destructive)."""
        try:
            # Import the ROLLBACK module
            spec = importlib.util.spec_from_file_location(
                "migrations.ROLLBACK",
                MIGRATIONS_DIR / "ROLLBACK.py"
            )
            if not spec or not spec.loader:
                print("✗ Could not load ROLLBACK.py")
                return False

            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)

            # Find the Rollback class
            rollback_class = None
            for name, obj in inspect.getmembers(module, inspect.isclass):
                if hasattr(obj, 'run') and obj.__module__ == module.__name__:
                    rollback_class = obj
                    break

            if not rollback_class:
                print("✗ No Rollback class found in ROLLBACK.py")
                return False

        except Exception as e:
            print(f"✗ Error loading ROLLBACK: {e}")
            return False

        applied = await self.get_applied_migrations()

        if not applied:
            print("No migrations to rollback")
            return True

        print(f"\nApplied migrations to rollback ({len(applied)}):")
        for a in applied:
            print(f"  - {a['migration']} (v{a.get('version', '?')})")

        response = input("\nRollback ALL migrations? THIS WILL DELETE DATA! (type 'YES'): ")
        if response != "YES":
            print("Cancelled")
            return False

        rollback = rollback_class()
        await rollback.run(self.db, confirmed=True)
        return True

    async def status(self):
        """Show migration status."""
        applied = await self.get_applied_migrations()
        applied_names = {a["migration"] for a in applied}

        print("\nMigration Status:")
        print("─" * 80)
        print(f"{'Migration':<40} {'Type':<12} {'Status':<12} {'Version':<8} {'Applied At'}")
        print("─" * 80)

        for mig in self.migrations:
            if mig.name in applied_names:
                record = next((a for a in applied if a["migration"] == mig.name), {})
                status = "✓ Applied"
                version = str(record.get("version", "-"))
                applied_at = record.get("applied_at", "").strftime("%Y-%m-%d %H:%M") if record.get("applied_at") else "-"
            else:
                status = "pending"
                version = "-"
                applied_at = "-"

            print(f"{mig.name:<40} {mig.type:<12} {status:<12} {version:<8} {applied_at}")

        print("─" * 80)
        print(f"Total: {len(self.migrations)} migrations, {len(applied)} applied")

        # Collection counts
        print("\nCollection Document Counts:")
        collections = ["jobs", "resumes", "users", "applications", "companies",
                      "skills", "searchHistory", "jobMatches"]
        for coll in collections:
            try:
                count = await self.db[coll].count_documents({})
                print(f"  {coll:<20} {count:>8}")
            except:
                print(f"  {coll:<20} {'N/A':>8}")

    async def run_all(self) -> bool:
        """Run all pending migrations in order."""
        applied = await self.get_applied_migrations()
        applied_names = {a["migration"] for a in applied}

        print(f"\nApplied migrations: {len(applied)}")
        for a in applied[:5]:
            print(f"  - {a['migration']} (v{a.get('version')})")
        if len(applied) > 5:
            print(f"  ... and {len(applied) - 5} more")

        pending = [m for m in self.migrations if m.name not in applied_names]

        if not pending:
            print("\n✓ No pending migrations to apply")
            return True

        print(f"\nPending migrations ({len(pending)}):")
        for mig in pending:
            print(f"  - {mig.name} ({mig.type})")

        response = input(f"\nApply {len(pending)} migration(s)? (yes/no): ")
        if response.lower() != "yes":
            print("Cancelled")
            return False

        # Apply in order
        all_success = True
        for mig in pending:
            try:
                success = await self.apply_migration(mig)
                if not success:
                    all_success = False
                    response = input("Continue with next migration? (yes/no): ")
                    if response.lower() != "yes":
                        break
            except Exception as e:
                print(f"\n✗ Error applying {mig.name}: {e}")
                all_success = False
                response = input("Continue? (yes/no): ")
                if response.lower() != "yes":
                    break

        print("\n✅ Migration run complete" if all_success else "\n⚠ Migration run completed with errors")
        return all_success


async def main():
    import argparse

    parser = argparse.ArgumentParser(description="MongoDB Migration Runner (Python & JavaScript)")
    parser.add_argument("--uri", help="MongoDB connection URI")
    parser.add_argument("--db", default="jobapp", help="Database name")
    parser.add_argument("--list", action="store_true", help="List available migrations")
    parser.add_argument("--status", action="store_true", help="Show migration status")
    parser.add_argument("--rollback", action="store_true", help="Rollback all migrations")

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
            await runner.run_all()

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
