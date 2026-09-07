"""jobctl entry point (PLAN.md §3). Milestone 1 + 2 commands:

    jobctl ingest [--source X] [--org X] [--dry-run] [--json]
    jobctl sources list [--json]
    jobctl sources doctor [--json]
    jobctl stats [--json]
    jobctl list [--new] [--since 24h] [--unjudged|--judged] [--verdict X]
                [--provider X] [--org X] [--limit 40] [--json]
    jobctl show <id> [--json]
    jobctl next [--limit 25] [--format md|json]
    jobctl judge --apply verdicts.json [--force] [--json]

Later milestones add ``profile``, ``shortlist``, ``mark``, ``tailor``,
``cover``, ``digest``.
"""

import asyncio
import json as jsonlib
import logging
from dataclasses import asdict
from pathlib import Path
from typing import Optional

import typer
from pydantic import ValidationError

from app.ingest.doctor import run_doctor, summarize
from app.ingest.format import render_posting_md, render_posting_summary
from app.ingest.ids import assign_short_ids, resolve_posting_id, short_id
from app.ingest.query import DEFAULT_LIST_LIMIT, DEFAULT_NEXT_LIMIT, PostingFilter, list_postings, next_postings
from app.ingest.registry import load_and_resolve_sources
from app.ingest.runner import run_ingest
from app.ingest.time_util import parse_duration
from app.ingest.verdicts import Verdict, apply_verdicts
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


@app.command("list")
def list_cmd(
    new: bool = typer.Option(False, "--new", help="Only postings first seen within --since (default 24h)."),
    since: Optional[str] = typer.Option(None, "--since", help="Time window, e.g. 24h, 7d, 30m."),
    unjudged: bool = typer.Option(False, "--unjudged", help="Only postings not yet judged."),
    judged: bool = typer.Option(False, "--judged", help="Only postings already judged."),
    verdict: Optional[str] = typer.Option(None, "--verdict", help="apply|maybe|skip"),
    provider: Optional[str] = typer.Option(None, "--provider"),
    org: Optional[str] = typer.Option(None, "--org"),
    limit: int = typer.Option(DEFAULT_LIST_LIMIT, "--limit"),
    json_out: bool = typer.Option(False, "--json"),
) -> None:
    """List postings, most recently seen first. Excludes near-duplicates."""
    if unjudged and judged:
        typer.echo("error: pass at most one of --unjudged / --judged", err=True)
        raise typer.Exit(1)
    if verdict is not None and verdict not in ("apply", "maybe", "skip"):
        typer.echo("error: --verdict must be apply, maybe, or skip", err=True)
        raise typer.Exit(1)

    try:
        since_delta = parse_duration(since) if since else (parse_duration("24h") if new else None)
    except ValueError as e:
        typer.echo(f"error: {e}", err=True)
        raise typer.Exit(1)

    filters = PostingFilter(
        judged=True if judged else (False if unjudged else None),
        verdict=verdict,
        provider=provider,
        org=org,
        since=since_delta,
    )

    async def _run() -> list[dict]:
        async with db_session() as db:
            return await list_postings(db, filters, limit=limit)

    docs = asyncio.run(_run())
    display_ids = assign_short_ids([d["_id"] for d in docs])
    rows = [render_posting_summary(d, display_ids[d["_id"]]) for d in docs]

    if json_out:
        typer.echo(jsonlib.dumps(rows, indent=2, default=str))
        return

    for row in rows:
        state = f"judged:{row['verdict']}" if row["judged"] else "unjudged"
        typer.echo(f"[{row['id']}] {row['title']} — {row['company_name']} ({row['provider']}, {state})")
    typer.echo(f"\n{len(rows)} posting(s)")


@app.command()
def show(
    id: str = typer.Argument(..., help="Full posting id or an unambiguous prefix."),
    json_out: bool = typer.Option(False, "--json"),
) -> None:
    """Show one posting in full, including its verdict if judged."""

    async def _run() -> tuple[Optional[dict], Optional[str], Optional[dict]]:
        async with db_session() as db:
            doc, error = await resolve_posting_id(db, id)
            if doc is None:
                return None, error, None
            verdict_doc = await db.verdicts.find_one({"_id": doc["_id"]}) if doc.get("judged") else None
            return doc, None, verdict_doc

    doc, error, verdict_doc = asyncio.run(_run())
    if error:
        typer.echo(f"error: {error}", err=True)
        raise typer.Exit(1)

    if json_out:
        data = dict(doc)
        if verdict_doc:
            data["verdict_detail"] = verdict_doc
        typer.echo(jsonlib.dumps(data, indent=2, default=str))
        return

    typer.echo(f"[{short_id(doc['_id'])}] {doc['title']} — {doc['company_name']}")
    typer.echo(f"full id: {doc['_id']}")
    typer.echo(f"location: {doc.get('location') or 'n/a'}{' (remote)' if doc.get('remote_flag') else ''}")
    typer.echo(f"provider/org: {doc.get('provider')}/{doc.get('org')}")
    typer.echo(f"posted: {doc.get('posted_at')} · first seen: {doc.get('first_seen_at')}")
    typer.echo(f"url: {doc.get('url')}")
    if doc.get("duplicate_of"):
        typer.echo(f"duplicate of: {doc['duplicate_of']}")
    typer.echo(f"\n{doc.get('description_text') or ''}")

    if verdict_doc:
        typer.echo(f"\n--- verdict: {verdict_doc.get('verdict')} (score {verdict_doc.get('score')}) ---")
        typer.echo(f"judged by {verdict_doc.get('judged_by')} at {verdict_doc.get('judged_at')}")
        for label, key in (
            ("reasons", "reasons"), ("concerns", "concerns"),
            ("matched requirements", "matched_requirements"),
            ("missing requirements", "missing_requirements"),
        ):
            values = verdict_doc.get(key) or []
            if values:
                typer.echo(f"{label}: " + "; ".join(values))


@app.command("next")
def next_cmd(
    limit: int = typer.Option(DEFAULT_NEXT_LIMIT, "--limit"),
    format: str = typer.Option("md", "--format", help="md|json"),
) -> None:
    """Next batch of unjudged postings for the agent to read (PLAN.md §3).
    Returns empty (no stdout for md, ``[]`` for json) once nothing is left
    to judge — ``jobctl judge --apply`` marks postings judged, so looping
    this command needs no offset/cursor of its own."""
    if format not in ("md", "json"):
        typer.echo("error: --format must be md or json", err=True)
        raise typer.Exit(1)

    async def _run() -> list[dict]:
        async with db_session() as db:
            return await next_postings(db, limit=limit)

    docs = asyncio.run(_run())
    if not docs:
        if format == "json":
            typer.echo("[]")
        return

    display_ids = assign_short_ids([d["_id"] for d in docs])

    if format == "json":
        rows = [render_posting_summary(d, display_ids[d["_id"]]) for d in docs]
        typer.echo(jsonlib.dumps(rows, indent=2, default=str))
        return

    for doc in docs:
        typer.echo(render_posting_md(doc, display_ids[doc["_id"]]))


@app.command()
def judge(
    apply_path: Path = typer.Option(..., "--apply", exists=True, readable=True, help="Path to verdicts.json"),
    force: bool = typer.Option(False, "--force", help="Overwrite postings already judged."),
    json_out: bool = typer.Option(False, "--json"),
) -> None:
    """Write verdicts back (PLAN.md §3 verdict schema). Validates the whole
    file's shape up front; unknown ids and already-judged postings (without
    --force) are rejected individually, without losing the rest of the batch."""
    try:
        raw = jsonlib.loads(apply_path.read_text(encoding="utf-8"))
    except jsonlib.JSONDecodeError as e:
        typer.echo(f"error: {apply_path} is not valid JSON: {e}", err=True)
        raise typer.Exit(1)

    if not isinstance(raw, list):
        typer.echo("error: verdicts.json must be a JSON array of verdict objects", err=True)
        raise typer.Exit(1)

    verdicts: list[Verdict] = []
    schema_errors: list[str] = []
    for i, entry in enumerate(raw):
        try:
            verdicts.append(Verdict.model_validate(entry))
        except ValidationError as e:
            schema_errors.append(f"entry {i}: {e}")

    if schema_errors:
        typer.echo(f"error: {len(schema_errors)} verdict(s) failed schema validation, applying none:", err=True)
        for err in schema_errors:
            typer.echo(f"  - {err}", err=True)
        raise typer.Exit(1)

    async def _run():
        async with db_session() as db:
            return await apply_verdicts(db, verdicts, force=force)

    result = asyncio.run(_run())
    data = result.to_dict()

    if json_out:
        typer.echo(jsonlib.dumps(data, indent=2, default=str))
        return

    typer.echo(f"applied: {data['applied']}")
    if data["rejected"]:
        typer.echo(f"rejected: {len(data['rejected'])}")
        for r in data["rejected"]:
            typer.echo(f"  - {r['id']}: {r['reason']}")


if __name__ == "__main__":
    app()
