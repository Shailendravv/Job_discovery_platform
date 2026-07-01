import React, { useState, useRef, useCallback, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { Search, Radar, Check, Lightbulb, ChevronRight, MapPin, X, Hourglass, ShieldCheck, Brain, Globe, Lock, BarChart2, DollarSign, UserCheck } from "lucide-react";
import { api, ApiError } from "@/services/api";
import type { Job } from "@/types";

type SearchPhase = "idle" | "searching" | "results" | "error";

const statusMessages = [
  "Gathering Metadata...",
  "Scrubbing duplicates...",
  "Analyzing job descriptions...",
  "Ranking match scores...",
  "Finalizing report...",
];

export const DiscoveryView: React.FC = () => {
  const navigate = useNavigate();
  const [query, setQuery] = useState("");
  const [location, setLocation] = useState("");
  const [phase, setPhase] = useState<SearchPhase>("idle");
  const [jobs, setJobs] = useState<Job[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [progress, setProgress] = useState(0);
  const [activeStatus, setActiveStatus] = useState(0);
  const [savedCount, setSavedCount] = useState(0);
  const [recentSearches, setRecentSearches] = useState<string[]>([
    "Senior React Lead",
    "Cloud Architect AWS",
    "Product Designer (Fintech)",
  ]);

  const progressIntervalRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const statusIntervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const clearIntervals = useCallback(() => {
    if (progressIntervalRef.current) {
      clearInterval(progressIntervalRef.current);
      progressIntervalRef.current = null;
    }
    if (statusIntervalRef.current) {
      clearInterval(statusIntervalRef.current);
      statusIntervalRef.current = null;
    }
  }, []);

  useEffect(() => {
    return () => { clearIntervals(); };
  }, [clearIntervals]);

  const startProgressAnimation = useCallback(() => {
    clearIntervals();
    let currentProgress = 0;
    let currentStatusIdx = 0;

    progressIntervalRef.current = setInterval(() => {
      currentProgress += Math.floor(Math.random() * 2) + 1;
      if (currentProgress > 90) currentProgress = 90;
      setProgress(currentProgress);
    }, 2000);

    statusIntervalRef.current = setInterval(() => {
      currentStatusIdx = (currentStatusIdx + 1) % statusMessages.length;
      setActiveStatus(currentStatusIdx);
    }, 4000);
  }, [clearIntervals]);

  const executeSearch = useCallback(async (searchQuery: string) => {
    setPhase("searching");
    setError(null);
    setJobs([]);
    setProgress(0);
    setActiveStatus(0);
    startProgressAnimation();

    try {
      const response = await api.searchJobs({ user_input: searchQuery, location: location || undefined });
      clearIntervals();
      setJobs(response.jobs);
      setSavedCount(response.saved);
      setProgress(100);
      setPhase("results");
    } catch (err) {
      clearIntervals();
      setError(err instanceof ApiError ? err.message : "An unexpected error occurred during search.");
      setPhase("error");
    }
  }, [startProgressAnimation, clearIntervals, location]);

  const handleSearch = useCallback(() => {
    const trimmed = query.trim();
    if (!trimmed) return;
    setRecentSearches((prev) => {
      const filtered = prev.filter((s) => s.toLowerCase() !== trimmed.toLowerCase());
      return [trimmed, ...filtered].slice(0, 5);
    });
    executeSearch(trimmed);
  }, [query, executeSearch]);

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter") handleSearch();
  };

  const resetSearch = () => {
    clearIntervals();
    setPhase("idle");
    setProgress(0);
    setError(null);
    setJobs([]);
    setQuery("");
    setLocation("");
  };

  const handleRecentClick = (search: string) => {
    setQuery(search);
    executeSearch(search);
  };

  const dashArray = 578;
  const dashOffset = dashArray - (progress / 100) * dashArray;

  const formatSource = (src: string | null | undefined): string => {
    if (!src) return "UNKNOWN";
    const s = src.toLowerCase();
    if (s.includes("linkedin")) return "LINKEDIN";
    if (s.includes("indeed")) return "INDEED";
    if (s.includes("searx")) return "SEARXNG";
    return src.toUpperCase();
  };

  const getSourceStyles = (src: string | null | undefined) => {
    const formatted = formatSource(src);
    switch (formatted) {
      case "LINKEDIN": return "border-blue-200 text-blue-700 bg-blue-50/50";
      case "INDEED": return "border-orange-200 text-orange-700 bg-orange-50/50";
      case "SEARXNG": return "border-emerald-200 text-emerald-700 bg-emerald-50/50";
      default: return "border-slate-200 text-slate-600 bg-slate-50";
    }
  };

  return (
    <div className="animate-fade-in min-h-screen" style={{ background: "var(--color-background)", color: "var(--color-on-surface)" }}>

      {/* ── Hero ── */}
      <section className="flex flex-col items-center text-center pt-10 pb-8 px-6">
        <div className="max-w-3xl w-full">
          <h1 className="text-4xl md:text-5xl font-extrabold tracking-tight mb-3" style={{ color: "var(--color-primary)" }}>
            Deep Search Discovery
          </h1>
          <p className="text-base mb-8 font-medium" style={{ color: "var(--color-on-surface-variant)" }}>
            Our AI engine scans hundreds of sources to find your perfect candidate match.
          </p>

          {/* Search Bar */}
          <div className="relative w-full search-glow rounded-2xl">
            <div className="absolute inset-y-0 left-4 flex items-center pointer-events-none">
              <Search className="w-5 h-5" style={{ color: "var(--color-secondary)" }} />
            </div>
            <input
              type="text"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder="e.g. React developer Python 4 years experience remote"
              className="w-full h-16 pl-12 pr-36 rounded-2xl text-base outline-none transition-all border"
              style={{
                background: "var(--color-surface-container-lowest)",
                borderColor: "var(--color-outline-variant)",
                color: "var(--color-on-surface)",
              }}
              disabled={phase === "searching"}
            />
            <div className="absolute inset-y-2 right-2 flex items-center gap-1">
              {query && phase === "idle" && (
                <button
                  onClick={() => setQuery("")}
                  className="p-2 rounded-lg transition-colors hover:opacity-70"
                  style={{ color: "var(--color-outline)" }}
                >
                  <X className="w-4 h-4" />
                </button>
              )}
              {phase === "results" && (
                <button
                  onClick={resetSearch}
                  className="h-full px-5 font-semibold text-xs rounded-xl border transition-colors uppercase tracking-wider"
                  style={{ background: "var(--color-surface-container-low)", color: "var(--color-secondary)", borderColor: "var(--color-secondary)" }}
                >
                  New Search
                </button>
              )}
              <button
                onClick={phase === "searching" ? resetSearch : handleSearch}
                disabled={!query.trim()}
                className="h-full px-6 font-bold text-xs rounded-xl disabled:opacity-40 disabled:cursor-not-allowed transition-all active:scale-95 uppercase tracking-widest shadow"
                style={{ background: "var(--color-primary)", color: "var(--color-on-primary)" }}
              >
                {phase === "searching" ? "Cancel" : "Search"}
              </button>
            </div>
          </div>

          {/* Location Input */}
          <div className="relative w-full mt-3">
            <div className="absolute inset-y-0 left-3 flex items-center pointer-events-none">
              <MapPin className="w-4 h-4" style={{ color: "var(--color-secondary)" }} />
            </div>
            <input
              type="text"
              value={location}
              onChange={(e) => setLocation(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder="Location (optional) — e.g. Remote, India, San Francisco"
              className="w-full h-11 pl-10 pr-4 rounded-xl text-sm outline-none transition-all border"
              style={{
                background: "var(--color-surface-container-lowest)",
                borderColor: "var(--color-outline-variant)",
                color: "var(--color-on-surface)",
              }}
              disabled={phase === "searching"}
            />
          </div>
        </div>
      </section>

      {/* ── Error ── */}
      {phase === "error" && error && (
        <section className="max-w-4xl mx-auto mb-8 px-6">
          <div className="rounded-2xl p-6 text-center border" style={{ background: "#fff1f2", borderColor: "#fecdd3" }}>
            <p className="text-sm font-bold mb-2" style={{ color: "#be123c" }}>Search Failed</p>
            <p className="text-sm" style={{ color: "#e11d48" }}>{error}</p>
            <button
              onClick={resetSearch}
              className="mt-4 px-5 py-2 text-white text-xs font-bold rounded-xl transition-colors"
              style={{ background: "#be123c" }}
            >
              Try Again
            </button>
          </div>
        </section>
      )}

      {/* ── Discovery In Progress ── */}
      {phase === "searching" && (
        <section className="max-w-4xl mx-auto mb-8 px-6">
          <div
            className="rounded-2xl p-8 relative overflow-hidden border"
            style={{ background: "var(--color-surface-container-low)", borderColor: "var(--color-outline-variant)" }}
          >
            <div className="relative z-10 flex flex-col md:flex-row gap-8 items-start">

              {/* Circular Progress */}
              <div className="flex flex-col items-center gap-4 w-full md:w-1/3">
                <div className="relative w-48 h-48 flex items-center justify-center">
                  <div className="absolute inset-0 rounded-full border-4" style={{ borderColor: "var(--color-surface-container-highest)" }} />
                  <svg className="w-full h-full -rotate-90">
                    <circle
                      cx="96" cy="96" fill="transparent" r="92"
                      stroke="var(--color-secondary)"
                      strokeDasharray={dashArray}
                      strokeDashoffset={dashOffset}
                      strokeWidth="8"
                      style={{ transition: "stroke-dashoffset 1s ease-in-out" }}
                    />
                  </svg>
                  <div className="absolute flex flex-col items-center">
                    <Radar className="w-10 h-10 animate-pulse-ring" style={{ color: "var(--color-secondary)" }} />
                    <span className="text-xl font-bold mt-2" style={{ color: "var(--color-primary)" }}>{progress}%</span>
                  </div>
                </div>
                <div className="text-center">
                  <p className="text-xs font-bold uppercase tracking-widest mb-1" style={{ color: "var(--color-secondary)" }}>Status</p>
                  <p className="text-sm font-medium" style={{ color: "var(--color-on-surface)" }}>{statusMessages[activeStatus]}</p>
                </div>
              </div>

              {/* Timeline */}
              <div className="flex-1 w-full">
                <div className="flex justify-between items-end mb-5">
                  <div>
                    <h2 className="text-lg font-bold" style={{ color: "var(--color-primary)" }}>Discovery in Progress</h2>
                    <p className="text-xs" style={{ color: "var(--color-on-surface-variant)" }}>Estimated completion: 3 mins 12 secs</p>
                  </div>
                  <button
                    onClick={resetSearch}
                    className="flex items-center gap-1.5 px-4 py-2 rounded-xl text-xs font-bold border transition-all active:scale-95"
                    style={{ borderColor: "var(--color-secondary)", color: "var(--color-secondary)" }}
                  >
                    <X className="w-4 h-4" />
                    Background This Search
                  </button>
                </div>

                <div className="space-y-1">
                  {/* Step 1 – Completed */}
                  <div className="flex gap-4 items-start">
                    <div className="mt-1">
                      <div className="w-6 h-6 rounded-full bg-green-100 flex items-center justify-center text-green-700">
                        <Check className="w-3.5 h-3.5" strokeWidth={3} />
                      </div>
                      <div className="w-0.5 h-10 bg-green-100 mx-auto mt-1" />
                    </div>
                    <div className="flex-1 pb-3">
                      <p className="text-[10px] font-bold uppercase tracking-wider" style={{ color: "var(--color-on-surface-variant)" }}>STEP 1</p>
                      <p className="text-sm font-semibold" style={{ color: "var(--color-on-surface)" }}>Connecting to LinkedIn...</p>
                      <p className="text-xs" style={{ color: "var(--color-outline)" }}>API Handshake complete. Auth token refreshed.</p>
                    </div>
                  </div>

                  {/* Step 2 – Active */}
                  <div className="flex gap-4 items-start">
                    <div className="mt-1">
                      <div
                        className="w-6 h-6 rounded-full flex items-center justify-center text-white relative"
                        style={{ background: "var(--color-secondary-container)" }}
                      >
                        <div className="absolute inset-0 rounded-full animate-ping opacity-20" style={{ background: "var(--color-secondary)" }} />
                        <svg className="w-3.5 h-3.5 animate-spin" viewBox="0 0 24 24" fill="none">
                          <circle cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="3" strokeDasharray="31.4 31.4" />
                        </svg>
                      </div>
                      <div className="w-0.5 h-10 mx-auto mt-1" style={{ background: "var(--color-outline-variant)" }} />
                    </div>
                    <div className="flex-1 pb-3">
                      <p className="text-[10px] font-bold uppercase tracking-wider" style={{ color: "var(--color-secondary)" }}>ACTIVE</p>
                      <p className="text-sm font-bold" style={{ color: "var(--color-primary)" }}>Scanning Indeed &amp; Greenhouse...</p>
                      <div className="mt-1.5 w-full h-1.5 rounded-full overflow-hidden" style={{ background: "var(--color-surface-container-highest)" }}>
                        <div
                          className="h-full rounded-full progress-bar-fill"
                          style={{ width: `${Math.min(progress, 90)}%`, background: "var(--color-secondary)" }}
                        />
                      </div>
                      <p className="text-xs mt-1.5" style={{ color: "var(--color-on-surface-variant)" }}>
                        Found {Math.max(0, Math.floor(progress * 1.5))} candidates matching your query...
                      </p>
                    </div>
                  </div>

                  {/* Step 3 – Queued */}
                  <div className="flex gap-4 items-start opacity-50">
                    <div className="mt-1">
                      <div className="w-6 h-6 rounded-full flex items-center justify-center" style={{ background: "var(--color-surface-container-highest)", color: "var(--color-outline)" }}>
                        <Hourglass className="w-3.5 h-3.5" />
                      </div>
                    </div>
                    <div className="flex-1">
                      <p className="text-[10px] font-bold uppercase tracking-wider" style={{ color: "var(--color-on-surface-variant)" }}>QUEUED</p>
                      <p className="text-sm" style={{ color: "var(--color-on-surface)" }}>Aggregating &amp; Scoring Results</p>
                    </div>
                  </div>
                </div>
              </div>
            </div>
          </div>

          {/* Contextual Insight Cards shown during search too */}
          <div className="mt-4 grid grid-cols-1 md:grid-cols-3 gap-4">
            {[
              { icon: <BarChart2 className="w-5 h-5" />, label: "Market Saturation", value: "High", accent: "#f97316", bg: "#fff7ed" },
              { icon: <DollarSign className="w-5 h-5" />, label: "Avg. Salary Range", value: "$140k – $185k", accent: "var(--color-secondary)", bg: "var(--color-surface-container-low)" },
              { icon: <UserCheck className="w-5 h-5" />, label: "Top Candidate Match", value: "Ready in 2m", accent: "#16a34a", bg: "#f0fdf4" },
            ].map(({ icon, label, value, accent, bg }) => (
              <div
                key={label}
                className="rounded-xl p-4 flex items-center gap-3 border"
                style={{ background: "var(--color-surface)", borderColor: "var(--color-outline-variant)" }}
              >
                <div className="w-10 h-10 rounded-lg flex items-center justify-center shrink-0" style={{ background: bg, color: accent }}>
                  {icon}
                </div>
                <div>
                  <p className="text-[10px] font-bold uppercase tracking-wider" style={{ color: "var(--color-on-surface-variant)" }}>{label}</p>
                  <p className="text-lg font-bold" style={{ color: "var(--color-primary)" }}>{value}</p>
                </div>
              </div>
            ))}
          </div>
        </section>
      )}

      {/* ── Results ── */}
      {phase === "results" && jobs.length > 0 && (
        <section className="max-w-5xl mx-auto mb-8 px-6">
          <div className="flex items-center justify-between mb-5">
            <div>
              <h2 className="text-lg font-bold" style={{ color: "var(--color-primary)" }}>Results</h2>
              <p className="text-sm" style={{ color: "var(--color-on-surface-variant)" }}>
                Found {jobs.length} jobs{savedCount > 0 ? ` · ${savedCount} saved to database` : ""}
              </p>
            </div>
            <button onClick={resetSearch} className="text-xs font-bold transition-colors" style={{ color: "var(--color-secondary)" }}>
              New Search
            </button>
          </div>

          {/* Insight Cards */}
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4 mb-6">
            {[
              { icon: <BarChart2 className="w-5 h-5" />, label: "Market Saturation", value: jobs.length > 5 ? "High" : "Moderate", accent: "#f97316", bg: "#fff7ed" },
              { icon: <DollarSign className="w-5 h-5" />, label: "Avg. Salary Range", value: jobs.some((j) => j.salary) ? "Varies" : "Not specified", accent: "var(--color-secondary)", bg: "var(--color-surface-container-low)" },
              { icon: <UserCheck className="w-5 h-5" />, label: "Unique Employers", value: String(new Set(jobs.map((j) => j.company)).size), accent: "#16a34a", bg: "#f0fdf4" },
            ].map(({ icon, label, value, accent, bg }) => (
              <div key={label} className="rounded-xl p-4 flex items-center gap-3 border" style={{ background: "var(--color-surface)", borderColor: "var(--color-outline-variant)" }}>
                <div className="w-10 h-10 rounded-lg flex items-center justify-center shrink-0" style={{ background: bg, color: accent }}>
                  {icon}
                </div>
                <div>
                  <p className="text-[10px] font-bold uppercase tracking-wider" style={{ color: "var(--color-on-surface-variant)" }}>{label}</p>
                  <p className="text-lg font-bold" style={{ color: "var(--color-primary)" }}>{value}</p>
                </div>
              </div>
            ))}
          </div>

          {/* Job List */}
          <div className="rounded-2xl overflow-hidden border" style={{ background: "var(--color-surface)", borderColor: "var(--color-outline-variant)" }}>
            <div className="divide-y" style={{ borderColor: "var(--color-outline-variant)" }}>
              {jobs.map((job, idx) => (
                <div
                  key={job.id || idx}
                  className="p-5 cursor-pointer transition-colors hover:opacity-90"
                  style={{ background: "var(--color-surface)" }}
                  onClick={() => navigate(`/jobs/${job.id || ""}`)}
                >
                  <div className="flex items-start justify-between gap-4">
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2 mb-1">
                        <span className={`text-[9px] font-extrabold tracking-wider border px-2 py-0.5 rounded uppercase shrink-0 ${getSourceStyles(job.source)}`}>
                          {formatSource(job.source)}
                        </span>
                        {job.job_type && (
                          <span className="text-[9px] font-bold tracking-wider px-2 py-0.5 rounded border uppercase shrink-0" style={{ background: "var(--color-surface-container-low)", color: "var(--color-on-surface-variant)", borderColor: "var(--color-outline-variant)" }}>
                            {job.job_type}
                          </span>
                        )}
                      </div>
                      <h3 className="text-sm font-bold line-clamp-1 mt-1" style={{ color: "var(--color-on-surface)" }}>{job.title}</h3>
                      <p className="text-xs font-semibold mt-0.5" style={{ color: "var(--color-on-surface-variant)" }}>{job.company || "Unknown Company"}</p>
                      <div className="flex items-center gap-3 mt-2">
                        {job.location && (
                          <span className="text-xs flex items-center gap-1" style={{ color: "var(--color-outline)" }}>
                            <MapPin className="w-3 h-3" />{job.location}
                          </span>
                        )}
                        {job.salary && <span className="text-xs font-semibold text-emerald-600">{job.salary}</span>}
                      </div>
                      {job.skills && job.skills.length > 0 && (
                        <div className="flex flex-wrap gap-1.5 mt-2">
                          {job.skills.slice(0, 4).map((skill, sIdx) => (
                            <span key={sIdx} className="text-[10px] font-medium px-2 py-0.5 rounded border" style={{ color: "var(--color-secondary)", background: "var(--color-primary-fixed)", borderColor: "var(--color-primary-fixed-dim)" }}>
                              {skill}
                            </span>
                          ))}
                          {job.skills.length > 4 && <span className="text-[10px] font-medium" style={{ color: "var(--color-outline)" }}>+{job.skills.length - 4} more</span>}
                        </div>
                      )}
                    </div>
                    <ChevronRight className="w-4 h-4 shrink-0 mt-2" style={{ color: "var(--color-outline-variant)" }} />
                  </div>
                </div>
              ))}
            </div>
          </div>
        </section>
      )}

      {/* ── Empty Results ── */}
      {phase === "results" && jobs.length === 0 && (
        <section className="max-w-4xl mx-auto mb-8 px-6">
          <div className="rounded-2xl p-12 text-center border" style={{ background: "var(--color-surface)", borderColor: "var(--color-outline-variant)" }}>
            <div className="w-14 h-14 rounded-full flex items-center justify-center mx-auto mb-3" style={{ background: "var(--color-surface-container-low)" }}>
              <Search className="w-6 h-6" style={{ color: "var(--color-outline)" }} />
            </div>
            <h3 className="text-base font-bold mb-1" style={{ color: "var(--color-on-surface)" }}>No jobs found</h3>
            <p className="text-sm mb-4" style={{ color: "var(--color-on-surface-variant)" }}>Try a different search query or broader terms.</p>
            <button onClick={resetSearch} className="px-5 py-2 text-white text-xs font-bold rounded-xl transition-colors" style={{ background: "var(--color-primary)" }}>
              New Search
            </button>
          </div>
        </section>
      )}

      {/* ── Idle: Engine Capabilities + Sidebar ── */}
      {phase === "idle" && (
        <section className="max-w-5xl mx-auto px-6 pb-12 grid grid-cols-1 lg:grid-cols-12 gap-6">

          {/* Engine Capabilities */}
          <div className="lg:col-span-8 rounded-2xl overflow-hidden border" style={{ background: "var(--color-surface-container-lowest)", borderColor: "var(--color-outline-variant)" }}>
            <div className="p-4 border-b flex justify-between items-center" style={{ borderColor: "var(--color-outline-variant)", background: "var(--color-surface)" }}>
              <h3 className="text-base font-bold" style={{ color: "var(--color-primary)" }}>Engine Capabilities</h3>
              <span className="text-[10px] font-bold px-2 py-1 rounded uppercase" style={{ color: "var(--color-secondary)", background: "var(--color-surface-container-low)" }}>PRO FEATURE</span>
            </div>
            <div className="p-6 grid grid-cols-1 md:grid-cols-2 gap-6">
              {[
                {
                  icon: <ShieldCheck className="w-5 h-5" />,
                  title: "Identity Verification",
                  desc: "Automatically cross-references Github and LinkedIn profiles to ensure talent authenticity.",
                },
                {
                  icon: <Brain className="w-5 h-5" />,
                  title: "Semantic Analysis",
                  desc: 'Understands "Python developer" vs "Data Scientist who knows Python" for better mapping.',
                },
                {
                  icon: <Globe className="w-5 h-5" />,
                  title: "Global Reach",
                  desc: "Scrapes international job boards and niche community forums across 40+ countries.",
                },
                {
                  icon: <Lock className="w-5 h-5" />,
                  title: "Privacy First",
                  desc: "Aggregated data is encrypted and GDPR compliant. We never store personal contact info.",
                },
              ].map(({ icon, title, desc }) => (
                <div key={title} className="flex gap-4">
                  <div className="w-10 h-10 rounded-lg flex items-center justify-center shrink-0" style={{ background: "var(--color-surface-container-low)", color: "var(--color-secondary)" }}>
                    {icon}
                  </div>
                  <div>
                    <h4 className="text-sm font-bold" style={{ color: "var(--color-primary)" }}>{title}</h4>
                    <p className="text-xs mt-1" style={{ color: "var(--color-on-surface-variant)" }}>{desc}</p>
                  </div>
                </div>
              ))}
            </div>
          </div>

          {/* Sidebar */}
          <div className="lg:col-span-4 space-y-4">
            {/* Recent Searches */}
            <div className="rounded-2xl p-5 shadow-lg relative overflow-hidden" style={{ background: "var(--color-primary)" }}>
              <div className="absolute top-2 right-2 opacity-10 pointer-events-none">
                <svg className="w-20 h-20" fill="currentColor" viewBox="0 0 24 24" style={{ color: "var(--color-on-primary)" }}>
                  <path d="M7 2v11h3v9l7-12h-4l4-8z" />
                </svg>
              </div>
              <h3 className="text-base font-bold mb-1" style={{ color: "var(--color-on-primary)" }}>Recent Searches</h3>
              <p className="text-xs mb-4" style={{ color: "var(--color-primary-fixed-dim)" }}>Quick jump back to your history</p>
              <div className="space-y-1.5">
                {recentSearches.map((search, idx) => (
                  <button
                    key={idx}
                    onClick={() => handleRecentClick(search)}
                    className="w-full flex items-center justify-between p-3 rounded-xl transition-colors text-left cursor-pointer"
                    style={{ background: "rgba(255,255,255,0.10)", color: "var(--color-on-primary)" }}
                    onMouseEnter={(e) => (e.currentTarget.style.background = "rgba(255,255,255,0.18)")}
                    onMouseLeave={(e) => (e.currentTarget.style.background = "rgba(255,255,255,0.10)")}
                  >
                    <span className="text-sm font-medium">{search}</span>
                    <ChevronRight className="w-4 h-4 shrink-0 opacity-70" />
                  </button>
                ))}
              </div>
            </div>

            {/* Search Tip */}
            <div className="rounded-2xl p-5 border" style={{ background: "var(--color-surface-container-high)", borderColor: "var(--color-outline-variant)" }}>
              <div className="flex items-center gap-2 mb-3">
                <Lightbulb className="w-4 h-4" style={{ color: "var(--color-tertiary)" }} />
                <h4 className="text-xs font-bold uppercase tracking-wider" style={{ color: "var(--color-primary)" }}>Search Tip</h4>
              </div>
              <p className="text-sm leading-relaxed" style={{ color: "var(--color-on-surface)" }}>
                Try adding "ex-Google" or "Ivy League" to filter for specific pedigree benchmarks in your discovery engine.
              </p>
            </div>
          </div>
        </section>
      )}
    </div>
  );
};
