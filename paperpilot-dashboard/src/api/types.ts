export type ExportFormat = "markdown" | "html" | "pdf";

export type TaskStatus =
  | "created"
  | "queued"
  | "running"
  | "cancel_requested"
  | "cancelled"
  | "completed"
  | "failed"
  | "dead_letter"
  | "human_review";

export type TaskEventType =
  | "task_created"
  | "task_queued"
  | "task_started"
  | "task_completed"
  | "task_failed"
  | "task_cancelled"
  | "task_dead_letter"
  | "lease_renewed"
  | "lease_expired"
  | "execution_aborted"
  | "stale_worker_rejected"
  | "query_planning_started"
  | "query_planning_completed"
  | "retrieval_started"
  | "retrieval_completed"
  | "metadata_filtering_started"
  | "metadata_filtering_completed"
  | "pdf_processing_started"
  | "pdf_processing_progress"
  | "pdf_processing_completed"
  | "paper_reading_started"
  | "paper_reading_progress"
  | "paper_reading_completed"
  | "evidence_verification_started"
  | "evidence_verification_progress"
  | "evidence_verification_completed"
  | "final_relevance_started"
  | "final_relevance_completed"
  | "survey_synthesis_started"
  | "survey_synthesis_completed"
  | "artifact_export_started"
  | "artifact_export_completed"
  | "stage_failed";

export type ProgressStage =
  | "query_planning"
  | "retrieval"
  | "metadata_filtering"
  | "pdf_processing"
  | "paper_reading"
  | "evidence_verification"
  | "final_relevance"
  | "survey_synthesis"
  | "artifact_export";

export interface ProgressEventPayload {
  stage: ProgressStage;
  completed: number | null;
  total: number | null;
  succeeded: number | null;
  failed: number | null;
  skipped: number | null;
  paper_title_preview: string | null;
  elapsed_ms: number | null;
  message: string | null;
}

export type ManualSourceProvider = "google_scholar" | "cnki";

export interface ManualPaperSource {
  source: ManualSourceProvider;
  title: string;
  source_url: string;
  upload_id: string;
  authors: string[];
  publication_year?: number;
  abstract?: string;
  doi?: string;
}

export interface ManualSourceUploadResponse {
  upload_id: string;
  size_bytes: number;
  page_count: number;
  sha256: string;
}

/** JSON body accepted by POST /api/v1/research. */
export interface ResearchRequest {
  question: string;
  max_papers: number;
  export_format: ExportFormat;
  manual_sources?: ManualPaperSource[];
}

/** Backwards-compatible name used by the existing form. */
export type CreateResearchRequest = ResearchRequest;

export interface TaskAcceptedResponse {
  task_id: string;
  status: TaskStatus;
  created_at: string;
}

export interface TaskStatusResponse {
  task_id: string;
  run_id: string;
  status: TaskStatus;
  created_at: string;
  updated_at: string;
  artifact_available: boolean;
  artifact_format: ExportFormat | null;
  human_review_required: boolean;
  retryable: boolean;
  error_code: string | null;
}

export interface TaskEventResponse {
  event_id: number;
  event_type: TaskEventType;
  status: TaskStatus;
  attempt_count: number;
  duration_ms: number | null;
  created_at: string;
  progress?: ProgressEventPayload | null;
}

export interface MetricsResponse {
  submitted_total: number;
  completed_total: number;
  failed_total: number;
  cancelled_total: number;
  dead_letter_total: number;
  active_workers: number;
  queue_size: number;
  running_tasks: number;
  lease_expired_total: number;
  stale_worker_rejected_total: number;
  average_execution_time_ms: number;
}

export interface HealthResponse {
  kind: "liveness" | "readiness";
  status: "healthy" | "unhealthy";
  ready: boolean;
  checks: Array<{ name: string; healthy: boolean }>;
}

export interface ErrorResponse {
  code: string;
  message: string;
  request_id: string;
}

/** Browser-safe representation of the artifact FileResponse and public headers. */
export interface ArtifactResponse {
  blob: Blob;
  filename: string;
  contentType: string;
  sha256: string | null;
}

/** Backwards-compatible name used by the existing download component. */
export type ArtifactDownload = ArtifactResponse;
