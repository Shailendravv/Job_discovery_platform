import React, { useState, useEffect } from "react";
import { useApp } from "@/context/AppContext";
import type { Job } from "@/types";
import { 
  Search, 
  ChevronDown, 
  ArrowUpDown, 
  MapPin, 
  Briefcase, 
  ChevronLeft, 
  ChevronRight, 
  ExternalLink,
  X,
  SlidersHorizontal,
  Calendar,
  DollarSign
} from "lucide-react";

export const DashboardView: React.FC = () => {
  const {
    jobs,
    pagination,
    filters,
    sort,
    loading,
    error,
    setPage,
    setLimit,
    setSearchQuery,
    setSourceFilter,
    setJobTypeFilter,
    setLocationFilter,
    setSortOptions,
    resetFilters
  } = useApp();

  // Local state for debounced search input
  const [searchTerm, setSearchTerm] = useState(filters.q);
  // Selected job for detail modal
  const [selectedJob, setSelectedJob] = useState<Job | null>(null);

  // Dropdown states
  const [showSourceDropdown, setShowSourceDropdown] = useState(false);
  const [showTypeDropdown, setShowTypeDropdown] = useState(false);
  const [showSortDropdown, setShowSortDropdown] = useState(false);

  // List of unique sources & types to filter on (can also be queried dynamically)
  const sources = ["linkedin", "indeed", "searxng"];
  const jobTypes = ["remote", "on-site", "hybrid", "full-time", "part-time", "contract"];

  // Debounce search query input
  useEffect(() => {
    const delayDebounce = setTimeout(() => {
      if (searchTerm !== filters.q) {
        setSearchQuery(searchTerm);
      }
    }, 400);

    return () => clearTimeout(delayDebounce);
  }, [searchTerm, setSearchQuery, filters.q]);

  // Sync search input if filters reset
  useEffect(() => {
    let active = true;
    if (active) {
      Promise.resolve().then(() => {
        setSearchTerm(filters.q);
      });
    }
    return () => {
      active = false;
    };
  }, [filters.q]);

  const handleSortChange = (field: typeof sort.sort_by) => {
    const isSameField = sort.sort_by === field;
    const nextOrder = isSameField && sort.sort_order === "desc" ? "asc" : "desc";
    setSortOptions(field, nextOrder);
    setShowSortDropdown(false);
  };

  const formatSource = (src: string | null | undefined) => {
    if (!src) return "UNKNOWN";
    const s = src.toLowerCase();
    if (s.includes("linkedin")) return "LINKEDIN";
    if (s.includes("indeed")) return "INDEED";
    if (s.includes("searx")) return "SEARXNG";
    return src.toUpperCase();
  };

  // Badge styles helper
  const getSourceStyles = (src: string | null | undefined) => {
    const formatted = formatSource(src);
    switch (formatted) {
      case "LINKEDIN":
        return "border-blue-200 text-blue-700 bg-blue-50/50 hover:bg-blue-50";
      case "INDEED":
        return "border-orange-200 text-orange-700 bg-orange-50/50 hover:bg-orange-50";
      case "SEARXNG":
        return "border-emerald-200 text-emerald-700 bg-emerald-50/50 hover:bg-emerald-50";
      default:
        return "border-slate-200 text-slate-600 bg-slate-50";
    }
  };

  const getJobTypeStyles = (type: string | null | undefined) => {
    const t = (type || "").toLowerCase();
    if (t.includes("remote")) {
      return "bg-emerald-50 text-emerald-700 border-emerald-200";
    } else if (t.includes("site") || t.includes("office")) {
      return "bg-blue-50 text-blue-700 border-blue-200";
    } else if (t.includes("hybrid")) {
      return "bg-indigo-50 text-indigo-700 border-indigo-200";
    }
    return "bg-slate-50 text-slate-600 border-slate-200";
  };

  // Pagination calculation
  const currentPage = pagination?.page || 1;
  const totalEntries = pagination?.total || 0;
  const limit = pagination?.limit || 10;
  const totalPages = pagination?.pages || 1;
  const startIndex = totalEntries === 0 ? 0 : (currentPage - 1) * limit + 1;
  const endIndex = Math.min(currentPage * limit, totalEntries);

  return (
    <div className="space-y-6">
      {/* Title & Stats */}
      <div className="flex flex-col md:flex-row md:items-center md:justify-between gap-4">
        <div>
          <h1 className="text-3xl font-extrabold tracking-tight text-slate-900 m-0">Job Pipeline</h1>
          <p className="text-sm text-slate-500 mt-1 font-medium">
            Manage and track your high-priority job opportunities.
          </p>
        </div>
        <div className="bg-white border border-slate-100 rounded-xl px-5 py-3.5 shadow-sm flex items-center justify-between gap-6 self-start md:self-auto min-w-[180px]">
          <span className="text-sm font-semibold text-slate-500">Active Jobs:</span>
          <span className="text-2xl font-extrabold text-blue-600 animate-pulse">
            {totalEntries}
          </span>
        </div>
      </div>

      {/* Filters & Actions Panel */}
      <div className="bg-white rounded-2xl border border-slate-100 shadow-sm p-4 space-y-4">
        <div className="flex flex-col lg:flex-row gap-3">
          {/* Search bar */}
          <div className="relative flex-1">
            <Search className="absolute left-3.5 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-400" />
            <input
              type="text"
              placeholder="Search jobs by title, company, or keywords..."
              value={searchTerm}
              onChange={(e) => setSearchTerm(e.target.value)}
              className="w-full pl-10 pr-4 py-2.5 bg-slate-50/50 hover:bg-slate-50 border border-slate-200 rounded-xl text-sm focus:bg-white focus:ring-2 focus:ring-blue-500/10 focus:border-blue-500 transition-all outline-none"
            />
            {searchTerm && (
              <button
                onClick={() => setSearchTerm("")}
                className="absolute right-3 top-1/2 -translate-y-1/2 p-0.5 text-slate-400 hover:text-slate-600 rounded-md hover:bg-slate-200/50 transition-colors"
              >
                <X className="w-3.5 h-3.5" />
              </button>
            )}
          </div>

          {/* Filter Dropdowns */}
          <div className="flex flex-wrap sm:flex-nowrap gap-2">
            {/* Source Filter */}
            <div className="relative flex-1 sm:flex-none">
              <button
                onClick={() => {
                  setShowSourceDropdown(!showSourceDropdown);
                  setShowTypeDropdown(false);
                  setShowSortDropdown(false);
                }}
                className={`w-full sm:w-auto flex items-center justify-between space-x-2 px-4 py-2.5 border rounded-xl text-sm font-semibold transition-all duration-200 outline-none ${
                  filters.source 
                    ? "border-blue-500 bg-blue-50/30 text-blue-700 hover:bg-blue-50/50" 
                    : "border-slate-200 bg-white hover:border-slate-300 text-slate-700"
                }`}
              >
                <span className="capitalize">{filters.source || "Source"}</span>
                <ChevronDown className={`w-4 h-4 text-slate-400 transition-transform ${showSourceDropdown ? "rotate-180" : ""}`} />
              </button>
              {showSourceDropdown && (
                <>
                  <div className="fixed inset-0 z-10" onClick={() => setShowSourceDropdown(false)} />
                  <div className="absolute right-0 left-0 sm:left-auto sm:right-0 mt-2 w-full sm:w-44 bg-white border border-slate-100 rounded-xl shadow-lg z-20 py-1.5 animate-fade-in">
                    <button
                      onClick={() => {
                        setSourceFilter("");
                        setShowSourceDropdown(false);
                      }}
                      className="w-full text-left px-4 py-2 text-xs font-semibold text-rose-600 hover:bg-rose-50 transition-colors"
                    >
                      Clear Source
                    </button>
                    {sources.map((src) => (
                      <button
                        key={src}
                        onClick={() => {
                          setSourceFilter(src);
                          setShowSourceDropdown(false);
                        }}
                        className={`w-full text-left px-4 py-2 text-xs font-semibold hover:bg-slate-50 transition-colors ${
                          filters.source === src ? "text-blue-600 bg-blue-50/30" : "text-slate-700"
                        }`}
                      >
                        {formatSource(src)}
                      </button>
                    ))}
                  </div>
                </>
              )}
            </div>

            {/* Job Type Filter */}
            <div className="relative flex-1 sm:flex-none">
              <button
                onClick={() => {
                  setShowTypeDropdown(!showTypeDropdown);
                  setShowSourceDropdown(false);
                  setShowSortDropdown(false);
                }}
                className={`w-full sm:w-auto flex items-center justify-between space-x-2 px-4 py-2.5 border rounded-xl text-sm font-semibold transition-all duration-200 outline-none ${
                  filters.job_type 
                    ? "border-blue-500 bg-blue-50/30 text-blue-700 hover:bg-blue-50/50" 
                    : "border-slate-200 bg-white hover:border-slate-300 text-slate-700"
                }`}
              >
                <span className="capitalize">{filters.job_type || "Job Type"}</span>
                <ChevronDown className={`w-4 h-4 text-slate-400 transition-transform ${showTypeDropdown ? "rotate-180" : ""}`} />
              </button>
              {showTypeDropdown && (
                <>
                  <div className="fixed inset-0 z-10" onClick={() => setShowTypeDropdown(false)} />
                  <div className="absolute right-0 left-0 sm:left-auto sm:right-0 mt-2 w-full sm:w-44 bg-white border border-slate-100 rounded-xl shadow-lg z-20 py-1.5 animate-fade-in">
                    <button
                      onClick={() => {
                        setJobTypeFilter("");
                        setShowTypeDropdown(false);
                      }}
                      className="w-full text-left px-4 py-2 text-xs font-semibold text-rose-600 hover:bg-rose-50 transition-colors"
                    >
                      Clear Job Type
                    </button>
                    {jobTypes.map((type) => (
                      <button
                        key={type}
                        onClick={() => {
                          setJobTypeFilter(type);
                          setShowTypeDropdown(false);
                        }}
                        className={`w-full text-left px-4 py-2 text-xs font-semibold hover:bg-slate-50 transition-colors ${
                          filters.job_type === type ? "text-blue-600 bg-blue-50/30" : "text-slate-700"
                        }`}
                      >
                        <span className="capitalize">{type}</span>
                      </button>
                    ))}
                  </div>
                </>
              )}
            </div>

            {/* Location Input Filter */}
            <div className="relative flex-1 sm:flex-none">
              <input
                type="text"
                placeholder="Location..."
                value={filters.location}
                onChange={(e) => setLocationFilter(e.target.value)}
                className="w-full sm:w-36 px-4 py-2.5 bg-white border border-slate-200 rounded-xl text-sm font-medium hover:border-slate-300 focus:border-blue-500 focus:ring-2 focus:ring-blue-500/10 transition-all outline-none"
              />
            </div>

            {/* Sort Dropdown */}
            <div className="relative flex-1 sm:flex-none">
              <button
                onClick={() => {
                  setShowSortDropdown(!showSortDropdown);
                  setShowSourceDropdown(false);
                  setShowTypeDropdown(false);
                }}
                className="w-full sm:w-auto flex items-center justify-between space-x-2 px-4 py-2.5 border border-slate-200 bg-white hover:border-slate-300 rounded-xl text-sm font-semibold text-slate-700 transition-all duration-200 outline-none"
              >
                <div className="flex items-center space-x-1.5">
                  <SlidersHorizontal className="w-3.5 h-3.5 text-slate-400" />
                  <span className="capitalize">
                    Sort by: {sort.sort_by === "created_at" ? "Date Created" : sort.sort_by}
                  </span>
                </div>
                <ArrowUpDown className="w-3.5 h-3.5 text-slate-400" />
              </button>
              {showSortDropdown && (
                <>
                  <div className="fixed inset-0 z-10" onClick={() => setShowSortDropdown(false)} />
                  <div className="absolute right-0 mt-2 w-full sm:w-48 bg-white border border-slate-100 rounded-xl shadow-lg z-20 py-1.5 animate-fade-in">
                    <button
                      onClick={() => handleSortChange("created_at")}
                      className={`w-full text-left px-4 py-2.5 text-xs font-semibold hover:bg-slate-50 transition-colors ${
                        sort.sort_by === "created_at" ? "text-blue-600 bg-blue-50/30" : "text-slate-700"
                      }`}
                    >
                      Date Created ({sort.sort_by === "created_at" ? sort.sort_order : "desc"})
                    </button>
                    <button
                      onClick={() => handleSortChange("title")}
                      className={`w-full text-left px-4 py-2.5 text-xs font-semibold hover:bg-slate-50 transition-colors ${
                        sort.sort_by === "title" ? "text-blue-600 bg-blue-50/30" : "text-slate-700"
                      }`}
                    >
                      Job Title ({sort.sort_by === "title" ? sort.sort_order : "asc"})
                    </button>
                    <button
                      onClick={() => handleSortChange("company")}
                      className={`w-full text-left px-4 py-2.5 text-xs font-semibold hover:bg-slate-50 transition-colors ${
                        sort.sort_by === "company" ? "text-blue-600 bg-blue-50/30" : "text-slate-700"
                      }`}
                    >
                      Company ({sort.sort_by === "company" ? sort.sort_order : "asc"})
                    </button>
                  </div>
                </>
              )}
            </div>

            {/* Clear All Filters */}
            {(filters.q || filters.source || filters.job_type || filters.location || sort.sort_by !== "created_at") && (
              <button
                onClick={resetFilters}
                className="w-full sm:w-auto px-3 py-2.5 text-slate-500 hover:text-slate-800 text-xs font-semibold transition-colors duration-150 flex items-center justify-center space-x-1"
              >
                <span>Reset</span>
              </button>
            )}
          </div>
        </div>
      </div>

      {/* Jobs Listing Table */}
      <div className="bg-white rounded-2xl border border-slate-100 shadow-sm overflow-hidden animate-fade-in">
        {error && (
          <div className="p-6 text-center border-b border-slate-100 bg-rose-50/30">
            <p className="text-sm font-semibold text-rose-600">{error}</p>
          </div>
        )}

        <div className="overflow-x-auto">
          <table className="w-full min-w-[800px] text-left border-collapse">
            <thead>
              <tr className="border-b border-slate-100 bg-slate-50/40 text-[11px] font-extrabold tracking-wider text-slate-400 uppercase">
                <th className="px-6 py-4 font-bold">Job Title & Company</th>
                <th className="px-6 py-4 font-bold">Location & Type</th>
                <th className="px-6 py-4 font-bold">Skills</th>
                <th className="px-6 py-4 font-bold">Source</th>
                <th className="px-6 py-4 font-bold text-center">Action</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100 text-sm">
              {loading ? (
                <tr>
                  <td colSpan={5} className="py-24 text-center">
                    <div className="inline-block w-8 h-8 border-[3px] border-blue-500 border-t-transparent rounded-full animate-spin" />
                    <p className="text-slate-400 font-semibold text-xs mt-3">Loading pipeline details...</p>
                  </td>
                </tr>
              ) : jobs.length === 0 ? (
                <tr>
                  <td colSpan={5} className="py-20 text-center">
                    <div className="w-12 h-12 rounded-full bg-slate-50 flex items-center justify-center mx-auto mb-3">
                      <Briefcase className="w-5 h-5 text-slate-400" />
                    </div>
                    <p className="text-slate-800 font-bold text-sm">No jobs found</p>
                    <p className="text-slate-400 text-xs mt-1">Try resetting the filters or modifying your query.</p>
                  </td>
                </tr>
              ) : (
                jobs.map((job, idx) => (
                  <tr 
                    key={job.id || idx} 
                    className="hover:bg-slate-50/70 transition-colors"
                  >
                    {/* Job Title & Company */}
                    <td className="px-6 py-4.5 max-w-[280px]">
                      <div className="font-bold text-slate-900 line-clamp-1 hover:underline cursor-pointer" onClick={() => setSelectedJob(job)}>
                        {job.title}
                      </div>
                      <div className="text-xs font-semibold text-slate-400 mt-1 line-clamp-1">
                        {job.company || "Unknown"}
                      </div>
                    </td>

                    {/* Location & Type */}
                    <td className="px-6 py-4.5">
                      <div className="flex flex-col gap-1.5 items-start">
                        <span className="text-xs font-semibold text-slate-600 flex items-center">
                          <MapPin className="w-3.5 h-3.5 text-slate-400 mr-1 shrink-0" />
                          {job.location || "Remote"}
                        </span>
                        {job.job_type && (
                          <span className={`text-[9px] font-bold tracking-wider px-2 py-0.5 rounded-full border uppercase shrink-0 ${getJobTypeStyles(job.job_type)}`}>
                            {job.job_type}
                          </span>
                        )}
                      </div>
                    </td>

                    {/* Skills Tags */}
                    <td className="px-6 py-4.5 max-w-[260px]">
                      <div className="flex flex-wrap gap-1.5 max-h-[50px] overflow-hidden">
                        {job.skills && job.skills.length > 0 ? (
                          job.skills.map((skill, sIdx) => (
                            <span 
                              key={sIdx}
                              className="text-[10px] font-semibold text-blue-700 bg-blue-50 border border-blue-100/50 px-2 py-0.5 rounded-md"
                            >
                              {skill}
                            </span>
                          ))
                        ) : (
                          <span className="text-[10px] font-medium text-slate-400 italic">No skill tags</span>
                        )}
                      </div>
                    </td>

                    {/* Source Badge */}
                    <td className="px-6 py-4.5">
                      <div className="flex items-center">
                        <span className={`text-[10px] font-extrabold tracking-wider border px-2.5 py-1 rounded-lg shrink-0 transition-colors uppercase ${getSourceStyles(job.source)}`}>
                          {formatSource(job.source)}
                        </span>
                      </div>
                    </td>

                    {/* Action Button */}
                    <td className="px-6 py-4.5 text-center">
                      <button
                        onClick={() => setSelectedJob(job)}
                        className="inline-flex items-center justify-center px-4 py-2 bg-slate-900 hover:bg-slate-800 text-white font-bold text-xs tracking-wide rounded-xl shadow-sm hover:shadow transition-all duration-150 cursor-pointer"
                      >
                        View Details
                      </button>
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>

        {/* Table Pagination Footer */}
        {pagination && totalEntries > 0 && (
          <div className="px-6 py-4 bg-slate-50/50 border-t border-slate-100 flex flex-col md:flex-row items-center justify-between gap-4 text-xs font-semibold text-slate-500">
            <div>
              Showing <span className="font-bold text-slate-800">{startIndex}</span> to{" "}
              <span className="font-bold text-slate-800">{endIndex}</span> of{" "}
              <span className="font-bold text-slate-800">{totalEntries}</span> entries
            </div>

            <div className="flex items-center space-x-6">
              {/* Rows Per Page */}
              <div className="flex items-center space-x-2">
                <span>Rows per page</span>
                <div className="relative">
                  <select
                    value={limit}
                    onChange={(e) => setLimit(Number(e.target.value))}
                    className="appearance-none bg-white border border-slate-200 hover:border-slate-300 rounded-lg pl-3 pr-8 py-1.5 focus:outline-none focus:border-blue-500 font-bold text-slate-700 text-xs shadow-sm"
                  >
                    <option value={10}>10</option>
                    <option value={20}>20</option>
                    <option value={50}>50</option>
                  </select>
                  <ChevronDown className="w-3.5 h-3.5 text-slate-400 absolute right-2.5 top-1/2 -translate-y-1/2 pointer-events-none" />
                </div>
              </div>

              {/* Prev/Next buttons */}
              <div className="flex items-center space-x-1">
                <button
                  onClick={() => setPage(Math.max(1, currentPage - 1))}
                  disabled={currentPage === 1}
                  className="p-1.5 border border-slate-200 bg-white hover:bg-slate-50 text-slate-500 hover:text-slate-800 rounded-lg disabled:opacity-40 disabled:hover:bg-white disabled:pointer-events-none transition-colors"
                >
                  <ChevronLeft className="w-4 h-4" />
                </button>

                {Array.from({ length: totalPages }, (_, idx) => idx + 1)
                  .filter((p) => Math.abs(p - currentPage) <= 1 || p === 1 || p === totalPages)
                  .map((p, idx, arr) => {
                    const isPrevGap = idx > 0 && p - arr[idx - 1] > 1;
                    return (
                      <React.Fragment key={p}>
                        {isPrevGap && <span className="px-1 text-slate-400">...</span>}
                        <button
                          onClick={() => setPage(p)}
                          className={`w-7.5 h-7.5 rounded-lg flex items-center justify-center transition-all ${
                            currentPage === p
                              ? "bg-slate-900 text-white shadow"
                              : "border border-slate-200 bg-white hover:bg-slate-50 text-slate-600 hover:text-slate-800"
                          }`}
                        >
                          {p}
                        </button>
                      </React.Fragment>
                    );
                  })}

                <button
                  onClick={() => setPage(Math.min(totalPages, currentPage + 1))}
                  disabled={currentPage === totalPages}
                  className="p-1.5 border border-slate-200 bg-white hover:bg-slate-50 text-slate-500 hover:text-slate-800 rounded-lg disabled:opacity-40 disabled:hover:bg-white disabled:pointer-events-none transition-colors"
                >
                  <ChevronRight className="w-4 h-4" />
                </button>
              </div>
            </div>
          </div>
        )}
      </div>

      {/* Drawer / Center Detail Modal */}
      {selectedJob && (
        <div className="fixed inset-0 z-50 flex items-center justify-end overflow-hidden bg-slate-900/40 backdrop-blur-xs transition-opacity duration-300">
          {/* Backdrop Click */}
          <div className="absolute inset-0" onClick={() => setSelectedJob(null)} />
          
          {/* Content Pane */}
          <div className="relative w-full max-w-2xl h-full bg-white shadow-2xl flex flex-col animate-slide-in">
            {/* Header */}
            <div className="p-6 border-b border-slate-100 flex items-center justify-between bg-slate-50/50">
              <div>
                <div className="flex items-center space-x-2">
                  <span className={`text-[9px] font-extrabold tracking-wider border px-2 py-0.5 rounded-md ${getSourceStyles(selectedJob.source)}`}>
                    {formatSource(selectedJob.source)}
                  </span>
                  {selectedJob.job_type && (
                    <span className={`text-[9px] font-bold tracking-wider px-2 py-0.5 rounded-md border uppercase ${getJobTypeStyles(selectedJob.job_type)}`}>
                      {selectedJob.job_type}
                    </span>
                  )}
                </div>
                <h2 className="text-xl font-extrabold text-slate-950 mt-2 line-clamp-1">{selectedJob.title}</h2>
                <p className="text-sm font-semibold text-slate-400 mt-0.5">{selectedJob.company || "Unknown company"}</p>
              </div>
              <button
                onClick={() => setSelectedJob(null)}
                className="p-2 text-slate-400 hover:text-slate-600 rounded-xl hover:bg-slate-100 transition-colors"
              >
                <X className="w-5 h-5" />
              </button>
            </div>

            {/* Modal Body */}
            <div className="flex-1 overflow-y-auto p-6 space-y-6">
              {/* Quick Info Grid */}
              <div className="grid grid-cols-2 sm:grid-cols-3 gap-4">
                <div className="bg-slate-50 rounded-xl p-3 flex items-center space-x-3">
                  <MapPin className="w-4 h-4 text-slate-400 shrink-0" />
                  <div>
                    <div className="text-[10px] font-bold uppercase text-slate-400">Location</div>
                    <div className="text-xs font-semibold text-slate-800">{selectedJob.location || "Remote"}</div>
                  </div>
                </div>

                <div className="bg-slate-50 rounded-xl p-3 flex items-center space-x-3">
                  <DollarSign className="w-4 h-4 text-slate-400 shrink-0" />
                  <div>
                    <div className="text-[10px] font-bold uppercase text-slate-400">Salary</div>
                    <div className="text-xs font-semibold text-slate-800">{selectedJob.salary || "Not Specified"}</div>
                  </div>
                </div>

                <div className="bg-slate-50 rounded-xl p-3 flex items-center space-x-3 col-span-2 sm:col-span-1">
                  <Calendar className="w-4 h-4 text-slate-400 shrink-0" />
                  <div>
                    <div className="text-[10px] font-bold uppercase text-slate-400">Posted Date</div>
                    <div className="text-xs font-semibold text-slate-800">{selectedJob.posted_date || "Unknown"}</div>
                  </div>
                </div>
              </div>

              {/* Skills Area */}
              <div>
                <h3 className="text-xs font-bold uppercase tracking-wider text-slate-400 mb-2">Required Skills</h3>
                <div className="flex flex-wrap gap-2">
                  {selectedJob.skills && selectedJob.skills.length > 0 ? (
                    selectedJob.skills.map((skill, sIdx) => (
                      <span 
                        key={sIdx}
                        className="text-xs font-semibold text-blue-700 bg-blue-50 border border-blue-100/50 px-3 py-1 rounded-lg"
                      >
                        {skill}
                      </span>
                    ))
                  ) : (
                    <span className="text-xs text-slate-400 italic font-medium">No skill requirements listed</span>
                  )}
                </div>
              </div>

              {/* Job Description */}
              <div className="border-t border-slate-100 pt-6">
                <h3 className="text-xs font-bold uppercase tracking-wider text-slate-400 mb-3">Job Description</h3>
                <div className="text-slate-600 text-sm leading-relaxed whitespace-pre-wrap font-medium">
                  {selectedJob.description || "No description provided."}
                </div>
              </div>
            </div>

            {/* Modal Footer / CTAs */}
            <div className="p-6 border-t border-slate-100 bg-slate-50/50 flex items-center justify-between gap-4">
              <span className="text-xs font-semibold text-slate-400">
                Ref ID: {selectedJob.id || "N/A"}
              </span>
              <div className="flex space-x-3">
                <button
                  onClick={() => setSelectedJob(null)}
                  className="px-4 py-2.5 border border-slate-200 bg-white hover:bg-slate-50 text-slate-700 text-xs font-bold rounded-xl transition-colors cursor-pointer"
                >
                  Close
                </button>
                {selectedJob.url && (
                  <a
                    href={selectedJob.url}
                    target="_blank"
                    rel="noreferrer"
                    className="inline-flex items-center space-x-1.5 px-4 py-2.5 bg-blue-600 hover:bg-blue-700 text-white text-xs font-bold rounded-xl shadow-sm hover:shadow transition-all duration-150"
                  >
                    <span>View Posting</span>
                    <ExternalLink className="w-3.5 h-3.5" />
                  </a>
                )}
                {selectedJob.apply_url && selectedJob.apply_url !== selectedJob.url && (
                  <a
                    href={selectedJob.apply_url}
                    target="_blank"
                    rel="noreferrer"
                    className="inline-flex items-center space-x-1.5 px-4 py-2.5 bg-indigo-600 hover:bg-indigo-700 text-white text-xs font-bold rounded-xl shadow-sm hover:shadow transition-all duration-150"
                  >
                    <span>Apply Direct</span>
                    <ExternalLink className="w-3.5 h-3.5" />
                  </a>
                )}
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};
