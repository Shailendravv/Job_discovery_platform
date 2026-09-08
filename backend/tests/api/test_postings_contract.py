"""The posting id the frontend routes on must reach the wire as ``id``.

``Posting.id`` carries ``alias="_id"`` so a Mongo document validates
straight into the model (and ``model_dump(by_alias=True)`` writes it back
as ``_id`` in store.py). FastAPI serializes response models with
``by_alias=True`` by default, which leaked that storage-level name into
the public JSON: every posting came out keyed ``_id``, so ``posting.id``
was undefined in the frontend and the Job Details link fell back to the
row index — ``GET /api/v1/postings/0`` → 404.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.deps import get_db
from app.api.v1 import postings as postings_api

POSTING_ID = "a" * 64

DOC = {
    "_id": POSTING_ID,
    "provider": "lever",
    "org": "palantir",
    "company_name": "Palantir",
    "title": "Software Engineer",
    "title_normalized": "software engineer",
    "url": "https://jobs.lever.co/palantir/123",
}


@pytest.fixture
def client(monkeypatch):
    db = MagicMock()
    db.postings.find_one = AsyncMock(return_value=DOC)

    monkeypatch.setattr(postings_api, "list_postings", AsyncMock(return_value=[DOC]))
    monkeypatch.setattr(
        postings_api,
        "shortlist_postings",
        AsyncMock(
            return_value=[
                {
                    "_id": POSTING_ID,
                    "verdict": "apply",
                    "score": 8,
                    "reasons": [],
                    "concerns": [],
                    "judged_at": None,
                    "posting": DOC,
                }
            ]
        ),
    )
    monkeypatch.setattr(postings_api, "get_latest_resume", AsyncMock(return_value=None))
    monkeypatch.setattr(
        postings_api, "get_tailor_session_for_job", AsyncMock(return_value=None)
    )

    app = FastAPI()
    app.include_router(postings_api.router, prefix="/api/v1/postings")
    app.dependency_overrides[get_db] = lambda: db
    return TestClient(app)


def test_list_exposes_id_not_underscore_id(client):
    posting = client.get("/api/v1/postings").json()["postings"][0]
    assert posting["id"] == POSTING_ID
    assert "_id" not in posting


def test_detail_exposes_id_not_underscore_id(client):
    body = client.get(f"/api/v1/postings/{POSTING_ID}").json()
    assert body["id"] == POSTING_ID
    assert "_id" not in body


def test_shortlist_nested_posting_exposes_id(client):
    entry = client.get("/api/v1/postings/shortlist").json()["entries"][0]
    assert entry["id"] == POSTING_ID
    assert entry["posting"]["id"] == POSTING_ID
    assert "_id" not in entry["posting"]
