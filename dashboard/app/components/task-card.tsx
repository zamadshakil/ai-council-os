'use client';

import Link from 'next/link';
import { AlertTriangle, ArrowRight, CheckCircle2, Clock3, XCircle } from 'lucide-react';
import { Task, TaskStatus } from '../lib/types';

const STATUS_STYLES: Record<TaskStatus, string> = {
  queued: 'bg-cyan-300/8 text-cyan-300 border-cyan-300/20',
  running: 'bg-violet-300/10 text-violet-300 border-violet-300/20',
  awaiting_approval: 'bg-amber-300/10 text-amber-300 border-amber-300/20',
  needs_manual_review: 'bg-orange-300/10 text-orange-300 border-orange-300/20',
  approved: 'bg-emerald-300/10 text-emerald-300 border-emerald-300/20',
  rejected: 'bg-rose-300/10 text-rose-300 border-rose-300/20',
  publishing: 'bg-indigo-300/10 text-indigo-300 border-indigo-300/20',
  published: 'bg-emerald-300/10 text-emerald-300 border-emerald-300/20',
  failed: 'bg-rose-300/10 text-rose-300 border-rose-300/20',
  cancelled: 'bg-white/5 text-slate-400 border-white/10',
};

function StatusIcon({ status }: { status: TaskStatus }) {
  if (status === 'approved' || status === 'published') return <CheckCircle2 className="h-3.5 w-3.5" />;
  if (status === 'failed' || status === 'rejected') return <XCircle className="h-3.5 w-3.5" />;
  if (status === 'needs_manual_review') return <AlertTriangle className="h-3.5 w-3.5" />;
  return <Clock3 className="h-3.5 w-3.5" />;
}

export function TaskCard({ task }: { task: Task }) {
  return (
    <article className="surface-card interactive-surface rounded-2xl p-5">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <span className="rounded-full bg-white/5 px-2.5 py-1 text-xs font-bold capitalize text-slate-300">{task.council}</span>
            <span className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs font-semibold ${STATUS_STYLES[task.status]}`}>
              <StatusIcon status={task.status} />
              {task.status.replaceAll('_', ' ')}
            </span>
          </div>
          <h2 className="mt-3 line-clamp-2 text-base font-bold text-slate-100">{task.task_description}</h2>
          <div className="mt-3 flex flex-wrap gap-4 text-xs text-slate-500">
            <span>{new Date(task.created_at).toLocaleString()}</span>
            <span>{task.iterations} draft{task.iterations === 1 ? '' : 's'}</span>
            <span>{task.confidence_score === null ? 'Score unavailable' : `Score ${task.confidence_score.toFixed(0)}`}</span>
            <span>{task.cost_metrics_complete ? `$${task.total_cost_usd.toFixed(4)}` : 'Cost unavailable/partial'}</span>
          </div>
        </div>
        <Link href={`/approvals/${task.task_id}`} className="inline-flex h-10 items-center gap-2 rounded-xl border border-cyan-300/20 bg-cyan-300/10 px-4 text-sm font-semibold text-cyan-100 hover:bg-cyan-300/15">
          Review <ArrowRight className="h-4 w-4" />
        </Link>
      </div>
      {(task.error || task.warning) && <p className="mt-4 rounded-lg border border-amber-300/15 bg-amber-300/8 p-3 text-xs text-amber-200">{task.error || task.warning}</p>}
    </article>
  );
}
