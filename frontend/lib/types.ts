/* ── Backend API Types (matches backend-py/app/schemas.py) ── */

export interface SourceSpec {
  type: "web_search" | "site" | "connector";
  query_or_url: string;
  notes: string;
}

export interface WorkflowSpec {
  goal: string;
  fields: string[];
  sources: SourceSpec[];
  validation_rules: string[];
  dedupe_strategy: string;
}

export interface ResolvedResult {
  url: string;
  title: string | null;
  snippet: string | null;
}

export interface ResolvedSource extends SourceSpec {
  resolved: ResolvedResult[];
}

export interface ResolvedWorkflowSpec extends WorkflowSpec {
  sources: ResolvedSource[];
}

export interface ExtractedRecord {
  source_url: string;
  data: Record<string, string | null>;
  citation_snippet: string;
  citation_url: string;
  match_status?: "match" | "unconfirmed";
  match_reason?: string;
  flags?: string[];
}

export interface SourceExtractionResult {
  query_or_url: string;
  records: ExtractedRecord[];
  fetch_errors: string[];
}

export interface ValidationIssue {
  record_index: number;
  field: string;
  reason: string;
}

export interface MergeDecision {
  kept_index: number;
  dropped_index: number;
  reason: string;
  similarity_score: number;
}

export interface ValidatedResult {
  clean_records: ExtractedRecord[];
  issues: ValidationIssue[];
  merges: MergeDecision[];
}

/* ── API Response Types ── */

export interface PlanResponse {
  prompt: string;
  spec: WorkflowSpec;
}

export interface DiscoverResponse {
  spec: ResolvedWorkflowSpec;
}

export interface RunResponse {
  prompt: string;
  task_id: string | null;
  persist_error: string | null;
  spec: WorkflowSpec;
  resolved_spec: ResolvedWorkflowSpec;
  extraction_results: SourceExtractionResult[];
  validated_result: ValidatedResult;
}

/* ── SSE Event Types ── */

export type PipelineStage =
  | "idle"
  | "planning"
  | "discovering"
  | "extracting"
  | "critiquing"
  | "validating"
  | "complete"
  | "error";

export interface SSEEvent {
  event: string;
  data: Record<string, unknown>;
}

export interface LogEntry {
  id: string;
  timestamp: Date;
  stage: PipelineStage;
  agent: string;
  message: string;
  level: "info" | "success" | "warning" | "error";
}

/* ── History / Datasets (matches backend-py/app/db/persist.py) ── */

export interface TaskSummary {
  task_id: string;
  prompt: string;
  status: string;
  created_at: string | null;
  record_count: number;
}

export interface TaskDetail {
  task_id: string;
  prompt: string;
  status: string;
  created_at: string | null;
  spec: WorkflowSpec;
  sources: { url: string; status: string; record_count: number }[];
  validated_result: ValidatedResult;
}
/* ── Resume upload (matches backend-py/app/resume.py) ── */

export interface ResumeProfile {
  name: string;
  current_role: string;
  experience: string;
  skills: string[];
  target_roles: string[];
  locations: string[];
  summary: string;
}