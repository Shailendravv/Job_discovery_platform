import React, { createContext, useContext, useState, useEffect, useCallback, useMemo } from "react";
import type { Posting, PaginationMeta } from "@/types";
import { api, ApiError } from "@/services/api";

type SortField = "posted_at" | "first_seen_at" | "title" | "company_name";
type SortOrder = "asc" | "desc";

interface AppContextProps {
  jobs: Posting[]; // current page, filtered + sorted client-side
  pagination: PaginationMeta | null;
  filters: {
    q: string;
    source: string; // maps to Posting.provider
    job_type: string; // maps to Posting.employment_type
    location: string;
  };
  sort: {
    sort_by: SortField;
    sort_order: SortOrder;
  };
  loading: boolean;
  error: string | null;
  lastIngestRunId: string | null;
  activeTab: "Dashboard" | "Resumes" | "Applications";
  setActiveTab: (tab: "Dashboard" | "Resumes" | "Applications") => void;
  setPage: (page: number) => void;
  setLimit: (limit: number) => void;
  setSearchQuery: (q: string) => void;
  setSourceFilter: (source: string) => void;
  setJobTypeFilter: (type: string) => void;
  setLocationFilter: (location: string) => void;
  setSortOptions: (sort_by: SortField, sort_order: SortOrder) => void;
  resetFilters: () => void;
  refreshJobs: () => Promise<void>;
  triggerIngest: () => Promise<string>;
}

const AppContext = createContext<AppContextProps | undefined>(undefined);

export const AppContextProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [activeTab, setActiveTab] = useState<"Dashboard" | "Resumes" | "Applications">("Dashboard");

  // The full "200 latest" set, fetched once and refreshed on demand —
  // GET /api/v1/postings has no server-side pagination/full-text search,
  // so filtering/sorting/pagination all happen here on the client.
  const [allPostings, setAllPostings] = useState<Posting[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [lastIngestRunId, setLastIngestRunId] = useState<string | null>(null);

  const [page, setPageState] = useState(1);
  const [limit, setLimitState] = useState(10);
  const [q, setQ] = useState("");
  const [source, setSource] = useState("");
  const [jobType, setJobType] = useState("");
  const [location, setLocation] = useState("");
  const [sortBy, setSortBy] = useState<SortField>("posted_at");
  const [sortOrder, setSortOrder] = useState<SortOrder>("desc");

  const fetchJobs = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const response = await api.getPostings({ limit: 200 });
      setAllPostings(response.postings || []);
    } catch (err) {
      if (err instanceof ApiError) {
        setError(err.message);
      } else {
        setError("An unexpected error occurred while loading postings.");
      }
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    let active = true;
    if (active) {
      Promise.resolve().then(() => {
        fetchJobs();
      });
    }
    return () => {
      active = false;
    };
  }, [fetchJobs]);

  const triggerIngest = useCallback(async (): Promise<string> => {
    const result = await api.triggerIngest();
    setLastIngestRunId(result.run_id);
    return result.run_id;
  }, []);

  // ── Client-side filter → sort → paginate over allPostings ──
  const filtered = useMemo(() => {
    const needle = q.trim().toLowerCase();
    return allPostings.filter((p) => {
      if (source && p.provider !== source) return false;
      if (jobType && (p.employment_type || "") !== jobType) return false;
      if (location && !(p.location || "").toLowerCase().includes(location.toLowerCase())) return false;
      if (needle) {
        const haystack = `${p.title} ${p.company_name} ${p.description_text}`.toLowerCase();
        if (!haystack.includes(needle)) return false;
      }
      return true;
    });
  }, [allPostings, q, source, jobType, location]);

  const sorted = useMemo(() => {
    const dir = sortOrder === "asc" ? 1 : -1;
    return [...filtered].sort((a, b) => {
      let av: string, bv: string;
      switch (sortBy) {
        case "title": av = a.title; bv = b.title; break;
        case "company_name": av = a.company_name; bv = b.company_name; break;
        case "first_seen_at": av = a.first_seen_at || ""; bv = b.first_seen_at || ""; break;
        default: av = a.posted_at || ""; bv = b.posted_at || "";
      }
      return av < bv ? -1 * dir : av > bv ? 1 * dir : 0;
    });
  }, [filtered, sortBy, sortOrder]);

  const totalPages = Math.max(1, Math.ceil(sorted.length / limit));
  const clampedPage = Math.min(page, totalPages);
  const pageItems = sorted.slice((clampedPage - 1) * limit, clampedPage * limit);

  const pagination: PaginationMeta | null = allPostings.length
    ? { page: clampedPage, limit, total: sorted.length, pages: totalPages }
    : null;

  const setPage = (p: number) => setPageState(p);

  const setLimit = (l: number) => {
    setLimitState(l);
    setPageState(1);
  };

  const setSearchQuery = (query: string) => {
    setQ(query);
    setPageState(1);
  };

  const setSourceFilter = (src: string) => {
    setSource(src);
    setPageState(1);
  };

  const setJobTypeFilter = (type: string) => {
    setJobType(type);
    setPageState(1);
  };

  const setLocationFilter = (loc: string) => {
    setLocation(loc);
    setPageState(1);
  };

  const setSortOptions = (by: SortField, order: SortOrder) => {
    setSortBy(by);
    setSortOrder(order);
    setPageState(1);
  };

  const resetFilters = () => {
    setQ("");
    setSource("");
    setJobType("");
    setLocation("");
    setSortBy("posted_at");
    setSortOrder("desc");
    setPageState(1);
  };

  return (
    <AppContext.Provider
      value={{
        jobs: pageItems,
        pagination,
        filters: { q, source, job_type: jobType, location },
        sort: { sort_by: sortBy, sort_order: sortOrder },
        loading,
        error,
        lastIngestRunId,
        activeTab,
        setActiveTab,
        setPage,
        setLimit,
        setSearchQuery,
        setSourceFilter,
        setJobTypeFilter,
        setLocationFilter,
        setSortOptions,
        resetFilters,
        refreshJobs: fetchJobs,
        triggerIngest,
      }}
    >
      {children}
    </AppContext.Provider>
  );
};

// eslint-disable-next-line react-refresh/only-export-components
export const useApp = () => {
  const context = useContext(AppContext);
  if (context === undefined) {
    throw new Error("useApp must be used within an AppContextProvider");
  }
  return context;
};
