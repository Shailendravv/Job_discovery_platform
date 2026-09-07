"""normalize_posting() — including the length-cap regression found while
running the first full ingest at scale: Ashby's folded secondary-location
string can exceed the ``postings.location`` schema cap (500 chars) and
abort the whole bulk write if not truncated first."""

from app.ingest.normalize import normalize_posting
from app.ingest.registry import Source


def _source(**overrides) -> Source:
    defaults = dict(name="Acme", org="acme", careers_url="https://jobs.ashbyhq.com/acme",
                     provider_id="ashby", api_url="https://api.ashbyhq.com/x")
    defaults.update(overrides)
    return Source(**defaults)


def test_normalize_returns_none_for_missing_required_fields():
    raw = {"provider_job_id": "1", "title": "", "url": "https://x"}
    assert normalize_posting(raw, _source()) is None

    raw2 = {"provider_job_id": "", "title": "Engineer", "url": "https://x"}
    assert normalize_posting(raw2, _source()) is None


def test_normalize_truncates_overlong_location():
    huge_location = "Remote - " + ", ".join(f"State{i}" for i in range(200))
    assert len(huge_location) > 500

    raw = {"provider_job_id": "1", "title": "Engineer", "url": "https://x", "location": huge_location}
    posting = normalize_posting(raw, _source())

    assert posting is not None
    assert len(posting.location) <= 500
    assert posting.location.endswith("…")


def test_normalize_truncates_overlong_title_and_company_name():
    raw = {"provider_job_id": "1", "title": "T" * 400, "url": "https://x"}
    posting = normalize_posting(raw, _source(name="C" * 300))

    assert posting is not None
    assert len(posting.title) <= 300
    assert len(posting.company_name) <= 200


def test_normalize_employment_type_vocabulary():
    raw = {"provider_job_id": "1", "title": "Engineer", "url": "https://x", "employment_type": "FULLTIME"}
    posting = normalize_posting(raw, _source())
    assert posting.employment_type == "full-time"


def test_normalize_uses_deterministic_id():
    raw = {"provider_job_id": "42", "title": "Engineer", "url": "https://x"}
    posting = normalize_posting(raw, _source(provider_id="ashby", org="acme"))
    posting2 = normalize_posting(raw, _source(provider_id="ashby", org="acme"))
    assert posting.id == posting2.id
