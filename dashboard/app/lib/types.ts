export type JsonPrimitive = string | number | boolean | null;
export type JsonValue = JsonPrimitive | JsonObject | JsonValue[];
export interface JsonObject { [key: string]: JsonValue }

export type CouncilName = 'grant' | 'sales' | 'content';
export type Priority = 'normal' | 'high';
export type TaskStatus =
  | 'queued'
  | 'running'
  | 'awaiting_approval'
  | 'needs_manual_review'
  | 'approved'
  | 'rejected'
  | 'publishing'
  | 'published'
  | 'failed'
  | 'cancelled';

export interface User {
  username: string;
  name?: string;
  role: string;
  email?: string;
}

export interface AuthResponse {
  status?: string;
  authenticated?: boolean;
  user: User;
  csrf_token: string;
}

export interface MutationEnvelope<T> {
  resource: T;
  version: number;
  audit_event_id: string;
}

export interface DebateMessage {
  role: 'generator' | 'critic' | 'synthesizer';
  model: string;
  model_used?: string;
  content: string;
  confidence_score?: number;
  score_breakdown?: Record<string, number>;
  structured_output?: {
    category_scores?: Record<string, number>;
    [key: string]: JsonValue | Record<string, number> | undefined;
  };
  timestamp: string;
}

export interface Task {
  task_id: string;
  council: CouncilName;
  status: TaskStatus;
  task_description: string;
  final_output: string;
  confidence_score: number | null;
  iterations: number;
  total_cost_usd: number;
  cost_metrics_complete: boolean;
  debate_history: DebateMessage[];
  created_at: string;
  updated_at?: string;
  context: JsonObject;
  feedback_notes?: string;
  error?: string;
  warning?: string;
  version: number;
  approval_id?: string;
  approval_status?: 'awaiting_approval' | 'approved' | 'rejected' | 'cancelled' | 'failed';
  approval_version?: number;
}

export interface CouncilRunInput {
  council: CouncilName;
  task_description: string;
  context: JsonObject;
  priority: Priority;
  selected_document_hashes: string[];
}

export type ApprovalAction = 'approve' | 'reject' | 'retry' | 'cancel' | 'publish';

export interface ApprovalActionInput {
  action: ApprovalAction;
  expected_version: number;
  idempotency_key: string;
  edited_output?: string;
  notes?: string;
}

export interface Stats {
  total_tasks: number;
  pending: number;
  approved: number;
  rejected: number;
  failed?: number;
  total_cost_usd: number;
  cost_metrics_complete: boolean;
  avg_confidence: number | null;
  councils: Partial<Record<CouncilName, { tasks: number; cost: number; cost_metrics_complete: boolean; avg_confidence: number | null }>>;
}

export interface KillSwitchStatus {
  is_active: boolean;
  toggled_by: string;
  toggled_at: string;
  reason: string;
  version?: number;
}

export type CredentialStatus = 'connected' | 'verified' | 'ready' | 'missing' | 'invalid' | 'failed' | 'untested';

export interface WorkflowDefinition {
  id: string;
  display_name: string;
  is_enabled: boolean;
  is_paused: boolean;
  schedule: JsonObject;
  settings: JsonObject;
  credential_status: CredentialStatus;
  version: number;
  last_run?: WorkflowRun;
}

export interface WorkflowRun {
  id: string;
  workflow_id: string;
  job_type: string;
  status: 'queued' | 'running' | 'retry' | 'completed' | 'dead_letter' | 'cancelled';
  result: JsonObject;
  error: string;
  attempts: number;
  max_attempts: number;
  created_at: string;
  updated_at: string;
}

export type SchedulePreset =
  | 'manual'
  | 'every_5_minutes'
  | 'every_15_minutes'
  | 'every_30_minutes'
  | 'hourly'
  | 'every_3_hours'
  | 'every_6_hours'
  | 'every_12_hours'
  | 'daily';

export interface WorkflowPatch {
  paused?: boolean;
  enabled?: boolean;
  schedule_preset?: SchedulePreset;
  custom_prompt?: string;
  selected_document_hashes?: string[];
}

export interface WorkflowDetails extends WorkflowDefinition {
  runs: WorkflowRun[];
  integration_providers?: string[];
}

export interface WorkflowTriggerResult {
  resource?: WorkflowRun;
  run?: WorkflowRun;
  id?: string;
  status?: string;
  version?: number;
  audit_event_id?: string;
}

export interface IntegrationHealth {
  id: string;
  name: string;
  status: 'connected' | 'verified' | 'ready' | 'configured' | 'missing' | 'invalid' | 'failed' | 'degraded' | 'untested';
  detail?: string;
  checked_at?: string;
}

export interface IntegrationField {
  key: string;
  label: string;
  required: boolean;
  secret: boolean;
  help_text?: string;
}

export interface IntegrationConnection {
  id: string;
  display_name: string;
  description: string;
  fields: IntegrationField[];
  configured: boolean;
  configured_fields: string[];
  status: 'not_configured' | 'configured' | 'verified' | 'failed';
  last_error: string;
  verified_at: string | null;
  version: number;
  linked_workflows: string[];
}

export interface KnowledgeSearchResult {
  text: string;
  doc_name: string;
  doc_hash: string;
  score: number;
  chunk_index?: number;
  citation?: string;
}

export interface KnowledgeDoc {
  id: string;
  doc_hash: string;
  filename: string;
  chunk_count?: number;
  ingested_at?: string;
  created_at?: string;
  selected_for_grant?: boolean;
  status?: string;
  warning?: string;
}

export interface AppNotification {
  id: string;
  title: string;
  message: string;
  time: string;
  type: 'approval' | 'system' | 'workflow';
  read: boolean;
  link?: string;
}

export interface BlenderPod {
  id: string;
  name: string;
  desired_status: string;
  image_name: string;
  gpu_count: number;
  cost_per_hour: number;
  uptime_seconds: number;
  gpu_utilization: Array<{ id: string; gpu_percent: number; memory_percent: number }>;
  proxy_url: string;
}

export interface BlenderTemplateJob {
  id: string;
  status: string;
  stage: string;
  pod_id: string;
  source_path: string;
  output_name: string;
  frame: number;
  samples: number;
  resolution_percent: number;
  auto_stop: boolean;
  attempts: number;
  max_attempts: number;
  error: string;
  result: {
    stage?: string;
    output_path?: string;
    preview_path?: string;
    source_unchanged?: boolean;
    log_tail?: string[];
    report?: {
      gpu_engaged?: boolean;
      render_engine?: string;
      benchmark_seconds?: number;
      missing_assets?: string[];
      warnings?: string[];
      gpu?: { backend?: string; enabled_gpu_count?: number };
    };
  };
  version: number;
  created_at: string;
  updated_at: string;
  finished_at: string;
}
