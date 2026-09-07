"""ATS ingestion layer — normalize, dedupe, and store postings from
``app.agents.ats_providers`` into the ``postings`` collection.

See ``backend/docs/ingest.md`` for the full design and
``PLAN.md`` §2 for the original spec (registry deviation noted there).
"""
