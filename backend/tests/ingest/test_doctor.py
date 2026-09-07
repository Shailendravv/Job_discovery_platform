"""``jobctl sources doctor`` — PLAN.md §2: "reports which orgs returned 0
jobs or errored, so dead tokens get caught."

Milestone 5 deviation under test: doctor always calls the cheap ``fetch()``,
never ``fetch_postings()`` — see doctor.py's module docstring for why
(SmartRecruiters/Workday's fetch_postings() pays a per-job detail-call cost
that would turn a live health-check into ~20 minutes on this registry).
"""

import asyncio

from app.ingest.doctor import _probe_source
from app.ingest.registry import Source


class _FakeProvider:
    """Deliberately does NOT subclass AtsProvider — that would auto-register
    it into the real, shared AtsProvider._registry via __init_subclass__ and
    leak into other tests (e.g. test_ats_provider_registry.py). _probe_source
    only needs the fetch()/fetch_postings() duck-typed interface."""

    id = "fake"

    def __init__(self, jobs=None, error=None, fetch_postings_should_not_be_called=True):
        self._jobs = jobs if jobs is not None else []
        self._error = error
        self._fetch_postings_should_not_be_called = fetch_postings_should_not_be_called

    def detect(self, company):
        return "http://example.com"

    async def fetch(self, company, api_url):
        if self._error:
            raise self._error
        return self._jobs

    async def fetch_postings(self, company, api_url):
        if self._fetch_postings_should_not_be_called:
            raise AssertionError("doctor must never call fetch_postings() — see doctor.py docstring")
        return self._jobs


def _source(**overrides) -> Source:
    defaults = dict(name="Acme", org="acme", careers_url="https://acme.example.com", provider_id="fake", api_url="http://example.com")
    defaults.update(overrides)
    return Source(**defaults)


async def test_probe_uses_fetch_not_fetch_postings_even_when_supported():
    """Regression guard for the milestone 5 fix: a provider whose
    fetch_postings() is expensive (SmartRecruiters/Workday) must not have it
    invoked by the doctor probe."""
    provider = _FakeProvider(jobs=[{"title": "x"}])
    semaphore = asyncio.Semaphore(1)
    entry = await _probe_source(_source(), {"fake": provider}, semaphore)
    assert entry.status == "ok"
    assert entry.job_count == 1


async def test_probe_reports_zero_jobs():
    provider = _FakeProvider(jobs=[])
    semaphore = asyncio.Semaphore(1)
    entry = await _probe_source(_source(), {"fake": provider}, semaphore)
    assert entry.status == "zero_jobs"
    assert entry.job_count == 0


async def test_probe_reports_error():
    provider = _FakeProvider(error=RuntimeError("dead token"))
    semaphore = asyncio.Semaphore(1)
    entry = await _probe_source(_source(), {"fake": provider}, semaphore)
    assert entry.status == "error"
    assert "dead token" in entry.error


async def test_probe_reports_disabled_without_calling_provider():
    provider = _FakeProvider(fetch_postings_should_not_be_called=True)
    provider.fetch = None  # would AttributeError if doctor tried to call it
    semaphore = asyncio.Semaphore(1)
    entry = await _probe_source(_source(enabled=False), {"fake": provider}, semaphore)
    assert entry.status == "disabled"


async def test_probe_reports_no_provider_match_when_unresolved():
    semaphore = asyncio.Semaphore(1)
    entry = await _probe_source(_source(provider_id=None), {}, semaphore)
    assert entry.status == "no_provider_match"
