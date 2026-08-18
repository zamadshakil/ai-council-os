'use client';

import Link from 'next/link';
import { useCallback, useEffect, useState } from 'react';
import { ArrowLeft, Download, RefreshCw } from 'lucide-react';
import { DebateTrace } from '../../components/debate-trace';
import { fetchTask, getGrantExportUrl, submitApproval } from '../../lib/api';
import { ApprovalAction, Task } from '../../lib/types';

const ACTIVE_STATUSES = new Set(['queued', 'running', 'publishing']);

export function TaskDetailContent({ id }: { id: string }) {
  const [task, setTask] = useState<Task | null>(null);
  const [editedOutput, setEditedOutput] = useState('');
  const [notes, setNotes] = useState('');
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState<ApprovalAction | null>(null);
  const [error, setError] = useState('');

  const load = useCallback(async () => {
    try {
      const next = await fetchTask(id);
      setTask(next);
      setEditedOutput((current) => current || next.final_output || '');
      setError('');
    } catch (loadError) {
      setError(loadError instanceof Error ? loadError.message : 'Unable to load this task.');
    } finally {
      setLoading(false);
    }
  }, [id]);

  useEffect(() => {
    let active = true;
    void fetchTask(id)
      .then((next) => {
        if (!active) return;
        setTask(next);
        setEditedOutput(next.final_output || '');
        setError('');
      })
      .catch((loadError: unknown) => { if (active) setError(loadError instanceof Error ? loadError.message : 'Unable to load this task.'); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [id]);

  useEffect(() => {
    const hubspotStatus = typeof task?.context.hubspot_sync_status === 'string' ? task.context.hubspot_sync_status : '';
    if (!task || (!ACTIVE_STATUSES.has(task.status) && !['queued', 'syncing', 'retrying'].includes(hubspotStatus))) return;
    const timer = window.setInterval(() => void load(), 4_000);
    return () => window.clearInterval(timer);
  }, [load, task]);

  async function act(action: ApprovalAction) {
    if (!task) return;
    if (task.approval_version === undefined) {
      setError('Approval metadata is not ready. Refresh after the run reaches an approval state.');
      return;
    }
    setSubmitting(action);
    setError('');
    try {
      await submitApproval(id, {
        action,
        expected_version: task.approval_version,
        idempotency_key: crypto.randomUUID(),
        edited_output: editedOutput,
        notes,
      });
      await load();
    } catch (actionError) {
      setError(actionError instanceof Error ? actionError.message : 'Unable to update this task.');
      await load();
    } finally {
      setSubmitting(null);
    }
  }

  if (loading && !task) return <div className="flex min-h-96 items-center justify-center text-sm font-medium text-slate-500"><RefreshCw className="mr-2 h-5 w-5 animate-spin" /> Loading persisted task…</div>;
  if (!task) return <div className="rounded-2xl border border-rose-300/20 bg-rose-400/8 p-8 text-center text-sm text-rose-200">{error || 'Task not found.'}</div>;

  const reconciliationRequired = task.context.publication_state === 'reconciliation_required';
  const hubspotStatus = typeof task.context.hubspot_sync_status === 'string' ? task.context.hubspot_sync_status : '';
  const hubspotMessage = typeof task.context.hubspot_sync_message === 'string' ? task.context.hubspot_sync_message : '';
  const canDecide = !reconciliationRequired && task.approval_status === 'awaiting_approval' && (task.status === 'awaiting_approval' || task.status === 'needs_manual_review');
  const canRetry = !reconciliationRequired && task.approval_status !== 'approved' && (task.status === 'failed' || task.status === 'rejected' || task.status === 'cancelled');
  const canCancel = task.status === 'queued' || task.status === 'running';

  return (
    <div className="mx-auto max-w-6xl space-y-7 pb-16">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <Link href="/approvals" className="flex items-center gap-2 text-sm font-semibold text-slate-400 hover:text-slate-100"><ArrowLeft className="h-4 w-4" /> Back to queue</Link>
        <button onClick={() => void load()} className="flex items-center gap-2 rounded-xl border border-white/10 bg-white/5 px-4 py-2 text-sm font-semibold text-slate-300"><RefreshCw className="h-4 w-4" /> Refresh</button>
      </div>

      <section className="surface-card rounded-2xl p-6">
        <div className="flex flex-wrap items-center gap-2 text-xs font-bold uppercase tracking-wide">
          <span className="rounded-full bg-white/5 px-3 py-1 text-slate-300">{task.council}</span>
          <span className="rounded-full bg-cyan-300/8 px-3 py-1 text-cyan-300">{task.status.replaceAll('_', ' ')}</span>
          <span className="ml-auto text-slate-600">Task version {task.version} · Approval version {task.approval_version ?? 'not ready'}</span>
        </div>
        <h1 className="mt-4 text-2xl font-bold leading-tight text-slate-50">{task.task_description}</h1>
        <div className="mt-4 flex flex-wrap gap-5 text-sm text-slate-500">
          <span>Created {new Date(task.created_at).toLocaleString()}</span>
          <span>{task.iterations} drafts</span>
          <span>{task.confidence_score === null ? 'Score unavailable' : `Score ${task.confidence_score.toFixed(1)}`}</span>
          <span>{task.cost_metrics_complete ? `Cost $${task.total_cost_usd.toFixed(4)}` : 'Cost unavailable/partial'}</span>
        </div>
        {(task.warning || task.error) && <p className="mt-4 rounded-xl border border-amber-300/15 bg-amber-300/8 p-3 text-sm text-amber-200">{task.warning || task.error}</p>}
      </section>

      <div className="grid gap-7 xl:grid-cols-[1fr_22rem]">
        <section className="surface-card rounded-2xl p-6">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <h2 className="text-lg font-bold text-slate-100">Final output</h2>
            {task.council === 'grant' && task.final_output && (
              <div className="flex gap-2">
                <a href={getGrantExportUrl(task.task_id, 'docx')} className="flex items-center gap-1.5 rounded-lg border border-white/10 px-3 py-2 text-xs font-semibold text-slate-300"><Download className="h-3.5 w-3.5" /> DOCX</a>
                <a href={getGrantExportUrl(task.task_id, 'pdf')} className="flex items-center gap-1.5 rounded-lg border border-white/10 px-3 py-2 text-xs font-semibold text-slate-300"><Download className="h-3.5 w-3.5" /> PDF</a>
              </div>
            )}
          </div>
          <textarea
            value={editedOutput}
            onChange={(event) => setEditedOutput(event.target.value)}
            disabled={!canDecide}
            className="mt-4 min-h-[28rem] w-full resize-y input-shell rounded-xl p-4 text-sm leading-6 text-slate-200 outline-none disabled:cursor-default"
            placeholder="Output will appear when the council run completes."
          />
        </section>

        <aside className="space-y-4">
          {hubspotStatus && <div className="surface-card rounded-2xl p-5">
            <div className="flex items-center justify-between gap-3">
              <h2 className="text-sm font-bold text-slate-100">HubSpot CRM</h2>
              <span className={`rounded-full border px-2.5 py-1 text-[10px] font-black uppercase tracking-wide ${hubspotStatus === 'synced' ? 'border-emerald-300/20 bg-emerald-300/8 text-emerald-300' : hubspotStatus === 'failed' || hubspotStatus === 'blocked_unverified' ? 'border-rose-300/20 bg-rose-300/8 text-rose-200' : hubspotStatus.startsWith('skipped') ? 'border-amber-300/20 bg-amber-300/8 text-amber-200' : 'border-cyan-300/20 bg-cyan-300/8 text-cyan-200'}`}>{hubspotStatus.replaceAll('_', ' ')}</span>
            </div>
            <p className="mt-3 text-xs leading-5 text-slate-400">{hubspotMessage || 'CRM synchronization status is persisted with this approved task.'}</p>
          </div>}
          <div className="surface-card rounded-2xl p-5">
            <label htmlFor="decision-notes" className="text-sm font-bold text-slate-200">Decision notes</label>
            <textarea id="decision-notes" value={notes} onChange={(event) => setNotes(event.target.value)} maxLength={5_000} className="mt-3 min-h-28 w-full resize-y input-shell rounded-xl p-3 text-sm text-slate-100 outline-none focus:border-cyan-300/40" placeholder="Optional audit note" />
            {error && <p role="alert" className="mt-3 rounded-lg bg-red-50 p-3 text-xs text-red-700">{error}</p>}
            {reconciliationRequired && <p className="mt-3 rounded-lg bg-amber-50 p-3 text-xs text-amber-800">The provider outcome is uncertain. Check the destination manually; automatic retry is disabled to prevent a duplicate post.</p>}
            <div className="mt-4 grid gap-2">
              {canDecide && <>
                <button disabled={submitting !== null} onClick={() => void act('approve')} className="h-10 rounded-xl bg-emerald-600 text-sm font-bold text-white disabled:opacity-50">{submitting === 'approve' ? 'Approving…' : 'Approve'}</button>
                <button disabled={submitting !== null} onClick={() => void act('reject')} className="h-10 rounded-xl border border-red-200 bg-red-50 text-sm font-bold text-red-700 disabled:opacity-50">{submitting === 'reject' ? 'Rejecting…' : 'Reject'}</button>
              </>}
              {canRetry && <button disabled={submitting !== null} onClick={() => void act('retry')} className="h-10 rounded-xl bg-blue-600 text-sm font-bold text-white disabled:opacity-50">{submitting === 'retry' ? 'Queueing…' : 'Retry'}</button>}
              {canCancel && <button disabled={submitting !== null} onClick={() => void act('cancel')} className="h-10 rounded-xl border border-zinc-300 text-sm font-bold text-zinc-700 disabled:opacity-50">{submitting === 'cancel' ? 'Cancelling…' : 'Cancel run'}</button>}
              {!canDecide && !canRetry && !canCancel && <p className="text-center text-xs text-zinc-500">No action is available in this state.</p>}
            </div>
          </div>
        </aside>
      </div>

      <section>
        <h2 className="mb-4 text-lg font-bold text-slate-100">Model trace</h2>
        <DebateTrace messages={task.debate_history} />
      </section>
    </div>
  );
}
