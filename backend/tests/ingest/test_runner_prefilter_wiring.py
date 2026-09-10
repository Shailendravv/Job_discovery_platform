"""``run_ingest`` calls the milestone-3 prefilter and the deterministic
scoring stage once per run, over whatever the DB still has outstanding (not
just what this particular run fetched) -- so a run that itself fetches 0 new
postings still classifies any backlog, and the very first run after migrating
in the prefilter fields classifies everything at once.

Also covers the Job Discovery additions: per-stage timings on the result, and
the ``ingest_runs`` document being published at run *start* (status
``running``) rather than only at completion, which is what makes live
progress polling possible.

Only that wiring is under test here; fetch/normalize/dedupe/store are
exercised by their own unit tests (test_normalize.py, test_dedupe.py,
test_store.py) and by the live acceptance test (PLAN.md §2), so this test
short-circuits source selection to an empty registry to isolate the behavior
instead of re-mocking the whole pipeline.
"""

from datetime import timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest

import app.ingest.runner as runner
from app.ingest.prefilter import PrefilterConfig, PrefilterRunResult
from app.ingest.scoring import ScoringConfig, ScoringRunResult


def _mock_db():
    db = MagicMock()
    db.ingest_runs = MagicMock()
    db.ingest_runs.insert_one = AsyncMock()
    db.ingest_runs.update_one = AsyncMock()
    return db


@pytest.fixture
def stub_stages(monkeypatch):
    """Empty registry + stubbed prefilter/scoring, the shape almost every
    test here wants. Returns the two mocks so a test can assert on them."""
    monkeypatch.setattr(runner, "load_and_resolve_sources", lambda path: [])
    prefilter_mock = AsyncMock(return_value=PrefilterRunResult(input=5, hard_filter_rejected=4, passed=1))
    scoring_mock = AsyncMock(return_value=ScoringRunResult(input=1, auto_applied=1))
    monkeypatch.setattr(runner, "run_prefilter", prefilter_mock)
    monkeypatch.setattr(runner, "run_scoring", scoring_mock)
    return prefilter_mock, scoring_mock


@pytest.mark.asyncio
async def test_run_ingest_invokes_prefilter_and_merges_counts(stub_stages):
    prefilter_mock, _ = stub_stages
    db = _mock_db()

    result = await runner.run_ingest(db)

    prefilter_mock.assert_awaited_once()
    assert prefilter_mock.await_args.args[0] is db
    assert isinstance(prefilter_mock.await_args.args[1], PrefilterConfig)
    assert result.prefilter == PrefilterRunResult(input=5, hard_filter_rejected=4, passed=1).to_dict()


@pytest.mark.asyncio
async def test_run_ingest_invokes_deterministic_scoring(stub_stages):
    """The stage that keeps Claude Code out of the clear-cut cases runs on
    every non-dry-run ingest, with the same (db, config) contract as the
    prefilter."""
    _, scoring_mock = stub_stages
    db = _mock_db()

    result = await runner.run_ingest(db)

    scoring_mock.assert_awaited_once()
    assert scoring_mock.await_args.args[0] is db
    assert isinstance(scoring_mock.await_args.args[1], ScoringConfig)
    assert result.score == ScoringRunResult(input=1, auto_applied=1).to_dict()


@pytest.mark.asyncio
async def test_run_ingest_dry_run_skips_prefilter_and_scoring(monkeypatch):
    monkeypatch.setattr(runner, "load_and_resolve_sources", lambda path: [])
    prefilter_mock = AsyncMock()
    scoring_mock = AsyncMock()
    monkeypatch.setattr(runner, "run_prefilter", prefilter_mock)
    monkeypatch.setattr(runner, "run_scoring", scoring_mock)

    db = _mock_db()
    result = await runner.run_ingest(db, dry_run=True)

    prefilter_mock.assert_not_awaited()
    scoring_mock.assert_not_awaited()
    db.ingest_runs.insert_one.assert_not_awaited()
    assert result.prefilter is None
    assert result.score is None


@pytest.mark.asyncio
async def test_run_ingest_records_stage_timings(stub_stages):
    db = _mock_db()

    result = await runner.run_ingest(db)

    names = [stage.name for stage in result.stages]
    assert names == ["load_registry", "fetch", "prefilter", "score", "total"]
    assert all(stage.duration_ms >= 0 for stage in result.stages)
    # "total" is the wall clock for the whole run, so no individual stage can
    # exceed it -- a cheap guard against a stage being timed with the wrong
    # start point.
    total = next(s for s in result.stages if s.name == "total")
    assert all(s.duration_ms <= total.duration_ms + 1 for s in result.stages)
    assert result.elapsed_ms == total.duration_ms


@pytest.mark.asyncio
async def test_run_ingest_publishes_run_before_it_finishes(stub_stages):
    """The Discovery page polls ``ingest_runs`` while the run is in flight,
    so the document has to exist with status "running" from the start and be
    flipped to "completed" at the end."""
    db = _mock_db()

    await runner.run_ingest(db, run_id="abc123", role="backend engineer", window_label="24h")

    db.ingest_runs.insert_one.assert_awaited_once()
    opening = db.ingest_runs.insert_one.await_args.args[0]
    assert opening["_id"] == "abc123"
    assert opening["status"] == "running"
    assert opening["finished_at"] is None
    assert opening["role"] == "backend engineer"
    assert opening["window"] == "24h"

    closing = db.ingest_runs.update_one.await_args.args[1]["$set"]
    assert closing["status"] == "completed"
    assert closing["finished_at"] is not None
    assert closing["stages"]


@pytest.mark.asyncio
async def test_run_ingest_passes_window_cutoff_to_providers(monkeypatch, stub_stages):
    """A windowed run hands providers a ``posted_since`` cutoff so the two
    that pay a per-job description fetch can skip stale postings before
    spending that call."""
    seen = {}

    async def fake_fetch_source(source, providers_by_id, semaphore, posted_since=None):
        seen["posted_since"] = posted_since
        return runner.SourceOutcome("x", "x", "greenhouse", "ok"), []

    monkeypatch.setattr(runner, "load_and_resolve_sources", lambda path: [MagicMock(enabled=True, org="x")])
    monkeypatch.setattr(runner, "_select_sources", lambda sources, s, o: sources)
    monkeypatch.setattr(runner, "_fetch_source", fake_fetch_source)

    await runner.run_ingest(_mock_db(), window=timedelta(hours=24), window_label="24h")

    assert seen["posted_since"] is not None


@pytest.mark.asyncio
async def test_run_ingest_without_window_passes_no_cutoff(monkeypatch, stub_stages):
    """The unscoped nightly ingest must keep fetching everything -- passing a
    cutoff there would silently stop refreshing ``last_seen_at``."""
    seen = {}

    async def fake_fetch_source(source, providers_by_id, semaphore, posted_since=None):
        seen["posted_since"] = posted_since
        return runner.SourceOutcome("x", "x", "greenhouse", "ok"), []

    monkeypatch.setattr(runner, "load_and_resolve_sources", lambda path: [MagicMock(enabled=True, org="x")])
    monkeypatch.setattr(runner, "_select_sources", lambda sources, s, o: sources)
    monkeypatch.setattr(runner, "_fetch_source", fake_fetch_source)

    await runner.run_ingest(_mock_db())

    assert seen["posted_since"] is None


@pytest.mark.asyncio
async def test_progress_write_failure_does_not_fail_the_run(stub_stages):
    """Mid-run progress reporting is a convenience. An ingest that actually
    fetched postings must not be lost because one status write failed.

    The *final* write is deliberately not swallowed: if completion cannot be
    recorded the poller would wait on "running" forever, so that failure
    propagates and the API marks the run failed instead.
    """
    db = _mock_db()

    async def flaky_update(query, update, **kwargs):
        if update["$set"]["status"] == "running":
            raise RuntimeError("mongo down")
        return MagicMock()

    db.ingest_runs.update_one = AsyncMock(side_effect=flaky_update)

    result = await runner.run_ingest(db)

    assert result.finished_at
    assert db.ingest_runs.update_one.await_args.args[1]["$set"]["status"] == "completed"
