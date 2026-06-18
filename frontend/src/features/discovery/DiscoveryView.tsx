import React, { useState, useRef, useCallback, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { Search, Radar, Check, Lightbulb, ChevronRight, MapPin, X, Hourglass } from "lucide-react";
import { api, ApiError } from "@/services/api";
import type { Job } from "@/types";

type SearchPhase = "idle" | "searching" | "results" | "error";

const statusMessages = [
  "Gathering Metadata...",
  "Scrubbing duplicates...",
  "Analyzing job descriptions...",
  "Ranking match scores...",
  "Finalizing report..."];

export const DiscoveryView: React.FC = () => {
  const navigate = useNavigate();
  const [query, setQuery] = useState("");
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

  // Cleanup intervals on unmount
  useEffect(() => {
    return () => {
      clearIntervals();
    };
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
      const response = await api.searchJobs({ user_input: searchQuery });
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
  }, [startProgressAnimation, clearIntervals]);

  const handleSearch = useCallback(() => {
    const trimmed = query.trim();
    if (!trimmed) return;

    // Add to recent searches (avoid duplicates)
    setRecentSearches((prev) => {
      const filtered = prev.filter((s) => s.toLowerCase() !== trimmed.toLowerCase());
      return [trimmed, ...filtered].slice(0, 5);
    });

    executeSearch(trimmed);
  }, [query, executeSearch]);

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter") {
      handleSearch();
    }
  };

  const resetSearch = () => {
    clearIntervals();
    setPhase("idle");
    setProgress(0);
    setError(null);
    setJobs([]);
    setQuery("");
  };

  const handleRecentClick = (search: string) => {
    setQuery(search);
    executeSearch(search);
  };

  const dashArray = 578; // 2 * pi * 92
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
      case "LINKEDIN":
        return "border-blue-200 text-blue-700 bg-blue-50/50";
      case "INDEED":
        return "border-orange-200 text-orange-700 bg-orange-50/50";
      case "SEARXNG":
        return "border-emerald-200 text-emerald-700 bg-emerald-50/50";
      default:
        return "border-slate-200 text-slate-600 bg-slate-50";
    }
  };

  return (
    <div className="animate-fade-in">
      {/* Hero Section */}
      <section className="flex flex-col items-center text-center mb-8">
        <div className="max-w-3xl w-full">
          <h1 className="text-3xl md:text-4xl font-extrabold tracking-tight text-slate-900 mb-3">
            Deep Search Discovery
          </h1>
          <p className="text-base text-slate-500 mb-8 font-medium">
            Our AI engine scans hundreds of sources to find your perfect candidate match.
          </p>

          {/* Search Bar */}
          <div className="relative w-full group">
            <div className="absolute inset-y-0 left-4 flex items-center pointer-events-none">
              <Search className="w-5 h-5 text-blue-600" />
            </div>
            <input
              type="text"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder="e.g. React developer Python 4 years experience remote"
              className="w-full h-16 pl-12 pr-36 bg-white border border-slate-200 rounded-2xl text-base text-slate-900 placeholder:text-slate-400 focus:ring-2 focus:ring-blue-500/20 focus:border-blue-500 outline-none transition-all shadow-sm"
              disabled={phase === "searching"}
            />
            <div className="absolute inset-y-2 right-2 flex items-center gap-1">
              {query && phase === "idle" && (
                <button
                  onClick={() => setQuery("")}
                  className="p-2 text-slate-400 hover:text-slate-600 rounded-lg hover:bg-slate-100 transition-colors"
                >
                  <X className="w-4 h-4" />
                </button>
              )}
              {phase === "results" && (
                <button
                  onClick={resetSearch}
                  className="h-full px-5 bg-white text-slate-600 font-semibold text-xs rounded-xl border border-slate-200 hover:bg-slate-50 transition-colors uppercase tracking-wider"
                >
                  New Search
                </button>
              )}
              <button
                onClick={phase === "searching" ? resetSearch : handleSearch}
                disabled={!query.trim()}
                className="h-full px-6 bg-blue-600 text-white font-bold text-xs rounded-xl hover:bg-blue-700 disabled:opacity-40 disabled:cursor-not-allowed transition-all active:scale-95 uppercase tracking-widest shadow-sm"
              >
                {phase === "searching" ? "Cancel" : "Search"}
              </button>
            </div>
          </div>
        </div>
      </section>

      {/* Error State */}
      {phase === "error" && error && (
        <section className="max-w-4xl mx-auto mb-8">
          <div className="bg-rose-50 border border-rose-200 rounded-2xl p-6 text-center">
            <p className="text-sm font-bold text-rose-700 mb-2">Search Failed</p>
            <p className="text-sm text-rose-600">{error}</p>
            <button
              onClick={resetSearch}
              className="mt-4 px-5 py-2 bg-rose-600 text-white text-xs font-bold rounded-xl hover:bg-rose-700 transition-colors"
            >
              Try Again
            </button>
          </div>
        </section>
      )}

      {/* Discovery in Progress */}
      {phase === "searching" && (
        <section className="max-w-4xl mx-auto mb-8">
          <div className="bg-white border border-slate-100 rounded-2xl p-8 shadow-sm relative overflow-hidden">
            <div className="relative z-10 flex flex-col md:flex-row gap-8 items-start">
              {/* Circular Progress */}
              <div className="flex flex-col items-center gap-4 w-full md:w-1/3">
                <div className="relative w-48 h-48 flex items-center justify-center">
                  <div className="absolute inset-0 rounded-full border-4 border-slate-100" />
                  <svg className="w-full h-full -rotate-90">
                    <circle
                      className="text-blue-600 transition-all duration-1000"
                      cx="96"
                      cy="96"
                      fill="transparent"
                      r="92"
                      stroke="currentColor"
                      strokeDasharray={dashArray}
                      strokeDashoffset={dashOffset}
                      strokeWidth="8"
                      style={{ transition: "stroke-dashoffset 1s ease-in-out" }}
                    />
                  </svg>
                  <div className="absolute flex flex-col items-center">
                    <Radar className="w-10 h-10 text-blue-600 animate-pulse" />
                    <span className="text-xl font-bold text-slate-900 mt-2">{progress}%</span>
                  </div>
                </div>
                <div className="text-center">
                  <p className="text-xs font-bold uppercase tracking-widest text-blue-600 mb-1">Status</p>
                  <p className="text-sm text-slate-700 font-medium">{statusMessages[activeStatus]}</p>
                </div>
              </div>

              {/* Timeline */}
              <div className="flex-1 w-full">
                <div className="flex justify-between items-end mb-5">
                  <div>
                    <h2 className="text-lg font-bold text-slate-900">Discovery in Progress</h2>
                    <p className="text-xs text-slate-500">Estimated completion: 3 mins 12 secs</p>
                  </div>
                  <button
                    onClick={resetSearch}
                    className="flex items-center gap-1.5 px-4 py-2 border border-blue-200 text-blue-600 rounded-xl text-xs font-bold hover:bg-blue-50 transition-all active:scale-95"
                  >
                    <X className="w-4 h-4" />
                    Background This Search
                  </button>
                </div>
                <div className="space-y-1">
                  {/* Step 1 - Completed */}
                  <div className="flex gap-4 items-start group">
                    <div className="mt-1">
                      <div className="w-6 h-6 rounded-full bg-emerald-100 flex items-center justify-center text-emerald-700">
                        <Check className="w-3.5 h-3.5" />
                      </div>
                      <div className="w-0.5 h-10 bg-emerald-100 mx-auto mt-1" />
                    </div>
                    <div className="flex-1 pb-3">
                      <p className="text-[10px] font-bold text-slate-500 uppercase tracking-wider">STEP 1</p>
                      <p className="text-sm text-slate-800 font-semibold">Connecting to LinkedIn...</p>
                      <p className="text-xs text-slate-400">API Handshake complete. Auth token refreshed.</p>
                    </div>
                  </div>

                  {/* Step 2 - Active */}
                  <div className="flex gap-4 items-start">
                    <div className="mt-1">
                      <div className="w-6 h-6 rounded-full bg-blue-600 flex items-center justify-center text-white relative">
                        <div className="absolute inset-0 rounded-full animate-ping bg-blue-400 opacity-30" />
                        <svg className="w-3.5 h-3.5 animate-spin" viewBox="0 0 24 24" fill="none">
                          <circle cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="3" strokeDasharray="31.4 31.4" />
                        </svg>
                      </div>
                      <div className="w-0.5 h-10 bg-slate-200 mx-auto mt-1" />
                    </div>
                    <div className="flex-1 pb-3">
                      <p className="text-[10px] font-bold text-blue-600 uppercase tracking-wider">ACTIVE</p>
                      <p className="text-sm text-slate-900 font-bold">Scanning Indeed &amp; Greenhouse...</p>
                      <div className="mt-1.5 w-full bg-slate-100 h-1.5 rounded-full overflow-hidden">
                        <div
                          className="bg-blue-600 h-full rounded-full transition-all duration-1000"
                          style={{ width: `${Math.min(progress, 90)}%` }}
                        />
                      </div>
                      <p className="text-xs text-slate-500 mt-1.5">
                        Found {Math.max(0, Math.floor(progress * 1.5))} candidates matching your query...
                      </p>
                    </div>
                  </div>

                  {/* Step 3 - Pending */}
                  <div className="flex gap-4 items-start opacity-50">
                    <div className="mt-1">
                      <div className="w-6 h-6 rounded-full bg-slate-100 flex items-center justify-center text-slate-400">
                        <Hourglass className="w-3.5 h-3.5" />
                      </div>
                    </div>
                    <div className="flex-1">
                      <p className="text-[10px] font-bold text-slate-500 uppercase tracking-wider">QUEUED</p>
                      <p className="text-sm text-slate-700">Aggregating &amp; Scoring Results</p>
                    </div>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </section>
      )}

      {/* Results Section - Only when search completes */}
      {phase === "results" && jobs.length > 0 && (
        <section className="max-w-5xl mx-auto mb-8">
          <div className="flex items-center justify-between mb-5">
            <div>
              <h2 className="text-lg font-bold text-slate-900">Results</h2>
              <p className="text-sm text-slate-500">
                Found {jobs.length} jobs{savedCount > 0 ? ` · ${savedCount} saved to database` : ""}
              </p>
            </div>
            <button
              onClick={resetSearch}
              className="text-xs font-bold text-blue-600 hover:text-blue-700 transition-colors"
            >
              New Search
            </button>
          </div>

          {/* Insight Cards */}
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4 mb-6">
            <div className="bg-white border border-slate-100 rounded-xl p-4 flex items-center gap-3 shadow-sm">
              <div className="w-10 h-10 rounded-lg bg-orange-50 flex items-center justify-center text-orange-700 shrink-0">
                <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z" />
                </svg>
              </div>
              <div>
                <p className="text-[10px] font-bold text-slate-400 uppercase tracking-wider">Market Saturation</p>
                <p className="text-lg font-bold text-slate-900">{jobs.length > 5 ? "High" : "Moderate"}</p>
              </div>
            </div>

            <div className="bg-white border border-slate-100 rounded-xl p-4 flex items-center gap-3 shadow-sm">
              <div className="w-10 h-10 rounded-lg bg-blue-50 flex items-center justify-center text-blue-600 shrink-0">
                <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 8c-1.657 0-3 .895-3 2s1.343 2 3 2 3 .895 3 2-1.343 2-3 2m0-8c1.11 0 2.08.402 2.599 1M12 8V7m0 1v8m0 0v1m0-1c-1.11 0-2.08-.402-2.599-1M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
                </svg>
              </div>
              <div>
                <p className="text-[10px] font-bold text-slate-400 uppercase tracking-wider">Avg. Salary Range</p>
                <p className="text-lg font-bold text-slate-900">
                  {jobs.some((j) => j.salary) ? "Varies" : "Not specified"}
                </p>
              </div>
            </div>

            <div className="bg-white border border-slate-100 rounded-xl p-4 flex items-center gap-3 shadow-sm">
              <div className="w-10 h-10 rounded-lg bg-emerald-50 flex items-center justify-center text-emerald-600 shrink-0">
                <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M17 20h5v-2a3 3 0 00-5.356-1.857M17 20H7m10 0v-2c0-.656-.126-1.283-.356-1.857M7 20H2v-2a3 3 0 015.356-1.857M7 20v-2c0-.656.126-1.283.356-1.857m0 0a5.002 5.002 0 019.288 0M15 7a3 3 0 11-6 0 3 3 0 016 0z" />
                </svg>
              </div>
              <div>
                <p className="text-[10px] font-bold text-slate-400 uppercase tracking-wider">Unique Employers</p>
                <p className="text-lg font-bold text-slate-900">
                  {new Set(jobs.map((j) => j.company)).size}
                </p>
              </div>
            </div>
          </div>

          {/* Job Results List */}
          <div className="bg-white border border-slate-100 rounded-2xl overflow-hidden shadow-sm">
            <div className="divide-y divide-slate-100">
              {jobs.map((job, idx) => (
                <div
                  key={job.id || idx}
                  className="p-5 hover:bg-slate-50/50 transition-colors cursor-pointer"
                  onClick={() => navigate(`/jobs/${job.id || ""}`)}
                >
                  <div className="flex items-start justify-between gap-4">
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2 mb-1">
                        <span
                          className={`text-[9px] font-extrabold tracking-wider border px-2 py-0.5 rounded uppercase shrink-0 ${getSourceStyles(job.source)}`}
                        >
                          {formatSource(job.source)}
                        </span>
                        {job.job_type && (
                          <span className="text-[9px] font-bold tracking-wider px-2 py-0.5 rounded border uppercase bg-slate-50 text-slate-600 border-slate-200 shrink-0">
                            {job.job_type}
                          </span>
                        )}
                      </div>
                      <h3 className="text-sm font-bold text-slate-900 line-clamp-1 mt-1">{job.title}</h3>
                      <p className="text-xs font-semibold text-slate-500 mt-0.5">
                        {job.company || "Unknown Company"}
                      </p>
                      <div className="flex items-center gap-3 mt-2">
                        {job.location && (
                          <span className="text-xs text-slate-400 flex items-center gap-1">
                            <MapPin className="w-3 h-3" />
                            {job.location}
                          </span>
                        )}
                        {job.salary && (
                          <span className="text-xs font-semibold text-emerald-600">{job.salary}</span>
                        )}
                      </div>
                      {job.skills && job.skills.length > 0 && (
                        <div className="flex flex-wrap gap-1.5 mt-2">
                          {job.skills.slice(0, 4).map((skill, sIdx) => (
                            <span
                              key={sIdx}
                              className="text-[10px] font-medium text-blue-700 bg-blue-50 border border-blue-100/50 px-2 py-0.5 rounded"
                            >
                              {skill}
                            </span>
                          ))}
                          {job.skills.length > 4 && (
                            <span className="text-[10px] font-medium text-slate-400">+{job.skills.length - 4} more</span>
                          )}
                        </div>
                      )}
                    </div>
                    <ChevronRight className="w-4 h-4 text-slate-300 shrink-0 mt-2" />
                  </div>
                </div>
              ))}
            </div>
          </div>
        </section>
      )}

      {/* Results - Empty State */}
      {phase === "results" && jobs.length === 0 && (
        <section className="max-w-4xl mx-auto mb-8">
          <div className="bg-white border border-slate-100 rounded-2xl p-12 text-center shadow-sm">
            <div className="w-14 h-14 rounded-full bg-slate-50 flex items-center justify-center mx-auto mb-3">
              <Search className="w-6 h-6 text-slate-400" />
            </div>
            <h3 className="text-base font-bold text-slate-800 mb-1">No jobs found</h3>
            <p className="text-sm text-slate-500 mb-4">Try a different search query or broader terms.</p>
            <button
              onClick={resetSearch}
              className="px-5 py-2 bg-slate-900 text-white text-xs font-bold rounded-xl hover:bg-slate-800 transition-colors"
            >
              New Search
            </button>
          </div>
        </section>
      )}

      {/* Engine Capabilities + Sidebar - show when idle */}
      {phase === "idle" && (
        <section className="grid grid-cols-1 lg:grid-cols-12 gap-6">
          {/* Engine Capabilities */}
          <div className="lg:col-span-8 bg-white border border-slate-100 rounded-2xl overflow-hidden shadow-sm">
            <div className="p-4 border-b border-slate-100 bg-slate-50/50 flex justify-between items-center">
              <h3 className="text-base font-bold text-slate-900">Engine Capabilities</h3>
              <span className="text-[10px] font-bold text-blue-600 bg-blue-50 px-2 py-1 rounded uppercase">PRO FEATURE</span>
            </div>
            <div className="p-6 grid grid-cols-1 md:grid-cols-2 gap-6">
              <div className="flex gap-4">
                <div className="w-10 h-10 rounded-lg bg-blue-50 flex items-center justify-center text-blue-600 shrink-0">
                  <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12l2 2 4-4m5.618-4.016A11.955 11.955 0 0112 2.944a11.955 11.955 0 01-8.618 3.04A12.02 12.02 0 003 9c0 5.591 3.824 10.29 9 11.622 5.176-1.332 9-6.03 9-11.622 0-1.042-.133-2.052-.382-3.016z" />
                  </svg>
                </div>
                <div>
                  <h4 className="text-sm font-bold text-slate-800">Identity Verification</h4>
                  <p className="text-xs text-slate-500 mt-1">
                    Automatically cross-references Github and LinkedIn profiles to ensure talent authenticity.
                  </p>
                </div>
              </div>
              <div className="flex gap-4">
                <div className="w-10 h-10 rounded-lg bg-blue-50 flex items-center justify-center text-blue-600 shrink-0">
                  <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 117.072 0l-.548.547A3.374 3.374 0 0014 18.469V19a2 2 0 11-4 0v-.531c0-.895-.356-1.754-.988-2.386l-.548-.547z" />
                  </svg>
                </div>
                <div>
                  <h4 className="text-sm font-bold text-slate-800">Semantic Analysis</h4>
                  <p className="text-xs text-slate-500 mt-1">
                    Understands "Python developer" vs "Data Scientist who knows Python" for better mapping.
                  </p>
                </div>
              </div>
              <div className="flex gap-4">
                <div className="w-10 h-10 rounded-lg bg-blue-50 flex items-center justify-center text-blue-600 shrink-0">
                  <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M3.055 11H5a2 2 0 012 2v1a2 2 0 002 2 2 2 0 012 2v2.945M8 3.935V5.5A2.5 2.5 0 0010.5 8h.5a2 2 0 012 2 2 2 0 104 0 2 2 0 012-2h1.064M15 20.488V18a2 2 0 012-2h3.064M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
                  </svg>
                </div>
                <div>
                  <h4 className="text-sm font-bold text-slate-800">Global Reach</h4>
                  <p className="text-xs text-slate-500 mt-1">
                    Scrapes international job boards and niche community forums across 40+ countries.
                  </p>
                </div>
              </div>
              <div className="flex gap-4">
                <div className="w-10 h-10 rounded-lg bg-blue-50 flex items-center justify-center text-blue-600 shrink-0">
                  <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 15v2m-6 4h12a2 2 0 002-2v-6a2 2 0 00-2-2H6a2 2 0 00-2 2v6a2 2 0 002 2zm10-10V7a4 4 0 00-8 0v4h8z" />
                  </svg>
                </div>
                <div>
                  <h4 className="text-sm font-bold text-slate-800">Privacy First</h4>
                  <p className="text-xs text-slate-500 mt-1">
                    Aggregated data is encrypted and GDPR compliant. We never store personal contact info.
                  </p>
                </div>
              </div>
            </div>
          </div>

          {/* Sidebar */}
          <div className="lg:col-span-4 space-y-4">
            {/* Recent Searches */}
            <div className="bg-gradient-to-br from-blue-700 to-indigo-900 text-white rounded-2xl p-5 shadow-lg relative overflow-hidden">
              <div className="absolute top-2 right-2 opacity-10 pointer-events-none">
                <svg className="w-20 h-20" fill="currentColor" viewBox="0 0 24 24">
                  <path d="M11 15h2v2h-2v-2zm0-8h2v6h-2V7zm1-5C6.47 2 2 6.48 2 12s4.47 10 10 10c5.53 0 10-4.48 10-10S17.53 2 12 2zm0 18c-4.41 0-8-3.59-8-8s3.59-8 8-8 8 3.59 8 8-3.59 8-8 8z" />
                </svg>
              </div>
              <h3 className="text-base font-bold mb-1">Recent Searches</h3>
              <p className="text-xs text-blue-200 mb-4">Quick jump back to your history</p>
              <div className="space-y-1.5">
                {recentSearches.map((search, idx) => (
                  <button
                    key={idx}
                    onClick={() => handleRecentClick(search)}
                    className="w-full flex items-center justify-between p-3 rounded-xl hover:bg-white/10 transition-colors text-left cursor-pointer"
                  >
                    <span className="text-sm font-medium">{search}</span>
                    <ChevronRight className="w-4 h-4 text-blue-200 shrink-0" />
                  </button>
                ))}
              </div>
            </div>

            {/* Search Tip */}
            <div className="bg-amber-50 border border-amber-100 rounded-2xl p-5">
              <div className="flex items-center gap-2 mb-3">
                <Lightbulb className="w-4 h-4 text-amber-600" />
                <h4 className="text-xs font-bold text-amber-800 uppercase tracking-wider">Search Tip</h4>
              </div>
              <p className="text-sm text-amber-900 leading-relaxed">
                Try adding "ex-Google" or "Ivy League" to filter for specific pedigree benchmarks in your discovery engine.
              </p>
            </div>
          </div>
        </section>
      )}

      {/* Bottom padding for scroll comfort */}
      <div className="h-8" />
    </div>
  );
};
