"""``run_ingest`` calls the milestone-3 prefilter once per run, over
whatever the DB still has marked ``prefiltered=False`` (not just what this
particular run fetched) -- so a run that itself fetches 0 new postings still
classifies any backlog, and the very first run after migrating in the
prefilter fields classifies everything at once.

Only the prefilter wiring is under test here; fetch/normalize/dedupe/store
are exercised by their own unit tests (test_normalize.py, test_dedupe.py,
test_store.py) and by the live acceptance test (PLAN.md §2), so this test
short-circuits source selection to an empty registry to isolate the new
behavior instead of re-mocking the whole pipeline.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

import app.ingest.runner as runner
from app.ingest.prefilter import PrefilterConfig, PrefilterRunResult


def _mock_db():
    db = MagicMock()
    db.ingest_runs = MagicMock()
    db.ingest_runs.insert_one = AsyncMock()
    return db


@pytest.mark.asyncio
async def test_run_ingest_invokes_prefilter_and_merges_counts(monkeypatch):
    monkeypatch.setattr(runner, "load_and_resolve_sources", lambda path: [])
    fake_result = PrefilterRunResult(input=5, hard_filter_rejected=4, passed=1)
    prefilter_mock = AsyncMock(return_value=fake_result)
    monkeypatch.setattr(runner, "run_prefilter", prefilter_mock)

    db = _mock_db()
    result = await runner.run_ingest(db)

    prefilter_mock.assert_awaited_once()
    assert prefilter_mock.await_args.args[0] is db
    assert isinstance(prefilter_mock.await_args.args[1], PrefilterConfig)
    assert result.prefilter == fake_result.to_dict()


@pytest.mark.asyncio
async def test_run_ingest_dry_run_skips_prefilter(monkeypatch):
    monkeypatch.setattr(runner, "load_and_resolve_sources", lambda path: [])
    prefilter_mock = AsyncMock()
    monkeypatch.setattr(runner, "run_prefilter", prefilter_mock)

    db = _mock_db()
    result = await runner.run_ingest(db, dry_run=True)

    prefilter_mock.assert_not_awaited()
    assert result.prefilter is None
