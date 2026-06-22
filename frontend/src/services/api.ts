import { env } from "@/config/env";
import type {
  JobFilterParams,
  JobListResponse,
  JobDetail,
  JobSearchRequest,
  JobSearchResponse,
  ResumeUploadResponse,
  ResumeTailorRequest,
  ResumeTailorResponse,
} from "@/types";

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
  const baseUrl = env.apiUrl.endsWith("/")
    ? env.apiUrl.slice(0, -1)
    : env.apiUrl;
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
      errorInfo?.detail ||
        response.statusText ||
        "An error occurred while fetching data.",
      response.status,
      errorInfo,
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

  uploadResume: async (file: File): Promise<ResumeUploadResponse> => {
    const baseUrl = env.apiUrl.endsWith("/")
      ? env.apiUrl.slice(0, -1)
      : env.apiUrl;
    const formData = new FormData();
    formData.append("file", file);

    const response = await fetch(`${baseUrl}/api/v1/resumes/upload`, {
      method: "POST",
      body: formData,
      // Note: Do NOT set Content-Type — the browser sets it with the boundary
    });

    if (!response.ok) {
      let errorInfo;
      try {
        errorInfo = await response.json();
      } catch {
        errorInfo = null;
      }
      throw new ApiError(
        errorInfo?.detail || response.statusText || "Failed to upload resume.",
        response.status,
        errorInfo,
      );
    }

    return response.json() as Promise<ResumeUploadResponse>;
  },

  tailorResume: async (
    params: ResumeTailorRequest,
  ): Promise<ResumeTailorResponse> => {
    return request<ResumeTailorResponse>("/api/v1/resumes/tailor-structured", {
      method: "POST",
      body: JSON.stringify(params),
    });
  },

  downloadFromUrl: async (
    url: string,
  ): Promise<{ blob: Blob; filename: string }> => {
    const baseUrl = env.apiUrl.endsWith("/")
      ? env.apiUrl.slice(0, -1)
      : env.apiUrl;

    const response = await fetch(
      `${baseUrl}/api/v1/resumes/download-from-url`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ url }),
      },
    );

    if (!response.ok) {
      let errorInfo;
      try {
        errorInfo = await response.json();
      } catch {
        errorInfo = null;
      }
      throw new ApiError(
        errorInfo?.detail || response.statusText || "Failed to download file.",
        response.status,
        errorInfo,
      );
    }

    // Extract filename from Content-Disposition header
    const disposition = response.headers.get("Content-Disposition") || "";
    const filenameMatch = disposition.match(/filename="?(.+?)"?$/);
    const filename = filenameMatch ? filenameMatch[1] : "download";

    const blob = await response.blob();
    return { blob, filename };
  },

  getJobs: async (params: JobFilterParams): Promise<JobListResponse> => {
    const query = new URLSearchParams();

    if (params.page !== undefined) query.append("page", params.page.toString());
    if (params.limit !== undefined)
      query.append("limit", params.limit.toString());
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
