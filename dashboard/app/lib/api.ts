import {
  ApprovalActionInput,
  AuthResponse,
  BlenderPod,
  BlenderTemplateJob,
  CouncilRunInput,
  DebateMessage,
  IntegrationHealth,
  IntegrationConnection,
  JsonObject,
  KillSwitchStatus,
  KnowledgeDoc,
  KnowledgeSearchResult,
  MutationEnvelope,
  Stats,
  Task,
  WorkflowDefinition,
  WorkflowDetails,
  WorkflowPatch,
  WorkflowTriggerResult,
} from './types';

const API_BASE = process.env.NEXT_PUBLIC_API_URL?.replace(/\/$/, '') ?? '';
let csrfToken = '';

export class ApiError extends Error {
  constructor(
    message: string,
    public readonly status: number,
    public readonly code = 'request_failed',
  ) {
    super(message);
    this.name = 'ApiError';
  }
}

function isMutation(method?: string): boolean {
  return !['GET', 'HEAD', 'OPTIONS'].includes((method ?? 'GET').toUpperCase());
}

function pathWithQuery(path: string, query: Record<string, string | undefined>): string {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(query)) {
    if (value) params.set(key, value);
  }
  const suffix = params.toString();
  return `${API_BASE}${path}${suffix ? `?${suffix}` : ''}`;
}

function readError(payload: unknown, fallback: string): { message: string; code: string } {
  if (payload && typeof payload === 'object') {
    const object = payload as Record<string, unknown>;
    const detail = object.detail;
    const error = object.error;
    if (detail && typeof detail === 'object') {
      const structured = detail as Record<string, unknown>;
      return {
        message: typeof structured.message === 'string' ? structured.message : fallback,
        code: typeof structured.code === 'string' ? structured.code : 'request_failed',
      };
    }
    if (error && typeof error === 'object') {
      const structured = error as Record<string, unknown>;
      return {
        message: typeof structured.message === 'string' ? structured.message : fallback,
        code: typeof structured.code === 'string' ? structured.code : 'request_failed',
      };
    }
    if (typeof detail === 'string') return { message: detail, code: 'request_failed' };
    if (typeof error === 'string') return { message: error, code: 'request_failed' };
  }
  return { message: fallback, code: 'request_failed' };
}

export async function apiFetch<T>(path: string, options: RequestInit = {}): Promise<T> {
  const headers = new Headers(options.headers);
  if (isMutation(options.method) && !path.includes('/api/auth/login')) {
    // Re-read the token immediately before a write. This keeps multiple tabs
    // and Next.js Fast Refresh aligned with the current HTTP-only session and
    // prevents a stale in-memory token from causing repeated 403 responses.
    const sessionResponse = await fetch(`${API_BASE}/api/auth/session`, {
      credentials: 'same-origin', cache: 'no-store',
    });
    if (sessionResponse.ok) {
      const session = await sessionResponse.json() as AuthResponse;
      csrfToken = session.csrf_token;
    }
  }
  if (isMutation(options.method) && csrfToken) headers.set('X-CSRF-Token', csrfToken);
  const response = await fetch(path.startsWith('http') ? path : `${API_BASE}${path}`, {
    ...options,
    headers,
    credentials: 'same-origin',
    cache: 'no-store',
  });

  const contentType = response.headers.get('content-type') ?? '';
  const payload: unknown = response.status === 204
    ? null
    : contentType.includes('application/json')
      ? await response.json().catch(() => null)
      : await response.text().catch(() => '');

  if (!response.ok) {
    if (response.status === 401) {
      csrfToken = '';
      if (typeof window !== 'undefined') window.dispatchEvent(new Event('council:unauthorized'));
    }
    const parsed = readError(payload, response.statusText || 'Request failed.');
    throw new ApiError(parsed.message, response.status, parsed.code);
  }
  return payload as T;
}

function rememberSession(response: AuthResponse): AuthResponse {
  csrfToken = response.csrf_token;
  return response;
}

function normalizeTask(task: Task): Task {
  const debate_history = (task.debate_history ?? []).map((message): DebateMessage => {
    const model = message.model || message.model_used || 'Model not recorded';
    const score_breakdown = message.score_breakdown ?? message.structured_output?.category_scores;
    const content = message.content || (message.structured_output ? JSON.stringify(message.structured_output, null, 2) : '');
    return { ...message, model, content, score_breakdown };
  });
  return { ...task, debate_history };
}

export async function loginUser(username: string, password: string): Promise<AuthResponse> {
  const response = await apiFetch<AuthResponse>('/api/auth/login', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username, password }),
    signal: AbortSignal.timeout(10_000),
  });
  return rememberSession(response);
}

export async function fetchSession(): Promise<AuthResponse> {
  return rememberSession(await apiFetch<AuthResponse>('/api/auth/session'));
}

export async function logoutUser(): Promise<void> {
  try {
    await apiFetch<unknown>('/api/auth/logout', { method: 'POST' });
  } finally {
    csrfToken = '';
  }
}

export async function fetchTasks(status?: string, council?: string): Promise<Task[]> {
  const data = await apiFetch<{ tasks?: Task[] } | Task[]>(pathWithQuery('/api/tasks', { status, council }));
  return (Array.isArray(data) ? data : data.tasks ?? []).map(normalizeTask);
}

export async function fetchTask(id: string): Promise<Task> {
  return normalizeTask(await apiFetch<Task>(`/api/tasks/${encodeURIComponent(id)}`));
}

export async function submitApproval(id: string, data: ApprovalActionInput): Promise<MutationEnvelope<Task> | Task> {
  return apiFetch<MutationEnvelope<Task> | Task>(`/api/approvals/${encodeURIComponent(id)}/actions`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  });
}

export async function runCouncil(data: CouncilRunInput): Promise<MutationEnvelope<Task> | Task> {
  return apiFetch<MutationEnvelope<Task> | Task>('/api/council-runs', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'Idempotency-Key': crypto.randomUUID() },
    body: JSON.stringify(data),
  });
}

export async function fetchStats(): Promise<Stats> {
  return apiFetch<Stats>('/api/stats');
}

export async function fetchKillSwitch(): Promise<KillSwitchStatus> {
  return apiFetch<KillSwitchStatus>('/api/kill-switch');
}

export async function updateKillSwitch(active: boolean, reason = ''): Promise<MutationEnvelope<KillSwitchStatus> | KillSwitchStatus> {
  return apiFetch<MutationEnvelope<KillSwitchStatus> | KillSwitchStatus>('/api/kill-switch', {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ active, reason }),
  });
}

export async function fetchWorkflows(): Promise<WorkflowDefinition[]> {
  const data = await apiFetch<{ workflows?: WorkflowDefinition[] } | WorkflowDefinition[]>('/api/workflows');
  return Array.isArray(data) ? data : data.workflows ?? [];
}

export async function fetchWorkflowDetails(workflowId: string): Promise<WorkflowDetails> {
  const data = await apiFetch<WorkflowDefinition & { runs?: WorkflowDetails['runs'] }>(`/api/workflows/${encodeURIComponent(workflowId)}`);
  return { ...data, runs: data.runs ?? [] };
}

export async function updateWorkflow(workflowId: string, patch: WorkflowPatch): Promise<MutationEnvelope<WorkflowDefinition> | WorkflowDefinition> {
  return apiFetch<MutationEnvelope<WorkflowDefinition> | WorkflowDefinition>(`/api/workflows/${encodeURIComponent(workflowId)}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(patch),
  });
}

export async function triggerWorkflow(workflowId: string, payload: JsonObject = {}): Promise<WorkflowTriggerResult> {
  return apiFetch<WorkflowTriggerResult>(`/api/workflows/${encodeURIComponent(workflowId)}/trigger`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ payload, idempotency_key: crypto.randomUUID() }),
  });
}

export async function fetchIntegrationsHealth(): Promise<IntegrationHealth[]> {
  const data = await apiFetch<{
    integrations?: IntegrationHealth[];
    workflows?: Record<string, { credential_status: IntegrationHealth['status']; configured: boolean; enabled: boolean; paused: boolean; message?: string }>;
    publishing?: Record<string, boolean | { configured?: boolean; credential_status?: IntegrationHealth['status']; status?: IntegrationHealth['status']; message?: string }>;
    model_gateway?: { configured: boolean; status?: IntegrationHealth['status'] };
    crm?: Record<string, { configured?: boolean; status?: IntegrationHealth['status']; message?: string }>;
  } | IntegrationHealth[]>('/api/integrations/health');
  if (Array.isArray(data)) return data;
  if (data.integrations) return data.integrations;
  const items: IntegrationHealth[] = [];
  for (const [id, workflow] of Object.entries(data.workflows ?? {})) {
    items.push({
      id,
      name: id.replaceAll('_', ' '),
      status: workflow.credential_status,
      detail: workflow.message || (workflow.configured ? 'Configured but not verified.' : 'Required configuration is missing.'),
    });
  }
  for (const [id, health] of Object.entries(data.publishing ?? {})) {
    if (typeof health === 'boolean') {
      items.push({ id: `publishing_${id}`, name: `${id} publishing`, status: health ? 'configured' : 'missing', detail: health ? 'Credentials are configured but not verified.' : 'Required configuration is missing.' });
    } else {
      const configured = health.configured ?? false;
      items.push({
        id: `publishing_${id}`,
        name: `${id} publishing`,
        status: health.credential_status ?? health.status ?? (configured ? 'configured' : 'missing'),
        detail: health.message || (configured ? 'Credentials are configured but not verified.' : 'Required configuration is missing.'),
      });
    }
  }
  if (data.model_gateway) {
    items.push({ id: 'model_gateway', name: 'OpenRouter model gateway', status: data.model_gateway.status ?? (data.model_gateway.configured ? 'configured' : 'missing'), detail: data.model_gateway.configured ? 'Stored securely; provider verification controls workflow readiness.' : 'Required configuration is missing.' });
  }
  for (const [id, health] of Object.entries(data.crm ?? {})) {
    const configured = health.configured ?? false;
    items.push({
      id: `crm_${id}`,
      name: `${id} CRM`,
      status: health.status ?? (configured ? 'configured' : 'missing'),
      detail: health.message || (configured ? 'Stored securely; approval destinations require explicit linking.' : 'Required configuration is missing.'),
    });
  }
  return items;
}

export async function verifyIntegration(workflowId: string): Promise<MutationEnvelope<WorkflowDefinition> | WorkflowDefinition> {
  return apiFetch<MutationEnvelope<WorkflowDefinition> | WorkflowDefinition>(`/api/integrations/${encodeURIComponent(workflowId)}/verify`, { method: 'POST' });
}

export async function verifyPublishingIntegration(platform: string): Promise<unknown> {
  return apiFetch<unknown>(`/api/integrations/publishing/${encodeURIComponent(platform)}/verify`, { method: 'POST' });
}

export async function fetchIntegrationCatalog(): Promise<IntegrationConnection[]> {
  const data = await apiFetch<{ integrations: IntegrationConnection[] }>('/api/integrations/catalog');
  return data.integrations ?? [];
}

export async function saveIntegrationCredentials(
  provider: string,
  credentials: Record<string, string>,
  displayName = '',
): Promise<MutationEnvelope<IntegrationConnection>> {
  return apiFetch<MutationEnvelope<IntegrationConnection>>(`/api/integrations/${encodeURIComponent(provider)}/credentials`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ display_name: displayName, credentials }),
  });
}

export async function removeIntegrationCredentials(provider: string): Promise<void> {
  await apiFetch<unknown>(`/api/integrations/${encodeURIComponent(provider)}/credentials`, { method: 'DELETE' });
}

export async function verifyConnection(provider: string): Promise<MutationEnvelope<IntegrationConnection>> {
  return apiFetch<MutationEnvelope<IntegrationConnection>>(`/api/integrations/connections/${encodeURIComponent(provider)}/verify`, { method: 'POST' });
}

export async function updateWorkflowIntegrations(
  workflowId: string,
  providers: string[],
): Promise<MutationEnvelope<WorkflowDefinition>> {
  return apiFetch<MutationEnvelope<WorkflowDefinition>>(`/api/workflows/${encodeURIComponent(workflowId)}/integrations`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ providers }),
  });
}

export async function updateCouncilIntegrations(
  councilId: string,
  providers: string[],
): Promise<MutationEnvelope<{ id: string; integration_providers: string[] }>> {
  return apiFetch<MutationEnvelope<{ id: string; integration_providers: string[] }>>(`/api/councils/${encodeURIComponent(councilId)}/integrations`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ providers }),
  });
}

export function getGrantExportUrl(taskId: string, format: 'docx' | 'pdf'): string {
  return `${API_BASE}/api/grants/${encodeURIComponent(taskId)}/export.${format}`;
}

export async function fetchKnowledgeDocuments(): Promise<KnowledgeDoc[]> {
  const data = await apiFetch<{ documents?: KnowledgeDoc[] } | KnowledgeDoc[]>('/api/knowledge/documents');
  return Array.isArray(data) ? data : data.documents ?? [];
}

export async function uploadKnowledgeDocument(file: File): Promise<MutationEnvelope<KnowledgeDoc> | KnowledgeDoc> {
  const body = new FormData();
  body.append('file', file);
  return apiFetch<MutationEnvelope<KnowledgeDoc> | KnowledgeDoc>('/api/knowledge/upload', { method: 'POST', body });
}

export async function deleteKnowledgeDocument(documentId: string): Promise<void> {
  await apiFetch<unknown>(`/api/knowledge/documents/${encodeURIComponent(documentId)}`, { method: 'DELETE' });
}

export async function searchKnowledge(query: string, documentHashes: string[] = []): Promise<KnowledgeSearchResult[]> {
  const params = new URLSearchParams({ q: query });
  for (const hash of documentHashes) params.append('doc_hash', hash);
  const data = await apiFetch<{ results: KnowledgeSearchResult[] }>(`${API_BASE}/api/knowledge/search?${params.toString()}`);
  return data.results ?? [];
}

export async function fetchBlenderPods(): Promise<BlenderPod[]> {
  const data = await apiFetch<{ pods: BlenderPod[] }>('/api/blender/pods');
  return data.pods ?? [];
}

export async function actOnBlenderPod(podId: string, action: 'resume' | 'stop'): Promise<MutationEnvelope<BlenderPod>> {
  return apiFetch<MutationEnvelope<BlenderPod>>(`/api/blender/pods/${encodeURIComponent(podId)}/actions`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ action }),
  });
}

export async function fetchBlenderJobs(): Promise<BlenderTemplateJob[]> {
  const data = await apiFetch<{ jobs: BlenderTemplateJob[] }>('/api/blender/jobs');
  return data.jobs ?? [];
}

export async function createBlenderJob(input: {
  pod_id: string;
  source_path: string;
  output_name: string;
  frame: number;
  samples: number;
  resolution_percent: number;
  auto_stop: boolean;
  idempotency_key: string;
}): Promise<MutationEnvelope<BlenderTemplateJob>> {
  return apiFetch<MutationEnvelope<BlenderTemplateJob>>('/api/blender/jobs', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(input),
  });
}
