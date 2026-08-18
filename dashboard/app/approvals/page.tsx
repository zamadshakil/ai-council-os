'use client';

import { useCallback, useEffect, useMemo, useState } from 'react';
import { RefreshCw } from 'lucide-react';
import { TaskCard } from '../components/task-card';
import { fetchTasks } from '../lib/api';
import { Task, TaskStatus } from '../lib/types';

const TABS: Array<{ id: 'all' | TaskStatus; label: string }> = [
  { id: 'all', label: 'All' },
  { id: 'queued', label: 'Queued' },
  { id: 'running', label: 'Running' },
  { id: 'awaiting_approval', label: 'Awaiting approval' },
  { id: 'needs_manual_review', label: 'Manual review' },
  { id: 'approved', label: 'Approved' },
  { id: 'failed', label: 'Failed' },
];

export default function ApprovalsPage() {
  const [filter, setFilter] = useState<'all' | TaskStatus>('all');
  const [tasks, setTasks] = useState<Task[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  const load = useCallback(async () => {
    try {
      const next = await fetchTasks();
      setTasks(next);
      setError('');
    } catch (loadError) {
      setError(loadError instanceof Error ? loadError.message : 'Unable to load the queue.');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    let active = true;
    void fetchTasks()
      .then((next) => { if (active) { setTasks(next); setError(''); } })
      .catch((loadError: unknown) => { if (active) setError(loadError instanceof Error ? loadError.message : 'Unable to load the queue.'); })
      .finally(() => { if (active) setLoading(false); });
    const timer = window.setInterval(() => void load(), 10_000);
    return () => { active = false; window.clearInterval(timer); };
  }, [load]);

  const filtered = useMemo(() => filter === 'all' ? tasks : tasks.filter((task) => task.status === filter), [filter, tasks]);

  return (
    <div className="space-y-7 pb-16">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <p className="eyebrow">Human decision gate</p><h1 className="mt-2 text-3xl font-black tracking-tight text-slate-50">Queue & approvals</h1>
          <p className="mt-2 text-sm text-slate-400">Running work is visible but can only be approved after it reaches an approval state.</p>
        </div>
        <button onClick={() => void load()} className="flex h-10 items-center gap-2 rounded-xl border border-white/10 bg-white/5 px-4 text-sm font-semibold text-slate-300 hover:bg-white/8">
          <RefreshCw className={`h-4 w-4 ${loading ? 'animate-spin' : ''}`} /> Refresh
        </button>
      </div>

      <div className="flex flex-wrap gap-2">
        {TABS.map((tab) => {
          const count = tab.id === 'all' ? tasks.length : tasks.filter((task) => task.status === tab.id).length;
          return (
            <button key={tab.id} onClick={() => setFilter(tab.id)} className={`rounded-full px-4 py-2 text-sm font-semibold ${filter === tab.id ? 'bg-cyan-300 text-[#04111b]' : 'border border-white/10 bg-white/5 text-slate-400 hover:bg-white/8'}`}>
              {tab.label} <span className="ml-1 opacity-70">{count}</span>
            </button>
          );
        })}
      </div>

      {error && <p role="alert" className="rounded-xl border border-rose-300/20 bg-rose-400/8 p-4 text-sm text-rose-200">{error}</p>}
      {loading && tasks.length === 0 ? (
        <div className="space-y-3">{[1, 2, 3].map((item) => <div key={item} className="h-36 animate-pulse rounded-2xl bg-white/5" />)}</div>
      ) : filtered.length === 0 ? (
        <div className="surface-card rounded-2xl border-dashed py-24 text-center text-sm text-slate-500">No persisted tasks match this filter.</div>
      ) : (
        <div className="space-y-3">{filtered.map((task) => <TaskCard key={task.task_id} task={task} />)}</div>
      )}
    </div>
  );
}
