"""Fixture test against a saved real Ashby payload.

Fixture: tests/ingest/fixtures/ashby_langchain.json — 5 real jobs from
``api.ashbyhq.com/posting-api/job-board/LangChain?includeCompensation=true``,
captured 2026-09-07.
"""

import json
import os

import pytest

from app.agents.ats_providers import ashby as ashby_module
from app.agents.ats_providers.ashby import AshbyProvider

FIXTURE_PATH = os.path.join(os.path.dirname(__file__), "fixtures", "ashby_langchain.json")


@pytest.fixture
def fixture_data() -> dict:
    with open(FIXTURE_PATH, encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture
def company() -> dict:
    return {"name": "LangChain", "careers_url": "https://jobs.ashbyhq.com/LangChain"}


async def test_fetch_postings_normalizes_fixture(monkeypatch, fixture_data, company):
    async def fake_fetch_with_retry(url, **kwargs):
        return fixture_data

    monkeypatch.setattr(ashby_module, "fetch_with_retry", fake_fetch_with_retry)

    provider = AshbyProvider()
    api_url = provider.detect(company)
    postings = await provider.fetch_postings(company, api_url)

    listed_jobs = [j for j in fixture_data["jobs"] if j.get("isListed") is not False]
    assert len(postings) == len(listed_jobs)
    for posting, raw_job in zip(postings, listed_jobs):
        assert posting["provider_job_id"] == str(raw_job["id"])
        assert posting["url"] == raw_job["jobUrl"]
        assert posting["description_text"] == (raw_job.get("descriptionPlain") or "").strip()


async def test_fetch_postings_skips_unlisted_jobs(monkeypatch, company):
    async def fake_fetch_with_retry(url, **kwargs):
        return {"jobs": [
            {"id": "1", "title": "Closed Role", "jobUrl": "https://x/1", "isListed": False},
            {"id": "2", "title": "Open Role", "jobUrl": "https://x/2", "isListed": True},
        ]}

    monkeypatch.setattr(ashby_module, "fetch_with_retry", fake_fetch_with_retry)

    provider = AshbyProvider()
    api_url = provider.detect(company)
    postings = await provider.fetch_postings(company, api_url)

    assert len(postings) == 1
    assert postings[0]["provider_job_id"] == "2"
