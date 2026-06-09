# Job Search & MCP Workflow Changes - 2026-06-09

**Date:** 2026-06-09
**Branch:** async_linkedin_and_scrapper_08_06_26
**Files Modified:** 3 core files

---

## Summary

Fixed critical bug where LinkedIn job search returned 0 results due to shared deduplication context with SearXNG. Enhanced logging configurability.

---

## Changes

### 1. backend/app/agents/job_workflow.py

**Issue:** LinkedIn API was returning 0 jobs even when enabled because its results were being deduplicated against SearXNG results before collection.

**Root Cause:** The `seen_urls` and `seen_titles` sets were shared between both search sources. When SearXNG ran first, it populated these sets. LinkedIn results with matching URLs (or titles 95%+ similar) were filtered out **before** being added to `linkedin_candidates`.

**Fix Applied:**

1. **Created new helper function `_collect_unique_urls_only()`** (lines 239-251)
   - Removed title-based deduplication entirely
   - Only deduplicates by `url` or `apply_url`
   - Simpler and more reliable

2. **Separated dedup contexts per source** (lines 327-331)
   ```python
   # OLD (shared):
   seen_urls: set = set()
   seen_titles: List[str] = []

   # NEW (independent):
   searxng_seen_urls: set = set()
   linkedin_seen_urls: set = set()
   ```

3. **Updated calls to use separate contexts** (lines 338, 349)
   - SearXNG: `_collect_unique_urls_only(batch, searxng_seen_urls)`
   - LinkedIn: `_collect_unique_urls_only(batch, linkedin_seen_urls)`

4. **Preserved final title dedup** (line 357)
   - `final_seen_titles` remains shared at browsing stage
   - Prevents identical job titles from both sources appearing in final output
   - This is the appropriate level for cross-source deduplication

**Why URL-only Dedup is Better:**

| Scenario | Old (Title+URL) | New (URL-only) |
|----------|-----------------|----------------|
| Same job, slightly different title | ❌ Dropped (false positive) | ✅ Kept |
| Different jobs, similar title | ✅ Kept | ✅ Kept |
| Same job from both sources | ✅ URL matches | ✅ URL matches |

**Impact:** LinkedIn now contributes its full quota independently. Both sources can populate their candidate pools without interfering with each other.

---

### 2. backend/app/core/config.py

**Changes:**

1. **Removed default `False` from `LINKEDIN_GUEST_API_ENABLED`** (line 31)
   ```python
   # OLD:
   LINKEDIN_GUEST_API_ENABLED: bool = (
       False  # Set to True to enable LinkedIn Guest API search results
   )

   # NEW:
   LINKEDIN_GUEST_API_ENABLED: bool
   ```
   - Now requires explicit environment variable or .env setting
   - Makes dependency on configuration explicit

2. **Added `LOG_LEVEL` setting** (line 37)
   ```python
   LOG_LEVEL: str = "INFO"
   ```
   - Allows runtime log level configuration via environment
   - Default: INFO

**Reasoning:** Making `LINKEDIN_GUEST_API_ENABLED` without a default forces conscious configuration decision. Added `LOG_LEVEL` to support dynamic log level changes without code modification.

---

### 3. backend/app/main.py

**Changes:**

1. **Imported `settings`** (line 5)
   ```python
   from app.core.config import settings
   ```

2. **Changed logging configuration** (lines 7-10)
   ```python
   # OLD:
   logging.basicConfig(
       level=logging.DEBUG,
       format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
   )

   # NEW:
   log_level = getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO)
   logging.basicConfig(
       level=log_level,
       format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
   )
   ```
   - Log level now read from `settings.LOG_LEVEL`
   - Defaults to INFO (configurable via env or .env)
   - Backwards compatible: can still override to DEBUG if needed

---

## Testing & Verification

### Quick Test Commands

```bash
# Check git diff confirms changes
git diff --stat

# Set environment variables (PowerShell)
$env:SEARXNG_ENABLED="true"
$env:LINKEDIN_GUEST_API_ENABLED="true"
$env:LOG_LEVEL="DEBUG"

# Or set in .env file in backend/ directory
echo "SEARXNG_ENABLED=true" >> backend/.env
echo "LINKEDIN_GUEST_API_ENABLED=true" >> backend/.env
```

### Expected Log Output

After fix and enabling both sources:

```
[workflow] searxng unique candidates: X
[workflow] linkedin raw results: Y
[workflow] linkedin unique after dedup: Y  <-- Should equal raw results (no cross-filtering)
[workflow] done — N jobs extracted (searxng=A, linkedin=B)  <-- B should be > 0
```

**Before fix:** `linkedin unique after dedup: 0` even when `raw results: 10`
**After fix:** `linkedin unique after dedup` should equal or nearly equal `raw results`

---

## Rollback Notes

If issues arise, the changes can be reverted:

- **job_workflow.py**: Restore shared `seen_urls`/`seen_titles` and `_collect_unique` function
- **config.py**: Restore `LINKEDIN_GUEST_API_ENABLED: bool = False`
- **main.py**: Restore hardcoded `logging.DEBUG`

---

## Related Files

- **API endpoint:** `backend/app/api/v1/jobs.py` - calls `search_jobs_workflow`
- **Search provider:** `backend/app/agents/search_provider.py` - contains LinkedIn API integration
- **Settings model:** `backend/app/core/config.py` - all configurable options
- **Existing workflow docs:**
  - `backend_job_search_and_mcp_workflow_08_06_26.md` (previous day)
  - `backend_job_search_and_mcp_workflow.md` (original design)

---

## Uncommitted Files as of 2026-06-09

```
modified:   backend/app/agents/job_workflow.py
modified:   backend/app/core/config.py
modified:   backend/app/main.py
untracked:  backend/document/my_doc.md
```

---

**Next Steps:**
1. Restart backend service with updated code
2. Ensure environment variables are set: `SEARXNG_ENABLED=true`, `LINKEDIN_GUEST_API_ENABLED=true`
3. Run test queries and verify `linkedin=B > 0` in final log
4. Check that log level can be changed via `LOG_LEVEL` env var
5. Commit changes with descriptive message
