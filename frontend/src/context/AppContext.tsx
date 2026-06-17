import React, { createContext, useContext, useState, useEffect, useCallback } from "react";
import type { Job, PaginationMeta, JobFilterParams } from "@/types";
import { api, ApiError } from "@/services/api";

interface AppContextProps {
  jobs: Job[];
  pagination: PaginationMeta | null;
  filters: {
    q: string;
    source: string;
    job_type: string;
    location: string;
  };
  sort: {
    sort_by: "created_at" | "updated_at" | "title" | "company" | "score";
    sort_order: "asc" | "desc";
  };
  loading: boolean;
  error: string | null;
  activeTab: "Dashboard" | "Resumes" | "Applications";
  setActiveTab: (tab: "Dashboard" | "Resumes" | "Applications") => void;
  setPage: (page: number) => void;
  setLimit: (limit: number) => void;
  setSearchQuery: (q: string) => void;
  setSourceFilter: (source: string) => void;
  setJobTypeFilter: (type: string) => void;
  setLocationFilter: (location: string) => void;
  setSortOptions: (sort_by: "created_at" | "updated_at" | "title" | "company" | "score", sort_order: "asc" | "desc") => void;
  resetFilters: () => void;
  refreshJobs: () => Promise<void>;
}

const AppContext = createContext<AppContextProps | undefined>(undefined);

export const AppContextProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [activeTab, setActiveTab] = useState<"Dashboard" | "Resumes" | "Applications">("Dashboard");
  const [jobs, setJobs] = useState<Job[]>([]);
  const [pagination, setPagination] = useState<PaginationMeta | null>(null);
  
  // States corresponding to backend query parameters
  const [page, setPageState] = useState(1);
  const [limit, setLimitState] = useState(10);
  const [q, setQ] = useState("");
  const [source, setSource] = useState("");
  const [jobType, setJobType] = useState("");
  const [location, setLocation] = useState("");
  const [sortBy, setSortBy] = useState<"created_at" | "updated_at" | "title" | "company" | "score">("created_at");
  const [sortOrder, setSortOrder] = useState<"asc" | "desc">("desc");

  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const fetchJobs = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const params: JobFilterParams = {
        page,
        limit,
        q: q.trim() || null,
        source: source || null,
        job_type: jobType || null,
        location: location || null,
        sort_by: sortBy,
        sort_order: sortOrder,
      };
      
      const response = await api.getJobs(params);
      setJobs(response.jobs || []);
      setPagination(response.pagination || null);
    } catch (err) {
      if (err instanceof ApiError) {
        setError(err.message);
      } else {
        setError("An unexpected error occurred while loading jobs.");
      }
    } finally {
      setLoading(false);
    }
  }, [page, limit, q, source, jobType, location, sortBy, sortOrder]);

  // Trigger data fetching on filter/pagination changes
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

  const setPage = (p: number) => setPageState(p);
  
  const setLimit = (l: number) => {
    setLimitState(l);
    setPageState(1); // Always reset to page 1 on page limit adjustments
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
  
  const setSortOptions = (
    by: "created_at" | "updated_at" | "title" | "company" | "score",
    order: "asc" | "desc"
  ) => {
    setSortBy(by);
    setSortOrder(order);
    setPageState(1);
  };

  const resetFilters = () => {
    setQ("");
    setSource("");
    setJobType("");
    setLocation("");
    setSortBy("created_at");
    setSortOrder("desc");
    setPageState(1);
  };

  return (
    <AppContext.Provider
      value={{
        jobs,
        pagination,
        filters: { q, source, job_type: jobType, location },
        sort: { sort_by: sortBy, sort_order: sortOrder },
        loading,
        error,
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
