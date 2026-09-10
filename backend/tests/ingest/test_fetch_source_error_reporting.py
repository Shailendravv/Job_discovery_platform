"""``_fetch_source`` must report *something diagnosable* when a provider's
``fetch_postings`` raises — including the exceptions whose ``str()`` is
empty (bare ``RuntimeError()``, ``asyncio.TimeoutError()``, etc.), which are
common for network/timeout failures.

Regression coverage for a real production incident: a greenhouse fetch
failed mid-run with the log line

    [ingest] greenhouse/Duolingo fetch_postings failed:

— exception message blank, ``SourceOutcome.error`` blank, no way to tell
what happened. ``str(e)`` alone is not a safe way to render an exception;
the exception's *type* must always be present too.
"""

import asyncio

import pytest

from app.ingest.registry import Source
from app.ingest.runner import _fetch_source


class _RaisingProvider:
    """Stub provider whose fetch_postings raises a message-less exception."""

    id = "greenhouse"

    def __init__(self, exc: Exception):
        self._exc = exc

    async def fetch_postings(self, company, api_url, *, posted_since=None):
        raise self._exc


def _make_source() -> Source:
    return Source(
        name="Duolingo",
        org="duolingo",
        careers_url="https://job-boards.greenhouse.io/duolingo",
        provider_id="greenhouse",
        api_url="https://boards-api.greenhouse.io/v1/boards/duolingo/jobs",
    )


@pytest.mark.asyncio
async def test_fetch_source_reports_exception_type_when_message_is_empty(caplog):
    source = _make_source()
    provider = _RaisingProvider(RuntimeError())  # str(RuntimeError()) == ""
    providers_by_id = {"greenhouse": provider}
    semaphore = asyncio.Semaphore(1)

    with caplog.at_level("WARNING"):
        outcome, postings = await _fetch_source(source, providers_by_id, semaphore)

    assert postings == []
    assert outcome.status == "error"
    # The whole point: a blank str(e) must not produce a blank error field.
    assert outcome.error
    assert "RuntimeError" in outcome.error

    # And the log line itself must carry the exception type too, not just
    # whatever (possibly empty) text %s formats str(e) into.
    assert any("RuntimeError" in record.message for record in caplog.records)


@pytest.mark.asyncio
async def test_fetch_source_still_reports_normal_exception_messages(caplog):
    source = _make_source()
    provider = _RaisingProvider(ValueError("boom"))
    providers_by_id = {"greenhouse": provider}
    semaphore = asyncio.Semaphore(1)

    with caplog.at_level("WARNING"):
        outcome, postings = await _fetch_source(source, providers_by_id, semaphore)

    assert outcome.status == "error"
    assert "ValueError" in outcome.error
    assert "boom" in outcome.error
