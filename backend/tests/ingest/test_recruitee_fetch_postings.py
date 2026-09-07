"""Fixture test against a saved real Recruitee payload (PLAN.md §10:
"Every connector needs a fixture test against a saved real payload").

Fixture: tests/ingest/fixtures/recruitee_greatminds.json — 3 real offers from
``greatminds.recruitee.com/api/offers/``, captured 2026-09-07.
"""

import json
import os

import pytest

from app.agents.ats_providers import recruitee as recruitee_module
from app.agents.ats_providers.recruitee import RecruiteeProvider

FIXTURE_PATH = os.path.join(os.path.dirname(__file__), "fixtures", "recruitee_greatminds.json")


@pytest.fixture
def fixture_data() -> dict:
    with open(FIXTURE_PATH, encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture
def company() -> dict:
    return {"name": "Great Minds", "careers_url": "https://greatminds.recruitee.com/"}


async def test_fetch_postings_normalizes_fixture(monkeypatch, fixture_data, company):
    async def fake_fetch_json(url, **kwargs):
        assert url == "https://greatminds.recruitee.com/api/offers/"
        return fixture_data

    monkeypatch.setattr(recruitee_module, "fetch_json", fake_fetch_json)

    provider = RecruiteeProvider()
    api_url = provider.detect(company)
    postings = await provider.fetch_postings(company, api_url)

    assert len(postings) == len(fixture_data["offers"])
    for posting, raw_offer in zip(postings, fixture_data["offers"]):
        assert posting["provider_job_id"] == str(raw_offer["id"])
        assert posting["title"] == raw_offer["title"].strip()
        assert posting["url"] == raw_offer["careers_url"]
        assert posting["apply_url"] == raw_offer["careers_apply_url"]
        assert posting["remote_flag"] == raw_offer["remote"]
        # description + requirements are HTML — must be stripped plain text
        assert "<" not in posting["description_text"]
        assert len(posting["description_text"]) > 0
        assert "description" not in posting["raw"]
        assert "requirements" not in posting["raw"]


async def test_fetch_postings_skips_offers_without_url(monkeypatch, company):
    async def fake_fetch_json(url, **kwargs):
        return {"offers": [{"id": 1, "title": "No URL", "description": "<p>hi</p>"}]}

    monkeypatch.setattr(recruitee_module, "fetch_json", fake_fetch_json)

    provider = RecruiteeProvider()
    api_url = provider.detect(company)
    postings = await provider.fetch_postings(company, api_url)

    assert postings == []


async def test_legacy_fetch_is_unaffected_by_fetch_postings(monkeypatch, fixture_data, company):
    async def fake_fetch_json(url, **kwargs):
        return fixture_data

    monkeypatch.setattr(recruitee_module, "fetch_json", fake_fetch_json)

    provider = RecruiteeProvider()
    api_url = provider.detect(company)
    jobs = await provider.fetch(company, api_url)

    assert len(jobs) == len(fixture_data["offers"])
    assert set(jobs[0].keys()) == {"title", "url", "company", "location", "posted_date", "source"}


def test_detect_rejects_non_recruitee_host():
    provider = RecruiteeProvider()
    assert provider.detect({"careers_url": "https://example.com/careers"}) is None
