import { Task, Stats, KillSwitchStatus, WorkflowResult, User, LoginResponse } from './types';

const API_BASE = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

function getAuthHeader(): Record<string, string> {
  if (typeof window !== 'undefined') {
    const token = localStorage.getItem('council_os_auth_token');
    if (token) {
      return { 'Authorization': `Bearer ${token}` };
    }
  }
  return {};
}

async function apiFetch(url: string, options?: RequestInit) {
  const headers = {
    ...getAuthHeader(),
    ...(options?.headers || {}),
  };

  const res = await fetch(url, { cache: 'no-store', ...options, headers });
  if (!res.ok) {
    const err = await res.text().catch(() => 'Unknown error');
    throw new Error(err);
  }
  return res.json();
}

// ── Auth ─────────────────────────────
export async function loginUser(username: string, password: string): Promise<LoginResponse> {
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), 10000); // 10s timeout max

  try {
    const res = await fetch(`${API_BASE}/api/auth/login`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username, password }),
      signal: controller.signal,
    });
    clearTimeout(timeoutId);

    if (!res.ok) {
      const errData = await res.json().catch(() => null);
      const message = errData?.detail || 'Invalid username or password.';
      throw new Error(message);
    }
    return await res.json();
  } catch (err: any) {
    clearTimeout(timeoutId);
    if (err.name === 'AbortError') {
      throw new Error('Connection timed out. Please verify backend server URL.');
    }
    if (err.message && err.message !== 'Failed to fetch') {
      throw err;
    }
    throw new Error('Unable to connect to backend server. Please check your network or API URL.');
  }
}


export async function fetchCurrentUser(): Promise<User> {
  return apiFetch(`${API_BASE}/api/auth/me`);
}

// ── Tasks ───────────────────────────
export async function fetchTasks(status?: string, council?: string): Promise<Task[]> {
  const url = new URL(`${API_BASE}/api/tasks`);
  if (status && status !== 'all') url.searchParams.append('status', status);
  if (council) url.searchParams.append('council', council);
  const data = await apiFetch(url.toString());
  return data.tasks || data;
}

export async function fetchTask(id: string): Promise<Task> {
  return apiFetch(`${API_BASE}/api/tasks/${id}`);
}

export async function approveTask(id: string, data: { approved: boolean; edited_output?: string; notes?: string }): Promise<any> {
  return apiFetch(`${API_BASE}/api/tasks/${id}/approve`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  });
}

export async function runCouncil(data: any): Promise<any> {
  return apiFetch(`${API_BASE}/api/councils/run`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  });
}

export async function fetchStats(): Promise<Stats> {
  return apiFetch(`${API_BASE}/api/stats`);
}

// ── Kill Switch ─────────────────────
export async function fetchKillSwitch(): Promise<KillSwitchStatus> {
  return apiFetch(`${API_BASE}/api/kill-switch`);
}

export async function activateKillSwitch(reason?: string): Promise<any> {
  const url = new URL(`${API_BASE}/api/kill-switch/activate`);
  if (reason) url.searchParams.append('reason', reason);
  return apiFetch(url.toString(), { method: 'POST' });
}

export async function deactivateKillSwitch(): Promise<any> {
  return apiFetch(`${API_BASE}/api/kill-switch/deactivate`, { method: 'POST' });
}

// ── Workflow Triggers & Details ─────
export async function triggerWorkflow(workflow: string, body?: any): Promise<WorkflowResult> {
  return apiFetch(`${API_BASE}/api/workflows/${workflow}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: body ? JSON.stringify(body) : undefined,
  });
}

export async function fetchWorkflowDetails(workflowId: string): Promise<any> {
  return apiFetch(`${API_BASE}/api/workflows/${workflowId}/details`);
}
