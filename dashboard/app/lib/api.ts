import { Task, Stats } from './types';

const API_BASE = 'http://localhost:8000';

export async function fetchTasks(status?: string, council?: string): Promise<Task[]> {
  const url = new URL(`${API_BASE}/api/tasks`);
  if (status && status !== 'all') url.searchParams.append('status', status);
  if (council) url.searchParams.append('council', council);
  const res = await fetch(url.toString(), { cache: 'no-store' });
  if (!res.ok) throw new Error('Failed to fetch tasks');
  return res.json();
}

export async function fetchTask(id: string): Promise<Task> {
  const res = await fetch(`${API_BASE}/api/tasks/${id}`, { cache: 'no-store' });
  if (!res.ok) throw new Error('Failed to fetch task');
  return res.json();
}

export async function approveTask(id: string, data: { approved: boolean; feedback?: string }): Promise<any> {
  const res = await fetch(`${API_BASE}/api/tasks/${id}/approve`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  });
  if (!res.ok) throw new Error('Failed to approve task');
  return res.json();
}

export async function runCouncil(data: any): Promise<any> {
  const res = await fetch(`${API_BASE}/api/councils/run`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  });
  if (!res.ok) throw new Error('Failed to run council');
  return res.json();
}

export async function fetchStats(): Promise<Stats> {
  const res = await fetch(`${API_BASE}/api/stats`, { cache: 'no-store' });
  if (!res.ok) throw new Error('Failed to fetch stats');
  return res.json();
}
