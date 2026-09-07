"""Fixture test against a saved real Greenhouse payload (PLAN.md §10:
"Every connector needs a fixture test against a saved real payload").

Fixture: tests/ingest/fixtures/greenhouse_stripe.json — 5 real jobs from
``boards-api.greenhouse.io/v1/boards/stripe/jobs?content=true``, captured
2026-09-07.
"""

import json
import os

import pytest

from app.agents.ats_providers import greenhouse as greenhouse_module
from app.agents.ats_providers.greenhouse import GreenhouseProvider

FIXTURE_PATH = os.path.join(os.path.dirname(__file__), "fixtures", "greenhouse_stripe.json")


@pytest.fixture
def fixture_data() -> dict:
    with open(FIXTURE_PATH, encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture
def company() -> dict:
    return {"name": "Stripe", "careers_url": "https://job-boards.greenhouse.io/stripe"}


async def test_fetch_postings_normalizes_fixture(monkeypatch, fixture_data, company):
    async def fake_fetch_json(url, **kwargs):
        assert "content=true" in url
        return fixture_data

    monkeypatch.setattr(greenhouse_module, "fetch_json", fake_fetch_json)

    provider = GreenhouseProvider()
    api_url = provider.detect(company)
    postings = await provider.fetch_postings(company, api_url)

    assert len(postings) == len(fixture_data["jobs"])
    for posting, raw_job in zip(postings, fixture_data["jobs"]):
        assert posting["provider_job_id"] == str(raw_job["id"])
        assert posting["title"] == raw_job["title"].strip()
        assert posting["url"] == raw_job["absolute_url"]
        # content is HTML — description_text must be stripped plain text
        assert "<" not in posting["description_text"]
        assert len(posting["description_text"]) > 0
        # raw payload is kept for debugging but without the duplicated content blob
        assert "content" not in posting["raw"]


async def test_fetch_postings_skips_jobs_without_url(monkeypatch, company):
    async def fake_fetch_json(url, **kwargs):
        return {"jobs": [{"id": 1, "title": "No URL", "content": "<p>hi</p>"}]}

    monkeypatch.setattr(greenhouse_module, "fetch_json", fake_fetch_json)

    provider = GreenhouseProvider()
    api_url = provider.detect(company)
    postings = await provider.fetch_postings(company, api_url)

    assert postings == []


async def test_legacy_fetch_is_unaffected_by_fetch_postings(monkeypatch, fixture_data, company):
    """The dashboard search path calls fetch(), not fetch_postings() — make
    sure adding the ingestion method didn't change fetch()'s output shape."""
    async def fake_fetch_json(url, **kwargs):
        assert "content=true" not in url  # legacy fetch() never requests content
        return fixture_data

    monkeypatch.setattr(greenhouse_module, "fetch_json", fake_fetch_json)

    provider = GreenhouseProvider()
    api_url = provider.detect(company)
    jobs = await provider.fetch(company, api_url)

    assert len(jobs) == len(fixture_data["jobs"])
    assert set(jobs[0].keys()) == {"title", "url", "company", "location", "posted_date", "source"}
