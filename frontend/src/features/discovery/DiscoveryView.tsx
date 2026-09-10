import React, { useCallback, useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  Radar,
  CheckCircle2,
  ChevronRight,
  Clock,
  AlertCircle,
  Search,
  X,
  Building2,
  MapPin,
  ExternalLink,
  Info,
} from "lucide-react";
import { useApp } from "@/context/AppContext";
import { api, ApiError } from "@/services/api";
import type { IngestRunStatus, Posting } from "@/types";

type RunPhase = "idle" | "starting" | "running" | "done" | "error";

interface RunScope {
  role: string;
  window: string;
}

// How often the run-status endpoint is polled while a run is in flight. The
// backend updates the run document as each stage lands, so anything much
// faster than this just re-reads the same document.
const POLL_INTERVAL_MS = 2000;

// How long to wait after the last edit before re-filtering finished results.
// The window select would be fine firing immediately, but the role input
// shares this path and would otherwise issue a request per keystroke.
const FILTER_DEBOUNCE_MS = 400;

// Windows offered in the UI. The backend accepts any duration parse_duration
// understands ("30m", "2w", ...); these are the ones worth a button.
const WINDOWS = [
  { value: "24h", label: "Last 24 hours" },
  { value: "48h", label: "Last 48 hours" },
  { value: "7d", label: "Last 7 days" },
] as const;

// Human-readable names for the pipeline stages the runner reports. Anything
// not listed falls back to its raw name, so a new backend stage shows up
// rather than disappearing.
const STAGE_LABELS: Record<string, string> = {
  load_registry: "Load ATS registry",
  fetch: "Fetch from ATS connectors",
  dedupe: "Normalize & dedupe",
  store: "Store postings",
  prefilter: "Prefilter (rules)",
  score: "Score (deterministic)",
  total: "Total",
};

const formatDuration = (ms: number): string =>
  ms < 1000 ? `${Math.round(ms)} ms` : `${(ms / 1000).toFixed(1)} s`;

// The backend only writes elapsed_ms when the run finishes, so for a run
// still in flight we derive it from started_at — otherwise the timer would
// read 0 for exactly the minutes the user most wants to see it moving.
const elapsedOf = (run: IngestRunStatus, now: number): number => {
  if (run.status !== "running") return run.elapsed_ms;
  if (!run.started_at) return 0;
  // Mongo hands back a naive UTC timestamp; Date.parse would read it as
  // local time and produce a wildly wrong (often negative) elapsed.
  const startedUtc = run.started_at.endsWith("Z") ? run.started_at : `${run.started_at}Z`;
  return Math.max(0, now - new Date(startedUtc).getTime());
};

const formatPostedAt = (posting: Posting): string => {
  const raw = posting.posted_at || posting.first_seen_at;
  if (!raw) return "date unknown";
  const posted = new Date(raw);
  const hours = (Date.now() - posted.getTime()) / 3_600_000;
  if (hours < 1) return "just now";
  if (hours < 24) return `${Math.floor(hours)}h ago`;
  return `${Math.floor(hours / 24)}d ago`;
};

export const DiscoveryView: React.FC = () => {
  const navigate = useNavigate();
  const { triggerIngest } = useApp();

  const [role, setRole] = useState("");
  const [selectedWindow, setSelectedWindow] = useState<string>("24h");

  const [phase, setPhase] = useState<RunPhase>("idle");
  const [run, setRun] = useState<IngestRunStatus | null>(null);
  const [results, setResults] = useState<Posting[]>([]);
  const [error, setError] = useState<string | null>(null);
  // The broader role the backend fell back to when the exact query matched
  // nothing, or null on an exact match. Rendered rather than swallowed:
  // showing wider results as though they were exact is its own wrong answer.
  const [relaxedTo, setRelaxedTo] = useState<string | null>(null);

  // The scope the *running* session was started with — not the live input,
  // which the user may keep editing while the run is in flight. It is state
  // rather than a ref because the results header renders it.
  const [scope, setScope] = useState<RunScope>({ role: "", window: "24h" });
  const pollRef = useRef<number | null>(null);

  // Re-filtering keeps the current results on screen while it runs, so
  // without this the only feedback for changing the window would be the list
  // silently changing length a moment later.
  const [filtering, setFiltering] = useState(false);
  // Kept apart from `error`: that one is only rendered in the "error" phase,
  // which hides the results entirely. A filter that fails should leave the
  // postings you were already looking at alone.
  const [filterError, setFilterError] = useState<string | null>(null);
  // Guards against out-of-order responses — change the window twice quickly
  // and the first, slower GET must not overwrite the second one's results.
  const requestSeq = useRef(0);

  const stopPolling = useCallback(() => {
    if (pollRef.current !== null) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }
  }, []);

  // A run outlives this component's mount, so the interval has to be torn
  // down on unmount or it keeps polling a page nobody is looking at.
  useEffect(() => stopPolling, [stopPolling]);

  // Ticks the elapsed clock between polls. Only runs while a run is in
  // flight, so an idle or finished page re-renders no more than it must.
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (run?.status !== "running") return;
    const tick = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(tick);
  }, [run?.status]);

  const loadResults = useCallback(async (runScope: RunScope) => {
    const seq = ++requestSeq.current;
    // since_days is widened deliberately: it bounds when we first *saw* a
    // posting, while posted_within bounds when it was *posted*. A job
    // published an hour ago may have been in our corpus for a fortnight.
    const response = await api.getPostings({
      q: runScope.role || null,
      posted_within: runScope.window,
      since_days: 365,
      limit: 200,
    });
    if (seq !== requestSeq.current) return;
    setResults(response.postings);
    setRelaxedTo(response.role_relaxed_to ?? null);
  }, []);

  // `runScope` is passed in rather than read from state: this callback is
  // held by an interval created when the run started, so it must use the
  // scope of *that* run even if the user edits the inputs meanwhile.
  const poll = useCallback(
    async (runId: string, runScope: RunScope) => {
      try {
        const status = await api.getIngestRun(runId);
        setRun(status);

        if (status.status === "completed") {
          stopPolling();
          setPhase("done");
          await loadResults(runScope);
        } else if (status.status === "failed") {
          stopPolling();
          setPhase("error");
          setError(status.error || "The discovery run failed. Check the backend logs.");
        }
      } catch (err) {
        // A single failed poll is not a failed run — the run is happening in
        // the backend regardless. Only give up if the run itself is gone.
        if (err instanceof ApiError && err.status === 404) {
          stopPolling();
          setPhase("error");
          setError("That discovery run is no longer available.");
        }
      }
    },
    [loadResults, stopPolling],
  );

  // Once a run has produced results, the role and window inputs become live
  // filters over the corpus that run already stored. The backend deliberately
  // does not drop postings outside the window before storage and applies it
  // again at read time (runner.run_ingest), so narrowing or widening is a
  // re-GET — not another multi-minute crawl of every ATS source. Before this,
  // changing the window updated only the dropdown: nothing re-queried, and
  // the results header kept reporting the scope the run had started with.
  useEffect(() => {
    if (phase !== "done") return;

    const next: RunScope = { role: role.trim(), window: selectedWindow };
    if (next.role === scope.role && next.window === scope.window) return;

    const timer = setTimeout(() => {
      setFiltering(true);
      setScope(next);
      loadResults(next)
        .then(() => setFilterError(null))
        .catch((err) =>
          setFilterError(
            err instanceof ApiError ? err.message : "Could not re-filter the results.",
          ),
        )
        .finally(() => setFiltering(false));
    }, FILTER_DEBOUNCE_MS);

    return () => clearTimeout(timer);
  }, [role, selectedWindow, phase, scope.role, scope.window, loadResults]);

  const handleRunDiscovery = async () => {
    stopPolling();
    setPhase("starting");
    setError(null);
    setFilterError(null);
    setResults([]);
    setRelaxedTo(null);
    setRun(null);

    const runScope: RunScope = { role: role.trim(), window: selectedWindow };
    setScope(runScope);

    try {
      const runId = await triggerIngest({ role: runScope.role || null, window: runScope.window });
      setPhase("running");
      void poll(runId, runScope);
      pollRef.current = setInterval(() => void poll(runId, runScope), POLL_INTERVAL_MS);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to start the discovery run.");
      setPhase("error");
    }
  };

  const busy = phase === "starting" || phase === "running";

  return (
    <div
      className="animate-fade-in min-h-screen"
      style={{ background: "var(--color-background)", color: "var(--color-on-surface)" }}
    >
      {/* ── Hero + search ── */}
      <section className="flex flex-col items-center text-center pt-10 pb-8 px-6">
        <div className="max-w-2xl w-full">
          <h1
            className="text-4xl md:text-5xl font-extrabold tracking-tight mb-3"
            style={{ color: "var(--color-primary)" }}
          >
            Job Discovery
          </h1>
          <p className="text-base mb-8 font-medium" style={{ color: "var(--color-on-surface-variant)" }}>
            Search a role across every configured ATS company. Results are limited to
            jobs posted inside the window you pick — nothing older.
          </p>

          <div className="flex flex-col sm:flex-row gap-3 mb-4">
            <div className="relative flex-1">
              <Search
                className="absolute left-3.5 top-1/2 -translate-y-1/2 w-4 h-4"
                style={{ color: "var(--color-on-surface-variant)" }}
              />
              <input
                type="text"
                value={role}
                onChange={(e) => setRole(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && !busy) void handleRunDiscovery();
                }}
                placeholder="Role — e.g. backend engineer"
                disabled={busy}
                className="w-full h-14 pl-10 pr-10 rounded-2xl text-sm outline-none border transition-all disabled:opacity-60"
                style={{
                  background: "var(--color-surface)",
                  borderColor: "var(--color-outline-variant)",
                  color: "var(--color-on-surface)",
                }}
              />
              {role && !busy && (
                <button
                  onClick={() => setRole("")}
                  aria-label="Clear role"
                  className="absolute right-3 top-1/2 -translate-y-1/2 p-1 rounded-md transition-colors"
                  style={{ color: "var(--color-on-surface-variant)" }}
                >
                  <X className="w-4 h-4" />
                </button>
              )}
            </div>

            <select
              value={selectedWindow}
              onChange={(e) => setSelectedWindow(e.target.value)}
              disabled={busy}
              aria-label="Posted within"
              className="h-14 px-4 rounded-2xl text-sm font-medium outline-none border transition-all disabled:opacity-60"
              style={{
                background: "var(--color-surface)",
                borderColor: "var(--color-outline-variant)",
                color: "var(--color-on-surface)",
              }}
            >
              {WINDOWS.map((w) => (
                <option key={w.value} value={w.value}>
                  {w.label}
                </option>
              ))}
            </select>
          </div>

          <button
            onClick={handleRunDiscovery}
            disabled={busy}
            className="inline-flex items-center gap-2 h-14 px-8 rounded-2xl text-sm font-bold uppercase tracking-wider shadow transition-all active:scale-95 disabled:opacity-70 disabled:active:scale-100"
            style={{ background: "var(--color-primary)", color: "var(--color-on-primary)" }}
          >
            <Radar className={`w-5 h-5 ${busy ? "animate-spin" : ""}`} />
            {phase === "starting" ? "Starting…" : phase === "running" ? "Discovering…" : "Run Discovery"}
          </button>

          <p className="text-xs mt-3" style={{ color: "var(--color-on-surface-variant)" }}>
            Leave the role blank to fetch everything posted in the window.
          </p>
        </div>
      </section>

      {/* ── Error ── */}
      {phase === "error" && error && (
        <section className="max-w-2xl mx-auto mb-8 px-6">
          <div
            className="rounded-2xl p-6 border flex items-start gap-3"
            style={{ background: "#fff1f2", borderColor: "#fecdd3" }}
          >
            <AlertCircle className="w-5 h-5 shrink-0 mt-0.5" style={{ color: "#be123c" }} />
            <div className="text-left">
              <p className="text-sm font-bold mb-1" style={{ color: "#be123c" }}>
                Could not complete discovery
              </p>
              <p className="text-sm" style={{ color: "#e11d48" }}>{error}</p>
            </div>
          </div>
        </section>
      )}

      {/* ── Live run progress ── */}
      {run && (
        <section className="max-w-3xl mx-auto px-6 mb-8">
          <div
            className="rounded-2xl overflow-hidden border"
            style={{
              background: "var(--color-surface-container-lowest)",
              borderColor: "var(--color-outline-variant)",
            }}
          >
            <div
              className="p-4 border-b flex items-center justify-between gap-3 flex-wrap"
              style={{ borderColor: "var(--color-outline-variant)", background: "var(--color-surface)" }}
            >
              <div className="flex items-center gap-2">
                {run.status === "completed" ? (
                  <CheckCircle2 className="w-5 h-5" style={{ color: "#16a34a" }} />
                ) : (
                  <Clock className="w-5 h-5 animate-pulse" style={{ color: "var(--color-primary)" }} />
                )}
                <h3 className="text-base font-bold" style={{ color: "var(--color-primary)" }}>
                  {run.status === "completed" ? "Discovery complete" : "Discovery running"}
                </h3>
              </div>
              <span className="text-xs font-mono" style={{ color: "var(--color-on-surface-variant)" }}>
                run {run.run_id} · {formatDuration(elapsedOf(run, now))}
              </span>
            </div>

            <div className="p-6">
              <dl className="grid grid-cols-2 sm:grid-cols-4 gap-4 mb-6">
                {[
                  ["Sources", `${run.sources_ok} / ${run.sources_total}`],
                  ["Fetched", run.postings_fetched.toLocaleString()],
                  ["Posted in window", run.postings_fresh.toLocaleString()],
                  ["New", run.inserted.toLocaleString()],
                ].map(([label, value]) => (
                  <div key={label}>
                    <dt className="text-xs font-medium" style={{ color: "var(--color-on-surface-variant)" }}>
                      {label}
                    </dt>
                    <dd className="text-xl font-bold mt-0.5" style={{ color: "var(--color-primary)" }}>
                      {value}
                    </dd>
                  </div>
                ))}
              </dl>

              {run.stages.length === 0 && run.status === "running" && (
                <p className="text-sm" style={{ color: "var(--color-on-surface-variant)" }}>
                  Loading the ATS registry…
                </p>
              )}

              {run.stages.length > 0 && (
                <ul className="space-y-2">
                  {run.stages.map((stage) => (
                    <li
                      key={stage.name}
                      className="flex items-center justify-between gap-4 text-sm py-2 border-b last:border-b-0"
                      style={{ borderColor: "var(--color-outline-variant)" }}
                    >
                      <span className="flex items-center gap-2 font-medium">
                        <CheckCircle2 className="w-4 h-4 shrink-0" style={{ color: "#16a34a" }} />
                        {STAGE_LABELS[stage.name] ?? stage.name}
                      </span>
                      <span className="font-mono text-xs whitespace-nowrap" style={{ color: "var(--color-on-surface-variant)" }}>
                        {formatDuration(stage.duration_ms)} · {stage.count.toLocaleString()} items
                      </span>
                    </li>
                  ))}
                </ul>
              )}

              {run.status === "running" && (
                <p className="text-xs mt-4" style={{ color: "var(--color-on-surface-variant)" }}>
                  Fetching every configured ATS company — this takes a few minutes,
                  and the page keeps updating if you stay on it.
                </p>
              )}

              {run.sources_error > 0 && (
                <p className="text-xs mt-4" style={{ color: "var(--color-on-surface-variant)" }}>
                  {run.sources_error} source(s) errored and were skipped — the rest of the run was unaffected.
                </p>
              )}
            </div>
          </div>
        </section>
      )}

      {/* ── Results ── */}
      {phase === "done" && (
        <section className="max-w-3xl mx-auto px-6 pb-12">
          <div className="flex items-baseline justify-between gap-4 mb-4 flex-wrap">
            <h3 className="text-lg font-bold" style={{ color: "var(--color-primary)" }}>
              {filtering ? "Filtering…" : `${results.length} ${results.length === 1 ? "match" : "matches"}`}
            </h3>
            <p className="text-xs" style={{ color: "var(--color-on-surface-variant)" }}>
              {scope.role ? `“${scope.role}”` : "any role"} · posted within{" "}
              {WINDOWS.find((w) => w.value === scope.window)?.label.toLowerCase() ?? scope.window}
            </p>
          </div>

          {filterError && (
            <p className="text-xs mb-4" style={{ color: "#e11d48" }}>
              {filterError} — showing the previous results.
            </p>
          )}

          {relaxedTo && !filtering && (
            <div
              className="rounded-2xl px-4 py-3 mb-4 text-xs flex items-start gap-2 border"
              style={{
                background: "var(--color-surface-container-lowest)",
                borderColor: "var(--color-outline-variant)",
              }}
            >
              <Info className="w-4 h-4 shrink-0 mt-px" style={{ color: "var(--color-primary)" }} />
              <span style={{ color: "var(--color-on-surface-variant)" }}>
                Nothing matched <strong>“{scope.role}”</strong> exactly, so these are
                results for <strong>“{relaxedTo}”</strong>. Drop a word from the role to
                search wider yourself.
              </span>
            </div>
          )}

          {results.length === 0 ? (
            <div
              className="rounded-2xl p-8 text-center border"
              style={{ background: "var(--color-surface)", borderColor: "var(--color-outline-variant)" }}
            >
              <p className="text-sm font-medium mb-1">No postings matched.</p>
              <p className="text-xs" style={{ color: "var(--color-on-surface-variant)" }}>
                Broader forms of this role were tried too and found nothing, so widen
                the window or check the location rules in{" "}
                <code>backend/config/prefilter.yml</code> — a fixed registry over a
                short window is often genuinely empty.
              </p>
            </div>
          ) : (
            <ul className="space-y-3">
              {results.map((posting) => (
                <li key={posting.id}>
                  <button
                    onClick={() => navigate(`/jobs/${posting.id}`)}
                    className="w-full text-left p-5 rounded-2xl border transition-colors hover:opacity-90 flex items-start justify-between gap-4"
                    style={{ background: "var(--color-surface)", borderColor: "var(--color-outline-variant)" }}
                  >
                    <div className="min-w-0">
                      <p className="text-sm font-bold truncate" style={{ color: "var(--color-primary)" }}>
                        {posting.title}
                      </p>
                      <p
                        className="text-xs mt-1.5 flex items-center gap-3 flex-wrap"
                        style={{ color: "var(--color-on-surface-variant)" }}
                      >
                        <span className="inline-flex items-center gap-1">
                          <Building2 className="w-3.5 h-3.5" />
                          {posting.company_name}
                        </span>
                        {posting.location && (
                          <span className="inline-flex items-center gap-1">
                            <MapPin className="w-3.5 h-3.5" />
                            {posting.location}
                          </span>
                        )}
                        <span className="inline-flex items-center gap-1">
                          <Clock className="w-3.5 h-3.5" />
                          {formatPostedAt(posting)}
                        </span>
                      </p>
                    </div>
                    <ChevronRight
                      className="w-5 h-5 shrink-0 mt-0.5"
                      style={{ color: "var(--color-outline-variant)" }}
                    />
                  </button>
                </li>
              ))}
            </ul>
          )}

          <button
            onClick={() => navigate("/")}
            className="w-full mt-6 flex items-center justify-between p-5 rounded-2xl border transition-colors hover:opacity-90"
            style={{ background: "var(--color-surface)", borderColor: "var(--color-outline-variant)" }}
          >
            <div className="text-left">
              <p className="text-sm font-bold" style={{ color: "var(--color-primary)" }}>
                Open the full dashboard
              </p>
              <p className="text-xs mt-0.5" style={{ color: "var(--color-on-surface-variant)" }}>
                Everything this run stored, not just the postings inside the window.
              </p>
            </div>
            <ExternalLink className="w-5 h-5 shrink-0" style={{ color: "var(--color-outline-variant)" }} />
          </button>
        </section>
      )}
    </div>
  );
};
