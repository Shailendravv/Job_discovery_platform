"""Fixture test against a saved real Lever payload.

Fixture: tests/ingest/fixtures/lever_palantir.json — 5 real jobs from
``api.lever.co/v0/postings/palantir?mode=json``, captured 2026-09-07.
"""

import json
import os

import pytest

from app.agents.ats_providers import lever as lever_module
from app.agents.ats_providers.lever import LeverProvider

FIXTURE_PATH = os.path.join(os.path.dirname(__file__), "fixtures", "lever_palantir.json")


@pytest.fixture
def fixture_data() -> list:
    with open(FIXTURE_PATH, encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture
def company() -> dict:
    return {"name": "Palantir", "careers_url": "https://jobs.lever.co/palantir"}


async def test_fetch_postings_normalizes_fixture(monkeypatch, fixture_data, company):
    async def fake_fetch_json(url, **kwargs):
        return fixture_data

    monkeypatch.setattr(lever_module, "fetch_json", fake_fetch_json)

    provider = LeverProvider()
    api_url = provider.detect(company)
    postings = await provider.fetch_postings(company, api_url)

    assert len(postings) == len(fixture_data)
    for posting, raw_job in zip(postings, fixture_data):
        assert posting["provider_job_id"] == str(raw_job["id"])
        assert posting["url"] == raw_job["hostedUrl"]
        assert posting["description_text"]  # descriptionPlain is free on Lever
        assert posting["posted_at"] is not None


async def test_fetch_postings_handles_missing_optional_fields(monkeypatch, company):
    async def fake_fetch_json(url, **kwargs):
        return [{
            "id": "abc123",
            "text": "Software Engineer",
            "hostedUrl": "https://jobs.lever.co/palantir/abc123",
            # no descriptionPlain, no createdAt, no categories
        }]

    monkeypatch.setattr(lever_module, "fetch_json", fake_fetch_json)

    provider = LeverProvider()
    api_url = provider.detect(company)
    postings = await provider.fetch_postings(company, api_url)

    assert len(postings) == 1
    assert postings[0]["description_text"] == ""
    assert postings[0]["posted_at"] is None
    assert postings[0]["location"] is None
