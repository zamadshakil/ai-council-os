'use client';

import Link from 'next/link';
import { useCallback, useEffect, useState } from 'react';
import { Bot, ExternalLink, FilePenLine, MessageCircle, Newspaper, Pause, Play, RefreshCw, Send, ShieldCheck, Sparkles } from 'lucide-react';
import { fetchWorkflows, triggerWorkflow, updateWorkflow } from '../lib/api';
import { WorkflowDefinition } from '../lib/types';
import { StatusOrb } from '../components/status-orb';

const META: Record<string, { description: string; value: string; icon: typeof Bot }> = {
  telegram_control: { description: 'Private administrator approvals, alerts, pause controls, and global emergency stop.', value: 'Control plane', icon: Send },
  youtube_comments: { description: 'Discovers new comments, drafts contextual replies, and publishes only after approval.', value: 'Audience care', icon: MessageCircle },
  reddit_prospector: { description: 'Scans 45 targeted communities, scores buying intent, and stages manual-ready replies.', value: 'Qualified leads', icon: Newspaper },
  youtube_descriptions: { description: 'Improves existing descriptions and stages quota-aware official API updates.', value: 'Search visibility', icon: FilePenLine },
  content_engine: { description: 'Turns one transcript into six independently critiqued, separately approved platform variants.', value: 'Content leverage', icon: Sparkles },
  instagram_comments: { description: 'Finds new Instagram comments, drafts contextual replies, and posts only after approval.', value: 'Community care', icon: MessageCircle },
};

const verified = (workflow: WorkflowDefinition) => ['connected', 'verified'].includes(workflow.credential_status);
const unwrap = (value: { resource: WorkflowDefinition } | WorkflowDefinition) => 'resource' in value ? value.resource : value;

export default function WorkflowsPage() {
  const [workflows, setWorkflows] = useState<WorkflowDefinition[]>([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState('');
  const [error, setError] = useState('');

  const load = useCallback(async () => { try { setWorkflows(await fetchWorkflows()); setError(''); } catch (loadError) { setError(loadError instanceof Error ? loadError.message : 'Unable to load automations.'); } finally { setLoading(false); } }, []);
  useEffect(() => {
    let active = true;
    void fetchWorkflows()
      .then((items) => { if (active) setWorkflows(items); })
      .catch((loadError: unknown) => { if (active) setError(loadError instanceof Error ? loadError.message : 'Unable to load automations.'); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, []);

  async function patch(workflow: WorkflowDefinition, update: { enabled?: boolean; paused?: boolean }) {
    setBusy(workflow.id); setError('');
    try { const next = unwrap(await updateWorkflow(workflow.id, update)); setWorkflows((current) => current.map((item) => item.id === next.id ? next : item)); }
    catch (updateError) { setError(updateError instanceof Error ? updateError.message : 'Unable to update automation.'); }
    finally { setBusy(''); }
  }

  async function run(workflow: WorkflowDefinition) {
    setBusy(workflow.id); setError('');
    try { await triggerWorkflow(workflow.id); await load(); }
    catch (runError) { setError(runError instanceof Error ? runError.message : 'Unable to queue automation.'); }
    finally { setBusy(''); }
  }

  const online = workflows.filter((workflow) => workflow.is_enabled && !workflow.is_paused).length;
  return <div className="space-y-7 pb-16">
    <div className="flex flex-wrap items-end justify-between gap-4"><div><p className="eyebrow">Durable execution fabric</p><h1 className="mt-2 text-3xl font-black tracking-tight text-slate-50">Automation workflows</h1><p className="mt-2 max-w-2xl text-sm text-slate-300">Six focused automations with durable jobs, deduplication, verified credentials, and human approval before every external write.</p></div><div className="flex items-center gap-3"><span className="flex items-center gap-2 rounded-full border border-emerald-300/20 bg-emerald-300/8 px-4 py-2 text-xs font-bold text-emerald-300"><span className="status-dot" />{online} online</span><button aria-label="Refresh workflows" onClick={() => void load()} className="rounded-xl border border-white/10 bg-white/5 p-2.5 text-slate-300"><RefreshCw className={`h-4 w-4 ${loading ? 'animate-spin' : ''}`} /></button></div></div>
    {error && <p role="alert" className="rounded-2xl border border-rose-300/20 bg-rose-400/8 p-4 text-sm text-rose-200">{error}</p>}
    {loading && workflows.length === 0 ? <div className="grid gap-4 lg:grid-cols-2">{[1,2,3,4].map((id) => <div key={id} className="h-64 animate-pulse rounded-2xl bg-white/5" />)}</div> : <section className="grid gap-4 lg:grid-cols-2">{workflows.map((workflow) => {
      const meta = META[workflow.id] ?? { description: 'Durable production automation.', value: 'Automation', icon: Bot }; const Icon = meta.icon;
      const isOnline = workflow.is_enabled && !workflow.is_paused; const ready = verified(workflow); const working = busy === workflow.id;
      return <article key={workflow.id} className={`surface-card relative overflow-hidden rounded-2xl p-6 ${isOnline ? 'scan-line border-cyan-300/20' : ''}`}><div className="relative"><div className="flex items-start justify-between gap-4"><div className="flex min-w-0 gap-4"><span className="grid h-12 w-12 shrink-0 place-items-center rounded-2xl border border-white/10 bg-white/5 text-cyan-300"><Icon className="h-5 w-5" /></span><div><p className="eyebrow">{meta.value}</p><h2 className="mt-1 font-bold text-slate-100">{workflow.display_name}</h2></div></div><StatusOrb active={isOnline} size="sm" /></div><p className="mt-4 min-h-12 text-sm leading-6 text-slate-400">{meta.description}</p><div className="mt-5 grid grid-cols-2 gap-3"><div className="rounded-xl border border-white/8 bg-white/[0.025] p-3"><p className="text-[10px] font-bold uppercase tracking-wide text-slate-600">Readiness</p><p className={`mt-1 text-xs font-bold capitalize ${ready ? 'text-emerald-300' : 'text-amber-300'}`}>{workflow.credential_status}</p></div><div className="rounded-xl border border-white/8 bg-white/[0.025] p-3"><p className="text-[10px] font-bold uppercase tracking-wide text-slate-600">Latest run</p><p className="mt-1 truncate text-xs font-bold capitalize text-slate-300">{workflow.last_run ? workflow.last_run.status.replaceAll('_',' ') : 'Not run yet'}</p></div></div>{!ready && <p className="mt-3 flex items-center gap-2 text-xs text-amber-300"><ShieldCheck className="h-4 w-4" />Connect and verify the required providers first.</p>}<div className="mt-5 flex flex-wrap gap-2"><button disabled={working || (!ready && !workflow.is_enabled)} onClick={() => void patch(workflow,{enabled:!workflow.is_enabled})} className="h-9 rounded-xl border border-white/10 px-3 text-xs font-bold text-slate-300 disabled:opacity-40">{workflow.is_enabled ? 'Disable' : 'Enable'}</button><button disabled={working || !workflow.is_enabled} onClick={() => void patch(workflow,{paused:!workflow.is_paused})} className="flex h-9 items-center gap-1.5 rounded-xl border border-white/10 px-3 text-xs font-bold text-slate-300 disabled:opacity-40">{workflow.is_paused ? <Play className="h-3.5 w-3.5" /> : <Pause className="h-3.5 w-3.5" />}{workflow.is_paused ? 'Resume' : 'Pause'}</button><button disabled={working || !ready || !isOnline || ['telegram_control','content_engine'].includes(workflow.id)} onClick={() => void run(workflow)} className="flex h-9 items-center gap-1.5 rounded-xl bg-cyan-300 px-3 text-xs font-black text-[#04111b] disabled:opacity-30"><Play className="h-3.5 w-3.5" />{working ? 'Queueing…' : 'Run now'}</button><Link href={`/workflows/${workflow.id}`} className="ml-auto flex h-9 items-center gap-1.5 rounded-xl px-3 text-xs font-bold text-cyan-300 hover:bg-cyan-300/8">Configure <ExternalLink className="h-3.5 w-3.5" /></Link></div></div></article>;
    })}</section>}
  </div>;
}
