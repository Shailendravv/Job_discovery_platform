"""Rendering postings for the judging agent — PLAN.md §3 "``jobctl next``
output format": markdown, one posting per section, description truncated to
~1200 characters, id included so verdicts map back."""

from datetime import datetime

DESCRIPTION_TRUNCATE_CHARS = 1200


def truncate_description(text: str, limit: int = DESCRIPTION_TRUNCATE_CHARS) -> str:
    text = text or ""
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def render_posting_md(doc: dict, display_id: str) -> str:
    """One ``## [id] Title — Company`` section, per PLAN.md §3's example:

        ## [a3f9c1] Backend Engineer, Payments — Stripe
        Location: Bangalore (hybrid) · Posted 2026-09-05 · greenhouse
        URL: https://...

        <description>
    """
    location = doc.get("location") or "n/a"
    remote_suffix = " (remote)" if doc.get("remote_flag") else ""

    posted_at = doc.get("posted_at")
    posted_str = posted_at.date().isoformat() if isinstance(posted_at, datetime) else "unknown"

    description = truncate_description(doc.get("description_text") or "")

    return (
        f"## [{display_id}] {doc.get('title', '')} — {doc.get('company_name', '')}\n"
        f"Location: {location}{remote_suffix} · Posted {posted_str} · {doc.get('provider', '')}\n"
        f"URL: {doc.get('url', '')}\n\n"
        f"{description}\n"
    )


def render_posting_summary(doc: dict, display_id: str) -> dict:
    """The JSON-list shape used by ``list``/``next --format json`` and
    ``show`` — same fields, truncated description, plus the display id so
    the caller can pass it straight back to ``show``/``judge``."""
    return {
        "id": display_id,
        "full_id": doc.get("_id"),
        "title": doc.get("title"),
        "company_name": doc.get("company_name"),
        "location": doc.get("location"),
        "remote_flag": doc.get("remote_flag"),
        "provider": doc.get("provider"),
        "org": doc.get("org"),
        "url": doc.get("url"),
        "posted_at": doc.get("posted_at"),
        "first_seen_at": doc.get("first_seen_at"),
        "judged": doc.get("judged", False),
        "verdict": doc.get("verdict"),
        "description_text": truncate_description(doc.get("description_text") or ""),
    }
