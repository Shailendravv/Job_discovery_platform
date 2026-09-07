import React, { useState } from "react";
import { useNavigate } from "react-router-dom";
import { Radar, CheckCircle2, ChevronRight, ListChecks, Filter, ScanSearch, AlertCircle } from "lucide-react";
import { useApp } from "@/context/AppContext";
import { ApiError } from "@/services/api";

type RunPhase = "idle" | "starting" | "started" | "error";

// What the pipeline actually does, in order — app/ingest/runner.py.
const PIPELINE_STEPS = [
  {
    icon: <ScanSearch className="w-5 h-5" />,
    title: "Fetch from every ATS connector",
    desc: "Greenhouse, Lever, Ashby, Workday, Workable, SmartRecruiters, Recruitee — one request per configured company.",
  },
  {
    icon: <Filter className="w-5 h-5" />,
    title: "Normalize & dedupe",
    desc: "Postings are deduplicated by (provider, org, job id); near-duplicate titles at the same company/location are marked, not dropped.",
  },
  {
    icon: <ListChecks className="w-5 h-5" />,
    title: "Prefilter",
    desc: "Rule-based rejects (config/prefilter.yml) run automatically after every ingest, before anything reaches judging.",
  },
  {
    icon: <CheckCircle2 className="w-5 h-5" />,
    title: "Land in the dashboard",
    desc: "Prefiltered postings show up on the Dashboard, newest first. Judging into a shortlist runs separately via jobctl / /nightly.",
  },
];

export const DiscoveryView: React.FC = () => {
  const navigate = useNavigate();
  const { triggerIngest } = useApp();
  const [phase, setPhase] = useState<RunPhase>("idle");
  const [runId, setRunId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const handleRunDiscovery = async () => {
    setPhase("starting");
    setError(null);
    try {
      const id = await triggerIngest();
      setRunId(id);
      setPhase("started");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to start the discovery run.");
      setPhase("error");
    }
  };

  return (
    <div className="animate-fade-in min-h-screen" style={{ background: "var(--color-background)", color: "var(--color-on-surface)" }}>
      {/* ── Hero ── */}
      <section className="flex flex-col items-center text-center pt-10 pb-8 px-6">
        <div className="max-w-2xl w-full">
          <h1 className="text-4xl md:text-5xl font-extrabold tracking-tight mb-3" style={{ color: "var(--color-primary)" }}>
            Job Discovery
          </h1>
          <p className="text-base mb-8 font-medium" style={{ color: "var(--color-on-surface-variant)" }}>
            Fetches new postings from every configured ATS company registry and runs them through the prefilter — the same work as <code>jobctl ingest</code>.
          </p>

          {phase === "idle" || phase === "error" ? (
            <button
              onClick={handleRunDiscovery}
              className="inline-flex items-center gap-2 h-14 px-8 rounded-2xl text-sm font-bold uppercase tracking-wider shadow transition-all active:scale-95"
              style={{ background: "var(--color-primary)", color: "var(--color-on-primary)" }}
            >
              <Radar className="w-5 h-5" />
              Run Discovery
            </button>
          ) : phase === "starting" ? (
            <button
              disabled
              className="inline-flex items-center gap-2 h-14 px-8 rounded-2xl text-sm font-bold uppercase tracking-wider shadow opacity-70"
              style={{ background: "var(--color-primary)", color: "var(--color-on-primary)" }}
            >
              <Radar className="w-5 h-5 animate-spin" />
              Starting…
            </button>
          ) : (
            <div
              className="inline-flex flex-col items-center gap-1 px-8 py-4 rounded-2xl border"
              style={{ background: "var(--color-surface-container-low)", borderColor: "var(--color-outline-variant)" }}
            >
              <span className="flex items-center gap-2 text-sm font-bold" style={{ color: "var(--color-primary)" }}>
                <CheckCircle2 className="w-5 h-5" style={{ color: "#16a34a" }} />
                Discovery run started
              </span>
              <span className="text-xs" style={{ color: "var(--color-on-surface-variant)" }}>
                run id <code>{runId}</code> — runs in the background, typically a few minutes for the full registry.
              </span>
            </div>
          )}
        </div>
      </section>

      {/* ── Error ── */}
      {phase === "error" && error && (
        <section className="max-w-2xl mx-auto mb-8 px-6">
          <div className="rounded-2xl p-6 text-center border flex items-start gap-3" style={{ background: "#fff1f2", borderColor: "#fecdd3" }}>
            <AlertCircle className="w-5 h-5 shrink-0 mt-0.5" style={{ color: "#be123c" }} />
            <div className="text-left">
              <p className="text-sm font-bold mb-1" style={{ color: "#be123c" }}>Could not start discovery</p>
              <p className="text-sm" style={{ color: "#e11d48" }}>{error}</p>
            </div>
          </div>
        </section>
      )}

      {/* ── Started — link to the dashboard where results land ── */}
      {phase === "started" && (
        <section className="max-w-2xl mx-auto mb-8 px-6">
          <button
            onClick={() => navigate("/")}
            className="w-full flex items-center justify-between p-5 rounded-2xl border transition-colors hover:opacity-90"
            style={{ background: "var(--color-surface)", borderColor: "var(--color-outline-variant)" }}
          >
            <div className="text-left">
              <p className="text-sm font-bold" style={{ color: "var(--color-primary)" }}>View the pipeline</p>
              <p className="text-xs mt-0.5" style={{ color: "var(--color-on-surface-variant)" }}>
                New postings appear on the Dashboard as soon as this run lands them.
              </p>
            </div>
            <ChevronRight className="w-5 h-5 shrink-0" style={{ color: "var(--color-outline-variant)" }} />
          </button>
        </section>
      )}

      {/* ── What actually happens ── */}
      <section className="max-w-3xl mx-auto px-6 pb-12">
        <div className="rounded-2xl overflow-hidden border" style={{ background: "var(--color-surface-container-lowest)", borderColor: "var(--color-outline-variant)" }}>
          <div className="p-4 border-b" style={{ borderColor: "var(--color-outline-variant)", background: "var(--color-surface)" }}>
            <h3 className="text-base font-bold" style={{ color: "var(--color-primary)" }}>How discovery works</h3>
          </div>
          <div className="p-6 space-y-5">
            {PIPELINE_STEPS.map(({ icon, title, desc }, idx) => (
              <div key={title} className="flex gap-4">
                <div className="flex flex-col items-center">
                  <div className="w-10 h-10 rounded-lg flex items-center justify-center shrink-0" style={{ background: "var(--color-surface-container-low)", color: "var(--color-secondary)" }}>
                    {icon}
                  </div>
                  {idx < PIPELINE_STEPS.length - 1 && (
                    <div className="w-0.5 flex-1 mt-1" style={{ background: "var(--color-outline-variant)" }} />
                  )}
                </div>
                <div className="pb-1">
                  <h4 className="text-sm font-bold" style={{ color: "var(--color-primary)" }}>{title}</h4>
                  <p className="text-xs mt-1" style={{ color: "var(--color-on-surface-variant)" }}>{desc}</p>
                </div>
              </div>
            ))}
          </div>
        </div>
      </section>
    </div>
  );
};
