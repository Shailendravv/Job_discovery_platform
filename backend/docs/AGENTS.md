# AGENTS.md

## Mandatory Workflow
Read this file at the start of every session. Follow it for the entire session — not just the first turn.

## Source of Truth
- The codebase is the source of truth.
- Documentation describes the code. The code is never changed to match documentation.
- If documentation and code disagree, trust the code, then fix the documentation.

## Documentation Location
- All documentation lives in `backend/docs/`.
- `backend/documentation/` is deprecated. Do not create or edit anything there — if you find content there, it's a migration target, not a place to work.
- Do not create any other documentation directory.

## Before Creating or Touching Any Doc
1. Open `backend/docs/INDEX.md` first. It lists every doc file, the source paths it covers, and when it was last checked.
2. Match the code you're changing against the `covers` paths in the index. Use the index — don't guess a filename from memory or rely on search.
3. If nothing in the index covers this code, it's a new doc. Add it to the index when you create it.

## Naming Convention
- One file per feature/module, named after the **module path it documents**, not a description of the feature.
  - `backend/payments/refunds/` → `backend/docs/payments-refunds.md`
- Never create alternate names for the same thing (`auth.md`, `authentication.md`, `auth-flow.md`). If unsure whether a doc exists, check the index — don't create one "just in case."
- No scratch files in this directory: `NOTES.md`, `PLAN.md`, `SUMMARY.md`, `CHANGES.md`, `TODO.md` do not belong here. Keep working notes outside the repo, or delete them before finishing the task.

## Doc File Format
Use `backend/docs/DOC_TEMPLATE.md` as the structure for every doc — copy it when creating a new one. It separates content that changes with the code (current behavior, file paths) from content that doesn't (rationale, intent), so an edit usually touches one section instead of the whole file.

Every doc starts with frontmatter:
```yaml
---
covers: [backend/payments/refunds/]
last_verified: <date or commit hash you checked this against>
status: active
---
```
Update `last_verified` whenever you confirm or change the content — even if the text didn't change.

## Documentation Maintenance

**Modifying an existing feature:**
1. Find the doc via `INDEX.md`.
2. Update it to match the new implementation.
3. Delete anything no longer true — rewrite the section, don't append an "Update (date):" note on top of stale text.
4. Update `last_verified`.

**Creating a new feature:**
1. Check `INDEX.md` first.
2. If a doc already covers this area, extend it.
3. If not, create one file and add it to `INDEX.md`.

## Recovery: When You Find Conflicting or Stale Docs
This will come up while cleaning up existing code. When it does:
1. Don't trust any existing doc's content. Read the actual implementation first — that's the ground truth for whatever you're working on, regardless of what any doc claims.
2. Compare each candidate doc's last-modified date against the source it claims to cover (`git log -1 --format=%ai -- <path>`). If the source is newer than every candidate, treat all of them as stale — don't try to determine which one is "more right."
3. Salvage only what doesn't depend on implementation detail: rationale, intent, constraints still true today. Rewrite anything describing current behavior from the code, not from the old docs.
4. Write one new file using `DOC_TEMPLATE.md`, replacing every old candidate.
5. List the files you're about to delete and wait for confirmation before deleting them. Update `INDEX.md`.

## Before Finishing Any Task
- List every doc file you created or edited.
- Cross-check `INDEX.md` to confirm none of them duplicate an existing doc.
- Update `INDEX.md` if the doc set changed.
- Report this list to the user as part of your summary.

## Completion Checklist
- [ ] Code updated
- [ ] Corresponding doc found via `INDEX.md` (not created blind)
- [ ] Doc content matches current implementation, stale parts removed
- [ ] `last_verified` updated
- [ ] No new doc directory, no duplicate doc, no scratch file left behind
- [ ] `INDEX.md` updated if the doc set changed
