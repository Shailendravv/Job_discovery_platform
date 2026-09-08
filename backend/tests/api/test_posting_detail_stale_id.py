"""A stale Job Details link must fail as a *link* problem, not a server fault.

The pre-fix Dashboard minted ``/jobs/${job.id || idx}``, so rows whose
``posting.id`` was undefined produced row-index URLs — ``/jobs/9``,
``/jobs/0``. Those URLs outlive the fix: they sit in open tabs, history
and bookmarks, and every reload refires ``GET /api/v1/postings/9`` (twice
in dev, via React's StrictMode double-effect) → 404.

Every ``_id`` in ``postings`` is a 64-char sha256 digest (models.posting_id),
so an id like ``9`` is *structurally* impossible — no lookup can ever match
it. The endpoint should say so instead of echoing a bare "Posting not
found: 9", which reads like the posting vanished from a healthy pipeline.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.deps import get_db
from app.api.v1 import postings as postings_api

VALID_ID = "b" * 64


@pytest.fixture
def db():
    db = MagicMock()
    db.postings.find_one = AsyncMock(return_value=None)
    return db


@pytest.fixture
def client(db, monkeypatch):
    monkeypatch.setattr(postings_api, "get_latest_resume", AsyncMock(return_value=None))
    monkeypatch.setattr(
        postings_api, "get_tailor_session_for_job", AsyncMock(return_value=None)
    )
    app = FastAPI()
    app.include_router(postings_api.router, prefix="/api/v1/postings")
    app.dependency_overrides[get_db] = lambda: db
    return TestClient(app)


@pytest.mark.parametrize("stale_id", ["9", "0", "42", "not-a-digest", "a" * 63])
def test_index_shaped_id_is_reported_as_a_stale_link(client, db, stale_id):
    response = client.get(f"/api/v1/postings/{stale_id}")

    assert response.status_code == 404
    detail = response.json()["detail"]
    assert "stale" in detail.lower(), detail
    # Structurally impossible ids must not cost a database round trip.
    db.postings.find_one.assert_not_awaited()


def test_wellformed_but_absent_id_reports_a_removed_posting(client, db):
    response = client.get(f"/api/v1/postings/{VALID_ID}")

    assert response.status_code == 404
    detail = response.json()["detail"]
    assert "stale" not in detail.lower(), detail
    assert "no longer available" in detail.lower(), detail
    db.postings.find_one.assert_awaited_once_with({"_id": VALID_ID})
