"""jobctl entry point (PLAN.md §3). Milestone 1 commands only:

    jobctl ingest [--source X] [--org X] [--dry-run] [--json]
    jobctl sources list [--json]
    jobctl sources doctor [--json]
    jobctl stats [--json]

Later milestones add ``profile``, ``list``, ``next``, ``judge``, ``shortlist``,
``show``, ``mark``, ``tailor``, ``cover``, ``digest``.
"""

import asyncio
import json as jsonlib
import logging
from dataclasses import asdict
from typing import Optional

import typer

from app.ingest.doctor import run_doctor, summarize
from app.ingest.registry import load_and_resolve_sources
from app.ingest.runner import run_ingest
from jobctl.db import db_session

logging.basicConfig(level=logging.WARNING, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")

app = typer.Typer(add_completion=False, help="ATS ingestion + judging pipeline CLI (PLAN.md).")
sources_app = typer.Typer(add_completion=False, help="Inspect the ATS company registry.")
app.add_typer(sources_app, name="sources")


def _print(data: dict, as_json: bool) -> None:
    if as_json:
        typer.echo(jsonlib.dumps(data, indent=2, default=str))
    else:
        _print_human(data)


def _print_human(data: dict) -> None:
    for key, value in data.items():
        if key in ("outcomes", "entries", "sources"):
            continue
        typer.echo(f"{key}: {value}")


@app.command()
def ingest(
    source: Optional[str] = typer.Option(None, "--source", help="Only this provider id (e.g. greenhouse)."),
    org: Optional[str] = typer.Option(None, "--org", help="Only this company (matches org slug or name)."),
    all_: bool = typer.Option(True, "--all/--no-all", help="Ingest the full registry (default)."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Fetch + normalize + dedupe, skip the DB write."),
    json_out: bool = typer.Option(False, "--json", help="Machine-readable JSON output."),
) -> None:
    """Fetch postings from ATS providers, normalize, dedupe, and upsert into
    the ``postings`` collection. Idempotent — a second run should insert ~0
    new rows (PLAN.md §2 acceptance criteria)."""

    async def _run():
        async with db_session() as db:
            return await run_ingest(db, source_filter=source, org_filter=org, dry_run=dry_run)

    result = asyncio.run(_run())
    data = result.to_dict()

    if json_out:
        typer.echo(jsonlib.dumps(data, indent=2, default=str))
        return

    typer.echo(f"run_id: {data['run_id']}{'  (dry-run)' if dry_run else ''}")
    typer.echo(f"sources: {data['sources_total']} total, {data['sources_ok']} ok, "
               f"{data['sources_error']} errored, {data['sources_skipped']} skipped")
    typer.echo(f"postings: {data['postings_fetched']} fetched, {data['postings_normalized']} normalized, "
               f"{data['duplicates_marked']} marked as near-duplicates")
    typer.echo(f"store: {data['inserted']} inserted, {data['updated']} updated")

    errors = [o for o in data["outcomes"] if o["status"] == "error"]
    if errors:
        typer.echo("\nsource errors:")
        for e in errors:
            typer.echo(f"  - {e['name']} ({e['provider']}): {e['error']}")

    if data.get("write_errors"):
        typer.echo(f"\n{len(data['write_errors'])} document(s) failed schema validation and were skipped:")
        for e in data["write_errors"]:
            typer.echo(f"  - {e}")


@sources_app.command("list")
def sources_list(json_out: bool = typer.Option(False, "--json")) -> None:
    """List every registry entry and which provider it resolved to."""
    sources = load_and_resolve_sources()
    rows = [
        {
            "name": s.name,
            "org": s.org,
            "provider": s.provider_id,
            "careers_url": s.careers_url,
            "enabled": s.enabled,
            "tags": s.tags,
        }
        for s in sources
    ]

    if json_out:
        typer.echo(jsonlib.dumps(rows, indent=2))
        return

    for row in rows:
        flag = "" if row["enabled"] else " [disabled]"
        provider = row["provider"] or "NO MATCH"
        typer.echo(f"{row['name']:<30} {provider:<12} {row['careers_url']}{flag}")
    typer.echo(f"\n{len(rows)} sources total")


@sources_app.command("doctor")
def sources_doctor(json_out: bool = typer.Option(False, "--json")) -> None:
    """Live-probe every source and report 0-job / errored / unmatched orgs
    so dead tokens get caught before a nightly run wastes time on them."""
    entries = asyncio.run(run_doctor())
    rows = [asdict(e) for e in entries]
    summary = summarize(entries)

    if json_out:
        typer.echo(jsonlib.dumps({"summary": summary, "entries": rows}, indent=2))
        return

    for row in rows:
        marker = {
            "ok": "✓", "not_ingestable_probe_ok": "✓",
            "zero_jobs": "⚠", "disabled": "-",
        }.get(row["status"], "✗")
        detail = f"{row['job_count']} jobs" if row["status"] in ("ok", "zero_jobs", "not_ingestable_probe_ok") else (row["error"] or row["status"])
        typer.echo(f"{marker} {row['name']:<30} {(row['provider'] or '-'):<12} {row['status']:<24} {detail}")

    typer.echo(f"\nsummary: {summary}")


@app.command()
def stats(json_out: bool = typer.Option(False, "--json")) -> None:
    """Posting counts overall, per-provider, and new in the last 24h."""

    async def _run() -> dict:
        async with db_session() as db:
            from datetime import datetime, timedelta, timezone

            total = await db.postings.count_documents({})
            duplicates = await db.postings.count_documents({"duplicate_of": {"$ne": None}})
            since = datetime.now(timezone.utc) - timedelta(hours=24)
            new_24h = await db.postings.count_documents({"first_seen_at": {"$gte": since}})

            per_provider: dict[str, int] = {}
            async for doc in db.postings.aggregate([{"$group": {"_id": "$provider", "count": {"$sum": 1}}}]):
                per_provider[doc["_id"] or "unknown"] = doc["count"]

            last_run = await db.ingest_runs.find_one(sort=[("started_at", -1)])

            return {
                "total_postings": total,
                "duplicates": duplicates,
                "new_last_24h": new_24h,
                "per_provider": per_provider,
                "last_run": {
                    "run_id": last_run.get("_id"),
                    "started_at": last_run.get("started_at"),
                    "inserted": last_run.get("inserted"),
                    "updated": last_run.get("updated"),
                } if last_run else None,
            }

    data = asyncio.run(_run())
    _print(data, json_out)


if __name__ == "__main__":
    app()
