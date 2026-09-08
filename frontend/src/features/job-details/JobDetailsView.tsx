import React, { useEffect, useState, useRef } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { ArrowLeft, ExternalLink, Upload, CloudUpload, CheckCircle, Download, Sparkles, FileText, AlertCircle, X } from "lucide-react";
import { api, ApiError } from "@/services/api";
import type { PostingDetail, ResumeUploadResponse, ResumeTailorResponse } from "@/types";
import { sanitizeHtml, isHtmlContent, isTreeFormat, extractTreeText } from "@/utils/sanitize";
import { isPostingId } from "@/utils/postingId";

export const JobDetailsView: React.FC = () => {
  const { jobId } = useParams<{ jobId: string }>();
  const navigate = useNavigate();

  const [job, setJob] = useState<PostingDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Resume upload state
  const [uploadedResume, setUploadedResume] = useState<ResumeUploadResponse | null>(null);
  const [uploadLoading, setUploadLoading] = useState(false);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  // Tailoring state
  const [isTailoring, setIsTailoring] = useState(false);
  const [showResults, setShowResults] = useState(false);
  const [showLoadingState, setShowLoadingState] = useState(false);
  const [tailorResult, setTailorResult] = useState<ResumeTailorResponse | null>(null);
  const [tailorError, setTailorError] = useState<string | null>(null);

  // Download state (tracking which URL is being downloaded)
  const [downloadingUrls, setDownloadingUrls] = useState<Set<string>>(new Set());

  // A route param that isn't a posting id can only have come from a stale
  // link — the row-index URLs (/jobs/9, /jobs/0) the old Dashboard minted
  // still sit in tabs, history and bookmarks. Don't spend a request on it.
  const staleLink = !isPostingId(jobId);
  // The posting id is well formed but the backend has no such row (404) —
  // a removed posting, not a broken app. Retrying can't help, so that state
  // gets its own copy and no Retry button.
  const [notFound, setNotFound] = useState(false);
  // Bumped by Retry so the fetch effect re-runs after a transient failure.
  const [reloadKey, setReloadKey] = useState(0);

  useEffect(() => {
    // Nothing to fetch for a stale link. `loading` is left as-is and the
    // render guard below skips the spinner instead, so the effect stays
    // free of synchronous setState.
    if (staleLink || !jobId) return;

    const fetchJobDetail = async () => {
      setLoading(true);
      setError(null);
      setNotFound(false);
      try {
        const data = await api.getPostingById(jobId);
        setJob(data);

        // ── Hydrate resume lifecycle state from backend ──
        if (data.active_resume) {
          setUploadedResume({
            resume_id: data.active_resume.resume_id,
            cloudinary_url: data.active_resume.cloudinary_url,
            parsed_data: {
              name: data.active_resume.name,
              skills: data.active_resume.skills,
            },
            extracted_text_preview: "",
            processing_status: data.active_resume.processing_status,
          });
        }

        if (data.tailoring_status?.tailored && data.tailoring_status.download_urls) {
          const urls = data.tailoring_status.download_urls;
          setTailorResult({
            resume_id: data.tailoring_status.resume_id || "",
            job_id: data.tailoring_status.job_id || "",
            tailored_text: "",
            cover_letter: "",
            download_urls: {
              pdf: urls.pdf || "",
              docx: urls.docx || "",
              cover_letter_pdf: urls.cover_letter_pdf || null,
            },
          });
          setShowResults(true);
        }
      } catch (err) {
        if (err instanceof ApiError) {
          setNotFound(err.status === 404);
          setError(err.message);
        } else {
          setError("An unexpected error occurred while loading job details.");
        }
      } finally {
        setLoading(false);
      }
    };

    fetchJobDetail();
  }, [jobId, staleLink, reloadKey]);

  const handleFileSelect = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;

    // Validate file type
    const allowedTypes = [
      "application/pdf",
      "application/msword",
      "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ];
    if (!allowedTypes.includes(file.type)) {
      setUploadError("Invalid file type. Please upload a PDF or DOCX file.");
      return;
    }

    // Validate file size (10 MB)
    if (file.size > 10 * 1024 * 1024) {
      setUploadError("File too large. Maximum size is 10 MB.");
      return;
    }

    setUploadLoading(true);
    setUploadError(null);

    try {
      const result = await api.uploadResume(file);
      setUploadedResume(result);
      // New resume invalidates any previous tailoring
      setTailorResult(null);
      setShowResults(false);
      setUploadLoading(false);
    } catch (err) {
      setUploadLoading(false);
      if (err instanceof ApiError) {
        setUploadError(err.message);
      } else {
        setUploadError("An unexpected error occurred while uploading the resume.");
      }
    } finally {
      // Reset the file input so the same file can be re-uploaded
      if (fileInputRef.current) {
        fileInputRef.current.value = "";
      }
    }
  };

  const handleRemoveResume = () => {
    setUploadedResume(null);
    setUploadError(null);
    setShowResults(false);
    setTailorResult(null);
    setTailorError(null);
  };

  const handleTailorResume = async () => {
    if (!uploadedResume || !jobId || !job) return;

    setIsTailoring(true);
    setShowResults(false);
    setShowLoadingState(true);
    setTailorResult(null);
    setTailorError(null);

    try {
      const result = await api.tailorResume({
        resume_id: uploadedResume.resume_id,
        job_id: jobId,
      });

      setShowLoadingState(false);
      setShowResults(true);
      setTailorResult(result);
    } catch (err) {
      setShowLoadingState(false);
      let errorMsg = "Tailoring failed. Please try again.";
      if (err instanceof ApiError) {
        errorMsg = err.message;
      }
      setTailorError(errorMsg);
    } finally {
      setIsTailoring(false);
    }
  };

  const handleDownload = async (url: string, label: string) => {
    if (downloadingUrls.has(url)) return;

    setDownloadingUrls((prev) => new Set(prev).add(url));

    try {
      const { blob, filename } = await api.downloadFromUrl(url);

      // Create a blob URL and trigger download
      const blobUrl = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = blobUrl;
      anchor.download = filename;
      document.body.appendChild(anchor);
      anchor.click();

      // Clean up
      setTimeout(() => {
        document.body.removeChild(anchor);
        URL.revokeObjectURL(blobUrl);
      }, 100);
    } catch (err) {
      let errorMsg = `Failed to download ${label}. Please try again.`;
      if (err instanceof ApiError) {
        errorMsg = err.message;
      }
      setTailorError(errorMsg);
    } finally {
      setDownloadingUrls((prev) => {
        const next = new Set(prev);
        next.delete(url);
        return next;
      });
    }
  };

  const getSourceLabel = (src: string | null | undefined): string => {
    if (!src) return "UNKNOWN";
    return src.toUpperCase();
  };

  // ── Loading State ──
  // A stale link never starts a fetch, so it must never show the spinner.
  if (loading && !staleLink) {
    return (
      <div className="flex flex-col items-center justify-center py-24">
        <div className="w-12 h-12 border-[3px] border-blue-600 border-t-transparent rounded-full animate-spin mb-4" />
        <p className="font-semibold text-sm text-slate-700">Loading job details...</p>
        <p className="text-xs text-slate-400 mt-1">Fetching job specification</p>
      </div>
    );
  }

  // ── Error State ──
  //
  // Three outcomes, not one. A stale link and a removed posting are both
  // expected and both unfixable by retrying, so they get a plain
  // explanation and a way back to the dashboard; only a genuine failure
  // (network, 5xx) offers Retry. Collapsing all three into "Failed to Load
  // Job — Posting not found: 9" is what made a dead link look like a
  // broken app.
  if (staleLink || error || !job) {
    const unreachable = staleLink || notFound;
    const heading = staleLink
      ? "This link is out of date"
      : notFound
        ? "This posting is no longer available"
        : "Failed to Load Job";
    const message = staleLink
      ? "The address doesn't point at a real posting — it's left over from an older version of the dashboard. Open the job from the jobs list again."
      : notFound
        ? "It may have been taken down at the source, or the link may be from an older version of the dashboard."
        : error;

    return (
      <div className="max-w-lg mx-auto py-16 text-center">
        <div
          className={`w-16 h-16 rounded-full flex items-center justify-center mx-auto mb-4 ${
            unreachable ? "bg-amber-50" : "bg-red-50"
          }`}
        >
          <AlertCircle
            className={`w-6 h-6 ${unreachable ? "text-amber-500" : "text-red-500"}`}
          />
        </div>
        <h2 className="text-lg font-bold text-slate-900 mb-1">{heading}</h2>
        <p className="text-sm text-slate-500 mb-6">{message}</p>
        <div className="flex items-center justify-center gap-3">
          <button
            onClick={() => navigate("/")}
            className="inline-flex items-center gap-2 px-5 py-2.5 bg-slate-900 text-white text-sm font-bold rounded-xl hover:bg-slate-800 transition-all shadow-sm"
          >
            <ArrowLeft className="w-4 h-4" />
            Back to Jobs
          </button>
          {!unreachable && (
            <button
              onClick={() => setReloadKey((k) => k + 1)}
              className="inline-flex items-center gap-2 px-5 py-2.5 border border-slate-200 bg-white text-slate-700 text-sm font-bold rounded-xl hover:bg-slate-50 transition-all shadow-sm"
            >
              Retry
            </button>
          )}
        </div>
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
                    {job.location || "Remote"} • {job.company_name}
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
                <p className="text-[10px] font-bold uppercase text-slate-400 tracking-wider mb-1">Posted</p>
                <p className="text-sm font-bold text-slate-800">
                  {job.posted_at ? new Date(job.posted_at).toLocaleDateString() : "Unknown"}
                </p>
              </div>
              <div>
                <p className="text-[10px] font-bold uppercase text-slate-400 tracking-wider mb-1">Job Type</p>
                <p className="text-sm font-bold text-slate-800 capitalize">{job.employment_type || "Unknown"}</p>
              </div>
              <div>
                <p className="text-[10px] font-bold uppercase text-slate-400 tracking-wider mb-1">ID</p>
                <p className="text-sm font-bold text-slate-800">{job.id?.slice(-8).toUpperCase() || "N/A"}</p>
              </div>
            </div>

            {/* Job Description Content */}
            <div className="space-y-6">
              <div>
                <h2 className="text-base font-bold text-slate-900 mb-2">About the Role</h2>
                {job.description_text && isHtmlContent(job.description_text) ? (
                  <div
                    className="text-sm text-slate-600 leading-relaxed [&_h1]:text-lg [&_h1]:font-bold [&_h1]:text-slate-900 [&_h1]:mb-2 [&_h2]:text-base [&_h2]:font-bold [&_h2]:text-slate-900 [&_h2]:mb-2 [&_h3]:text-sm [&_h3]:font-semibold [&_h3]:text-slate-800 [&_h3]:mb-1 [&_ul]:list-disc [&_ul]:list-inside [&_ul]:space-y-1 [&_li]:text-sm [&_p]:mb-2 [&_strong]:font-semibold [&_a]:text-blue-600 [&_a]:underline [&_a]:hover:text-blue-800"
                    dangerouslySetInnerHTML={{ __html: sanitizeHtml(job.description_text) }}
                  />
                ) : job.description_text && isTreeFormat(job.description_text) ? (
                  <p className="text-sm text-slate-600 leading-relaxed whitespace-pre-wrap">
                    {extractTreeText(job.description_text)}
                  </p>
                ) : (
                  <p className="text-sm text-slate-600 leading-relaxed whitespace-pre-wrap">
                    {job.description_text || "No description provided."}
                  </p>
                )}
              </div>

              {job.tags && job.tags.length > 0 && (
                <div>
                  <h3 className="text-xs font-bold uppercase tracking-wider text-slate-500 mb-2">Tags</h3>
                  <div className="flex flex-wrap gap-2">
                    {job.tags.map((tag, idx) => (
                      <span
                        key={idx}
                        className="text-xs font-semibold text-blue-700 bg-blue-50 border border-blue-100/50 px-2.5 py-1 rounded-lg"
                      >
                        {tag}
                      </span>
                    ))}
                  </div>
                </div>
              )}

              {/* Source Badge */}
              <div className="flex items-center gap-2 pt-2 border-t border-slate-100">
                <span className="text-[10px] font-semibold text-slate-400 uppercase tracking-wider">Source:</span>
                <span className="text-[10px] font-extrabold tracking-wider border px-2.5 py-1 rounded-lg uppercase bg-emerald-50 text-emerald-700 border-emerald-200">
                  {getSourceLabel(job.provider)}
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

            {/* Hidden file input */}
            <input
              ref={fileInputRef}
              type="file"
              accept=".pdf,.doc,.docx,application/pdf,application/msword,application/vnd.openxmlformats-officedocument.wordprocessingml.document"
              className="hidden"
              onChange={handleFileSelect}
            />

            {/* Upload loading state */}
            {uploadLoading ? (
              <div className="flex flex-col items-center justify-center py-8">
                <div className="w-10 h-10 border-[3px] border-blue-200 border-t-blue-600 rounded-full animate-spin mb-3" />
                <p className="text-sm font-bold text-slate-700">Uploading Resume...</p>
                <p className="text-xs text-slate-400 mt-1">Parsing with AI & storing to cloud</p>
              </div>
            ) : uploadedResume ? (
              /* State B: Resume Uploaded Successfully */
              <div className="flex flex-col gap-4">
                <div className="flex items-center justify-between p-4 bg-slate-50 rounded-xl border border-slate-100 border-l-4 border-l-emerald-500">
                  <div className="flex items-center gap-3 min-w-0">
                    <FileText className="w-5 h-5 text-emerald-600 shrink-0" />
                    <div className="min-w-0">
                      <p className="text-xs font-bold text-slate-800 truncate">
                        {uploadedResume.parsed_data?.name || "Active Resume"}
                      </p>
                      <p className="text-[11px] text-slate-500 font-medium truncate">
                        ID: {uploadedResume.resume_id.slice(-8).toUpperCase()}
                      </p>
                    </div>
                  </div>
                  <span className="text-[10px] font-bold px-2 py-0.5 rounded bg-emerald-50 text-emerald-700 border border-emerald-200 uppercase shrink-0">
                    {uploadedResume.processing_status === "completed" ? "READY" : "PENDING"}
                  </span>
                </div>

                {/* Parsed skills preview */}
                {uploadedResume.parsed_data?.skills && uploadedResume.parsed_data.skills.length > 0 && (
                  <div className="flex flex-wrap gap-1.5">
                    {uploadedResume.parsed_data.skills.slice(0, 8).map((skill, idx) => (
                      <span
                        key={idx}
                        className="text-[10px] font-semibold text-slate-600 bg-white border border-slate-200 px-2 py-0.5 rounded-md"
                      >
                        {skill}
                      </span>
                    ))}
                    {uploadedResume.parsed_data.skills.length > 8 && (
                      <span className="text-[10px] font-medium text-slate-400 px-1 py-0.5">
                        +{uploadedResume.parsed_data.skills.length - 8} more
                      </span>
                    )}
                  </div>
                )}

                {/* Cloudinary link */}
                <a
                  href={uploadedResume.cloudinary_url}
                  target="_blank"
                  rel="noreferrer"
                  className="flex items-center justify-between p-3 bg-white border border-slate-200 rounded-xl hover:bg-slate-50 transition-colors group"
                >
                  <div className="flex items-center gap-2 min-w-0">
                    <CloudUpload className="w-4 h-4 text-slate-400 shrink-0" />
                    <span className="text-[11px] text-slate-500 font-medium truncate">
                      View on Cloudinary
                    </span>
                  </div>
                  <ExternalLink className="w-3.5 h-3.5 text-slate-400 group-hover:text-blue-600 transition-colors shrink-0" />
                </a>

                {/* Replace / Remove buttons */}
                <div className="flex gap-2">
                  <button
                    onClick={() => fileInputRef.current?.click()}
                    className="flex-1 flex items-center justify-center gap-2 py-2.5 bg-slate-100 text-slate-600 border border-slate-200 rounded-xl text-xs font-bold hover:bg-slate-200 transition-colors cursor-pointer"
                  >
                    <Upload className="w-4 h-4" />
                    Replace Resume
                  </button>
                  <button
                    onClick={handleRemoveResume}
                    className="flex items-center justify-center gap-2 py-2.5 px-3 bg-white text-red-500 border border-red-200 rounded-xl text-xs font-bold hover:bg-red-50 transition-colors cursor-pointer"
                  >
                    <X className="w-4 h-4" />
                  </button>
                </div>
              </div>
            ) : (
              /* State A: No Resume - Upload Area */
              <div>
                <button
                  onClick={() => fileInputRef.current?.click()}
                  className="w-full flex flex-col items-center justify-center gap-2 border-2 border-dashed border-slate-200 p-8 rounded-xl hover:bg-slate-50 transition-all group cursor-pointer"
                >
                  <CloudUpload className="w-10 h-10 text-slate-300 group-hover:text-blue-500 transition-colors" />
                  <span className="text-xs font-bold text-slate-700">Upload Resume</span>
                  <span className="text-[11px] text-slate-400">PDF, DOCX up to 10MB</span>
                </button>

                {uploadError && (
                  <div className="mt-3 flex items-start gap-2 p-3 bg-red-50 border border-red-100 rounded-xl">
                    <AlertCircle className="w-4 h-4 text-red-500 shrink-0 mt-0.5" />
                    <p className="text-xs text-red-700 font-medium">{uploadError}</p>
                  </div>
                )}
              </div>
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
                Our AI will analyze <span className="font-bold text-white">Job ID: {job.id?.slice(-8).toUpperCase() || "N/A"}</span>
                {uploadedResume ? (
                  <> and optimize <span className="font-bold text-white">Resume: {uploadedResume.parsed_data?.name || uploadedResume.resume_id.slice(-8).toUpperCase()}</span> to highlight the most relevant skills and experiences.</>
                ) : (
                  <> against your resume once uploaded.</>
                )}
              </p>
              <button
                onClick={handleTailorResume}
                disabled={isTailoring || !uploadedResume}
                className="w-full bg-white text-blue-800 py-3 rounded-xl text-xs font-bold hover:bg-blue-50 active:scale-[0.98] transition-all flex items-center justify-center gap-2 shadow-md disabled:opacity-50 disabled:cursor-not-allowed cursor-pointer"
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
          {showResults && tailorResult && (
            <div className="bg-white border-2 border-blue-100 rounded-2xl p-6 shadow-sm animate-fade-in">
              <div className="flex items-center gap-3 mb-5">
                <div className="w-10 h-10 bg-orange-50 rounded-full flex items-center justify-center">
                  <CheckCircle className="w-5 h-5 text-orange-600" />
                </div>
                <div>
                  <h3 className="text-sm font-bold text-slate-800">Generation Complete</h3>
                  <p className="text-xs text-slate-500">
                    Resume tailored for <span className="font-semibold">{job?.title || "position"}</span>
                  </p>
                </div>
              </div>

              <div className="space-y-3 mb-6">
                {uploadedResume && (
                  <div className="flex items-center justify-between p-3 bg-slate-50 rounded-lg border border-slate-100">
                    <div className="flex items-center gap-2">
                      <CloudUpload className="w-4 h-4 text-slate-400" />
                      <span className="text-xs text-slate-600 font-medium">Original Resume</span>
                    </div>
                    <a
                      href={uploadedResume.cloudinary_url}
                      target="_blank"
                      rel="noreferrer"
                      className="text-[11px] font-bold text-blue-600 hover:underline"
                    >
                      View on Cloudinary
                    </a>
                  </div>
                )}
              </div>

              {/* ATS Optimisation Metrics */}
              {tailorResult.keyword_coverage_pct !== undefined && (
                <div className="mb-4 p-3 bg-slate-50 rounded-lg border border-slate-200">
                  <div className="flex items-center justify-between mb-2">
                    <span className="text-xs font-semibold text-slate-600">ATS Match</span>
                    <span className={`text-xs font-bold px-2 py-0.5 rounded ${
                      tailorResult.keyword_coverage_pct >= 70
                        ? 'bg-green-100 text-green-700'
                        : tailorResult.keyword_coverage_pct >= 50
                        ? 'bg-yellow-100 text-yellow-700'
                        : 'bg-red-100 text-red-700'
                    }`}>
                      {tailorResult.keyword_coverage_pct}%
                    </span>
                  </div>
                  {tailorResult.paper_format && (
                    <p className="text-[10px] text-slate-400 mb-2">
                      Format: {tailorResult.paper_format === 'letter' ? 'Letter (US/Canada)' : 'A4 (Rest of World)'}
                    </p>
                  )}
                  {tailorResult.selected_project_count !== undefined && (
                    <p className="text-[10px] text-slate-400 mb-2">
                      {tailorResult.selected_project_count} most relevant projects selected
                    </p>
                  )}
                  {tailorResult.jd_keywords && tailorResult.jd_keywords.length > 0 && (
                    <details className="text-[11px]">
                      <summary className="cursor-pointer text-blue-600 hover:text-blue-800 font-medium">
                        {tailorResult.ats_keywords_matched?.length || 0}/{tailorResult.jd_keywords.length} keywords matched
                      </summary>
                      <div className="mt-2 flex flex-wrap gap-1">
                        {tailorResult.jd_keywords.map((kw, i) => {
                          const isMatched = tailorResult.ats_keywords_matched?.includes(kw);
                          return (
                            <span key={i} className={`px-2 py-0.5 rounded text-[10px] ${
                              isMatched ? 'bg-green-100 text-green-700' : 'bg-red-100 text-red-700'
                            }`}>
                              {kw}
                            </span>
                          );
                        })}
                      </div>
                    </details>
                  )}
                </div>
              )}

              {/* Download buttons */}
              <div className="flex flex-col gap-2">
                {tailorResult.download_urls.pdf && (
                  <button
                    onClick={() => handleDownload(tailorResult.download_urls.pdf, "Tailored Resume PDF")}
                    disabled={downloadingUrls.has(tailorResult.download_urls.pdf)}
                    className="w-full bg-blue-600 text-white py-3 rounded-xl text-xs font-bold hover:bg-blue-700 disabled:bg-blue-400 disabled:cursor-not-allowed flex items-center justify-center gap-2 shadow-sm transition-all cursor-pointer"
                  >
                    {downloadingUrls.has(tailorResult.download_urls.pdf) ? (
                      <div className="w-4 h-4 border-2 border-white border-t-transparent rounded-full animate-spin" />
                    ) : (
                      <Download className="w-4 h-4" />
                    )}
                    Download Tailored Resume (PDF)
                  </button>
                )}
                {tailorResult.download_urls.docx && (
                  <button
                    onClick={() => handleDownload(tailorResult.download_urls.docx, "Tailored Resume DOCX")}
                    disabled={downloadingUrls.has(tailorResult.download_urls.docx)}
                    className="w-full bg-white text-slate-700 border border-slate-200 py-2.5 rounded-xl text-xs font-bold hover:bg-slate-50 disabled:opacity-50 disabled:cursor-not-allowed flex items-center justify-center gap-2 shadow-sm transition-all cursor-pointer"
                  >
                    {downloadingUrls.has(tailorResult.download_urls.docx) ? (
                      <div className="w-4 h-4 border-2 border-slate-400 border-t-transparent rounded-full animate-spin" />
                    ) : (
                      <Download className="w-4 h-4" />
                    )}
                    Download Tailored Resume (DOCX)
                  </button>
                )}
                {tailorResult.download_urls.cover_letter_pdf && (
                  <button
                    onClick={() => handleDownload(tailorResult.download_urls.cover_letter_pdf!, "Cover Letter PDF")}
                    disabled={downloadingUrls.has(tailorResult.download_urls.cover_letter_pdf)}
                    className="w-full bg-indigo-50 text-indigo-700 border border-indigo-200 py-2.5 rounded-xl text-xs font-bold hover:bg-indigo-100 disabled:opacity-50 disabled:cursor-not-allowed flex items-center justify-center gap-2 shadow-sm transition-all cursor-pointer"
                  >
                    {downloadingUrls.has(tailorResult.download_urls.cover_letter_pdf) ? (
                      <div className="w-4 h-4 border-2 border-indigo-400 border-t-transparent rounded-full animate-spin" />
                    ) : (
                      <Download className="w-4 h-4" />
                    )}
                    Download Cover Letter (PDF)
                  </button>
                )}
              </div>
            </div>
          )}

          {/* Tailor Error */}
          {tailorError && (
            <div className="flex items-start gap-2 p-4 bg-red-50 border border-red-100 rounded-2xl animate-fade-in">
              <AlertCircle className="w-4 h-4 text-red-500 shrink-0 mt-0.5" />
              <p className="text-xs text-red-700 font-medium">{tailorError}</p>
            </div>
          )}
        </aside>
      </div>
    </div>
  );
};
