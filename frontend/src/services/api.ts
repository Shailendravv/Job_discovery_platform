import { env } from "@/config/env";
import type { JobFilterParams, JobListResponse, JobDetail, JobSearchRequest, JobSearchResponse } from "@/types";

export class ApiError extends Error {
  status: number;
  info: unknown;

  constructor(message: string, status: number, info?: unknown) {
    super(message);
    this.status = status;
    this.info = info;
    this.name = "ApiError";
  }
}

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  // Trim any double slashes
  const baseUrl = env.apiUrl.endsWith("/") ? env.apiUrl.slice(0, -1) : env.apiUrl;
  const targetPath = path.startsWith("/") ? path : `/${path}`;
  const url = `${baseUrl}${targetPath}`;
  
  const defaultHeaders = {
    "Content-Type": "application/json",
  };

  const response = await fetch(url, {
    ...options,
    headers: {
      ...defaultHeaders,
      ...options?.headers,
    },
  });

  if (!response.ok) {
    let errorInfo;
    try {
      errorInfo = await response.json();
    } catch {
      errorInfo = null;
    }
    throw new ApiError(
      errorInfo?.detail || response.statusText || "An error occurred while fetching data.",
      response.status,
      errorInfo
    );
  }

  // Handle empty responses
  if (response.status === 204) {
    return {} as T;
  }

  return response.json() as Promise<T>;
}

export const api = {
  searchJobs: async (params: JobSearchRequest): Promise<JobSearchResponse> => {
    return request<JobSearchResponse>("/api/v1/jobs/search", {
      method: "POST",
      body: JSON.stringify(params),
    });
  },

  getJobById: async (jobId: string): Promise<JobDetail> => {
    return request<JobDetail>(`/api/v1/jobs/jobs/${jobId}`);
  },

  getJobs: async (params: JobFilterParams): Promise<JobListResponse> => {
    const query = new URLSearchParams();
    
    if (params.page !== undefined) query.append("page", params.page.toString());
    if (params.limit !== undefined) query.append("limit", params.limit.toString());
    if (params.source) query.append("source", params.source);
    if (params.job_type) query.append("job_type", params.job_type);
    if (params.location) query.append("location", params.location);
    if (params.q) query.append("q", params.q);
    if (params.sort_by) query.append("sort_by", params.sort_by);
    if (params.sort_order) query.append("sort_order", params.sort_order);

    const queryString = query.toString();
    const endpoint = `/api/v1/jobs/jobs${queryString ? `?${queryString}` : ""}`;
    return request<JobListResponse>(endpoint);
  },
};
