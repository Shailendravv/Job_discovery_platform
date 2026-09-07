"""Fixture test against a saved real Workable payload (PLAN.md §10:
"Every connector needs a fixture test against a saved real payload").

Fixture: tests/ingest/fixtures/workable_jobrack.json — 3 real jobs from
``apply.workable.com/api/v1/widget/accounts/jobrack?details=true``, captured
2026-09-07.
"""

import json
import os

import pytest

from app.agents.ats_providers import workable as workable_module
from app.agents.ats_providers.workable import WorkableProvider

FIXTURE_PATH = os.path.join(os.path.dirname(__file__), "fixtures", "workable_jobrack.json")


@pytest.fixture
def fixture_data() -> dict:
    with open(FIXTURE_PATH, encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture
def company() -> dict:
    return {"name": "JobRack", "careers_url": "https://apply.workable.com/jobrack/"}


async def test_fetch_postings_normalizes_fixture(monkeypatch, fixture_data, company):
    async def fake_fetch_json(url, **kwargs):
        assert "details=true" in url
        return fixture_data

    monkeypatch.setattr(workable_module, "fetch_json", fake_fetch_json)

    provider = WorkableProvider()
    api_url = provider.detect(company)
    postings = await provider.fetch_postings(company, api_url)

    assert len(postings) == len(fixture_data["jobs"])
    for posting, raw_job in zip(postings, fixture_data["jobs"]):
        assert posting["provider_job_id"] == raw_job["shortcode"]
        assert posting["title"] == raw_job["title"].strip()
        assert posting["url"] == raw_job["url"]
        assert posting["apply_url"] == raw_job["application_url"]
        assert posting["remote_flag"] is True  # telecommuting: true in the fixture
        # description is HTML — description_text must be stripped plain text
        assert "<" not in posting["description_text"]
        assert len(posting["description_text"]) > 0
        assert "description" not in posting["raw"]


async def test_fetch_postings_skips_jobs_without_shortcode(monkeypatch, company):
    async def fake_fetch_json(url, **kwargs):
        return {"jobs": [{"title": "No shortcode", "url": "https://apply.workable.com/j/x"}]}

    monkeypatch.setattr(workable_module, "fetch_json", fake_fetch_json)

    provider = WorkableProvider()
    api_url = provider.detect(company)
    postings = await provider.fetch_postings(company, api_url)

    assert postings == []


async def test_legacy_fetch_is_unaffected_by_fetch_postings(monkeypatch, fixture_data, company):
    """The dashboard search path calls fetch(), not fetch_postings() — make
    sure adding the ingestion method didn't change fetch()'s output shape,
    and that fetch() never asks for the (larger) details=true payload."""
    async def fake_fetch_json(url, **kwargs):
        assert "details=true" not in url
        return fixture_data

    monkeypatch.setattr(workable_module, "fetch_json", fake_fetch_json)

    provider = WorkableProvider()
    api_url = provider.detect(company)
    jobs = await provider.fetch(company, api_url)

    assert len(jobs) == len(fixture_data["jobs"])
    assert set(jobs[0].keys()) == {"title", "url", "company", "location", "posted_date", "source"}
