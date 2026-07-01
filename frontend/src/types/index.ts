export interface Job {
  id?: string;
  title: string;
  company: string;
  location?: string | null;
  description: string;
  url?: string | null;
  apply_url?: string | null;
  skills: string[];
  job_type: string;
  posted_date?: string | null;
  salary?: string | null;
  source?: string | null;
  created_at?: string;
  updated_at?: string;
}

export interface PaginationMeta {
  page: number;
  limit: number;
  total: number;
  pages: number;
}

export interface JobListResponse {
  jobs: Job[];
  pagination: PaginationMeta;
}

export interface JobFilterParams {
  page?: number;
  limit?: number;
  source?: string | null;
  job_type?: string | null;
  location?: string | null;
  q?: string | null;
  sort_by?: "created_at" | "updated_at" | "title" | "company" | "score";
  sort_order?: "asc" | "desc";
}

export interface JobSearchRequest {
  user_input: string;
  location?: string;
}

export interface JobSearchResponse {
  jobs: Job[];
  saved: number;
}

export interface ActiveResumeInfo {
  resume_id: string;
  cloudinary_url: string;
  filename: string;
  name?: string | null;
  skills: string[];
  processing_status: string;
}

export interface TailoringDownloadUrls {
  pdf?: string | null;
  docx?: string | null;
  cover_letter_pdf?: string | null;
}

export interface TailoringStatus {
  tailored: boolean;
  resume_id?: string | null;
  job_id?: string | null;
  download_urls?: TailoringDownloadUrls | null;
}

export interface JobDetail {
  id: string;
  title: string;
  company: string;
  location: string | null;
  description: string;
  url: string | null;
  apply_url: string | null;
  skills: string[];
  job_type: string;
  posted_date: string | null;
  salary: string | null;
  source: string | null;
  experience: string | null;
  requirements: string[];
  ref_id: string | null;
  created_at: string | null;
  updated_at: string | null;
  // Resume lifecycle fields
  active_resume?: ActiveResumeInfo | null;
  tailoring_status?: TailoringStatus | null;
}

// ── Resume Upload Types ──

export interface EducationEntry {
  institution?: string | null;
  degree?: string | null;
  year?: number | null;
}

export interface ExperienceEntry {
  company?: string | null;
  title?: string | null;
  duration?: string | null;
  description?: string | null;
}

export interface ParsedResumeData {
  name?: string | null;
  email?: string | null;
  phone?: string | null;
  education?: EducationEntry[];
  experience?: ExperienceEntry[];
  skills?: string[];
  languages?: string[];
  certifications?: string[];
}

export interface ResumeUploadResponse {
  resume_id: string;
  cloudinary_url: string;
  parsed_data: ParsedResumeData;
  extracted_text_preview: string;
  processing_status: string;
}

// ── Resume Tailor Types ──

export interface ResumeTailorRequest {
  resume_id: string;
  job_id: string;
}

export interface DownloadUrls {
  pdf: string;
  docx: string;
  cover_letter_pdf?: string | null;
}

export interface ResumeTailorResponse {
  resume_id: string;
  job_id: string;
  tailored_text: string;
  cover_letter: string;
  download_urls: DownloadUrls;
  // ATS optimisation metadata
  keyword_coverage_pct?: number;
  paper_format?: string;
  jd_keywords?: string[];
  competency_keywords?: string[];
  selected_project_count?: number;
  keyword_distribution?: {
    summary?: string[];
    experience?: string[];
    skills?: string[];
    projects?: string[];
  };
}
