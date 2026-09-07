"""Rendering for ``jobctl next``/``list`` — PLAN.md §3's markdown format and
the ~1200-char description truncation."""

from datetime import datetime, timezone

from app.ingest.format import (
    DESCRIPTION_TRUNCATE_CHARS,
    render_posting_md,
    render_posting_summary,
    render_shortlist_entry,
    truncate_description,
)


def test_truncate_leaves_short_text_untouched():
    assert truncate_description("short") == "short"


def test_truncate_caps_long_text_with_ellipsis():
    text = "x" * 2000
    result = truncate_description(text)
    assert len(result) == DESCRIPTION_TRUNCATE_CHARS
    assert result.endswith("…")


def test_truncate_handles_missing_text():
    assert truncate_description("") == ""
    assert truncate_description(None) == ""


def test_render_posting_md_includes_id_title_company_and_url():
    doc = {
        "title": "Backend Engineer, Payments",
        "company_name": "Stripe",
        "location": "Bangalore",
        "remote_flag": True,
        "provider": "greenhouse",
        "url": "https://example.com/job/1",
        "posted_at": datetime(2026, 9, 5, tzinfo=timezone.utc),
        "description_text": "Build payment systems.",
    }
    rendered = render_posting_md(doc, "a3f9c1")

    assert "## [a3f9c1] Backend Engineer, Payments — Stripe" in rendered
    assert "Bangalore (remote)" in rendered
    assert "2026-09-05" in rendered
    assert "greenhouse" in rendered
    assert "https://example.com/job/1" in rendered
    assert "Build payment systems." in rendered


def test_render_posting_md_handles_missing_optional_fields():
    doc = {"title": "Role", "company_name": "Acme", "url": "https://acme.example/job"}
    rendered = render_posting_md(doc, "abc123")
    assert "n/a" in rendered
    assert "unknown" in rendered  # posted date


def test_render_posting_summary_shape():
    doc = {
        "_id": "full-id-123",
        "title": "Role",
        "company_name": "Acme",
        "judged": True,
        "verdict": "apply",
        "description_text": "x" * 2000,
    }
    summary = render_posting_summary(doc, "abc123")
    assert summary["id"] == "abc123"
    assert summary["full_id"] == "full-id-123"
    assert summary["judged"] is True
    assert summary["verdict"] == "apply"
    assert len(summary["description_text"]) == DESCRIPTION_TRUNCATE_CHARS


def test_render_shortlist_entry_merges_verdict_and_joined_posting():
    verdict_doc = {
        "_id": "full-id-456",
        "verdict": "apply",
        "score": 9,
        "reasons": ["strong stack match"],
        "missing_requirements": [],
        "judged_at": datetime(2026, 9, 6, tzinfo=timezone.utc),
        "posting": {
            "title": "Backend Engineer",
            "company_name": "Stripe",
            "location": "Bangalore",
            "provider": "greenhouse",
            "url": "https://example.com/job/1",
        },
    }
    entry = render_shortlist_entry(verdict_doc, "a3f9c1")

    assert entry["id"] == "a3f9c1"
    assert entry["full_id"] == "full-id-456"
    assert entry["title"] == "Backend Engineer"
    assert entry["company_name"] == "Stripe"
    assert entry["score"] == 9
    assert entry["verdict"] == "apply"
    assert entry["reasons"] == ["strong stack match"]


def test_render_shortlist_entry_handles_missing_posting_subdocument():
    entry = render_shortlist_entry({"_id": "x", "verdict": "maybe", "score": 7}, "abc")
    assert entry["title"] is None
    assert entry["reasons"] == []
    assert entry["missing_requirements"] == []
