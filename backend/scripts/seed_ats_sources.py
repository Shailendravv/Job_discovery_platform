#!/usr/bin/env python3
"""Verify a candidate list of ATS companies live and emit only the ones that
actually work — PLAN.md §2: "Verify each one with a live request before
building on it — these change, and some need a board token that differs
from the company name."

Usage:
    python scripts/seed_ats_sources.py [--candidates scripts/ats_candidates.yml]
                                        [--out /tmp/verified.yml]
                                        [--append]

``--append`` merges the verified, non-duplicate entries directly into
``config/ats_companies.yml``. Without it, verified entries are written to
``--out`` for review first.

Honest by design: entries that 404, time out, or return 0 jobs are dropped
and reported, not guessed at further. The final registry size is whatever
actually verifies — this script does not pad the count.
"""

import argparse
import asyncio
import logging
import os
import sys
from dataclasses import dataclass, field
from typing import Optional

import yaml

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.agents.ats_providers import AtsProvider  # noqa: E402
from app.agents.ats_providers._http import HostThrottle, reset_host_throttle, set_host_throttle  # noqa: E402
from app.ingest.registry import CONFIG_PATH, load_raw_companies  # noqa: E402

logging.basicConfig(level=logging.WARNING, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
log = logging.getLogger("seed_ats_sources")

MAX_CONCURRENT = 8
MIN_HOST_INTERVAL_SECONDS = 1.0
CANDIDATES_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ats_candidates.yml")


@dataclass
class ProbeResult:
    name: str
    careers_url: str
    provider: Optional[str] = None
    job_count: int = 0
    ok: bool = False
    reason: str = ""


def _load_candidates(path: str) -> list[dict]:
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return data.get("candidates") or []


def _existing_careers_urls(config_path: str) -> set[str]:
    return {
        str(c.get("careers_url") or "").strip().rstrip("/").lower()
        for c in load_raw_companies(config_path)
        if c.get("careers_url")
    }


async def _probe(entry: dict, providers: list[AtsProvider], semaphore: asyncio.Semaphore) -> ProbeResult:
    name = entry["name"]
    careers_url = entry["careers_url"]
    company = {"name": name, "careers_url": careers_url}

    for provider in providers:
        try:
            api_url = provider.detect(company)
        except Exception:
            continue
        if not api_url:
            continue
        async with semaphore:
            try:
                jobs = await provider.fetch(company, api_url)
            except Exception as e:
                return ProbeResult(name, careers_url, provider.id, reason=str(e)[:200])
        if not jobs:
            return ProbeResult(name, careers_url, provider.id, job_count=0, reason="0 jobs")
        return ProbeResult(name, careers_url, provider.id, job_count=len(jobs), ok=True)

    return ProbeResult(name, careers_url, reason="no provider matched URL pattern")


async def main(candidates_path: str, out_path: Optional[str], append: bool, config_path: str) -> None:
    candidates = _load_candidates(candidates_path)
    existing = _existing_careers_urls(config_path)

    fresh = [c for c in candidates if str(c["careers_url"]).strip().rstrip("/").lower() not in existing]
    log.info("Loaded %d candidates, %d already in registry, probing %d", len(candidates), len(candidates) - len(fresh), len(fresh))

    providers = AtsProvider.get_providers()
    semaphore = asyncio.Semaphore(MAX_CONCURRENT)
    token = set_host_throttle(HostThrottle(MIN_HOST_INTERVAL_SECONDS))
    try:
        results = await asyncio.gather(*(_probe(c, providers, semaphore) for c in fresh))
    finally:
        reset_host_throttle(token)

    verified = [r for r in results if r.ok]
    rejected = [r for r in results if not r.ok]

    print(f"\nVerified: {len(verified)} / {len(fresh)} candidates")
    print(f"Rejected: {len(rejected)}")
    for r in rejected:
        print(f"  ✗ {r.name:<30} {r.careers_url:<55} {r.reason}")

    verified_yaml_entries = [
        {"name": r.name, "careers_url": r.careers_url}
        for r in sorted(verified, key=lambda x: (x.provider or "", x.name))
    ]

    if append:
        with open(config_path, "r", encoding="utf-8") as f:
            content = f.read()
        addition_lines = ["\n  # === Added by seed_ats_sources.py ===\n"]
        for e in verified_yaml_entries:
            addition_lines.append(f"  - name: {e['name']}\n")
            addition_lines.append(f"    careers_url: {e['careers_url']}\n")
        with open(config_path, "a", encoding="utf-8") as f:
            f.write("".join(addition_lines))
        print(f"\nAppended {len(verified_yaml_entries)} verified entries to {config_path}")
    elif out_path:
        with open(out_path, "w", encoding="utf-8") as f:
            yaml.safe_dump({"ats_companies": verified_yaml_entries}, f, sort_keys=False)
        print(f"\nWrote {len(verified_yaml_entries)} verified entries to {out_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidates", default=CANDIDATES_PATH)
    parser.add_argument("--out", default=None)
    parser.add_argument("--append", action="store_true")
    parser.add_argument("--config", default=CONFIG_PATH)
    args = parser.parse_args()
    asyncio.run(main(args.candidates, args.out, args.append, args.config))
