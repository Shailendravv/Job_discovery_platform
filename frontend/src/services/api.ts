import { env } from "@/config/env";
import type {
  PostingFilterParams,
  PostingListResponse,
  PostingDetail,
  IngestTriggerParams,
  IngestTriggerResponse,
  IngestRunStatus,
  ShortlistResponse,
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
  // GET /api/v1/postings — up to `limit` latest postings (default 200),
  // newest first, already deduplicated + prefiltered server-side.
  getPostings: async (
    params: PostingFilterParams = {},
  ): Promise<PostingListResponse> => {
    const query = new URLSearchParams();
    if (params.limit !== undefined) query.append("limit", params.limit.toString());
    if (params.since_days !== undefined)
      query.append("since_days", params.since_days.toString());
    if (params.provider) query.append("provider", params.provider);
    if (params.org) query.append("org", params.org);
    if (params.q) query.append("q", params.q);
    if (params.posted_within) query.append("posted_within", params.posted_within);

    const queryString = query.toString();
    const endpoint = `/api/v1/postings${queryString ? `?${queryString}` : ""}`;
    return request<PostingListResponse>(endpoint);
  },

  getPostingById: async (postingId: string): Promise<PostingDetail> => {
    return request<PostingDetail>(`/api/v1/postings/${postingId}`);
  },

  getShortlist: async (): Promise<ShortlistResponse> => {
    return request<ShortlistResponse>("/api/v1/postings/shortlist");
  },

  // POST /api/v1/postings/ingest — starts a background discovery run (same
  // work as `jobctl ingest`) and returns immediately with a run id. Poll
  // getIngestRun() for progress; the run itself can take minutes.
  triggerIngest: async (
    params: IngestTriggerParams = {},
  ): Promise<IngestTriggerResponse> => {
    return request<IngestTriggerResponse>("/api/v1/postings/ingest", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(params),
    });
  },

  // GET /api/v1/postings/ingest/{run_id} — live stage timings for a run.
  getIngestRun: async (runId: string): Promise<IngestRunStatus> => {
    return request<IngestRunStatus>(`/api/v1/postings/ingest/${runId}`);
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
};
