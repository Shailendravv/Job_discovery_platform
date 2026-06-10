import pytest
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock
from bson import ObjectId

from app.services.db_service import save_jobs

@pytest.fixture
def mock_db():
    db = MagicMock()
    db.jobs = MagicMock()
    db.jobs.bulk_write = AsyncMock()
    return db

@pytest.mark.asyncio
async def test_save_jobs_returns_count(mock_db):
    """Test that save_jobs returns the count of saved jobs."""
    jobs = [
        {"title": "Job 1", "url": "http://example.com/1"},
        {"title": "Job 2", "url": "http://example.com/2"},
    ]
    mock_result = MagicMock()
    mock_result.upserted_count = 2
    mock_result.modified_count = 0
    mock_db.jobs.bulk_write.return_value = mock_result

    saved_count = await save_jobs(mock_db, jobs, search_query="test")

    assert saved_count == 2

@pytest.mark.asyncio
async def test_save_jobs_skips_jobs_without_url(mock_db):
    """Jobs without URL should be skipped for upsert (to avoid duplicates)."""
    jobs = [
        {"title": "Job with URL", "url": "http://example.com/1"},
        {"title": "Job without URL"},  # No URL
    ]
    await save_jobs(mock_db, jobs)

    # Only one operation should be in bulk_write (the job with URL)
    args, kwargs = mock_db.jobs.bulk_write.call_args
    operations = kwargs.get('operations', args[0] if args else [])
    assert len(operations) == 1

@pytest.mark.asyncio
async def test_save_jobs_sets_timestamps_and_search_query(mock_db):
    """Each job should get created_at/updated_at and search_query."""
    jobs = [{"title": "Job", "url": "http://example.com/1"}]
    mock_result = MagicMock()
    mock_result.upserted_count = 1
    mock_result.modified_count = 0
    mock_db.jobs.bulk_write.return_value = mock_result

    await save_jobs(mock_db, jobs, search_query="python remote")

    # Check that bulk_write was called with UpdateOne operations
    args, kwargs = mock_db.jobs.bulk_write.call_args
    operations = args[0] if args else kwargs.get('operations')
    assert len(operations) == 1
    op = operations[0]
    # op should be UpdateOne with filter on url
    assert op._filter == {"url": "http://example.com/1"}
    # update doc should contain $setOnInsert with created_at and $set with updated_at and search_query
    update_doc = op._update
    assert "$setOnInsert" in update_doc
    assert "$set" in update_doc
    assert "created_at" in update_doc["$setOnInsert"]
    assert "updated_at" in update_doc["$set"]
    assert "search_query" in update_doc["$set"]
    assert update_doc["$set"]["search_query"] == "python remote"

@pytest.mark.asyncio
async def test_save_jobs_empty_list_returns_zero(mock_db):
    """Empty jobs list should return 0."""
    saved_count = await save_jobs(mock_db, [])
    assert saved_count == 0
    mock_db.jobs.bulk_write.assert_not_called()
