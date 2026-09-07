"""Loads and resolves ``backend/config/ats_companies.yml`` into ``Source``
objects the ingest runner can iterate.

PLAN.md §2 specifies a new ``config/sources.yaml`` (org/provider/token/tags).
We deliberately extend the existing, already-verified
``backend/config/ats_companies.yml`` instead of adding a second registry that
would drift from it — see PLAN.md §2 for the recorded deviation. This module
adds the new optional ``org``, ``provider``, and ``tags`` keys on top of the
existing ``name`` / ``careers_url`` / ``api`` / ``enabled`` keys, so every
entry written before this milestone keeps working unchanged.
"""

import logging
import os
import re
from dataclasses import dataclass, field
from typing import Optional

import yaml

from app.agents.ats_providers import AtsProvider

log = logging.getLogger(__name__)

# backend/app/ingest/registry.py -> up 3 levels -> backend/ -> config/ats_companies.yml
CONFIG_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "config",
    "ats_companies.yml",
)


@dataclass
class Source:
    """One resolved ATS source — a company config entry matched to a provider."""

    name: str
    org: str
    careers_url: str
    tags: list[str] = field(default_factory=list)
    enabled: bool = True
    company: dict = field(default_factory=dict)  # raw yaml entry, passed to provider.fetch()
    provider_id: Optional[str] = None  # resolved by detect(), None until resolve_sources() runs
    api_url: Optional[str] = None


def _slugify(name: str) -> str:
    """Company name -> stable slug used as the ``org`` partition key when the
    yaml entry doesn't set one explicitly. Only needs to be stable across
    runs, not match the ATS's own token — provider_job_id (from the ATS)
    is what actually makes each posting id unique."""
    slug = re.sub(r"[^a-z0-9]+", "-", name.strip().lower()).strip("-")
    return slug or "unknown"


def load_raw_companies(config_path: str = CONFIG_PATH) -> list[dict]:
    """Parse the ATS companies YAML file. Returns [] if missing/malformed —
    degrades quietly rather than raising, since a bad config file shouldn't
    crash the whole ingest run."""
    if not os.path.isfile(config_path):
        log.warning("[ingest] config file not found: %s", config_path)
        return []
    try:
        with open(config_path, encoding="utf-8") as f:
            data = yaml.safe_load(f)
        companies = data.get("ats_companies") if isinstance(data, dict) else None
        if not isinstance(companies, list):
            log.warning("[ingest] ats_companies is not a list in %s", config_path)
            return []
        return companies
    except Exception as e:
        log.warning("[ingest] failed to load %s: %s", config_path, e)
        return []


def load_sources(config_path: str = CONFIG_PATH) -> list[Source]:
    """Parse yaml entries into ``Source`` objects (provider not yet resolved)."""
    sources: list[Source] = []
    for entry in load_raw_companies(config_path):
        if not isinstance(entry, dict) or not entry.get("name"):
            log.warning("[ingest] skipping malformed entry: %r", entry)
            continue
        name = str(entry["name"]).strip()
        org = str(entry.get("org") or _slugify(name))
        sources.append(Source(
            name=name,
            org=org,
            careers_url=str(entry.get("careers_url") or "").strip(),
            tags=list(entry.get("tags") or []),
            enabled=bool(entry.get("enabled", True)),
            company=entry,
        ))
    return sources


def resolve_sources(sources: list[Source]) -> list[Source]:
    """Match each source to a provider via ``detect()``, mutating and
    returning the same list. Sources with no match keep
    ``provider_id is None`` so ``jobctl sources doctor`` can report them."""
    providers = AtsProvider.get_providers()
    for source in sources:
        explicit = str(source.company.get("provider") or "").strip().lower()
        candidates = [p for p in providers if p.id == explicit] if explicit else providers
        for provider in candidates:
            try:
                api_url = provider.detect(source.company)
            except Exception as e:
                log.warning("[ingest] %s/%s detect() raised: %s", provider.id, source.name, e)
                continue
            if api_url:
                source.provider_id = provider.id
                source.api_url = api_url
                break
    return sources


def load_and_resolve_sources(config_path: str = CONFIG_PATH) -> list[Source]:
    return resolve_sources(load_sources(config_path))
