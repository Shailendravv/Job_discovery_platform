"""Milestone 3 (PLAN.md §4/§9): rule-based prefilter between ``jobctl ingest``
and ``jobctl next``. Acceptance test: ``run_prefilter`` against a realistic
mixed batch drops >=80% before judging, with per-stage counts logged.

Mocked-db style matches ``test_query.py``/``test_verdicts.py`` — no real
Mongo, ``MagicMock``/``AsyncMock`` on the collections actually touched.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic import ValidationError

from app.ingest.prefilter import (
    EmbeddingConfig,
    HardFilterConfig,
    KeywordFloorConfig,
    PrefilterConfig,
    extract_years_required,
    hard_filter_reject,
    keyword_floor_pass,
    embedding_similarity_reject,
    load_prefilter_config,
    run_prefilter,
)

SAMPLE_YAML = """
hard_filters:
  title_blocklist: ["\\\\bstaff\\\\b", "\\\\bprincipal\\\\b", "\\\\bdirector\\\\b"]
  allowed_locations: ["remote", "bangalore", "india"]
  remote_ok: true
  max_years_experience: 3
  disqualifying_keywords: ["security clearance", "us citizenship required"]
keyword_floor:
  skills: ["python", "fastapi", "react"]
  min_matches: 2
embedding:
  enabled: false
"""


def _posting(**overrides) -> dict:
    doc = {
        "_id": "a" * 64,
        "title": "Backend Engineer",
        "company_name": "Acme",
        "location": "Bangalore",
        "remote_flag": False,
        "description_text": "We use Python and FastAPI. 2 years experience required.",
    }
    doc.update(overrides)
    return doc


# ---- config loading ----------------------------------------------------

def test_load_prefilter_config_parses_yaml(tmp_path):
    path = tmp_path / "prefilter.yml"
    path.write_text(SAMPLE_YAML, encoding="utf-8")

    config = load_prefilter_config(str(path))

    assert config.hard_filters.max_years_experience == 3
    assert "python" in config.keyword_floor.skills
    assert config.embedding.enabled is False


def test_load_prefilter_config_missing_file_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_prefilter_config(str(tmp_path / "does_not_exist.yml"))


def test_prefilter_config_defaults_are_permissive():
    config = PrefilterConfig()
    assert config.hard_filters.title_blocklist == []
    assert config.keyword_floor.min_matches == 0
    assert config.embedding.enabled is False


# ---- extract_years_required ---------------------------------------------

@pytest.mark.parametrize(
    "text,expected",
    [
        ("Looking for someone with 5+ years of experience", 5),
        ("3-5 years experience with Python", 3),
        ("We'd love a great teammate, no specific years mentioned", None),
        ("At least 10 years in backend engineering", 10),
    ],
)
def test_extract_years_required(text, expected):
    assert extract_years_required(text) == expected


# ---- hard_filter_reject ---------------------------------------------------

def test_hard_filter_reject_passes_clean_posting():
    config = HardFilterConfig(
        title_blocklist=[r"\bstaff\b"],
        allowed_locations=["bangalore"],
        max_years_experience=3,
        disqualifying_keywords=["security clearance"],
    )
    assert hard_filter_reject(_posting(), config) is None


def test_hard_filter_reject_title_blocklist():
    config = HardFilterConfig(title_blocklist=[r"\bstaff\b"])
    reason = hard_filter_reject(_posting(title="Staff Backend Engineer"), config)
    assert reason is not None and "title" in reason


def test_hard_filter_reject_title_allowlist_requires_a_match():
    config = HardFilterConfig(title_allowlist=[r"\bengineer\b"])
    assert hard_filter_reject(_posting(title="Engineer II"), config) is None
    reason = hard_filter_reject(_posting(title="Sales Manager"), config)
    assert reason is not None


def test_hard_filter_reject_disallowed_location_not_remote():
    config = HardFilterConfig(allowed_locations=["bangalore"], remote_ok=True)
    reason = hard_filter_reject(_posting(location="London", remote_flag=False), config)
    assert reason is not None and "location" in reason


def test_hard_filter_reject_remote_ok_overrides_location_list():
    config = HardFilterConfig(allowed_locations=["bangalore"], remote_ok=True)
    reason = hard_filter_reject(_posting(location="London", remote_flag=True), config)
    assert reason is None


def test_hard_filter_reject_years_ceiling():
    config = HardFilterConfig(max_years_experience=3)
    reason = hard_filter_reject(
        _posting(description_text="Requires 7+ years of experience"), config
    )
    assert reason is not None and "years" in reason


def test_hard_filter_reject_disqualifying_keyword():
    config = HardFilterConfig(disqualifying_keywords=["security clearance"])
    reason = hard_filter_reject(
        _posting(description_text="Active security clearance required."), config
    )
    assert reason is not None and "security clearance" in reason


# ---- keyword_floor_pass ----------------------------------------------------

def test_keyword_floor_pass_empty_skill_list_always_passes():
    assert keyword_floor_pass(_posting(), KeywordFloorConfig(skills=[], min_matches=5)) is True


def test_keyword_floor_pass_below_floor_fails():
    config = KeywordFloorConfig(skills=["python", "fastapi", "kubernetes"], min_matches=3)
    assert keyword_floor_pass(_posting(), config) is False


def test_keyword_floor_pass_at_floor_passes():
    config = KeywordFloorConfig(skills=["python", "fastapi"], min_matches=2)
    assert keyword_floor_pass(_posting(), config) is True


# ---- embedding_similarity_reject (disabled by default this milestone) ----

def test_embedding_similarity_reject_returns_none_when_disabled():
    config = EmbeddingConfig(enabled=False)
    assert embedding_similarity_reject(_posting(), config) is None


def test_embedding_similarity_reject_degrades_when_enabled_but_unavailable():
    # sentence-transformers is not a project dependency yet (deferred, see
    # PLAN.md deviation note) -- enabling the stage must not crash a run.
    config = EmbeddingConfig(enabled=True, resume_path="profile/resume.md")
    assert embedding_similarity_reject(_posting(), config) is None


# ---- run_prefilter ----------------------------------------------------

def _mock_db(docs):
    db = MagicMock()
    db.postings = MagicMock()
    cursor = MagicMock()
    cursor.to_list = AsyncMock(return_value=docs)
    db.postings.find.return_value = cursor
    db.postings.bulk_write = AsyncMock()
    db.prefilter_runs = MagicMock()
    db.prefilter_runs.insert_one = AsyncMock()
    return db


def _written_sets(db) -> dict:
    """``{posting_id: $set payload}`` from the single bulk_write the stage
    issues. run_prefilter batches its classifications into one unordered
    bulk_write rather than awaiting an update per document, so the
    assertions read the operations out of that call."""
    assert db.postings.bulk_write.await_count == 1
    operations = db.postings.bulk_write.await_args.args[0]
    return {
        op._filter["_id"]: op._doc["$set"]
        for op in operations
    }


def _mixed_batch() -> list[dict]:
    """20 synthetic postings: 3 genuine matches, 17 that should be rejected
    by one stage or another -- >=80% reject rate."""
    postings = []
    for i in range(3):
        postings.append(_posting(_id=f"good{i}".rjust(64, "0"), title=f"Backend Engineer {i}"))
    for i in range(6):
        postings.append(_posting(_id=f"senior{i}".rjust(64, "0"), title=f"Staff Engineer {i}"))
    for i in range(5):
        postings.append(_posting(
            _id=f"loc{i}".rjust(64, "0"), location="London", remote_flag=False,
        ))
    for i in range(3):
        postings.append(_posting(
            _id=f"clr{i}".rjust(64, "0"),
            description_text="Active security clearance required. Python, FastAPI.",
        ))
    for i in range(3):
        postings.append(_posting(
            _id=f"kw{i}".rjust(64, "0"), description_text="We use Go and Rust only.",
        ))
    return postings


@pytest.mark.asyncio
async def test_run_prefilter_drops_at_least_80_percent():
    config = PrefilterConfig(
        hard_filters=HardFilterConfig(
            title_blocklist=[r"\bstaff\b"],
            allowed_locations=["bangalore", "india"],
            remote_ok=True,
            max_years_experience=3,
            disqualifying_keywords=["security clearance"],
        ),
        keyword_floor=KeywordFloorConfig(skills=["python", "fastapi"], min_matches=2),
    )
    docs = _mixed_batch()
    db = _mock_db(docs)

    result = await run_prefilter(db, config)

    assert result.input == len(docs)
    total_rejected = result.hard_filter_rejected + result.keyword_floor_rejected + result.embedding_rejected
    assert total_rejected / result.input >= 0.8
    assert result.passed == len(docs) - total_rejected
    db.prefilter_runs.insert_one.assert_awaited_once()


@pytest.mark.asyncio
async def test_run_prefilter_writes_status_and_reason_back_to_postings():
    config = PrefilterConfig(
        hard_filters=HardFilterConfig(title_blocklist=[r"\bstaff\b"]),
    )
    docs = [_posting(_id="x" * 64, title="Staff Engineer"), _posting(_id="y" * 64)]
    db = _mock_db(docs)

    await run_prefilter(db, config)

    calls = _written_sets(db)
    assert calls["x" * 64]["prefiltered"] is True
    assert calls["x" * 64]["prefilter_status"] == "hard_filter"
    assert calls["y" * 64]["prefilter_status"] == "passed"


@pytest.mark.asyncio
async def test_run_prefilter_only_reads_unprefiltered_postings():
    db = _mock_db([])

    await run_prefilter(db, PrefilterConfig())

    db.postings.find.assert_called_once_with({"prefiltered": False})


@pytest.mark.asyncio
async def test_run_prefilter_dry_run_computes_counts_without_writing():
    config = PrefilterConfig(hard_filters=HardFilterConfig(title_blocklist=[r"\bstaff\b"]))
    docs = [_posting(_id="x" * 64, title="Staff Engineer"), _posting(_id="y" * 64)]
    db = _mock_db(docs)

    result = await run_prefilter(db, config, dry_run=True)

    assert result.hard_filter_rejected == 1
    assert result.passed == 1
    db.postings.bulk_write.assert_not_awaited()
    db.prefilter_runs.insert_one.assert_not_awaited()


# ---- reclassify --------------------------------------------------------
#
# Editing prefilter.yml used to be inert: run_prefilter only ever read
# {"prefiltered": False}, so a corrected allowed_locations list changed
# nothing for the postings already classified under the old one.

@pytest.mark.asyncio
async def test_run_prefilter_reclassify_reads_every_posting():
    db = _mock_db([])

    await run_prefilter(db, PrefilterConfig(), reclassify=True)

    db.postings.find.assert_called_once_with({})


@pytest.mark.asyncio
async def test_run_prefilter_reclassify_reverses_a_stale_rejection():
    """A posting rejected under the old location list must be able to come
    back as passed once the list is corrected -- otherwise the only way to
    apply a config change is to wipe the collection."""
    config = PrefilterConfig(
        hard_filters=HardFilterConfig(allowed_locations=["gurugram"], remote_ok=True),
    )
    stale = _posting(
        _id="z" * 64,
        location="Gurugram, India",
        prefiltered=True,
        prefilter_status="hard_filter",
        prefilter_reason="location not allowed: Gurugram, India",
    )
    db = _mock_db([stale])

    result = await run_prefilter(db, config, reclassify=True)

    assert result.passed == 1
    written = _written_sets(db)["z" * 64]
    assert written["prefilter_status"] == "passed"
    assert written["prefilter_reason"] is None
