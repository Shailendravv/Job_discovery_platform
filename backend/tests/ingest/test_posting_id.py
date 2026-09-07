"""posting_id() determinism is what makes re-ingestion idempotent
(PLAN.md §2 acceptance: second ``jobctl ingest`` run inserts ~0 rows)."""

from app.ingest.models import posting_id


def test_same_inputs_produce_same_id():
    a = posting_id("greenhouse", "stripe", "12345")
    b = posting_id("greenhouse", "stripe", "12345")
    assert a == b


def test_different_provider_job_id_produces_different_id():
    a = posting_id("greenhouse", "stripe", "12345")
    b = posting_id("greenhouse", "stripe", "67890")
    assert a != b


def test_different_org_produces_different_id():
    a = posting_id("greenhouse", "stripe", "12345")
    b = posting_id("greenhouse", "airbnb", "12345")
    assert a != b


def test_different_provider_produces_different_id():
    a = posting_id("greenhouse", "acme", "12345")
    b = posting_id("lever", "acme", "12345")
    assert a != b


def test_id_is_a_hex_sha256_digest():
    result = posting_id("greenhouse", "stripe", "12345")
    assert len(result) == 64
    int(result, 16)  # raises ValueError if not valid hex
