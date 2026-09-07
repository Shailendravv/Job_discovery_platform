// ── Posting types (backend: app/ingest/models.py Posting) ──
//
// Postings come from the ATS ingest pipeline (jobctl ingest / POST
// /api/v1/postings/ingest), not a live per-search scrape — see
// AGENTS.md. GET /api/v1/postings returns up to 200 latest, newest
// first, already deduplicated and prefiltered.

export interface Posting {
  id: string;
  provider: string;
  org: string;
  company_name: string;

  title: string;
  title_normalized: string;
  location?: string | null;
  location_normalized: string;
  remote_flag?: boolean | null;
  employment_type?: string | null;

  description_text: string;
  salary?: string | null;

  url: string;
  apply_url?: string | null;

  posted_at?: string | null;
  first_seen_at?: string | null;
  last_seen_at?: string | null;

  duplicate_of?: string | null;
  tags: string[];

  judged: boolean;
  verdict?: string | null;

  prefiltered: boolean;
  prefilter_status?: string | null;
  prefilter_reason?: string | null;
}

export interface PostingListResponse {
  postings: Posting[];
  total: number;
}

// Client-side pagination over the fetched postings — see AppContext.tsx.
// GET /api/v1/postings itself has no page/skip param (it returns up to
// `limit` latest postings in one shot).
export interface PaginationMeta {
  page: number;
  limit: number;
  total: number;
  pages: number;
}

export interface PostingFilterParams {
  limit?: number;
  since_days?: number;
  provider?: string | null;
  org?: string | null;
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

export interface PostingDetail extends Posting {
  active_resume?: ActiveResumeInfo | null;
  tailoring_status?: TailoringStatus | null;
}

export interface IngestTriggerResponse {
  run_id: string;
  status: string;
}

export interface ShortlistEntry {
  id: string;
  verdict: string;
  score: number;
  reasons: string[];
  concerns: string[];
  judged_at?: string | null;
  posting: Posting;
}

export interface ShortlistResponse {
  entries: ShortlistEntry[];
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
  ats_keywords_matched?: string[];
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
