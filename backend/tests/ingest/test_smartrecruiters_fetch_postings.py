"""Fixture test against saved real SmartRecruiters payloads (PLAN.md §10:
"Every connector needs a fixture test against a saved real payload").

Fixtures, captured 2026-09-07 against ``ServiceNow`` (614 open postings):
- tests/ingest/fixtures/smartrecruiters_servicenow_list.json — one page (3
  items) of ``GET /v1/companies/ServiceNow/postings``
- tests/ingest/fixtures/smartrecruiters_servicenow_detail.json — the full
  detail (``jobAd`` HTML sections) for the first item's id
"""

import json
import os

import pytest

from app.agents.ats_providers import smartrecruiters as sr_module
from app.agents.ats_providers.smartrecruiters import MAX_DESCRIPTION_FETCHES, SmartRecruitersProvider

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures")


@pytest.fixture
def list_page() -> dict:
    with open(os.path.join(FIXTURES, "smartrecruiters_servicenow_list.json"), encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture
def detail() -> dict:
    with open(os.path.join(FIXTURES, "smartrecruiters_servicenow_detail.json"), encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture
def company() -> dict:
    return {"name": "ServiceNow", "careers_url": "https://jobs.smartrecruiters.com/ServiceNow"}


async def test_fetch_postings_normalizes_fixture(monkeypatch, list_page, detail, company):
    call_count = {"n": 0}

    async def fake_fetch_json(url, **kwargs):
        call_count["n"] += 1
        if "/postings/" in url:
            assert url.endswith(f"/postings/{detail['id']}")
            return detail
        # list page — only one page exists in this fixture (< PAGE_SIZE items)
        assert "limit=100&offset=0" in url
        return list_page

    monkeypatch.setattr(sr_module, "fetch_json", fake_fetch_json)

    provider = SmartRecruitersProvider()
    api_url = provider.detect(company)
    postings = await provider.fetch_postings(company, api_url)

    assert len(postings) == len(list_page["content"])
    # one list call + one detail call per posting
    assert call_count["n"] == 1 + len(list_page["content"])

    top = next(p for p in postings if p["provider_job_id"] == detail["id"])
    assert top["title"] == detail["name"].strip()
    assert top["url"] == f"https://jobs.smartrecruiters.com/ServiceNow/{detail['id']}"
    assert top["apply_url"] == detail["applyUrl"]
    assert top["remote_flag"] is False  # location.remote: false in the fixture
    assert "<" not in top["description_text"]
    assert len(top["description_text"]) > 0


async def test_fetch_postings_caps_description_fetches(monkeypatch, company):
    """More postings than MAX_DESCRIPTION_FETCHES — only the newest N get a
    detail call; the rest are dropped from the ingested batch entirely
    (a provider-level cost cap, not a per-item skip)."""
    many = MAX_DESCRIPTION_FETCHES + 5
    content = [
        {"id": str(i), "name": f"Job {i}", "releasedDate": f"2026-01-{i % 28 + 1:02d}T00:00:00.000Z",
         "location": {}}
        for i in range(many)
    ]
    detail_calls = []

    async def fake_fetch_json(url, **kwargs):
        if "/postings/" in url:
            posting_id = url.rsplit("/", 1)[-1]
            detail_calls.append(posting_id)
            return {"jobAd": {"sections": {}}, "postingUrl": f"https://x/{posting_id}"}
        return {"content": content}

    monkeypatch.setattr(sr_module, "fetch_json", fake_fetch_json)

    provider = SmartRecruitersProvider()
    api_url = provider.detect(company)
    postings = await provider.fetch_postings(company, api_url)

    assert len(postings) == MAX_DESCRIPTION_FETCHES
    assert len(detail_calls) == MAX_DESCRIPTION_FETCHES


async def test_legacy_fetch_needs_no_detail_call(monkeypatch, list_page, company):
    """The dashboard search path calls fetch(), not fetch_postings() — it
    must build a working URL from the id alone, with zero detail calls."""
    async def fake_fetch_json(url, **kwargs):
        assert "/postings/" not in url  # a detail URL always has a trailing /{id}
        return list_page

    monkeypatch.setattr(sr_module, "fetch_json", fake_fetch_json)

    provider = SmartRecruitersProvider()
    api_url = provider.detect(company)
    jobs = await provider.fetch(company, api_url)

    assert len(jobs) == len(list_page["content"])
    assert set(jobs[0].keys()) == {"title", "url", "company", "location", "posted_date", "source"}
    first_id = list_page["content"][0]["id"]
    assert jobs[0]["url"] == f"https://jobs.smartrecruiters.com/ServiceNow/{first_id}"
