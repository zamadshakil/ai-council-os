'use client';

import Link from 'next/link';
import { FormEvent, useCallback, useEffect, useMemo, useState } from 'react';
import {
  Box, CheckCircle2, CircleDollarSign, CloudCog, Cpu, ExternalLink,
  FileCheck2, Gauge, LoaderCircle, Pause, Play, RefreshCw, ShieldCheck,
  Sparkles, TriangleAlert,
} from 'lucide-react';
import {
  actOnBlenderPod, createBlenderJob, fetchBlenderJobs, fetchBlenderPods,
} from '../lib/api';
import { BlenderPod, BlenderTemplateJob } from '../lib/types';

function duration(seconds: number): string {
  if (!seconds) return 'Not running';
  const hours = Math.floor(seconds / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  return `${hours}h ${minutes}m`;
}

function label(value: string): string {
  return value.replaceAll('_', ' ').replace(/\b\w/g, (character) => character.toUpperCase());
}

const ACTIVE = new Set(['queued', 'running', 'retry']);

export default function BlenderManagerPage() {
  const [pods, setPods] = useState<BlenderPod[]>([]);
  const [jobs, setJobs] = useState<BlenderTemplateJob[]>([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [podId, setPodId] = useState('');
  const [sourcePath, setSourcePath] = useState('/workspace/template.blend');
  const [outputName, setOutputName] = useState('template_gpu_fixed.blend');
  const [frame, setFrame] = useState(1);
  const [samples, setSamples] = useState(64);
  const [resolutionPercent, setResolutionPercent] = useState(25);
  const [autoStop, setAutoStop] = useState(true);

  const load = useCallback(async (quiet = false) => {
    if (!quiet) setLoading(true);
    setError('');
    const [podResult, jobResult] = await Promise.allSettled([
      fetchBlenderPods(),
      fetchBlenderJobs(),
    ]);
    if (podResult.status === 'fulfilled') {
      setPods(podResult.value);
      setPodId((current) => current || podResult.value[0]?.id || '');
    } else {
      setPods([]);
      setError(podResult.reason instanceof Error ? podResult.reason.message : 'RunPod status is unavailable.');
    }
    if (jobResult.status === 'fulfilled') setJobs(jobResult.value);
    if (!quiet) setLoading(false);
  }, []);

  useEffect(() => {
    let active = true;
    void Promise.allSettled([fetchBlenderPods(), fetchBlenderJobs()]).then(([podResult, jobResult]) => {
      if (!active) return;
      if (podResult.status === 'fulfilled') {
        setPods(podResult.value);
        setPodId(podResult.value[0]?.id || '');
      } else {
        setError(podResult.reason instanceof Error ? podResult.reason.message : 'RunPod status is unavailable.');
      }
      if (jobResult.status === 'fulfilled') setJobs(jobResult.value);
      setLoading(false);
    });
    return () => { active = false; };
  }, []);
  useEffect(() => {
    if (!jobs.some((job) => ACTIVE.has(job.status))) return;
    const timer = window.setInterval(() => { void load(true); }, 5000);
    return () => window.clearInterval(timer);
  }, [jobs, load]);

  async function act(pod: BlenderPod, action: 'resume' | 'stop') {
    setBusy(pod.id);
    setError('');
    try {
      const result = await actOnBlenderPod(pod.id, action);
      setPods((current) => current.map((item) => item.id === pod.id ? result.resource : item));
    } catch (actionError) {
      setError(actionError instanceof Error ? actionError.message : 'RunPod action failed.');
    } finally {
      setBusy('');
    }
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSubmitting(true);
    setError('');
    setNotice('');
    try {
      const response = await createBlenderJob({
        pod_id: podId,
        source_path: sourcePath,
        output_name: outputName,
        frame,
        samples,
        resolution_percent: resolutionPercent,
        auto_stop: autoStop,
        idempotency_key: `blender-${crypto.randomUUID()}`,
      });
      setJobs((current) => [response.resource, ...current.filter((job) => job.id !== response.resource.id)]);
      setNotice('GPU repair queued. The original file will remain unchanged.');
    } catch (submitError) {
      setError(submitError instanceof Error ? submitError.message : 'The Blender job could not be queued.');
    } finally {
      setSubmitting(false);
    }
  }

  const hourly = useMemo(
    () => pods.filter((pod) => pod.desired_status === 'RUNNING').reduce((sum, pod) => sum + pod.cost_per_hour, 0),
    [pods],
  );

  return <div className="mx-auto max-w-6xl space-y-7 pb-16">
    <section className="command-hero surface-card relative overflow-hidden rounded-[30px] p-7 lg:p-9">
      <div className="relative flex flex-col justify-between gap-6 lg:flex-row lg:items-end">
        <div>
          <p className="eyebrow">Cloud production control</p>
          <h1 className="mt-2 text-4xl font-black text-white">Blender GPU Manager</h1>
          <p className="mt-3 max-w-3xl text-sm leading-7 text-slate-300">Start the selected RunPod, validate a persistent-volume template, repair safe Cycles settings, prove GPU engagement with a benchmark frame, and save a new copy with durable logs.</p>
        </div>
        <div className="flex flex-wrap gap-3">
          <Link href="/settings" className="glass-control inline-flex h-11 items-center gap-2 rounded-full px-4 text-sm font-bold text-slate-100"><ShieldCheck className="h-4 w-4 text-cyan-300" />Configure RunPod</Link>
          <button disabled={loading} onClick={() => void load()} className="inline-flex h-11 items-center gap-2 rounded-full bg-cyan-300 px-4 text-sm font-black text-[#04111b] transition active:scale-[.985] disabled:opacity-50"><RefreshCw className={`h-4 w-4 ${loading ? 'animate-spin' : ''}`} />Refresh</button>
        </div>
      </div>
    </section>

    {error && <div role="alert" className="rounded-2xl border border-amber-300/25 bg-amber-300/8 p-4 text-sm text-amber-100"><strong>Attention:</strong> {error} <Link className="ml-1 font-bold underline" href="/settings">Open integrations</Link></div>}
    {notice && <div role="status" className="rounded-2xl border border-emerald-300/25 bg-emerald-300/8 p-4 text-sm text-emerald-100">{notice}</div>}

    <section className="grid gap-4 sm:grid-cols-3">
      <div className="metric-tile surface-card rounded-[22px] p-5"><p className="text-xs font-bold uppercase tracking-wider text-slate-400">Pods</p><p className="mt-2 text-3xl font-black text-white">{loading ? '—' : pods.length}</p></div>
      <div className="metric-tile surface-card rounded-[22px] p-5"><p className="text-xs font-bold uppercase tracking-wider text-slate-400">Running</p><p className="mt-2 text-3xl font-black text-emerald-300">{loading ? '—' : pods.filter((pod) => pod.desired_status === 'RUNNING').length}</p></div>
      <div className="metric-tile surface-card rounded-[22px] p-5"><p className="text-xs font-bold uppercase tracking-wider text-slate-400">Live hourly rate</p><p className="mt-2 text-3xl font-black text-cyan-200">{loading ? '—' : `$${hourly.toFixed(2)}`}</p></div>
    </section>

    <section aria-labelledby="gpu-repair-title" className="workspace-panel surface-card rounded-[30px] p-6 lg:p-8">
      <div className="flex items-start gap-4">
        <span className="grid h-12 w-12 shrink-0 place-items-center rounded-2xl border border-fuchsia-300/20 bg-fuchsia-300/10 text-fuchsia-200"><Sparkles className="h-6 w-6" /></span>
        <div><p className="eyebrow">Allowlisted operation</p><h2 id="gpu-repair-title" className="mt-1 text-2xl font-black text-white">Validate, repair & benchmark template</h2><p className="mt-2 text-sm leading-6 text-slate-300">No generated Python is executed. This operation only enables Cycles GPU devices, persistent data, controlled samples/resolution, checks missing assets, saves a copy, and benchmarks one frame.</p></div>
      </div>
      <form onSubmit={submit} className="mt-7 grid gap-5 lg:grid-cols-2">
        <div className="space-y-2">
          <label htmlFor="blender-pod" className="field-label">RunPod machine</label>
          <select
            id="blender-pod"
            required
            disabled={loading || pods.length === 0}
            aria-describedby="blender-pod-help"
            value={podId}
            onChange={(event) => setPodId(event.target.value)}
            className="input-shell h-12 rounded-xl px-4"
          >
            <option value="">{loading ? 'Loading available machines…' : pods.length === 0 ? 'No machine connected' : 'Choose a machine'}</option>
            {pods.map((pod) => <option key={pod.id} value={pod.id}>{pod.name} · {pod.desired_status}</option>)}
          </select>
          <span id="blender-pod-help" className="field-helper">
            {pods.length === 0 && !loading ? <>Connect and verify RunPod in <Link href="/settings" className="font-bold text-cyan-200 underline underline-offset-2">Settings &amp; Integrations</Link> first.</> : 'Choose the GPU machine that contains your Blender project.'}
          </span>
        </div>

        <label htmlFor="blender-source" className="space-y-2">
          <span className="field-label">Source Blender template</span>
          <input id="blender-source" required aria-describedby="blender-source-help" value={sourcePath} onChange={(event) => setSourcePath(event.target.value)} placeholder="/workspace/project/template.blend" className="input-shell h-12 rounded-xl px-4" />
          <span id="blender-source-help" className="field-helper">Full path to an existing .blend file on the machine&apos;s persistent storage.</span>
        </label>

        <label htmlFor="blender-output" className="space-y-2">
          <span className="field-label">Save repaired copy as</span>
          <input id="blender-output" required aria-describedby="blender-output-help" pattern="[A-Za-z0-9][A-Za-z0-9._-]{0,119}\.blend" value={outputName} onChange={(event) => setOutputName(event.target.value)} className="input-shell h-12 rounded-xl px-4" />
          <span id="blender-output-help" className="field-helper">A new file is created. Your original template is never overwritten.</span>
        </label>

        <div className="grid gap-3 sm:grid-cols-3" role="group" aria-label="Benchmark quality settings">
          <label htmlFor="blender-frame" className="space-y-2"><span className="field-label">Test frame</span><input id="blender-frame" type="number" min={0} value={frame} onChange={(event) => setFrame(Number(event.target.value))} className="input-shell h-12 rounded-xl px-3" /><span className="field-helper">Frame to render</span></label>
          <label htmlFor="blender-samples" className="space-y-2"><span className="field-label">Quality samples</span><input id="blender-samples" type="number" min={1} max={4096} value={samples} onChange={(event) => setSamples(Number(event.target.value))} className="input-shell h-12 rounded-xl px-3" /><span className="field-helper">1–4096 samples</span></label>
          <label htmlFor="blender-resolution" className="space-y-2"><span className="field-label">Resolution scale</span><div className="relative"><input id="blender-resolution" aria-describedby="blender-resolution-help" type="number" min={1} max={100} value={resolutionPercent} onChange={(event) => setResolutionPercent(Number(event.target.value))} className="input-shell h-12 rounded-xl px-3 pr-10" /><span aria-hidden="true" className="pointer-events-none absolute inset-y-0 right-3 flex items-center text-sm font-bold text-slate-400">%</span></div><span id="blender-resolution-help" className="field-helper">1–100 percent</span></label>
        </div>

        <label htmlFor="blender-auto-stop" className="flex min-h-20 cursor-pointer items-start gap-3 rounded-xl border border-white/18 bg-white/[0.04] p-4 text-slate-200 transition hover:border-cyan-300/35">
          <input id="blender-auto-stop" type="checkbox" checked={autoStop} onChange={(event) => setAutoStop(event.target.checked)} className="mt-0.5 h-5 w-5 shrink-0 accent-cyan-300" />
          <span><span className="block text-sm font-bold">Stop GPU billing automatically</span><span className="field-helper mt-1">Stops the machine when the job finishes or fails. Recommended for cost safety.</span></span>
        </label>
        <div>
          <button aria-describedby={!podId ? 'gpu-submit-help' : undefined} disabled={submitting || !podId} className="inline-flex h-13 w-full items-center justify-center gap-2 rounded-full bg-gradient-to-r from-cyan-300 to-emerald-300 px-5 text-sm font-black text-[#03131a] shadow-[0_12px_35px_rgba(70,220,230,0.18)] transition hover:brightness-110 active:scale-[.985] disabled:border disabled:border-white/14 disabled:bg-none disabled:bg-slate-700 disabled:text-slate-300 disabled:shadow-none">{submitting ? <LoaderCircle className="h-4 w-4 animate-spin" /> : <CloudCog className="h-4 w-4" />}{submitting ? 'Queuing secure GPU job…' : 'Run safe GPU repair'}</button>
          {!podId && <p id="gpu-submit-help" className="mt-2 text-center text-xs font-semibold text-amber-100">Connect a RunPod machine to enable this action.</p>}
        </div>
      </form>
    </section>

    <section aria-busy={loading} className="space-y-4">
      <div className="flex items-end justify-between"><div><p className="eyebrow">Live provider state</p><h2 className="mt-1 text-2xl font-black text-white">RunPod machines</h2></div></div>
      {loading && <div className="surface-card rounded-2xl p-10 text-center text-slate-300">Reading live RunPod status…</div>}
      {!loading && !error && pods.length === 0 && <div className="surface-card rounded-2xl p-10 text-center"><Box className="mx-auto h-8 w-8 text-slate-500" /><h3 className="mt-3 text-lg font-bold text-white">No RunPod pods found</h3><p className="mt-1 text-sm text-slate-400">The verified account currently has no pods.</p></div>}
      {pods.map((pod) => {
        const running = pod.desired_status === 'RUNNING';
        const gpu = pod.gpu_utilization[0];
        return <article key={pod.id} className={`surface-card rounded-2xl border p-6 ${running ? 'border-emerald-300/25' : ''}`}>
          <div className="flex flex-col justify-between gap-5 lg:flex-row lg:items-center"><div className="flex min-w-0 gap-4"><span className={`grid h-12 w-12 shrink-0 place-items-center rounded-2xl border ${running ? 'border-emerald-300/25 bg-emerald-300/10 text-emerald-300' : 'border-white/10 bg-white/5 text-slate-400'}`}><Cpu className="h-6 w-6" /></span><div className="min-w-0"><div className="flex flex-wrap items-center gap-2"><h3 className="truncate text-lg font-bold text-white">{pod.name}</h3><span className={`rounded-full px-2.5 py-1 text-[10px] font-black tracking-wider ${running ? 'bg-emerald-300/12 text-emerald-200' : 'bg-white/7 text-slate-300'}`}>{pod.desired_status}</span></div><p className="mt-1 truncate text-sm text-slate-400">{pod.image_name || 'Image not reported'} · {pod.gpu_count} GPU</p></div></div>
            <div className="flex flex-wrap gap-2">{pod.proxy_url && <a target="_blank" rel="noreferrer" href={pod.proxy_url} className="inline-flex h-10 items-center gap-2 rounded-xl border border-white/12 px-4 text-sm font-bold text-slate-200 hover:border-cyan-300/35"><ExternalLink className="h-4 w-4" />Open workspace</a>}<button disabled={busy === pod.id} onClick={() => void act(pod, running ? 'stop' : 'resume')} className={`inline-flex h-10 items-center gap-2 rounded-xl px-4 text-sm font-black disabled:opacity-50 ${running ? 'bg-amber-300 text-[#181004]' : 'bg-emerald-300 text-[#04140d]'}`}>{running ? <Pause className="h-4 w-4" /> : <Play className="h-4 w-4" />}{busy === pod.id ? 'Updating…' : running ? 'Stop billing' : 'Resume pod'}</button></div></div>
          <div className="mt-5 grid gap-3 border-t border-white/8 pt-5 sm:grid-cols-3"><div className="flex items-center gap-3 text-sm text-slate-300"><CircleDollarSign className="h-4 w-4 text-cyan-300" /><span>${pod.cost_per_hour.toFixed(3)}/hour</span></div><div className="flex items-center gap-3 text-sm text-slate-300"><Gauge className="h-4 w-4 text-cyan-300" /><span>{gpu ? `${gpu.gpu_percent.toFixed(0)}% GPU · ${gpu.memory_percent.toFixed(0)}% VRAM` : 'Utilization not reported'}</span></div><div className="text-sm text-slate-300">Uptime: {duration(pod.uptime_seconds)}</div></div>
        </article>;
      })}
    </section>

    <section className="space-y-4">
      <div><p className="eyebrow">Durable execution history</p><h2 className="mt-1 text-2xl font-black text-white">Template jobs</h2></div>
      {jobs.length === 0 && <div className="surface-card rounded-2xl p-8 text-sm text-slate-400">No template jobs have been queued.</div>}
      {jobs.map((job) => {
        const report = job.result?.report;
        const successful = job.status === 'completed' && report?.gpu_engaged;
        return <article key={job.id} className={`surface-card rounded-2xl border p-6 ${successful ? 'border-emerald-300/25' : job.error ? 'border-rose-300/25' : 'border-cyan-300/15'}`}>
          <div className="flex flex-col justify-between gap-4 sm:flex-row"><div className="flex gap-3">{successful ? <CheckCircle2 className="mt-1 h-5 w-5 text-emerald-300" /> : job.error ? <TriangleAlert className="mt-1 h-5 w-5 text-rose-300" /> : <LoaderCircle className="mt-1 h-5 w-5 animate-spin text-cyan-300" />}<div><h3 className="font-bold text-white">{job.output_name}</h3><p className="mt-1 text-sm text-slate-400">{job.source_path}</p></div></div><span className="h-fit rounded-full border border-white/10 bg-white/5 px-3 py-1 text-xs font-black text-slate-200">{label(job.stage || job.status)}</span></div>
          {job.error && <p role="alert" className="mt-4 rounded-xl bg-rose-300/8 p-3 text-sm text-rose-100">{job.error}</p>}
          {report && <div className="mt-5 grid gap-3 border-t border-white/8 pt-5 sm:grid-cols-4"><div className="text-sm text-slate-300"><span className="block text-xs uppercase tracking-wider text-slate-500">GPU proof</span>{report.gpu_engaged ? `${report.gpu?.backend || 'GPU'} · ${report.gpu?.enabled_gpu_count || 1} device` : 'Not confirmed'}</div><div className="text-sm text-slate-300"><span className="block text-xs uppercase tracking-wider text-slate-500">Engine</span>{report.render_engine || 'Unavailable'}</div><div className="text-sm text-slate-300"><span className="block text-xs uppercase tracking-wider text-slate-500">Benchmark</span>{typeof report.benchmark_seconds === 'number' ? `${report.benchmark_seconds.toFixed(2)} sec` : 'Unavailable'}</div><div className="text-sm text-slate-300"><span className="block text-xs uppercase tracking-wider text-slate-500">Missing assets</span>{report.missing_assets?.length ?? 0}</div></div>}
          {job.result?.output_path && <p className="mt-4 flex items-center gap-2 break-all rounded-xl bg-white/[0.03] p-3 text-sm text-slate-300"><FileCheck2 className="h-4 w-4 shrink-0 text-emerald-300" />Saved on pod: {job.result.output_path}</p>}
          {(job.result?.log_tail?.length ?? 0) > 0 && <details className="mt-4"><summary className="cursor-pointer text-sm font-bold text-cyan-200">View Blender log tail</summary><pre className="mt-3 max-h-64 overflow-auto rounded-xl border border-white/8 bg-[#050b13] p-4 text-xs leading-6 text-slate-300">{job.result.log_tail?.join('\n')}</pre></details>}
        </article>;
      })}
    </section>
  </div>;
}
