"""``jobctl judge --apply`` round-trip (milestone 2 acceptance test: verdicts
round-trip end to end, PLAN.md §9). Schema validation is exercised via
``Verdict`` directly; ``apply_verdicts`` is exercised against a mocked db —
unknown ids, duplicate ids in-file, and the --force gate are all per-item
outcomes (PLAN.md §3)."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic import ValidationError

from app.ingest.verdicts import RejectedVerdict, Verdict, VerdictApplyResult, apply_verdicts

FULL_ID = "b" * 64


def _mock_db(posting_doc):
    db = MagicMock()
    db.postings = MagicMock()
    db.postings.find_one = AsyncMock(return_value=posting_doc)
    db.postings.update_one = AsyncMock()
    db.verdicts = MagicMock()
    db.verdicts.update_one = AsyncMock()
    return db


def _verdict(**overrides) -> Verdict:
    data = {
        "id": FULL_ID,
        "verdict": "apply",
        "score": 8,
        "reasons": ["matches core stack"],
        "concerns": [],
        "matched_requirements": ["Python"],
        "missing_requirements": [],
        "judged_by": "claude-code",
    }
    data.update(overrides)
    return Verdict.model_validate(data)


def test_verdict_rejects_score_out_of_range():
    with pytest.raises(ValidationError):
        Verdict.model_validate({"id": FULL_ID, "verdict": "apply", "score": 11})


def test_verdict_rejects_unknown_verdict_label():
    with pytest.raises(ValidationError):
        Verdict.model_validate({"id": FULL_ID, "verdict": "definitely", "score": 5})


def test_verdict_judged_by_defaults_to_claude_code():
    v = Verdict.model_validate({"id": FULL_ID, "verdict": "skip", "score": 2})
    assert v.judged_by == "claude-code"


def test_verdict_apply_result_to_dict_shape():
    result = VerdictApplyResult(
        applied=1,
        rejected=[RejectedVerdict(id="abc123", reason="unknown id: 'abc123'")],
    )
    assert result.to_dict() == {
        "applied": 1,
        "rejected": [{"id": "abc123", "reason": "unknown id: 'abc123'"}],
    }


@pytest.mark.asyncio
async def test_apply_verdicts_round_trips_a_fresh_posting():
    db = _mock_db({"_id": FULL_ID, "judged": False})

    result = await apply_verdicts(db, [_verdict()])

    assert result.applied == 1
    assert result.rejected == []
    db.postings.update_one.assert_awaited_once()
    set_fields = db.postings.update_one.call_args.args[1]["$set"]
    assert set_fields["judged"] is True
    assert set_fields["verdict"] == "apply"
    db.verdicts.update_one.assert_awaited_once()


@pytest.mark.asyncio
async def test_apply_verdicts_rejects_unknown_id_without_losing_others():
    db = MagicMock()
    db.postings = MagicMock()
    db.postings.find_one = AsyncMock(side_effect=[None, {"_id": FULL_ID, "judged": False}])
    db.postings.update_one = AsyncMock()
    db.verdicts = MagicMock()
    db.verdicts.update_one = AsyncMock()

    unknown_id = "c" * 64
    verdicts = [_verdict(id=unknown_id), _verdict(id=FULL_ID)]

    result = await apply_verdicts(db, verdicts)

    assert result.applied == 1
    assert len(result.rejected) == 1
    assert result.rejected[0].id == unknown_id
    assert "unknown id" in result.rejected[0].reason


@pytest.mark.asyncio
async def test_apply_verdicts_refuses_to_overwrite_without_force():
    db = _mock_db({"_id": FULL_ID, "judged": True, "verdict": "skip"})

    result = await apply_verdicts(db, [_verdict()])

    assert result.applied == 0
    assert "already judged" in result.rejected[0].reason
    db.postings.update_one.assert_not_awaited()


@pytest.mark.asyncio
async def test_apply_verdicts_force_overwrites_existing_verdict():
    db = _mock_db({"_id": FULL_ID, "judged": True, "verdict": "skip"})

    result = await apply_verdicts(db, [_verdict()], force=True)

    assert result.applied == 1
    assert result.rejected == []


@pytest.mark.asyncio
async def test_apply_verdicts_rejects_duplicate_id_within_file():
    db = _mock_db({"_id": FULL_ID, "judged": False})

    result = await apply_verdicts(db, [_verdict(), _verdict()])

    assert result.applied == 1
    assert len(result.rejected) == 1
    assert "duplicate id in this file" in result.rejected[0].reason
