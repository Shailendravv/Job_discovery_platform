"""The deterministic scorer — the stage that decides which postings a Claude
Code judging session ever sees.

Two properties matter most and are asserted directly: the score is a pure
function of (posting, config), and only the clear-cut bands get an automatic
verdict. Everything in the middle must stay unjudged so ``jobctl next`` still
hands it to the agent.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.ingest.scoring import (
    BandConfig,
    ExperienceConfig,
    LocationConfig,
    ScoringConfig,
    SeniorityConfig,
    SkillsConfig,
    load_scoring_config,
    run_scoring,
    score_posting,
)
from app.ingest.verdicts import VerdictApplyResult


def _config(**overrides) -> ScoringConfig:
    """A small config with the real weights. Only the lists are shrunk —
    base_score and the per-component weights come from the model defaults so
    these tests fail if the calibration drifts, which is the whole point of
    asserting on bands."""
    base = dict(
        skills=SkillsConfig(core=["python", "fastapi"], bonus=["docker"]),
        seniority=SeniorityConfig(preferred=[r"\bjunior\b"], too_senior=[r"\bstaff\b"]),
        location=LocationConfig(allowed=["india", "remote"]),
        experience=ExperienceConfig(max_years=3),
        bands=BandConfig(auto_apply_min=8, auto_skip_max=3),
    )
    base.update(overrides)
    return ScoringConfig(**base)


def _posting(**overrides) -> dict:
    doc = {
        "_id": "a" * 64,
        "title": "Software Engineer",
        "description_text": "",
        "location": "Bangalore, India",
        "remote_flag": False,
    }
    doc.update(overrides)
    return doc


# ---- score_posting ----------------------------------------------------

def test_scoring_is_deterministic():
    """The same posting and config always produce the same result — that is
    what makes an auto-written verdict defensible."""
    doc, config = _posting(description_text="python fastapi docker"), _config()
    first, second = score_posting(doc, config), score_posting(doc, config)
    assert first.to_dict() == second.to_dict()


def test_score_is_clamped_to_the_verdict_range():
    """Verdict.score is a pydantic Field(ge=1, le=10); a score outside that
    would be rejected at write time."""
    great = score_posting(_posting(title="Junior Engineer", description_text="python fastapi docker"), _config())
    awful = score_posting(_posting(title="Staff Engineer", description_text="20 years", location="Berlin"), _config())
    assert 1 <= great.score <= 10
    assert 1 <= awful.score <= 10


def test_strong_match_lands_in_the_apply_band():
    result = score_posting(
        _posting(title="Junior Engineer", description_text="python fastapi docker, 2 years"),
        _config(),
    )
    assert result.band == "apply"
    assert result.score >= 8


def test_clear_mismatch_lands_in_the_skip_band():
    result = score_posting(
        _posting(title="Staff Engineer", description_text="10 years of enterprise sales", location="Berlin"),
        _config(),
    )
    assert result.band == "skip"


def test_middling_posting_is_left_for_the_agent():
    """The whole point of the stage: a posting with real signal on both sides
    is exactly where a human-quality judgement earns its cost, so it must not
    be auto-decided."""
    result = score_posting(
        _posting(title="Software Engineer", description_text="python only"),
        _config(),
    )
    assert result.band == "needs_review"
    assert 3 < result.score < 8


def test_skill_hits_are_reported_as_matched_requirements():
    result = score_posting(_posting(description_text="python and docker"), _config())
    assert "python" in result.matched_requirements
    assert "docker" in result.matched_requirements
    assert "fastapi" in result.missing_requirements


def test_keyword_stuffing_alone_cannot_reach_auto_apply():
    """max_points caps the skills term so a description repeating every
    keyword cannot buy its way past the band on that alone."""
    result = score_posting(
        _posting(title="Software Engineer", description_text="python fastapi docker " * 50, location="Berlin"),
        _config(),
    )
    assert result.band != "apply"


def test_high_score_without_skill_overlap_is_held_for_review():
    """Regression: seniority + location + years-of-experience are all weak or
    table-stakes signals, and together they used to carry a posting to the
    apply band with no skill overlap at all. Observed on the live registry:
    "Associate Manager, Strategic Partnerships" auto-applied at 8/10 matching
    none of the core skills."""
    result = score_posting(
        _posting(title="Associate Manager, Strategic Partnerships",
                 description_text="stakeholder management, 3 years", remote_flag=True),
        _config(),
    )

    assert result.core_skill_hits == 0
    assert result.band == "needs_review"
    assert any("core skill" in c for c in result.concerns)


def test_the_gate_does_not_block_auto_skip():
    """A posting with no skill overlap being skipped is the correct outcome,
    so the gate must not push obvious rejects back into the review queue."""
    result = score_posting(
        _posting(title="Staff Engineer", description_text="10 years of sales", location="Berlin"),
        _config(),
    )

    assert result.core_skill_hits == 0
    assert result.band == "skip"


def test_enough_skill_overlap_still_auto_applies():
    result = score_posting(
        _posting(title="Junior Engineer", description_text="python fastapi docker, 2 years"),
        _config(),
    )

    assert result.core_skill_hits == 2
    assert result.band == "apply"


def test_too_senior_titles_are_penalised_and_explained():
    result = score_posting(_posting(title="Staff Engineer"), _config())
    assert any("seniority" in c for c in result.concerns)
    assert "seniority fit" in result.missing_requirements


def test_remote_satisfies_the_location_rule():
    result = score_posting(_posting(location="Anywhere", remote_flag=True), _config())
    assert "location" in result.matched_requirements


def test_years_beyond_the_ceiling_are_penalised_proportionally():
    near = score_posting(_posting(description_text="4 years required"), _config())
    far = score_posting(_posting(description_text="12 years required"), _config())
    assert far.score < near.score


def test_unstated_experience_is_neutral():
    """No stated requirement is not evidence either way — it must neither
    reward nor punish."""
    silent = score_posting(_posting(description_text="build things"), _config())
    within = score_posting(_posting(description_text="build things, 2 years"), _config())
    assert within.score > silent.score


def test_shipped_config_parses():
    """config/scoring.yml ships as a documented sample; a syntax error in it
    would silently disable the stage via the runner's FileNotFoundError-only
    guard, so this asserts it actually loads."""
    config = load_scoring_config()
    assert config.bands.auto_apply_min > config.bands.auto_skip_max
    assert config.skills.core


# ---- run_scoring ------------------------------------------------------

def _mock_db(docs):
    db = MagicMock()
    cursor = MagicMock()
    cursor.to_list = AsyncMock(return_value=docs)
    db.postings = MagicMock()
    db.postings.find.return_value = cursor
    db.postings.bulk_write = AsyncMock()
    db.scoring_runs = MagicMock()
    db.scoring_runs.insert_one = AsyncMock()
    return db


@pytest.mark.asyncio
async def test_only_scores_unjudged_prefiltered_postings(monkeypatch):
    """A prefilter-rejected posting is already out, and re-scoring a judged
    one would fight with the agent or a previous pass."""
    db = _mock_db([])
    monkeypatch.setattr("app.ingest.scoring.apply_verdicts", AsyncMock())

    await run_scoring(db, _config())

    db.postings.find.assert_called_once_with(
        {"judged": False, "prefilter_status": "passed", "duplicate_of": None}
    )


@pytest.mark.asyncio
async def test_writes_verdicts_only_for_the_decided_bands(monkeypatch):
    docs = [
        _posting(_id="a" * 64, title="Junior Engineer", description_text="python fastapi docker, 2 years"),
        _posting(_id="b" * 64, title="Staff Engineer", description_text="10 years sales", location="Berlin"),
        _posting(_id="c" * 64, title="Software Engineer", description_text="python only"),
    ]
    apply_mock = AsyncMock(return_value=VerdictApplyResult(applied=2))
    monkeypatch.setattr("app.ingest.scoring.apply_verdicts", apply_mock)
    db = _mock_db(docs)

    result = await run_scoring(db, _config())

    assert (result.auto_applied, result.auto_skipped, result.needs_review) == (1, 1, 1)

    written = apply_mock.await_args.args[1]
    assert {v.id for v in written} == {"a" * 64, "b" * 64}
    assert all(v.judged_by == "deterministic" for v in written)


@pytest.mark.asyncio
async def test_every_posting_gets_its_score_recorded(monkeypatch):
    """Including needs_review ones — seeing their scores is how you tell
    whether the bands are set sensibly."""
    docs = [_posting(_id="c" * 64, title="Software Engineer", description_text="python only")]
    monkeypatch.setattr("app.ingest.scoring.apply_verdicts", AsyncMock(return_value=VerdictApplyResult()))
    db = _mock_db(docs)

    await run_scoring(db, _config())

    operations = db.postings.bulk_write.await_args.args[0]
    assert len(operations) == 1
    written = operations[0]._doc["$set"]
    assert written["score_band"] == "needs_review"
    assert isinstance(written["score"], int)


@pytest.mark.asyncio
async def test_dry_run_computes_bands_without_writing(monkeypatch):
    docs = [_posting(title="Junior Engineer", description_text="python fastapi docker, 2 years")]
    apply_mock = AsyncMock()
    monkeypatch.setattr("app.ingest.scoring.apply_verdicts", apply_mock)
    db = _mock_db(docs)

    result = await run_scoring(db, _config(), dry_run=True)

    assert result.auto_applied == 1
    apply_mock.assert_not_awaited()
    db.postings.bulk_write.assert_not_awaited()
    db.scoring_runs.insert_one.assert_not_awaited()


@pytest.mark.asyncio
async def test_makes_no_llm_call(monkeypatch):
    """The stage exists to remove LLM cost, so this asserts the absence
    directly rather than trusting the imports to stay clean."""
    import app.core.llm as core_llm

    monkeypatch.setattr("app.ingest.scoring.apply_verdicts", AsyncMock(return_value=VerdictApplyResult()))
    monkeypatch.setattr(core_llm, "call_llm_async", AsyncMock(side_effect=AssertionError("LLM called")))

    await run_scoring(_mock_db([_posting()]), _config())
