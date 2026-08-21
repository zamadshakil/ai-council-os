'use client';

import Link from 'next/link';
import { useCallback, useEffect, useState } from 'react';
import { ArrowLeft, Download, RefreshCw, Send, Workflow } from 'lucide-react';
import { DebateTrace } from '../../components/debate-trace';
import { ContentVariantGrid, readContentVariants } from '../../components/structured-output';
import { fetchTask, getGrantExportUrl, submitApproval } from '../../lib/api';
import { ApprovalAction, Task } from '../../lib/types';

const ACTIVE_STATUSES = new Set(['queued', 'running', 'publishing']);

function recoverableOutput(task: Task): string {
  if (task.final_output) return task.final_output;
  const generator = [...(task.debate_history ?? [])].reverse().find((message) => message.role === 'generator' && message.content.trim());
  return generator?.content ?? '';
}

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
      setEditedOutput((current) => current || recoverableOutput(next));
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
        setEditedOutput(recoverableOutput(next));
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
  const isDraftOnlyContent = task.council === 'content' && !task.context.workflow;
  const workflowName = typeof task.context.workflow === 'string' ? task.context.workflow : '';
  const platformName = typeof task.context.platform_name === 'string' ? task.context.platform_name : typeof task.context.platform === 'string' ? task.context.platform : '';
  const manualPosting = task.context.manual_posting_required === true;
  const publicationState = typeof task.context.publication_state === 'string' ? task.context.publication_state.replaceAll('_', ' ') : '';
  const retiredModelFailure = /anthropic\/claude-sonnet-5/i.test(task.error || task.warning || '');
  const finalVariants = readContentVariants(editedOutput) ?? readContentVariants(task.context.structured_output);
  const progress = task.context.progress && typeof task.context.progress === 'object' && !Array.isArray(task.context.progress)
    ? task.context.progress as { stage?: string; step_count?: number; draft_count?: number; last_role?: string }
    : null;
  const progressStage = progress?.stage?.replaceAll('_', ' ') ?? (task.status === 'queued' ? 'waiting for worker' : task.status.replaceAll('_', ' '));

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
        {(task.warning || task.error) && <p className="mt-4 rounded-xl border border-amber-300/15 bg-amber-300/8 p-3 text-sm text-amber-200">{retiredModelFailure ? 'Historical run: this attempt used the retired Sonnet model and failed its output contract. Retry uses the current Luna Pro/Gemini routing.' : task.warning || task.error}</p>}
      </section>

      {isDraftOnlyContent && <section className="flex flex-col gap-4 rounded-2xl border border-amber-300/20 bg-amber-300/8 p-5 sm:flex-row sm:items-center sm:justify-between"><div><p className="flex items-center gap-2 font-bold text-amber-100"><Workflow className="h-4 w-4" /> Draft lab result — no destination automation is attached</p><p className="mt-1 text-sm leading-6 text-slate-300">This Council run can review copy, but it cannot publish or track six destinations. Content Engine creates one independently validated approval per platform and sends approved items through verified integrations.</p></div><Link href="/workflows/content_engine" className="flex h-10 shrink-0 items-center justify-center rounded-xl bg-cyan-300 px-4 text-sm font-black text-[#04111b]">Create real automation</Link></section>}

      {workflowName && <section className="surface-card flex flex-col gap-4 rounded-2xl border-cyan-300/20 p-5 sm:flex-row sm:items-center sm:justify-between"><div><p className="flex items-center gap-2 font-bold text-cyan-100"><Send className="h-4 w-4" /> Automation delivery attached</p><p className="mt-1 text-sm leading-6 text-slate-300"><span className="font-bold capitalize">{workflowName.replaceAll('_', ' ')}</span>{platformName ? ` · ${platformName}` : ''} · {manualPosting ? 'approval prepares a manual-ready item' : 'approval queues the verified destination API'}.</p></div><span className="rounded-full border border-cyan-300/20 bg-cyan-300/8 px-3 py-1.5 text-xs font-bold capitalize text-cyan-200">{publicationState || task.status.replaceAll('_', ' ')}</span></section>}

      <section className="surface-card rounded-2xl p-6" aria-live="polite">
        <div className="flex flex-wrap items-center justify-between gap-3"><div><p className="eyebrow">Live execution</p><h2 className="mt-1 text-lg font-bold capitalize text-slate-100">{progressStage}</h2></div>{ACTIVE_STATUSES.has(task.status) && <span className="flex items-center gap-2 rounded-full border border-cyan-300/20 bg-cyan-300/8 px-3 py-1.5 text-xs font-bold text-cyan-200"><RefreshCw className="h-3.5 w-3.5 animate-spin" /> Updating every 4 seconds</span>}</div>
        <div className="mt-4 grid gap-3 sm:grid-cols-3"><div className="rounded-xl border border-white/8 bg-white/[0.025] p-3"><p className="text-[10px] font-bold uppercase tracking-wide text-slate-500">Completed model steps</p><p className="mt-1 text-xl font-black text-slate-100">{progress?.step_count ?? task.debate_history.length}</p></div><div className="rounded-xl border border-white/8 bg-white/[0.025] p-3"><p className="text-[10px] font-bold uppercase tracking-wide text-slate-500">Drafts generated</p><p className="mt-1 text-xl font-black text-slate-100">{progress?.draft_count ?? task.iterations}</p></div><div className="rounded-xl border border-white/8 bg-white/[0.025] p-3"><p className="text-[10px] font-bold uppercase tracking-wide text-slate-500">Latest actor</p><p className="mt-1 text-sm font-bold capitalize text-slate-200">{progress?.last_role || (task.debate_history.length ? task.debate_history.at(-1)?.role : 'Not started')}</p></div></div>
        <div className="mt-5"><DebateTrace messages={task.debate_history} /></div>
      </section>

      <div className="grid gap-7 xl:grid-cols-[1fr_22rem]">
        <section className="surface-card rounded-2xl p-6">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div><p className="eyebrow">Human decision payload</p><h2 className="mt-1 text-lg font-bold text-slate-100">{finalVariants ? 'Platform deliverables' : task.final_output ? 'Final output' : editedOutput ? 'Last valid draft recovered' : 'Final output'}</h2></div>
            {task.council === 'grant' && task.final_output && (
              <div className="flex gap-2">
                <a href={getGrantExportUrl(task.task_id, 'docx')} className="flex items-center gap-1.5 rounded-lg border border-white/10 px-3 py-2 text-xs font-semibold text-slate-300"><Download className="h-3.5 w-3.5" /> DOCX</a>
                <a href={getGrantExportUrl(task.task_id, 'pdf')} className="flex items-center gap-1.5 rounded-lg border border-white/10 px-3 py-2 text-xs font-semibold text-slate-300"><Download className="h-3.5 w-3.5" /> PDF</a>
              </div>
            )}
          </div>
          <div className="mt-4">
            {finalVariants ? <ContentVariantGrid variants={finalVariants} editable={canDecide} onChange={(next) => setEditedOutput(JSON.stringify(next))} /> : <textarea
              value={editedOutput}
              onChange={(event) => setEditedOutput(event.target.value)}
              disabled={!canDecide}
              className="min-h-[28rem] w-full resize-y input-shell rounded-xl p-4 text-sm leading-6 text-slate-200 outline-none disabled:cursor-default"
              placeholder="Output will appear when the council run completes."
            />}
          </div>
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
                <button disabled={submitting !== null} onClick={() => void act('approve')} className="h-10 rounded-xl bg-emerald-600 text-sm font-bold text-white disabled:opacity-50">{submitting === 'approve' ? 'Approving…' : manualPosting ? 'Approve as manual-ready' : platformName ? `Approve & queue ${platformName}` : 'Approve'}</button>
                <button disabled={submitting !== null} onClick={() => void act('reject')} className="h-10 rounded-xl border border-red-200 bg-red-50 text-sm font-bold text-red-700 disabled:opacity-50">{submitting === 'reject' ? 'Rejecting…' : 'Reject'}</button>
              </>}
              {canRetry && <button disabled={submitting !== null} onClick={() => void act('retry')} className="h-10 rounded-xl bg-blue-600 text-sm font-bold text-white disabled:opacity-50">{submitting === 'retry' ? 'Queueing…' : 'Retry'}</button>}
              {canCancel && <button disabled={submitting !== null} onClick={() => void act('cancel')} className="h-10 rounded-xl border border-zinc-300 text-sm font-bold text-zinc-700 disabled:opacity-50">{submitting === 'cancel' ? 'Cancelling…' : 'Cancel run'}</button>}
              {!canDecide && !canRetry && !canCancel && <p className="text-center text-xs text-zinc-500">No action is available in this state.</p>}
            </div>
          </div>
        </aside>
      </div>

    </div>
  );
}
