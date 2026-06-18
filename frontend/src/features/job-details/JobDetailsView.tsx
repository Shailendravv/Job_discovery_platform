import React, { useEffect, useState } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { ArrowLeft, ExternalLink, Upload, CloudUpload, CheckCircle, Download, Sparkles } from "lucide-react";
import { api, ApiError } from "@/services/api";
import type { JobDetail } from "@/types";

export const JobDetailsView: React.FC = () => {
  const { jobId } = useParams<{ jobId: string }>();
  const navigate = useNavigate();

  const [job, setJob] = useState<JobDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [hasResume, setHasResume] = useState(true); // Toggle between state A/B
  const [isTailoring, setIsTailoring] = useState(false);
  const [showResults, setShowResults] = useState(false);
  const [showLoadingState, setShowLoadingState] = useState(false);

  useEffect(() => {
    if (!jobId) return;

    const fetchJobDetail = async () => {
      setLoading(true);
      setError(null);
      try {
        const data = await api.getJobById(jobId);
        setJob(data);
      } catch (err) {
        if (err instanceof ApiError) {
          setError(err.message);
        } else {
          setError("An unexpected error occurred while loading job details.");
        }
      } finally {
        setLoading(false);
      }
    };

    fetchJobDetail();
  }, [jobId]);

  const handleTailorResume = () => {
    setIsTailoring(true);
    setShowResults(false);
    setShowLoadingState(false);

    // Simulate processing steps
    setTimeout(() => {
      setShowLoadingState(true);
    }, 1000);

    setTimeout(() => {
      setShowLoadingState(false);
      setShowResults(true);
      setIsTailoring(false);
    }, 3000);
  };

  const getSourceLabel = (src: string | null | undefined): string => {
    if (!src) return "UNKNOWN";
    const s = src.toLowerCase();
    if (s.includes("linkedin")) return "LINKEDIN";
    if (s.includes("indeed")) return "INDEED";
    if (s.includes("searx")) return "SEARXNG";
    return src.toUpperCase();
  };

  // ── Loading State ──
  if (loading) {
    return (
      <div className="flex flex-col items-center justify-center py-24">
        <div className="w-12 h-12 border-[3px] border-blue-600 border-t-transparent rounded-full animate-spin mb-4" />
        <p className="font-semibold text-sm text-slate-700">Loading job details...</p>
        <p className="text-xs text-slate-400 mt-1">Fetching job specification</p>
      </div>
    );
  }

  // ── Error State ──
  if (error || !job) {
    return (
      <div className="max-w-lg mx-auto py-16 text-center">
        <div className="w-16 h-16 rounded-full bg-red-50 flex items-center justify-center mx-auto mb-4">
          <ExternalLink className="w-6 h-6 text-red-500" />
        </div>
        <h2 className="text-lg font-bold text-slate-900 mb-1">Failed to Load Job</h2>
        <p className="text-sm text-slate-500 mb-6">{error || "Job not found"}</p>
        <button
          onClick={() => navigate("/")}
          className="inline-flex items-center gap-2 px-5 py-2.5 bg-slate-900 text-white text-sm font-bold rounded-xl hover:bg-slate-800 transition-all shadow-sm"
        >
          <ArrowLeft className="w-4 h-4" />
          Back to Jobs
        </button>
      </div>
    );
  }

  return (
    <div className="animate-fade-in">
      {/* Back Navigation */}
      <div className="mb-6">
        <button
          onClick={() => navigate("/")}
          className="inline-flex items-center gap-1.5 text-sm font-semibold text-slate-500 hover:text-slate-800 transition-colors group"
        >
          <ArrowLeft className="w-4 h-4 group-hover:-translate-x-0.5 transition-transform" />
          Back to Jobs
        </button>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-12 gap-6 items-start">
        {/* ── Left Pane: Job Spec ── */}
        <section className="lg:col-span-7 flex flex-col gap-6">
          {/* Hero Header Card */}
          <div className="bg-white border border-slate-100 rounded-2xl p-6 shadow-sm">
            {/* Header Row */}
            <div className="flex flex-col md:flex-row justify-between items-start md:items-center gap-4 mb-6">
              <div className="flex gap-4 items-center">
                <div className="w-16 h-16 bg-slate-50 rounded-xl flex items-center justify-center border border-slate-100 shrink-0">
                  <span className="text-3xl text-blue-600 font-bold">JS</span>
                </div>
                <div>
                  <h1 className="text-xl font-extrabold text-slate-900">{job.title}</h1>
                  <p className="text-sm text-slate-500 flex items-center gap-1 mt-0.5">
                    <svg className="w-4 h-4 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M17.657 16.657L13.414 20.9a1.998 1.998 0 01-2.827 0l-4.244-4.243a8 8 0 1111.314 0z" />
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 11a3 3 0 11-6 0 3 3 0 016 0z" />
                    </svg>
                    {job.location || "Remote"} • {job.company}
                  </p>
                </div>
              </div>
              <div className="flex gap-2 shrink-0">
                {job.url && (
                  <a
                    href={job.url}
                    target="_blank"
                    rel="noreferrer"
                    className="inline-flex items-center gap-1.5 px-4 py-2 bg-white border border-slate-200 text-slate-700 text-xs font-bold rounded-xl hover:bg-slate-50 transition-colors"
                  >
                    <ExternalLink className="w-3.5 h-3.5" />
                    Job URL
                  </a>
                )}
                {job.apply_url && (
                  <a
                    href={job.apply_url}
                    target="_blank"
                    rel="noreferrer"
                    className="inline-flex items-center gap-1.5 px-4 py-2 bg-blue-600 text-white text-xs font-bold rounded-xl hover:bg-blue-700 transition-all shadow-sm"
                  >
                    <ExternalLink className="w-3.5 h-3.5" />
                    Apply URL
                  </a>
                )}
              </div>
            </div>

            {/* Job Metadata Grid */}
            <div className="grid grid-cols-2 md:grid-cols-4 gap-4 p-4 bg-slate-50 rounded-xl border border-slate-100 mb-6">
              <div>
                <p className="text-[10px] font-bold uppercase text-slate-400 tracking-wider mb-1">Salary Range</p>
                <p className="text-sm font-bold text-slate-800">{job.salary || "Not specified"}</p>
              </div>
              <div>
                <p className="text-[10px] font-bold uppercase text-slate-400 tracking-wider mb-1">Experience</p>
                <p className="text-sm font-bold text-slate-800">{job.experience || "Not specified"}</p>
              </div>
              <div>
                <p className="text-[10px] font-bold uppercase text-slate-400 tracking-wider mb-1">Job Type</p>
                <p className="text-sm font-bold text-slate-800 capitalize">{job.job_type || "Unknown"}</p>
              </div>
              <div>
                <p className="text-[10px] font-bold uppercase text-slate-400 tracking-wider mb-1">ID</p>
                <p className="text-sm font-bold text-slate-800">{job.ref_id || job.id?.slice(-8).toUpperCase() || "N/A"}</p>
              </div>
            </div>

            {/* Job Description Content */}
            <div className="space-y-6">
              <div>
                <h2 className="text-base font-bold text-slate-900 mb-2">About the Role</h2>
                <p className="text-sm text-slate-600 leading-relaxed whitespace-pre-wrap">
                  {job.description || "No description provided."}
                </p>
              </div>

              {job.requirements && job.requirements.length > 0 && (
                <div>
                  <h3 className="text-xs font-bold uppercase tracking-wider text-slate-500 mb-2">Requirements</h3>
                  <ul className="list-disc list-inside text-sm text-slate-600 space-y-1">
                    {job.requirements.map((req, idx) => (
                      <li key={idx}>{req}</li>
                    ))}
                  </ul>
                </div>
              )}

              {job.skills && job.skills.length > 0 && (
                <div>
                  <h3 className="text-xs font-bold uppercase tracking-wider text-slate-500 mb-2">Required Skills</h3>
                  <div className="flex flex-wrap gap-2">
                    {job.skills.map((skill, idx) => (
                      <span
                        key={idx}
                        className="text-xs font-semibold text-blue-700 bg-blue-50 border border-blue-100/50 px-2.5 py-1 rounded-lg"
                      >
                        {skill}
                      </span>
                    ))}
                  </div>
                </div>
              )}

              {/* Source Badge */}
              <div className="flex items-center gap-2 pt-2 border-t border-slate-100">
                <span className="text-[10px] font-semibold text-slate-400 uppercase tracking-wider">Source:</span>
                <span className="text-[10px] font-extrabold tracking-wider border px-2.5 py-1 rounded-lg uppercase bg-emerald-50 text-emerald-700 border-emerald-200">
                  {getSourceLabel(job.source)}
                </span>
              </div>
            </div>
          </div>
        </section>

        {/* ── Right Pane: Resume Management & Tailoring ── */}
        <aside className="lg:col-span-5 flex flex-col gap-6 lg:sticky lg:top-[104px]">
          {/* Resume Management */}
          <div className="bg-white border border-slate-100 rounded-2xl p-6 shadow-sm relative overflow-hidden">
            {/* Decorative icon */}
            <div className="absolute top-2 right-2 opacity-5 pointer-events-none">
              <svg className="w-24 h-24 text-slate-500" fill="currentColor" viewBox="0 0 24 24">
                <path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8l-6-6zM6 20V4h7v5h5v11H6z" />
              </svg>
            </div>

            <h2 className="text-base font-bold text-slate-900 mb-4">Resume Management</h2>

            {hasResume ? (
              /* State B: Active Resume */
              <div className="flex flex-col gap-4">
                <div className="flex items-center justify-between p-4 bg-slate-50 rounded-xl border border-slate-100 border-l-4 border-l-blue-600">
                  <div className="flex items-center gap-3">
                    <CheckCircle className="w-5 h-5 text-blue-600 shrink-0" />
                    <div>
                      <p className="text-xs font-bold text-slate-800">Active Resume</p>
                      <p className="text-[11px] text-slate-500 font-medium">ID: {job.ref_id || `${job.id?.slice(-8).toUpperCase() || "MASTER"}`}</p>
                    </div>
                  </div>
                  <span className="text-[10px] font-bold px-2 py-0.5 rounded bg-blue-50 text-blue-700 border border-blue-100 uppercase">MASTER</span>
                </div>
                <button
                  onClick={() => setHasResume(false)}
                  className="w-full flex items-center justify-center gap-2 py-3 bg-slate-100 text-slate-600 border border-slate-200 rounded-xl text-xs font-bold hover:bg-slate-200 transition-colors cursor-pointer"
                >
                  <Upload className="w-4 h-4" />
                  Upload Latest Resume
                </button>
              </div>
            ) : (
              /* State A: No Resume - Upload */
              <button
                onClick={() => setHasResume(true)}
                className="w-full flex flex-col items-center justify-center gap-2 border-2 border-dashed border-slate-200 p-8 rounded-xl hover:bg-slate-50 transition-all group cursor-pointer"
              >
                <CloudUpload className="w-10 h-10 text-slate-300 group-hover:text-blue-500 transition-colors" />
                <span className="text-xs font-bold text-slate-700">Upload Resume</span>
                <span className="text-[11px] text-slate-400">PDF, DOCX up to 10MB</span>
              </button>
            )}
          </div>

          {/* AI Tailoring Engine */}
          <div className="bg-gradient-to-br from-blue-700 via-blue-800 to-indigo-900 rounded-2xl p-6 shadow-lg relative overflow-hidden">
            <div className="absolute inset-0 bg-gradient-to-br from-blue-600/20 via-transparent to-indigo-800/20 pointer-events-none" />
            <div className="relative z-10">
              <div className="flex items-center justify-between mb-3">
                <h2 className="text-base font-bold text-white">AI Tailoring Engine</h2>
                <Sparkles className="w-5 h-5 text-blue-200 animate-pulse" />
              </div>
              <p className="text-sm text-blue-100 mb-5 leading-relaxed">
                Our AI will analyze <span className="font-bold text-white">Job ID: {job.ref_id || job.id?.slice(-8).toUpperCase() || "N/A"}</span> and optimize <span className="font-bold text-white">Resume ID: {job.ref_id ? `${job.ref_id}-RES` : "RES-8821"}</span> to highlight the most relevant skills and experiences.
              </p>
              <button
                onClick={handleTailorResume}
                disabled={isTailoring}
                className="w-full bg-white text-blue-800 py-3 rounded-xl text-xs font-bold hover:bg-blue-50 active:scale-[0.98] transition-all flex items-center justify-center gap-2 shadow-md disabled:opacity-60 disabled:cursor-not-allowed cursor-pointer"
              >
                {isTailoring ? (
                  <>
                    <div className="w-4 h-4 border-2 border-blue-800 border-t-transparent rounded-full animate-spin" />
                    Processing...
                  </>
                ) : (
                  "Tailor Resume"
                )}
              </button>
            </div>
          </div>

          {/* Loading State */}
          {showLoadingState && (
            <div className="flex flex-col items-center justify-center py-10 bg-white border border-slate-100 border-dashed rounded-2xl animate-fade-in">
              <div className="w-10 h-10 border-3 border-blue-200 border-t-blue-600 rounded-full animate-spin mb-3" />
              <p className="text-sm font-bold text-slate-700">Synthesizing Content...</p>
              <p className="text-xs text-slate-400 mt-1">Analyzing job requirements vs. your experience</p>
            </div>
          )}

          {/* Results Panel */}
          {showResults && (
            <div className="bg-white border-2 border-blue-100 rounded-2xl p-6 shadow-sm animate-fade-in">
              <div className="flex items-center gap-3 mb-5">
                <div className="w-10 h-10 bg-orange-50 rounded-full flex items-center justify-center">
                  <CheckCircle className="w-5 h-5 text-orange-600" />
                </div>
                <div>
                  <h3 className="text-sm font-bold text-slate-800">Generation Complete</h3>
                  <p className="text-xs text-slate-500">98% Job Match Score</p>
                </div>
              </div>

              <div className="space-y-3 mb-6">
                <div className="flex items-center justify-between p-3 bg-slate-50 rounded-lg border border-slate-100">
                  <div className="flex items-center gap-2">
                    <ExternalLink className="w-4 h-4 text-slate-400" />
                    <span className="text-xs text-slate-600 font-medium">View Document Source</span>
                  </div>
                  <a
                    href={job.apply_url || job.url || "#"}
                    target="_blank"
                    rel="noreferrer"
                    className="text-[11px] font-bold text-blue-600 hover:underline"
                  >
                    Cloudinary URL
                  </a>
                </div>
              </div>

              <button className="w-full bg-blue-600 text-white py-3 rounded-xl text-xs font-bold hover:bg-blue-700 flex items-center justify-center gap-2 shadow-sm transition-all cursor-pointer">
                <Download className="w-4 h-4" />
                Download Tailored Resume and Cover Letter
              </button>
            </div>
          )}
        </aside>
      </div>
    </div>
  );
};
