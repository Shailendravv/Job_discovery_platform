# Documentation Index

This file is the lookup table for `backend/docs/`. Check here before creating or searching for any doc — this is the only file an agent should need to read to know whether a doc already exists for a given piece of code.

Keep this list alphabetical by file name. Every doc file in this directory must have a row here.

| File | Covers (source paths) | Status | Last verified |
|---|---|---|---|---|
| ats_optimization.md | backend/app/services/ats_keywords.py, backend/app/services/ats_scoring.py, backend/app/services/ats_location.py, backend/app/services/html_renderer.py, backend/templates/cv-template.html, backend/static/fonts/ | active | 2026-07-01 |
| jobs.md | backend/app/api/v1/jobs.py, backend/app/services/db_service.py, backend/app/models/job.py | active | 2026-06-28 |
| payments-refunds.md | backend/payments/refunds/ | active | 2026-06-01 |
| resume.md | backend/app/api/v1/resumes.py, backend/app/models/resume.py, backend/app/services/db_service.py | active | 2026-06-28 |
| tailor_structured.md | backend/app/api/v1/resumes.py, backend/app/services/structured_tailor.py, backend/app/services/pii_service.py, backend/app/services/llm/, backend/app/services/cover_letter.py, backend/app/services/html_service.py, backend/app/services/cloudinary_service.py, backend/app/services/db_service.py, backend/app/models/resume.py | active | 2026-06-28 |

## Rules for this file
- Add a row whenever you create a doc.
- Remove a row whenever you delete or merge a doc.
- `Covers` should list the source directories/files the doc describes — used for matching code changes to docs.
- `Status` is `active` or `deprecated`. Deprecated docs should be merged or removed, not left in this state long-term.
- `Last verified` updates any time someone confirms the doc still matches the code, even without a content change.
