"""The Job Discovery API surface: scoping a run, polling its progress, and
reading back the role/freshness-filtered results.

The pipeline itself is covered by tests/ingest/; what matters here is the
contract the frontend depends on — that the ingest body stays optional, that
``q``/``posted_within`` reach ``PostingFilter``, and that a run is pollable
while it is still running.
"""

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.deps import get_db
from app.api.v1 import postings as postings_api

RUN_ID = "abc123def456"
NOW = datetime(2026, 9, 8, 12, 0, 0, tzinfo=timezone.utc)


@pytest.fixture
def db():
    db = MagicMock()
    db.ingest_runs.find_one = AsyncMock(return_value=None)
    return db


@pytest.fixture
def list_mock(monkeypatch):
    mock = AsyncMock(return_value=[])
    monkeypatch.setattr(postings_api, "list_postings", mock)
    return mock


@pytest.fixture
def run_mock(monkeypatch, db):
    """Stub run_ingest so the background task does no real work, and capture
    the kwargs the endpoint threaded into it.

    ``get_database()`` is stubbed too: the background task resolves its own
    handle rather than using the request's ``get_db`` dependency, because it
    outlives the request.
    """
    mock = AsyncMock(return_value=MagicMock(
        sources_ok=1, sources_error=0, postings_fetched=10,
        postings_fresh=3, inserted=2, updated=1, elapsed_ms=1234.0,
    ))
    monkeypatch.setattr(postings_api, "run_ingest", mock)
    monkeypatch.setattr(postings_api, "get_database", lambda: db)
    monkeypatch.setattr(postings_api, "mark_run_failed", AsyncMock())
    return mock


@pytest.fixture
def client(db):
    app = FastAPI()
    app.include_router(postings_api.router, prefix="/api/v1/postings")
    app.dependency_overrides[get_db] = lambda: db
    return TestClient(app)


# ---- POST /ingest -----------------------------------------------------

def test_ingest_body_is_optional(client, run_mock):
    """The nightly loop and every caller predating the Discovery search post
    no body at all; that must still start a full run."""
    response = client.post("/api/v1/postings/ingest")

    assert response.status_code == 202
    assert response.json()["status"] == "started"
    assert run_mock.await_args.kwargs["role"] is None


def test_ingest_threads_role_and_window_into_the_run(client, run_mock):
    response = client.post(
        "/api/v1/postings/ingest",
        json={"role": "backend engineer", "window": "48h"},
    )

    assert response.status_code == 202
    kwargs = run_mock.await_args.kwargs
    assert kwargs["role"] == "backend engineer"
    assert kwargs["window"] == timedelta(hours=48)
    assert kwargs["window_label"] == "48h"


def test_ingest_defaults_the_window_when_unset(client, run_mock):
    client.post("/api/v1/postings/ingest", json={"role": "data engineer"})

    assert run_mock.await_args.kwargs["window"] == timedelta(hours=24)


def test_ingest_rejects_a_malformed_window(client, run_mock):
    """A typo'd window must be a 422, not a silent fall back to 24h that
    quietly returns the wrong postings."""
    response = client.post("/api/v1/postings/ingest", json={"window": "last tuesday"})

    assert response.status_code == 422
    run_mock.assert_not_awaited()


def test_ingest_returns_before_the_run_completes(client, run_mock):
    """The whole reason this endpoint is backgrounded: the old inline
    /search hung for hours."""
    response = client.post("/api/v1/postings/ingest", json={"role": "backend engineer"})

    assert response.status_code == 202
    assert response.json()["run_id"]


# ---- GET /ingest/{run_id} ---------------------------------------------

def test_run_status_reports_stages_while_still_running(client, db):
    db.ingest_runs.find_one = AsyncMock(return_value={
        "_id": RUN_ID,
        "status": "running",
        "started_at": NOW,
        "finished_at": None,
        "role": "backend engineer",
        "window": "24h",
        "stages": [
            {"name": "load_registry", "duration_ms": 12.5, "count": 200},
            {"name": "fetch", "duration_ms": 9400.0, "count": 4812},
        ],
        "postings_fetched": 4812,
        "postings_fresh": 37,
    })

    body = client.get(f"/api/v1/postings/ingest/{RUN_ID}").json()

    assert body["status"] == "running"
    assert body["finished_at"] is None
    assert [s["name"] for s in body["stages"]] == ["load_registry", "fetch"]
    assert body["stages"][1]["duration_ms"] == 9400.0
    assert body["postings_fresh"] == 37


def test_run_status_reports_completion(client, db):
    db.ingest_runs.find_one = AsyncMock(return_value={
        "_id": RUN_ID,
        "status": "completed",
        "started_at": NOW,
        "finished_at": NOW + timedelta(seconds=30),
        "elapsed_ms": 30000.0,
        "stages": [],
    })

    body = client.get(f"/api/v1/postings/ingest/{RUN_ID}").json()

    assert body["status"] == "completed"
    assert body["elapsed_ms"] == 30000.0
    assert body["finished_at"]


def test_run_status_infers_status_for_pre_existing_runs(client, db):
    """Runs recorded before the status field existed have finished_at but no
    status; reporting them as "running" would hang a poller forever."""
    db.ingest_runs.find_one = AsyncMock(return_value={
        "_id": RUN_ID, "started_at": NOW, "finished_at": NOW,
    })

    assert client.get(f"/api/v1/postings/ingest/{RUN_ID}").json()["status"] == "completed"


def test_run_status_404s_for_an_unknown_run(client, db):
    db.ingest_runs.find_one = AsyncMock(return_value=None)

    assert client.get(f"/api/v1/postings/ingest/{RUN_ID}").status_code == 404


def test_run_status_route_is_not_swallowed_by_the_posting_detail_route(client, db):
    """`/ingest/{run_id}` has to resolve before `/{posting_id}` — the same
    ordering trap `/shortlist` and `/ingest` already document."""
    db.ingest_runs.find_one = AsyncMock(return_value={
        "_id": RUN_ID, "status": "completed", "started_at": NOW, "finished_at": NOW,
    })

    body = client.get(f"/api/v1/postings/ingest/{RUN_ID}").json()

    assert body["run_id"] == RUN_ID
    assert "posting" not in body


# ---- GET /postings with the discovery filters -------------------------

def test_role_query_reaches_the_filter(client, list_mock):
    client.get("/api/v1/postings", params={"q": "backend engineer"})

    assert list_mock.await_args.args[1].role_query == "backend engineer"


def test_posted_within_becomes_a_timedelta(client, list_mock):
    client.get("/api/v1/postings", params={"posted_within": "24h"})

    assert list_mock.await_args.args[1].posted_since == timedelta(hours=24)


def test_posted_within_is_unset_by_default(client, list_mock):
    """The Dashboard read must keep its since_days behaviour; only the
    Discovery page opts into the posted-at window."""
    client.get("/api/v1/postings")

    filters = list_mock.await_args.args[1]
    assert filters.posted_since is None
    assert filters.role_query is None


def test_malformed_posted_within_is_a_422(client, list_mock):
    response = client.get("/api/v1/postings", params={"posted_within": "soon"})

    assert response.status_code == 422
    list_mock.assert_not_awaited()
