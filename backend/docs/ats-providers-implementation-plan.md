# ATS Provider Implementation

## Overview

Direct ATS API job providers (Greenhouse, Ashby, Lever, Workday) integrated into the existing job search pipeline. Providers fetch structured JSON directly from public ATS APIs — no LLM extraction needed, zero browsing cost.

### Goals

- Add ATS jobs as a third data source alongside SearXNG and LinkedIn
- Merge into the existing `POST /search` endpoint (frontend sends only `user_input`)
- Configure tracked companies in a YAML file with auto-detection (providers are resolved by URL pattern matching)
- Zero LLM tokens for ATS data collection

---

## File Structure

```
backend/app/agents/ats_providers/
├── __init__.py              # Exports AtsProvider base, triggers auto-registration
├── base.py                  # AtsProvider ABC: id, detect(), fetch() + auto-registry
├── _http.py                 # Shared HTTP utilities (fetch_json, fetch_text, fetch_with_retry)
├── greenhouse.py            # Greenhouse provider
├── ashby.py                 # Ashby provider (compensation parsing + location aggregation)
├── lever.py                 # Lever provider (with descriptionPlain)
└── workday.py               # Workday provider (POST-based paginated API)

backend/config/
└── ats_companies.yml        # YAML config for tracked companies (4 example companies)

backend/app/agents/
└── ats_workflow.py          # scan_ats_companies() — orchestrates all ATS providers

backend/app/agents/
└── job_workflow.py          # (modified) Phase 1c integration in search_jobs_workflow()
```

---

## Provider Contract (`ats_providers/base.py`)

Every provider extends `AtsProvider` and registers automatically via `__init_subclass__`:

```python
class AtsProvider(ABC):
    id: str  # "greenhouse", "ashby", "lever", "workday"

    # Auto-registry — subclasses register via __init_subclass__
    _registry: dict[str, type["AtsProvider"]] = {}

    @classmethod
    def get_providers(cls) -> list["AtsProvider"]:
        """Instantiate all registered providers in fixed order:
        greenhouse → lever → ashby → workday"""

    @abstractmethod
    def detect(self, company: dict) -> str | None:
        """Match company config to this provider via URL regex.
        Returns API URL string or None if no match."""

    @abstractmethod
    async def fetch(self, company: dict, api_url: str) -> list[dict]:
        """Fetch jobs from the ATS API.
        Returns list of normalized job dicts matching JobResult shape."""
```

**Registration mechanism:** Instead of a manual registry, `__init_subclass__` automatically adds each subclass to `AtsProvider._registry` keyed by `cls.id`. The `__init__.py` imports all four provider modules to trigger registration, then `get_providers()` returns instances in detection-priority order.

---

## Provider Implementations

### 1. Greenhouse (`greenhouse.py`)

| Aspect | Detail |
|--------|--------|
| **URL pattern** | `job-boards.greenhouse.io/{slug}`, `job-boards.eu.greenhouse.io/{slug}`, `boards.greenhouse.io/{slug}` |
| **API endpoint** | `GET https://boards-api.greenhouse.io/v1/boards/{slug}/jobs` |
| **Response shape** | `{ jobs: [...] }` |
| **Job fields** | `title`, `absolute_url`, `location.name`, `first_published` |
| **Security** | Host allowlist (`boards-api.greenhouse.io`, `boards.greenhouse.io`, `job-boards.greenhouse.io`, `job-boards.eu.greenhouse.io`), HTTPS enforced, redirects blocked via `redirect="error"` |
| **Explicit API URL** | Supports `api` field in YAML config to bypass auto-detection |

### 2. Ashby (`ashby.py`)

| Aspect | Detail |
|--------|--------|
| **URL pattern** | `jobs.ashbyhq.com/{slug}` |
| **API endpoint** | `GET https://api.ashbyhq.com/posting-api/job-board/{slug}?includeCompensation=true` |
| **Response shape** | `{ jobs: [...] }` |
| **Job fields** | `title`, `jobUrl`, `location`, `secondaryLocations[]`, `compensation` (minValue, maxValue, currency, interval), `publishedAt` |
| **Special handling** | 30s timeout (API has ~10s+ latency), 2 retries with exponential backoff + jitter (`fetch_with_retry`), secondary location aggregation via `_format_location()`, salary annualization + formatting via `_parse_compensation()` |

**Compensation parsing** (`_parse_compensation`): Returns a formatted string like `"USD $150,000 - $200,000"` or `None`. Supports all intervals (hourly → 2080x, daily → 260x, weekly → 52x, monthly → 12x, yearly → 1x). Min/max ordering is enforced (corrects swapped values). `_fmt_salary()` formats numbers like `150000 → "$150,000"`.

**Location aggregation** (`_format_location`): Folds `secondaryLocations[].location`, `address.postalAddress.addressLocality`, and `address.postalAddress.addressCountry` into a single deduplicated string joined by `" · "`.

### 3. Lever (`lever.py`)

| Aspect | Detail |
|--------|--------|
| **URL pattern** | `jobs.lever.co/{slug}` |
| **API endpoint** | `GET https://api.lever.co/v0/postings/{slug}` |
| **Response shape** | Bare JSON array (no wrapper object) — handled by `isinstance(json_data, list)` check |
| **Job fields** | `text`, `hostedUrl`, `categories.location`, `descriptionPlain`, `createdAt` (epoch ms) |
| **Key differentiator** | Only provider that supplies `descriptionPlain` for free — enables content-level filtering without an extra request |

### 4. Workday (`workday.py`)

| Aspect | Detail |
|--------|--------|
| **URL pattern** | `https://{tenant}.{instance}.myworkdayjobs.com/{site}` (optional locale segment: `/{locale}/{site}`) |
| **API endpoint** | `POST {origin}/wday/cxs/{tenant}/{site}/jobs` |
| **Request body** | `{ limit: 20, offset: <page*20>, searchText: "", appliedFacets: {} }` |
| **Response shape** | `{ jobPostings: [...] }` |
| **Job fields** | `title`, `externalPath`, `locationsText`, `postedOn` (relative label) |
| **Special handling** | Paginated (20 results/page, max 50 pages = 1000 posting safety cap), relative date parsing via `_parse_posted_on()` |

**Date parsing** (`_parse_posted_on`):
- `"Posted Today"` → `Date.now()` (epoch ms)
- `"Posted Yesterday"` → `now - 86,400,000 ms`
- `"Posted {N} Days Ago"` (no `+`) → `now - N * 86,400,000 ms`
- `"Posted 30+ Days Ago"` (has `+`) → `None` (unbounded, omitted)
- Any other format → `None`

---

## HTTP Layer (`_http.py`)

Shared async HTTP utilities used by all providers:

```python
async def fetch_json(url, *, timeout_ms=10000, method="GET", body=None, headers=None, redirect="follow")
async def fetch_text(url, *, timeout_ms=10000, method="GET", body=None, headers=None, redirect="follow")
async def fetch_with_retry(url, *, timeout_ms=10000, retries=2, method="GET", body=None, headers=None, redirect="follow")
```

- **Default timeout**: 10s (configurable per call via `timeout_ms`)
- **User-Agent**: `Mozilla/5.0 (compatible; job-app-ats/1.0)`
- **SSRF protection**: `redirect="error"` prevents following redirects
- **Retry**: Exponential backoff `1000 * 2^(n-1)` + random jitter `[0, 500]` ms
- **Supports**: GET and POST methods with custom headers and body

---

## Configuration (`ats_companies.yml`)

```yaml
# ATS companies configuration.
# Providers are auto-detected from the URL pattern in this order:
# greenhouse -> lever -> ashby -> workday.
# Set enabled: false to skip a company.
# Greenhouse companies can optionally set an explicit ``api`` URL.

ats_companies:
  - name: Anthropic
    careers_url: https://job-boards.greenhouse.io/anthropic
    enabled: true

  - name: Mistral AI
    careers_url: https://jobs.lever.co/mistral
    enabled: true

  - name: Cohere
    careers_url: https://jobs.ashbyhq.com/cohere
    enabled: true

  - name: 23andMe
    careers_url: https://23andme.wd5.myworkdayjobs.com/23
    enabled: true
```

**Auto-detection logic:** Providers are checked in order (greenhouse → lever → ashby → workday). Each provider's `detect()` runs a regex against `careers_url`. The first match wins. No need to specify `provider:` explicitly.

**Path resolution** (`ats_workflow.py`): The config file path is resolved relative to the `ats_workflow.py` file location, going up 3 directory levels to the project root and joining with `config/ats_companies.yml`.

---

## Orchestrator (`ats_workflow.py`)

```python
async def scan_ats_companies(user_input: str | None = None) -> list[dict]:
    """Fetch all jobs from all configured ATS companies.

    Parameters
    ----------
    user_input : str or None
        The user's search query. Used for relevance filtering.
        If None, all jobs are returned unfiltered.

    Returns
    -------
    list[dict]
        Normalised job results with keys matching JobResult.
    """
    companies = _load_ats_companies()   # parse YAML (with missing/malformed handling)
    providers = _load_providers()       # AtsProvider.get_providers()

    for company in companies:
        if not company.get("enabled", True):
            continue

        for provider in providers:
            try:
                api_url = provider.detect(company)
                if not api_url:
                    continue
                matched = True
                jobs = await provider.fetch(company, api_url)
                all_jobs.extend(jobs)
                break
            except Exception as e:
                log.warning("[ats] %s/%s failed: %s", provider.id, company["name"], e)

    if user_input:
        return _filter_by_relevance(all_jobs, user_input)

    return all_jobs
```

**Key differences from original plan:**
- `scan_ats_companies()` accepts an optional `user_input` parameter for relevance filtering
- Providers are instantiated via the auto-registration registry rather than manual imports
- The try/except wraps both `detect()` and `fetch()` to handle API errors gracefully
- `matched` flag logs when no provider matched a company's URL

### Relevance Filtering

Since ATS APIs return ALL jobs from a company (no keyword search), filter by `user_input`:

```python
def _filter_by_relevance(jobs: list[dict], user_input: str) -> list[dict]:
    keywords = _extract_keywords(user_input)  # lowercase, split, remove stop words
    scored = []

    for job in jobs:
        score = 0
        title = (job.get("title") or "").lower()
        company = (job.get("company") or "").lower()
        location = (job.get("location") or "").lower()
        description = (job.get("description") or "").lower()

        for kw in keywords:
            if kw in title:        score += 3
            if kw in company:      score += 1
            if kw in location:     score += 1
            if kw in description:  score += 2

        if score > 0:
            scored.append((score, job))

    scored.sort(key=lambda x: -x[0])
    return [job for _, job in scored]
```

**Keyword extraction** (`_extract_keywords`): Uses `re.split(r"\W+", ...)` to tokenize, filters out stop words (90+ common English words) and single-character tokens.

**Note:** `"ai"` is a substring of words like `"mountain"`, `"train"`, `"detail"` etc., so short keywords may produce false-positive matches at low scores. Jobs with higher scores (multiple keyword hits in title/description) rank correctly.

---

## Integration into `search_jobs_workflow`

Phase 1c is inserted in `backend/app/agents/job_workflow.py` between Phase 1a (SearXNG) and Phase 1b (LinkedIn):

```
Existing flow:
  Phase 0:  Build search queries from user_input
  Phase 1a: SearXNG search → URLs
  Phase 1b: LinkedIn search → URLs
  Phase 2:  Browse & extract details from each URL (LLM)

Updated flow:
  Phase 0:  Build search queries from user_input
  Phase 1a: SearXNG search → URLs
  Phase 1c: ATS API direct fetch (zero-LLM)
    ├── Load ats_companies.yml
    ├── Resolve providers via detect()
    ├── Fetch all jobs from each company's ATS API
    ├── Filter by relevance to user_input (keyword matching)
    └── Deduplicate by URL against SearXNG results
  Phase 1b: LinkedIn search → URLs
  Phase 2:  Browse & extract (SearXNG/LI only — ATS data is already structured)
  Phase 3:  Merge, dedup titles, save to MongoDB, return
```

**Key integration details:**

1. **Import:** `from app.agents.ats_workflow import scan_ats_companies`
2. **ATS dedup:** ATS URLs are checked against `searxng_seen_urls` set (ATS data is higher quality, so it gets priority — if an ATS URL matches a SearXNG URL, the ATS version is kept and the URL is reserved so SearXNG dedup skips it)
3. **No LLM browsing:** ATS jobs bypass `_browse_and_build()` (Phase 2) since they're already structured — they go directly into `JobResult.model_dump()`
4. **Title dedup:** ATS jobs participate in the shared `final_seen_titles` list for cross-source title dedup
5. **Merge order:** ATS jobs are placed first in the final merge (`ats_structured + searxng_jobs + linkedin_jobs`) since they have the highest data quality

### ATS Job Construction

```python
ats_structured.append(JobResult(
    title=title,
    company=job["company"],
    location=job.get("location"),
    description=description,
    url=url,
    skills=extract_skills_from_text(description) if description else [],
    job_type="unknown",
    posted_date=str(job.get("posted_date")) if job.get("posted_date") else None,
    salary=job.get("salary"),
    source=job.get("source"),  # "greenhouse", "lever", "ashby", or "workday"
).model_dump())
```

---

## Data Flow Summary

```
User → POST /search { "user_input": "AI engineer remote" }
                            │
                            ▼
                  search_jobs_workflow()
                      │
                      ├── Phase 0: Build queries (LLM)
                      │
                      ├── Phase 1a: SearXNG search → URLs
                      │
                      ├── Phase 1c (NEW): ATS API fetch (zero-LLM, zero-browse)
                      │     ├── Load ats_companies.yml
                      │     ├── Auto-detect providers (regex match in order)
                      │     ├── Fetch all jobs from each ATS
                      │     └── Filter by relevance to user_input
                      │
                      ├── Phase 1b: LinkedIn search → URLs
                      │
                      ├── Phase 2: Browse & extract (SearXNG + LinkedIn only)
                      │
                      └── Phase 3: Merge ATS + SearXNG + LinkedIn, dedup by title,
                                    save to MongoDB, return
```

---

## Edge Cases & Considerations

| Consideration | Handling |
|---------------|----------|
| **ATS rate limits** | Ashby: 30s timeout + 2 retries with exponential backoff + jitter. Others: 10s default timeout |
| **No keyword search in ATS APIs** | Keyword-based relevance filter on title/company/location/description |
| **Stale jobs** | Use `posted_date` (epoch ms) where available (Greenhouse `first_published`, Ashby `publishedAt`, Lever `createdAt`). Workday: only relative labels via `_parse_posted_on()` |
| **SSRF protection** | Validate hostnames against allowlists (Greenhouse), enforce HTTPS, block redirects via `redirect="error"` |
| **Dedup** | URL-based against SearXNG results. Title-based across all sources (fuzzy match > 0.95). ATS jobs have higher data quality (no LLM extraction artifacts) so they take priority |
| **Empty YAML config** | If no companies configured or file missing/malformed, `_load_ats_companies()` returns empty list, Phase 1c is skipped silently with a log message |
| **Per-provider timeouts** | `_http.py` accepts `timeout_ms` parameter per call. `fetch_with_retry()` supports per-call retry count |
| **Company not matched** | If no provider's `detect()` matches a company's URL, it's logged and skipped — no crash |
| **Provider fetch failure** | Errors in `fetch()` are caught per-provider, logged, and the next provider is tried (allows fallback) |
| **Auto-registration** | Adding a new provider = drop a new `.py` file in `ats_providers/` that extends `AtsProvider` with `id` set, then import it in `__init__.py` |

---

## Provider API Reference

| ATS | URL Pattern | API Endpoint | Response Shape | Auth | Key Fields |
|-----|------------|-------------|----------------|------|-----------|
| **Greenhouse** | `job-boards.greenhouse.io/{slug}` | `GET boards-api.greenhouse.io/v1/boards/{slug}/jobs` | `{ jobs: [...] }` | None | `title`, `absolute_url`, `location.name`, `first_published` |
| **Ashby** | `jobs.ashbyhq.com/{slug}` | `GET api.ashbyhq.com/posting-api/job-board/{slug}?includeCompensation=true` | `{ jobs: [...] }` | None | `title`, `jobUrl`, `location`, `secondaryLocations[]`, `compensation`, `publishedAt` |
| **Lever** | `jobs.lever.co/{slug}` | `GET api.lever.co/v0/postings/{slug}` | Bare `[...]` array | None | `text`, `hostedUrl`, `categories.location`, `descriptionPlain`, `createdAt` |
| **Workday** | `{tenant}.{instance}.myworkdayjobs.com/{site}` | `POST {origin}/wday/cxs/{tenant}/{site}/jobs` | `{ jobPostings: [...] }` | None | `title`, `externalPath`, `locationsText`, `postedOn` |

---

## Adding a New Provider

1. Create `backend/app/agents/ats_providers/new_provider.py`
2. Extend `AtsProvider` with `id = "new_provider"` and implement `detect()` + `fetch()`
3. Add `from app.agents.ats_providers import new_provider  # noqa: F401` in `__init__.py`
4. Add its `id` to the `order` list in `AtsProvider.get_providers()` in `base.py`
5. Add example companies to `ats_companies.yml`

No other changes needed — the orchestrator discovers all providers via the auto-registration registry.
