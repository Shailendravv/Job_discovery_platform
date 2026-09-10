"""``posted_since`` must cut per-job description fetches, and only for the
two providers that actually pay for them.

This is the largest time saving a Job Discovery run can make: smartrecruiters
and workday each need a *second* HTTP call per job to get the description,
and both carry a usable date on the cheap list response, so a posting outside
the window can be discarded before that call is spent. Measured on the live
registry, a 24h run skips ~98% of them.

The other five providers return descriptions in the same bulk response, so
there is nothing to save; they must accept the kwarg and ignore it rather
than dropping postings (which would stop refreshing ``last_seen_at`` for no
benefit).
"""

import json
import os
from datetime import datetime, timedelta, timezone

import pytest

from app.agents.ats_providers import smartrecruiters as sr_module
from app.agents.ats_providers import workday as wd_module
from app.agents.ats_providers.smartrecruiters import SmartRecruitersProvider
from app.agents.ats_providers.workday import WorkdayProvider

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures")


def _fixture(name: str) -> dict:
    with open(os.path.join(FIXTURES, name), encoding="utf-8") as f:
        return json.load(f)


# ── smartrecruiters ────────────────────────────────────────────────────
# The fixture's three postings were released 2026-09-06T15:40 .. 2026-09-07T03:09.

@pytest.fixture
def sr_company() -> dict:
    return {"name": "ServiceNow", "careers_url": "https://jobs.smartrecruiters.com/ServiceNow"}


def _sr_patch(monkeypatch, list_page, detail, detail_calls):
    async def fake_fetch_json(url, **kwargs):
        if "/postings/" in url:
            detail_calls.append(url)
            return detail
        return list_page

    monkeypatch.setattr(sr_module, "fetch_json", fake_fetch_json)


async def test_smartrecruiters_skips_detail_fetches_for_stale_postings(monkeypatch, sr_company):
    list_page = _fixture("smartrecruiters_servicenow_list.json")
    detail = _fixture("smartrecruiters_servicenow_detail.json")
    detail_calls: list[str] = []
    _sr_patch(monkeypatch, list_page, detail, detail_calls)

    # Between the oldest (09-06 15:40) and the two newer ones (09-07).
    cutoff = datetime(2026, 9, 7, 0, 0, tzinfo=timezone.utc)

    provider = SmartRecruitersProvider()
    postings = await provider.fetch_postings(
        sr_company, provider.detect(sr_company), posted_since=cutoff
    )

    assert len(detail_calls) == 2, "the posting released before the cutoff still cost a detail fetch"
    assert len(postings) == 2


async def test_smartrecruiters_without_cutoff_fetches_everything(monkeypatch, sr_company):
    """The default must be exactly the old behaviour — the nightly full
    ingest relies on it."""
    list_page = _fixture("smartrecruiters_servicenow_list.json")
    detail = _fixture("smartrecruiters_servicenow_detail.json")
    detail_calls: list[str] = []
    _sr_patch(monkeypatch, list_page, detail, detail_calls)

    provider = SmartRecruitersProvider()
    postings = await provider.fetch_postings(sr_company, provider.detect(sr_company))

    assert len(detail_calls) == len(list_page["content"])
    assert len(postings) == len(list_page["content"])


async def test_smartrecruiters_cutoff_in_the_past_keeps_everything(monkeypatch, sr_company):
    list_page = _fixture("smartrecruiters_servicenow_list.json")
    detail = _fixture("smartrecruiters_servicenow_detail.json")
    detail_calls: list[str] = []
    _sr_patch(monkeypatch, list_page, detail, detail_calls)

    provider = SmartRecruitersProvider()
    await provider.fetch_postings(
        sr_company,
        provider.detect(sr_company),
        posted_since=datetime(2020, 1, 1, tzinfo=timezone.utc),
    )

    assert len(detail_calls) == len(list_page["content"])


async def test_smartrecruiters_keeps_postings_with_no_parseable_date(monkeypatch, sr_company):
    """A missing date is not proof of staleness — the ingest layer decides
    with the first_seen_at fallback rather than the provider dropping it."""
    list_page = _fixture("smartrecruiters_servicenow_list.json")
    for item in list_page["content"]:
        item.pop("releasedDate", None)
    detail_calls: list[str] = []
    _sr_patch(monkeypatch, list_page, _fixture("smartrecruiters_servicenow_detail.json"), detail_calls)

    provider = SmartRecruitersProvider()
    await provider.fetch_postings(
        sr_company, provider.detect(sr_company), posted_since=datetime.now(timezone.utc)
    )

    assert len(detail_calls) == len(list_page["content"])


# ── workday ────────────────────────────────────────────────────────────
# The fixture's postings are all labelled "Posted 2 Days Ago".

@pytest.fixture
def wd_company() -> dict:
    return {"name": "Workday", "careers_url": "https://workday.wd5.myworkdayjobs.com/Workday"}


def _wd_patch(monkeypatch, list_page, detail, detail_calls):
    async def fake_fetch_json(url, **kwargs):
        if "/job/" in url or url.rstrip("/").split("/")[-1].startswith("Job"):
            detail_calls.append(url)
            return detail
        if url.endswith("/jobs"):
            return list_page
        detail_calls.append(url)
        return detail

    monkeypatch.setattr(wd_module, "fetch_json", fake_fetch_json)


async def test_workday_skips_detail_fetches_for_stale_postings(monkeypatch, wd_company):
    list_page = _fixture("workday_list.json")
    detail = _fixture("workday_detail.json")
    detail_calls: list[str] = []
    _wd_patch(monkeypatch, list_page, detail, detail_calls)

    provider = WorkdayProvider()
    postings = await provider.fetch_postings(
        wd_company,
        provider.detect(wd_company),
        # Everything in the fixture is "Posted 2 Days Ago", so a 24h window
        # rejects all of it.
        posted_since=datetime.now(timezone.utc) - timedelta(hours=24),
    )

    assert detail_calls == []
    assert postings == []


async def test_workday_without_cutoff_fetches_everything(monkeypatch, wd_company):
    list_page = _fixture("workday_list.json")
    detail = _fixture("workday_detail.json")
    detail_calls: list[str] = []
    _wd_patch(monkeypatch, list_page, detail, detail_calls)

    provider = WorkdayProvider()
    await provider.fetch_postings(wd_company, provider.detect(wd_company))

    assert len(detail_calls) == len(list_page["jobPostings"])


async def test_workday_wide_window_keeps_everything(monkeypatch, wd_company):
    list_page = _fixture("workday_list.json")
    detail = _fixture("workday_detail.json")
    detail_calls: list[str] = []
    _wd_patch(monkeypatch, list_page, detail, detail_calls)

    provider = WorkdayProvider()
    await provider.fetch_postings(
        wd_company,
        provider.detect(wd_company),
        posted_since=datetime.now(timezone.utc) - timedelta(days=7),
    )

    assert len(detail_calls) == len(list_page["jobPostings"])


# ── the bulk providers ─────────────────────────────────────────────────

@pytest.mark.parametrize("module_name,provider_name,company", [
    ("greenhouse", "GreenhouseProvider", {"name": "Stripe", "careers_url": "https://boards.greenhouse.io/stripe"}),
    ("lever", "LeverProvider", {"name": "Palantir", "careers_url": "https://jobs.lever.co/palantir"}),
    ("ashby", "AshbyProvider", {"name": "LangChain", "careers_url": "https://jobs.ashbyhq.com/LangChain"}),
    ("workable", "WorkableProvider", {"name": "Acme", "careers_url": "https://apply.workable.com/acme"}),
    ("recruitee", "RecruiteeProvider", {"name": "Acme", "careers_url": "https://acme.recruitee.com"}),
])
def test_bulk_providers_accept_posted_since(module_name, provider_name, company):
    """They must take the kwarg without error — run_ingest passes it to
    every provider uniformly — and their signature must keep it optional."""
    import importlib
    import inspect

    module = importlib.import_module(f"app.agents.ats_providers.{module_name}")
    provider = getattr(module, provider_name)()

    signature = inspect.signature(provider.fetch_postings)
    parameter = signature.parameters["posted_since"]
    assert parameter.default is None
    assert parameter.kind is inspect.Parameter.KEYWORD_ONLY
