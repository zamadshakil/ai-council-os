'use client';

import Link from 'next/link';
import { useEffect, useMemo, useState } from 'react';
import { ArrowUpRight, CheckCircle2, Clock3, Database, Plus, Radio, ShieldCheck, Sparkles } from 'lucide-react';
import { fetchIntegrationsHealth, fetchTasks, fetchWorkflows } from './lib/api';
import { IntegrationHealth, Task, WorkflowDefinition } from './lib/types';
import { TaskCard } from './components/task-card';
import { StatusOrb } from './components/status-orb';

export default function OverviewPage() {
  const [tasks, setTasks] = useState<Task[]>([]);
  const [integrations, setIntegrations] = useState<IntegrationHealth[]>([]);
  const [workflows, setWorkflows] = useState<WorkflowDefinition[]>([]);
  const [error, setError] = useState('');

  useEffect(() => {
    void Promise.all([fetchTasks(), fetchIntegrationsHealth(), fetchWorkflows()])
      .then(([nextTasks, nextIntegrations, nextWorkflows]) => {
        setTasks(nextTasks); setIntegrations(nextIntegrations); setWorkflows(nextWorkflows);
      })
      .catch((loadError: unknown) => setError(loadError instanceof Error ? loadError.message : 'Unable to load command-center data.'));
  }, []);

  const waiting = tasks.filter((task) => ['awaiting_approval', 'needs_manual_review'].includes(task.status)).length;
  const active = tasks.filter((task) => ['queued', 'running', 'publishing'].includes(task.status)).length;
  const verified = integrations.filter((item) => ['ready', 'verified', 'connected'].includes(item.status)).length;
  const enabled = workflows.filter((workflow) => workflow.is_enabled && !workflow.is_paused).length;
  const costComplete = tasks.every((task) => task.cost_metrics_complete);
  const cost = tasks.reduce((sum, task) => sum + task.total_cost_usd, 0);
  const systemActive = workflows.some((workflow) => workflow.is_enabled && !workflow.is_paused);
  const recent = useMemo(() => tasks.slice(0, 5), [tasks]);

  const metrics = [
    { label: 'Jobs in motion', value: active.toString(), hint: 'Queued, running, or publishing', icon: Clock3, tone: 'text-cyan-300' },
    { label: 'Human decisions', value: waiting.toString(), hint: 'Outputs waiting for review', icon: CheckCircle2, tone: 'text-amber-300' },
    { label: 'Automations online', value: `${enabled}/${workflows.length}`, hint: 'Enabled and not paused', icon: Radio, tone: 'text-emerald-300' },
    { label: 'Recorded spend', value: costComplete ? `$${cost.toFixed(4)}` : 'Partial', hint: costComplete ? 'Provider-reported cost' : 'Some providers omitted cost data', icon: Database, tone: 'text-violet-300' },
  ];

  return (
    <div className="space-y-7 pb-16">
      <section className="command-hero surface-card relative overflow-hidden rounded-[30px] p-6 lg:p-8">
        <div className="absolute inset-y-0 right-0 w-1/2 bg-[radial-gradient(circle_at_center,rgba(89,225,247,.12),transparent_62%)]" />
        <div className="relative flex flex-col justify-between gap-8 lg:flex-row lg:items-center">
          <div className="max-w-2xl">
            <div className="mb-5 flex items-center gap-4"><StatusOrb active={systemActive} size="lg" /><div><p className="eyebrow">Live operations layer</p><p className="mt-1 text-xs text-slate-500">Database-backed · Human-approved · Durable execution</p></div></div>
            <h1 className="text-3xl font-black tracking-[-.035em] text-slate-50 sm:text-4xl">Your AI operating system,<br /><span className="bg-gradient-to-r from-cyan-300 to-emerald-300 bg-clip-text text-transparent">under real control.</span></h1>
            <p className="mt-4 max-w-xl text-sm leading-6 text-slate-400">Monitor councils, review decisions, and orchestrate integrations from one truthful command center. Motion reflects active system state—not decorative fake activity.</p>
          </div>
          <div className="grid min-w-[270px] gap-3 sm:grid-cols-2 lg:grid-cols-1">
            <Link href="/councils" className="flex items-center justify-between rounded-full bg-cyan-300 px-5 py-4 text-sm font-black text-[#04111b] transition hover:bg-cyan-200 active:scale-[.985]"><span className="flex items-center gap-2"><Plus className="h-4 w-4" />Start council</span><ArrowUpRight className="h-4 w-4" /></Link>
            <Link href="/workflows" className="glass-control flex items-center justify-between rounded-full px-5 py-4 text-sm font-bold text-slate-200"><span className="flex items-center gap-2"><Sparkles className="h-4 w-4 text-emerald-300" />Automation control</span><ArrowUpRight className="h-4 w-4" /></Link>
          </div>
        </div>
      </section>

      {error && <p role="alert" className="rounded-2xl border border-rose-300/20 bg-rose-400/8 p-4 text-sm text-rose-200">{error}</p>}

      <section className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        {metrics.map((item) => <article key={item.label} className="metric-tile surface-card rounded-[22px] p-5"><div className="flex items-start justify-between"><item.icon className={`h-5 w-5 ${item.tone}`} /><span className="status-dot text-slate-700" /></div><p className="mt-6 text-3xl font-black tracking-tight text-slate-50">{item.value}</p><p className="mt-2 text-xs font-bold uppercase tracking-[.13em] text-slate-400">{item.label}</p><p className="mt-1 text-xs text-slate-600">{item.hint}</p></article>)}
      </section>

      <div className="grid gap-5 xl:grid-cols-[1.5fr_.8fr]">
        <section>
          <div className="mb-4 flex items-end justify-between"><div><p className="eyebrow">Decision stream</p><h2 className="mt-1 text-xl font-bold text-slate-100">Recent work</h2></div><Link href="/approvals" className="text-xs font-bold text-cyan-300 hover:text-cyan-200">Open full queue →</Link></div>
          {recent.length === 0 ? <div className="surface-card rounded-2xl border-dashed py-20 text-center text-sm text-slate-500">No persisted tasks yet. Start a council when you are ready.</div> : <div className="space-y-3">{recent.map((task) => <TaskCard key={task.task_id} task={task} />)}</div>}
        </section>
        <aside className="surface-card h-fit rounded-2xl p-5">
          <div className="flex items-center justify-between"><div><p className="eyebrow">Readiness matrix</p><h2 className="mt-1 font-bold text-slate-100">Connected systems</h2></div><ShieldCheck className="h-5 w-5 text-emerald-300" /></div>
          <div className="mt-5 space-y-3">{integrations.slice(0, 7).map((item) => { const ready = ['ready','verified','connected'].includes(item.status); return <div key={item.id} className="flex items-center gap-3 rounded-xl border border-white/7 bg-white/[0.025] px-3 py-3"><span className={`status-dot ${ready ? 'text-emerald-300' : 'text-slate-600'}`} /><span className="min-w-0 flex-1 truncate text-sm font-semibold capitalize text-slate-300">{item.name}</span><span className="text-[10px] font-bold uppercase tracking-wide text-slate-600">{item.status}</span></div>; })}{integrations.length === 0 && <p className="py-8 text-center text-xs text-slate-600">Integration health unavailable.</p>}</div>
          <Link href="/settings" className="mt-5 flex h-10 items-center justify-center rounded-xl border border-white/10 text-xs font-bold text-slate-300 hover:bg-white/5">Manage secure connections</Link>
          {integrations.length > 0 && <p className="mt-3 text-center text-[11px] text-slate-600">{verified} of {integrations.length} currently verified</p>}
        </aside>
      </div>
    </div>
  );
}
