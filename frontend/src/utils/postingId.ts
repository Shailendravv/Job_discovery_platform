// A posting's id is the deterministic sha256 digest minted by
// `posting_id()` in backend/app/ingest/models.py — 64 lowercase hex chars,
// always. Anything else can never match a row, so the client can reject it
// without a round trip.
//
// This exists because such ids do reach us: the Dashboard used to link to
// `/jobs/${job.id || idx}`, so rows with a missing id produced row-index
// URLs (/jobs/9, /jobs/0). The fallback is gone, but those URLs live on in
// open tabs, history and bookmarks.
const POSTING_ID_RE = /^[0-9a-f]{64}$/;

export const isPostingId = (value: string | undefined | null): value is string =>
  !!value && POSTING_ID_RE.test(value);
