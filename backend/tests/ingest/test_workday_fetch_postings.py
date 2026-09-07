"""Fixture test against saved real Workday payloads (PLAN.md §10:
"Every connector needs a fixture test against a saved real payload").

``fetch_postings()`` was a milestone 5 addition — previously it raised
``NotImplementedError`` (see ``ingest.md``'s "Open Issues" before this
milestone).

Fixtures, captured 2026-09-07 against Workday's own careers site
(``workday.wd5.myworkdayjobs.com/Workday``, 373 open postings):
- tests/ingest/fixtures/workday_list.json — one page (3 jobs) of the
  paginated ``POST .../jobs`` list endpoint
- tests/ingest/fixtures/workday_detail.json — the full per-job detail
  (``jobPostingInfo.jobDescription`` HTML) for the first list item
"""

import json
import os

import pytest

from app.agents.ats_providers import workday as workday_module
from app.agents.ats_providers.workday import MAX_DESCRIPTION_FETCHES, WorkdayProvider

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures")


@pytest.fixture
def list_page() -> dict:
    with open(os.path.join(FIXTURES, "workday_list.json"), encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture
def detail() -> dict:
    with open(os.path.join(FIXTURES, "workday_detail.json"), encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture
def company() -> dict:
    return {"name": "Workday", "careers_url": "https://workday.wd5.myworkdayjobs.com/Workday"}


async def test_fetch_postings_normalizes_fixture(monkeypatch, list_page, detail, company):
    call_count = {"n": 0}

    async def fake_fetch_json(url, method="GET", **kwargs):
        call_count["n"] += 1
        if method == "POST":
            return list_page
        return detail

    monkeypatch.setattr(workday_module, "fetch_json", fake_fetch_json)

    provider = WorkdayProvider()
    api_url = provider.detect(company)
    postings = await provider.fetch_postings(company, api_url)

    assert len(postings) == len(list_page["jobPostings"])
    # one list call + one detail call per job
    assert call_count["n"] == 1 + len(list_page["jobPostings"])

    jpi = detail["jobPostingInfo"]
    top = next(p for p in postings if p["provider_job_id"] == jpi["id"])
    assert top["title"] == jpi["title"].strip()
    assert top["url"] == jpi["externalUrl"]
    assert top["remote_flag"] is True  # remoteType: "Remote" in the fixture
    assert "<" not in top["description_text"]
    assert len(top["description_text"]) > 0


async def test_fetch_postings_caps_description_fetches(monkeypatch, company):
    """More postings than MAX_DESCRIPTION_FETCHES — only the newest N (by
    the parsed 'Posted N Days Ago' label) get a detail call."""
    many = MAX_DESCRIPTION_FETCHES + 5
    job_postings = [{
        "title": f"Job {i}",
        "externalPath": f"/job/Remote/Job-{i}_JR-{i:04d}",
        "locationsText": "Remote",
        "postedOn": f"Posted {i} Days Ago",
        "remoteType": "Remote",
    } for i in range(many)]
    detail_calls = []

    async def fake_fetch_json(url, method="GET", body=None, **kwargs):
        if method == "POST":
            # honor limit/offset like a real paginated API — a fake that
            # always returns everything would never trip the "< PAGE_SIZE"
            # end-of-pages check and loop needlessly
            req = json.loads(body)
            offset, limit = req["offset"], req["limit"]
            return {"total": many, "jobPostings": job_postings[offset:offset + limit]}
        detail_calls.append(url)
        return {"jobPostingInfo": {"id": url, "jobDescription": "<p>hi</p>", "timeType": "Full Time"}}

    monkeypatch.setattr(workday_module, "fetch_json", fake_fetch_json)

    provider = WorkdayProvider()
    api_url = provider.detect(company)
    postings = await provider.fetch_postings(company, api_url)

    assert len(postings) == MAX_DESCRIPTION_FETCHES
    assert len(detail_calls) == MAX_DESCRIPTION_FETCHES
    # newest (lowest "Posted N Days Ago") wins the cap: Job 0..N-1 survive,
    # the oldest (highest i) are the ones dropped.
    surviving_titles = {p["title"] for p in postings}
    assert surviving_titles == {f"Job {i}" for i in range(MAX_DESCRIPTION_FETCHES)}


async def test_fetch_postings_skips_job_without_detail(monkeypatch, company):
    """A detail fetch that fails (network error, 404) drops that one job
    rather than falling back to an unstable id."""
    job_postings = [{
        "title": "Flaky Job",
        "externalPath": "/job/Remote/Flaky-Job_JR-0001",
        "locationsText": "Remote",
        "postedOn": "Posted Today",
        "remoteType": "Remote",
    }]

    async def fake_fetch_json(url, method="GET", **kwargs):
        if method == "POST":
            return {"total": 1, "jobPostings": job_postings}
        raise RuntimeError("boom")

    monkeypatch.setattr(workday_module, "fetch_json", fake_fetch_json)

    provider = WorkdayProvider()
    api_url = provider.detect(company)
    postings = await provider.fetch_postings(company, api_url)

    assert postings == []


async def test_legacy_fetch_is_unaffected_by_fetch_postings(monkeypatch, list_page, company):
    async def fake_fetch_json(url, method="GET", **kwargs):
        assert method == "POST"
        return list_page

    monkeypatch.setattr(workday_module, "fetch_json", fake_fetch_json)

    provider = WorkdayProvider()
    api_url = provider.detect(company)
    jobs = await provider.fetch(company, api_url)

    assert len(jobs) == len(list_page["jobPostings"])
    assert set(jobs[0].keys()) == {"title", "url", "company", "location", "posted_date", "source"}
