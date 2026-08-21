'use client';

import Link from 'next/link';
import { FormEvent, useCallback, useEffect, useMemo, useState } from 'react';
import {
  Activity, Box, CircleDollarSign, CloudUpload,
  Cpu, ExternalLink, FileImage, FolderOpen, LoaderCircle,
  MonitorPlay, Pause, Play, RefreshCw, RotateCcw, ShieldCheck, Square, XCircle,
} from 'lucide-react';
import {
  actOnBlenderPod, actOnBlenderRenderJob, createBlenderRenderJob,
  fetchBlenderPods, fetchBlenderRenderArtifacts, fetchBlenderRenderFrames,
  fetchBlenderRenderJobs, fetchBlenderRenderTelemetry, provisionBlenderPod,
} from '../lib/api';
import {
  BlenderArtifact, BlenderPod, BlenderPodAccess, BlenderRenderFrame, BlenderRenderJob,
  BlenderTelemetrySample,
} from '../lib/types';

const ACTIVE = new Set([
  'queued', 'running', 'benchmarking', 'rendering', 'validating', 'encoding',
  'delivering', 'retrying', 'awaiting_kasm_render',
]);

function human(value: string): string {
  return value.replaceAll('_', ' ').replaceAll('.', ' ').replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function bytes(value: number): string {
  if (!value) return 'Unavailable';
  const units = ['B', 'KB', 'MB', 'GB', 'TB'];
  let size = value;
  let index = 0;
  while (size >= 1024 && index < units.length - 1) { size /= 1024; index += 1; }
  return `${size.toFixed(index > 1 ? 1 : 0)} ${units[index]}`;
}

function duration(seconds: number): string {
  if (!seconds) return 'Not running';
  const hours = Math.floor(seconds / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  return `${hours}h ${minutes}m`;
}

function record(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : {};
}

function number(value: unknown): number {
  return typeof value === 'number' && Number.isFinite(value) ? value : 0;
}

function text(value: unknown): string {
  return typeof value === 'string' ? value : '';
}

function statusTone(status: string): string {
  if (['completed', 'ready'].includes(status)) return 'border-emerald-300/25 bg-emerald-300/10 text-emerald-200';
  if (['failed', 'blocked', 'cancelled', 'needs_frame_retry'].includes(status)) return 'border-rose-300/25 bg-rose-300/10 text-rose-100';
  if (status.includes('awaiting')) return 'border-amber-300/25 bg-amber-300/10 text-amber-100';
  return 'border-cyan-300/25 bg-cyan-300/10 text-cyan-100';
}

function FrameMap({ frames }: { frames: BlenderRenderFrame[] }) {
  const buckets = useMemo(() => {
    if (!frames.length) return [];
    const bucketSize = Math.max(1, Math.ceil(frames.length / 180));
    const result = [];
    for (let index = 0; index < frames.length; index += bucketSize) {
      const values = frames.slice(index, index + bucketSize);
      const status = values.some((item) => item.status === 'failed') ? 'failed'
        : values.every((item) => item.status === 'completed') ? 'completed'
          : values.some((item) => item.status === 'rendering') ? 'rendering' : 'pending';
      result.push({ start: values[0].frame_number, end: values.at(-1)?.frame_number ?? values[0].frame_number, status });
    }
    return result;
  }, [frames]);
  if (!buckets.length) return <p className="text-sm text-slate-400">Frames appear after scene preflight.</p>;
  return <div className="grid grid-cols-[repeat(auto-fill,minmax(16px,1fr))] gap-1" role="img" aria-label="Render frame completion map">
    {buckets.map((bucket) => <span
      key={`${bucket.start}-${bucket.end}`}
      title={`Frames ${bucket.start}–${bucket.end}: ${bucket.status}`}
      aria-label={`Frames ${bucket.start} through ${bucket.end}: ${bucket.status}`}
      className={`h-7 rounded-md border ${bucket.status === 'completed' ? 'border-emerald-300/30 bg-emerald-300/55' : bucket.status === 'failed' ? 'border-rose-300/40 bg-rose-300/55' : bucket.status === 'rendering' ? 'animate-pulse border-cyan-300/40 bg-cyan-300/55 motion-reduce:animate-none' : 'border-white/8 bg-white/[0.035]'}`}
    />)}
  </div>;
}

function TelemetryChart({ samples }: { samples: BlenderTelemetrySample[] }) {
  const values = samples.slice(-80).map((item) => Math.max(0, Math.min(100, item.gpu_utilization)));
  const points = values.map((value, index) => `${(index / Math.max(1, values.length - 1)) * 100},${100 - value}`).join(' ');
  const latest = samples.at(-1);
  return <div className="rounded-2xl border border-white/10 bg-[#050d18]/70 p-4">
    <div className="flex flex-wrap justify-between gap-3">
      <div><p className="text-xs font-bold uppercase tracking-widest text-slate-500">Live GPU evidence</p><p className="mt-1 text-2xl font-black text-white">{latest ? `${latest.gpu_utilization.toFixed(0)}%` : 'No samples'}</p></div>
      <div className="grid grid-cols-2 gap-x-5 gap-y-1 text-xs text-slate-300">
        <span>VRAM</span><strong>{latest ? `${(latest.vram_used_mb / 1024).toFixed(1)} / ${(latest.vram_total_mb / 1024).toFixed(1)} GB` : '—'}</strong>
        <span>Power</span><strong>{latest ? `${latest.power_watts.toFixed(0)} W` : '—'}</strong>
        <span>Blender PID</span><strong>{latest?.blender_pid ?? 'Not observed'}</strong>
      </div>
    </div>
    <svg className="mt-4 h-24 w-full overflow-visible" viewBox="0 0 100 100" preserveAspectRatio="none" role="img" aria-label="Recent GPU utilization percentage">
      <defs><linearGradient id="gpu-fill" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stopColor="#5ee8f6" stopOpacity=".42" /><stop offset="1" stopColor="#5ee8f6" stopOpacity="0" /></linearGradient></defs>
      {points && <><polygon points={`0,100 ${points} 100,100`} fill="url(#gpu-fill)" /><polyline points={points} fill="none" stroke="#67e8f9" strokeWidth="2" vectorEffect="non-scaling-stroke" /></>}
    </svg>
  </div>;
}

export default function BlenderManagerPage() {
  const [pods, setPods] = useState<BlenderPod[]>([]);
  const [jobs, setJobs] = useState<BlenderRenderJob[]>([]);
  const [frames, setFrames] = useState<BlenderRenderFrame[]>([]);
  const [telemetry, setTelemetry] = useState<BlenderTelemetrySample[]>([]);
  const [artifacts, setArtifacts] = useState<BlenderArtifact[]>([]);
  const [selectedId, setSelectedId] = useState('');
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState('');
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [podId, setPodId] = useState('');
  const [sourcePath, setSourcePath] = useState('/workspace/template.blend');
  const [renderMode, setRenderMode] = useState<'headless' | 'kasm_gui'>('headless');
  const [profile, setProfile] = useState<'delivery' | 'compositing'>('delivery');
  const [drivePath, setDrivePath] = useState('Council OS Renders');
  const [requireDrive, setRequireDrive] = useState(true);
  const [autoStop, setAutoStop] = useState(true);
  const [runtimeAccess, setRuntimeAccess] = useState<BlenderPodAccess | null>(null);
  const [billingConfirmed, setBillingConfirmed] = useState(false);
  const [provisionFeedback, setProvisionFeedback] = useState<{
    kind: 'error' | 'success'; message: string;
  } | null>(null);

  const selected = jobs.find((job) => job.id === selectedId) ?? jobs[0];
  const selectedPod = pods.find((pod) => pod.id === (selected?.pod_id ?? podId));

  const load = useCallback(async (quiet = false) => {
    if (!quiet) setLoading(true);
    const [podResult, jobResult] = await Promise.allSettled([fetchBlenderPods(), fetchBlenderRenderJobs()]);
    if (podResult.status === 'fulfilled') {
      setPods(podResult.value);
      setPodId((current) => current || podResult.value[0]?.id || '');
    } else if (!quiet) setError(podResult.reason instanceof Error ? podResult.reason.message : 'RunPod status is unavailable.');
    if (jobResult.status === 'fulfilled') {
      setJobs(jobResult.value);
      setSelectedId((current) => current || jobResult.value[0]?.id || '');
    }
    if (!quiet) setLoading(false);
  }, []);

  const loadDetails = useCallback(async (id: string) => {
    const [frameResult, telemetryResult, artifactResult] = await Promise.allSettled([
      fetchBlenderRenderFrames(id), fetchBlenderRenderTelemetry(id), fetchBlenderRenderArtifacts(id),
    ]);
    if (frameResult.status === 'fulfilled') setFrames(frameResult.value);
    if (telemetryResult.status === 'fulfilled') setTelemetry(telemetryResult.value);
    if (artifactResult.status === 'fulfilled') setArtifacts(artifactResult.value);
  }, []);

  useEffect(() => {
    const timer = window.setTimeout(() => { void load(); }, 0);
    return () => window.clearTimeout(timer);
  }, [load]);
  useEffect(() => {
    if (!selected?.id) return;
    const timer = window.setTimeout(() => { void loadDetails(selected.id); }, 0);
    return () => window.clearTimeout(timer);
  }, [selected?.id, loadDetails]);
  useEffect(() => {
    if (!jobs.some((job) => ACTIVE.has(job.status)) && !pods.some((pod) => pod.desired_status === 'RUNNING')) return;
    const timer = window.setInterval(() => {
      void load(true);
      if (selected?.id) void loadDetails(selected.id);
    }, 5000);
    return () => window.clearInterval(timer);
  }, [jobs, pods, selected?.id, load, loadDetails]);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy('create'); setError(''); setNotice('');
    try {
      const response = await createBlenderRenderJob({
        pod_id: podId, source_path: sourcePath, render_mode: renderMode, output_profile: profile,
        frame_start: null, frame_end: null, frame_step: 1, samples: 0, resolution_percent: 100,
        require_drive: requireDrive, drive_path: drivePath, auto_stop: autoStop,
        idempotency_key: `render-${crypto.randomUUID()}`,
      });
      setJobs((current) => [response.resource, ...current]);
      setSelectedId(response.resource.id);
      setNotice('Scene preflight queued. Council OS will read the artist’s frame range and 4K settings from the .blend file.');
    } catch (cause) { setError(cause instanceof Error ? cause.message : 'Render job could not be created.'); }
    finally { setBusy(''); }
  }

  async function renderAction(action: Parameters<typeof actOnBlenderRenderJob>[1]) {
    if (!selected) return;
    if (action === 'cancel' && !window.confirm('Cancel this production render? Completed frames will remain on the pod.')) return;
    setBusy(action); setError(''); setNotice('');
    try {
      const response = await actOnBlenderRenderJob(selected.id, action, selected.version);
      setJobs((current) => current.map((job) => job.id === selected.id ? response.resource : job));
      setNotice(action === 'approve_benchmark'
        ? selected.render_mode === 'kasm_gui'
          ? 'Kasm render is armed. Open Blender and choose Render → Render Animation.'
          : 'Approved. Durable headless frame batches are now queued on the one-GPU baseline.'
        : `${human(action)} accepted.`);
    } catch (cause) { setError(cause instanceof Error ? cause.message : 'Render action failed.'); }
    finally { setBusy(''); }
  }

  async function podAction(
    pod: BlenderPod,
    action: 'resume' | 'stop' | 'prepare_runtime' | 'reveal_access',
  ) {
    const inventoryConfirmed = action === 'prepare_runtime'
      ? window.confirm('Before replacing the old container, confirm that you inventoried /workspace and copied every critical file from container storage into /workspace. Continue only after the one-A6000 smoke image has passed.')
      : false;
    if (action === 'prepare_runtime' && !inventoryConfirmed) return;
    setBusy(`${pod.id}:${action}`); setError(''); setNotice('');
    try {
      const response = await actOnBlenderPod(pod.id, action, inventoryConfirmed);
      setPods((current) => current.map((item) => item.id === pod.id ? response.resource : item));
      if (response.access) setRuntimeAccess(response.access);
      setNotice(action === 'prepare_runtime'
        ? 'The stopped pod now uses the approved immutable Blender/Kasm image. /workspace was preserved.'
        : action === 'reveal_access' ? 'Kasm access is shown below. Do not share this password.'
          : `${human(action)} accepted.`);
    } catch (cause) { setError(cause instanceof Error ? cause.message : 'Pod action failed.'); }
    finally { setBusy(''); }
  }

  async function provisionA6000() {
    if (!billingConfirmed) return;
    if (!window.confirm('Create and start one Secure Cloud NVIDIA RTX A6000 Pod? RunPod GPU and persistent-storage billing begins immediately.')) return;
    setBusy('provision'); setError(''); setNotice(''); setProvisionFeedback(null);
    try {
      const response = await provisionBlenderPod();
      setPods((current) => [response.resource, ...current.filter((item) => item.id !== response.resource.id)]);
      setPodId(response.resource.id);
      setBillingConfirmed(false);
      const message = 'One RTX A6000 Kasm workstation was created. Wait for RUNNING, then verify Kasm and GPU evidence before loading the production scene.';
      setNotice(message);
      setProvisionFeedback({ kind: 'success', message });
    } catch (cause) {
      const message = cause instanceof Error ? cause.message : 'The A6000 workstation could not be created.';
      setError(message);
      setProvisionFeedback({ kind: 'error', message });
    }
    finally { setBusy(''); }
  }

  const preflight = record(selected?.preflight);
  const scene = record(preflight.scene);
  const storage = record(preflight.storage);
  const drive = record(preflight.drive);
  const runtime = record(preflight.runtime);
  const benchmark = record(selected?.benchmark);
  const evidence = record(benchmark.gpu_evidence);
  const soak = record(benchmark.soak);
  const missingAssets = Array.isArray(preflight.missing_assets) ? preflight.missing_assets : [];
  const avgFrameSeconds = number(benchmark.average_frame_seconds);
  const estimatedHours = selected && avgFrameSeconds ? avgFrameSeconds * selected.expected_frame_count / 3600 : 0;
  const estimatedCost = estimatedHours * (selectedPod?.cost_per_hour ?? 0);
  const progress = selected?.expected_frame_count ? selected.completed_frame_count / selected.expected_frame_count * 100 : 0;
  const runningPods = pods.filter((pod) => pod.desired_status === 'RUNNING');

  return <div className="mx-auto max-w-[1480px] space-y-7 pb-16">
    <section className="command-hero surface-card overflow-hidden rounded-[30px] p-7 lg:p-9">
      <div className="flex flex-col justify-between gap-6 lg:flex-row lg:items-end">
        <div><p className="eyebrow">Kasm editing · durable GPU rendering</p><h1 className="mt-2 text-4xl font-black text-white">Blender Render Control</h1><p className="mt-3 max-w-3xl text-sm leading-7 text-slate-300">Open the scene in Kasm for artist review, then use the safe automated renderer by default. Council OS validates the scene, proves real GPU compute, watches every frame, protects storage, and delivers the result.</p></div>
        <div className="flex flex-wrap gap-3"><Link href="/settings" className="glass-control inline-flex h-11 items-center gap-2 rounded-full px-4 text-sm font-bold text-slate-100"><ShieldCheck className="h-4 w-4 text-cyan-300" />RunPod connection</Link><button disabled={loading} onClick={() => void load()} className="inline-flex h-11 items-center gap-2 rounded-full bg-cyan-300 px-4 text-sm font-black text-[#04111b] disabled:opacity-50"><RefreshCw className={`h-4 w-4 ${loading ? 'animate-spin motion-reduce:animate-none' : ''}`} />Refresh</button></div>
      </div>
    </section>

    {error && <div role="alert" className="rounded-2xl border border-rose-300/25 bg-rose-300/10 p-4 text-sm text-rose-100"><strong>Action needed:</strong> {error}</div>}
    {notice && <div role="status" className="rounded-2xl border border-emerald-300/25 bg-emerald-300/10 p-4 text-sm text-emerald-100">{notice}</div>}

    <section className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
      <div className="metric-tile surface-card rounded-[22px] p-5"><Cpu className="h-5 w-5 text-cyan-300" /><p className="mt-3 text-xs font-bold uppercase tracking-wider text-slate-400">Running GPUs</p><p className="mt-1 text-3xl font-black text-white">{runningPods.reduce((sum, pod) => sum + pod.gpu_count, 0)}</p></div>
      <div className="metric-tile surface-card rounded-[22px] p-5"><Activity className="h-5 w-5 text-emerald-300" /><p className="mt-3 text-xs font-bold uppercase tracking-wider text-slate-400">Active renders</p><p className="mt-1 text-3xl font-black text-white">{jobs.filter((job) => ACTIVE.has(job.status)).length}</p></div>
      <div className="metric-tile surface-card rounded-[22px] p-5"><FileImage className="h-5 w-5 text-fuchsia-300" /><p className="mt-3 text-xs font-bold uppercase tracking-wider text-slate-400">Frames complete</p><p className="mt-1 text-3xl font-black text-white">{jobs.reduce((sum, job) => sum + job.completed_frame_count, 0)}</p></div>
      <div className="metric-tile surface-card rounded-[22px] p-5"><CircleDollarSign className="h-5 w-5 text-amber-300" /><p className="mt-3 text-xs font-bold uppercase tracking-wider text-slate-400">Live hourly rate</p><p className="mt-1 text-3xl font-black text-white">${runningPods.reduce((sum, pod) => sum + pod.cost_per_hour, 0).toFixed(2)}</p></div>
    </section>

    <section className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_410px]">
      <div className="surface-card rounded-[30px] p-6 lg:p-8">
        <div className="flex items-start gap-4"><span className="grid h-12 w-12 place-items-center rounded-2xl border border-cyan-300/25 bg-cyan-300/10 text-cyan-200"><MonitorPlay className="h-6 w-6" /></span><div><p className="eyebrow">Artist workflow</p><h2 className="mt-1 text-2xl font-black text-white">Prepare a production render</h2><p className="mt-2 text-sm leading-6 text-slate-300">Preflight never edits the source. Kasm remains available for interactive inspection; final headless batches are restartable and avoid tying production to the desktop session.</p></div></div>
        <form onSubmit={submit} className="mt-7 grid gap-5 lg:grid-cols-2">
          <label className="space-y-2"><span className="field-label">RunPod machine</span><select required value={podId} onChange={(event) => setPodId(event.target.value)} className="input-shell h-12 rounded-xl px-4"><option value="">Choose a machine</option>{pods.map((pod) => <option key={pod.id} value={pod.id}>{pod.name} · {pod.desired_status} · {pod.gpu_count} GPU</option>)}</select><span className="field-helper">The one-GPU safety baseline is enforced.</span></label>
          <label className="space-y-2"><span className="field-label">Blender scene on /workspace</span><input required value={sourcePath} onChange={(event) => setSourcePath(event.target.value)} placeholder="/workspace/project/scene.blend" className="input-shell h-12 rounded-xl px-4" /><span className="field-helper">Use the actual persistent-volume path, not a Google Drive mount.</span></label>
          <fieldset className="space-y-2 lg:col-span-2"><legend className="field-label">Render control</legend><div className="grid gap-2 sm:grid-cols-2">{([
            { value: 'headless' as const, title: 'Automated safe run', detail: 'Recommended · durable batches, retries, and no desktop dependency' },
            { value: 'kasm_gui' as const, title: 'Render from Kasm', detail: 'Manual · click Render Animation in the Blender desktop' },
          ]).map((choice) => <button key={choice.value} type="button" aria-pressed={renderMode === choice.value} onClick={() => setRenderMode(choice.value)} className={`rounded-xl border p-4 text-left transition ${renderMode === choice.value ? 'border-cyan-300/55 bg-cyan-300/12 text-white ring-2 ring-cyan-300/20' : 'border-white/12 bg-white/[0.035] text-slate-300'}`}><strong className="block">{choice.title}</strong><span className="mt-1 block text-xs text-slate-400">{choice.detail}</span></button>)}</div></fieldset>
          <fieldset className="space-y-2"><legend className="field-label">Output workflow</legend><div className="grid grid-cols-2 gap-2">{(['delivery', 'compositing'] as const).map((value) => <button key={value} type="button" aria-pressed={profile === value} onClick={() => setProfile(value)} className={`rounded-xl border p-3 text-left text-sm transition ${profile === value ? 'border-cyan-300/55 bg-cyan-300/12 text-white ring-2 ring-cyan-300/20' : 'border-white/12 bg-white/[0.035] text-slate-300'}`}><strong className="block">{value === 'delivery' ? '4K delivery' : 'Compositing'}</strong><span className="mt-1 block text-xs text-slate-400">{value === 'delivery' ? '16-bit PNG + MP4' : 'Half-float EXR frames'}</span></button>)}</div></fieldset>
          <label className="space-y-2"><span className="field-label">Google Drive destination</span><input disabled={!requireDrive} value={drivePath} onChange={(event) => setDrivePath(event.target.value)} className="input-shell h-12 rounded-xl px-4 disabled:opacity-45" /><span className="field-helper">Drive is used only after local rendering finishes.</span></label>
          <label className="flex min-h-20 items-start gap-3 rounded-xl border border-white/12 bg-white/[0.035] p-4"><input type="checkbox" checked={requireDrive} onChange={(event) => setRequireDrive(event.target.checked)} className="mt-1 h-5 w-5 accent-cyan-300" /><span><strong className="block text-sm text-white">Require delivery capacity</strong><span className="field-helper mt-1">Block the full render if Drive quota or the write probe fails.</span></span></label>
          <label className="flex min-h-20 items-start gap-3 rounded-xl border border-white/12 bg-white/[0.035] p-4"><input type="checkbox" checked={autoStop} onChange={(event) => setAutoStop(event.target.checked)} className="mt-1 h-5 w-5 accent-cyan-300" /><span><strong className="block text-sm text-white">Stop pod at approval gates</strong><span className="field-helper mt-1">Saves billing, but the artist must resume it before opening Kasm.</span></span></label>
          <button disabled={busy === 'create' || !podId} className="lg:col-span-2 inline-flex h-13 items-center justify-center gap-2 rounded-full bg-gradient-to-r from-cyan-300 to-emerald-300 px-5 text-sm font-black text-[#03131a] disabled:opacity-45">{busy === 'create' ? <LoaderCircle className="h-4 w-4 animate-spin motion-reduce:animate-none" /> : <ShieldCheck className="h-4 w-4" />}{busy === 'create' ? 'Starting truthful preflight…' : 'Preflight scene & GPU'}</button>
        </form>
      </div>

      <aside className="surface-card rounded-[30px] p-6">
        <p className="eyebrow">RunPod machines</p><h2 className="mt-1 text-xl font-black text-white">Kasm access & billing</h2>
        <div className="mt-5 rounded-2xl border border-cyan-300/20 bg-cyan-300/[0.055] p-4">
          <div className="flex items-start gap-3"><Cpu className="mt-0.5 h-5 w-5 text-cyan-300" /><div><p className="text-sm font-black text-white">Create the safe baseline</p><p className="mt-1 text-xs leading-5 text-slate-300">Exactly 1× RTX A6000 · Secure Cloud · on-demand · 64 GB minimum host RAM · 250 GB persistent /workspace.</p></div></div>
          <label className="mt-4 flex items-start gap-3 text-xs text-slate-200"><input type="checkbox" checked={billingConfirmed} onChange={(event) => setBillingConfirmed(event.target.checked)} className="mt-0.5 h-4 w-4 accent-cyan-300" /><span>I understand RunPod GPU and storage billing begins when this Pod is created.</span></label>
          <button type="button" onClick={() => void provisionA6000()} disabled={!billingConfirmed || !!busy} className="mt-4 inline-flex h-10 w-full items-center justify-center gap-2 rounded-xl bg-cyan-300 px-3 text-xs font-black text-[#04111b] disabled:cursor-not-allowed disabled:opacity-40">{busy === 'provision' ? <LoaderCircle className="h-4 w-4 animate-spin motion-reduce:animate-none" /> : <Play className="h-4 w-4" />}{busy === 'provision' ? 'Creating A6000 workstation…' : 'Create 1-GPU Kasm workstation'}</button>
          {provisionFeedback && <div
            role={provisionFeedback.kind === 'error' ? 'alert' : 'status'}
            className={`mt-3 rounded-xl border p-3 text-xs leading-5 ${provisionFeedback.kind === 'error' ? 'border-rose-300/30 bg-rose-300/10 text-rose-100' : 'border-emerald-300/30 bg-emerald-300/10 text-emerald-100'}`}
          ><strong>{provisionFeedback.kind === 'error' ? 'Creation failed: ' : 'Created: '}</strong>{provisionFeedback.message}</div>}
        </div>
        <div className="mt-5 space-y-3">{pods.map((pod) => {
          const localSample = pod.local_runtime?.gpu_samples?.[0];
          const guiState = pod.local_runtime?.gui_state;
          const gpuValue = localSample?.gpu_utilization ?? pod.gpu_utilization[0]?.gpu_percent ?? 0;
          const vramValue = localSample?.vram_total_mb
            ? (localSample.vram_used_mb / localSample.vram_total_mb) * 100
            : pod.gpu_utilization[0]?.memory_percent ?? 0;
          const blenderPid = localSample?.blender_pid ?? pod.local_runtime?.blender_processes?.[0]?.pid ?? null;
          const gpuConfigured = guiState?.cycles_gpu_configured === true;
          return <article key={pod.id} className="rounded-2xl border border-white/10 bg-white/[0.035] p-4">
          <div className="flex items-start justify-between gap-3"><div><h3 className="font-bold text-white">{pod.name}</h3><p className="mt-1 break-all text-xs text-slate-400">{pod.image_name || 'Image not reported'}</p></div><span className={`rounded-full border px-2 py-1 text-[10px] font-black ${pod.desired_status === 'RUNNING' ? statusTone('ready') : statusTone('paused')}`}>{pod.desired_status}</span></div>
          <div className="mt-4 flex flex-wrap gap-2">
            {pod.proxy_url && <a href={pod.proxy_url} target="_blank" rel="noreferrer" className="inline-flex h-10 items-center gap-2 rounded-xl border border-cyan-300/25 px-3 text-xs font-bold text-cyan-100"><ExternalLink className="h-4 w-4" />Open Kasm</a>}
            <button onClick={() => void podAction(pod, pod.desired_status === 'RUNNING' ? 'stop' : 'resume')} disabled={busy.startsWith(pod.id)} className="inline-flex h-10 items-center gap-2 rounded-xl bg-white/8 px-3 text-xs font-bold text-white disabled:opacity-45">{pod.desired_status === 'RUNNING' ? <Square className="h-4 w-4" /> : <Play className="h-4 w-4" />}{pod.desired_status === 'RUNNING' ? 'Stop billing' : 'Resume'}</button>
            {pod.desired_status !== 'RUNNING' && <button onClick={() => void podAction(pod, 'prepare_runtime')} disabled={busy.startsWith(pod.id)} className="inline-flex h-10 items-center gap-2 rounded-xl border border-emerald-300/25 px-3 text-xs font-bold text-emerald-100 disabled:opacity-45"><ShieldCheck className="h-4 w-4" />Install approved runtime</button>}
            <button onClick={() => void podAction(pod, 'reveal_access')} disabled={busy.startsWith(pod.id)} className="inline-flex h-10 items-center gap-2 rounded-xl border border-white/12 px-3 text-xs font-bold text-slate-200 disabled:opacity-45">Show Kasm login</button>
          </div>
          <p className="mt-3 text-xs text-slate-400">${pod.cost_per_hour.toFixed(3)}/hr · {duration(pod.uptime_seconds)}</p>
          {pod.telemetry_status === 'live' ? <div className="mt-3 grid grid-cols-2 gap-2 text-[11px] text-slate-300 sm:grid-cols-4">
            <span className="rounded-lg border border-white/8 bg-black/15 px-2 py-1.5">GPU <strong className="text-cyan-200">{gpuValue.toFixed(0)}%</strong></span>
            <span className="rounded-lg border border-white/8 bg-black/15 px-2 py-1.5">VRAM <strong className="text-fuchsia-200">{vramValue.toFixed(0)}%</strong></span>
            <span className="rounded-lg border border-white/8 bg-black/15 px-2 py-1.5">CPU <strong className="text-emerald-200">{pod.cpu_percent.toFixed(0)}%</strong></span>
            <span className="rounded-lg border border-white/8 bg-black/15 px-2 py-1.5">RAM <strong className="text-amber-200">{pod.memory_percent.toFixed(0)}%</strong></span>
          </div> : <p className="mt-3 text-[11px] font-bold text-amber-200">Live provider telemetry unavailable</p>}
          {pod.agent_status === 'live' && <div className="mt-3 flex flex-wrap gap-2 text-[10px] font-bold">
            <span className={`rounded-full border px-2.5 py-1 ${gpuConfigured ? 'border-emerald-300/25 bg-emerald-300/10 text-emerald-100' : 'border-amber-300/25 bg-amber-300/10 text-amber-100'}`}>Cycles {gpuConfigured ? `${guiState?.backend || 'GPU'} configured` : 'waiting for a Cycles scene'}</span>
            <span className={`rounded-full border px-2.5 py-1 ${blenderPid ? 'border-cyan-300/25 bg-cyan-300/10 text-cyan-100' : 'border-white/10 bg-white/[0.035] text-slate-400'}`}>Blender {blenderPid ? `PID ${blenderPid}` : 'not open'}</span>
            <span className="rounded-full border border-white/10 bg-white/[0.035] px-2.5 py-1 text-slate-300">{gpuValue > 0 ? 'GPU active now' : 'GPU idle now'}</span>
          </div>}
          {pod.agent_status === 'live' && gpuValue === 0 && <p className="mt-2 text-[11px] leading-5 text-slate-400">0% means no GPU kernel was active at this instant; it does not mean the A6000 is unavailable.</p>}
          {guiState?.error && <p className="mt-2 text-[11px] font-bold text-rose-200">{guiState.error}</p>}
        </article>})}</div>
        {runtimeAccess && <div className="mt-4 rounded-2xl border border-amber-300/25 bg-amber-300/8 p-4" role="status"><p className="text-xs font-black uppercase tracking-wider text-amber-100">Private Kasm login</p><dl className="mt-3 grid grid-cols-[auto_1fr] gap-x-3 gap-y-2 text-xs"><dt className="text-slate-400">Username</dt><dd className="select-all font-mono text-white">{runtimeAccess.username}</dd><dt className="text-slate-400">Password</dt><dd className="select-all break-all font-mono text-white">{runtimeAccess.password}</dd></dl><a href={runtimeAccess.url} target="_blank" rel="noreferrer" className="mt-3 inline-flex items-center gap-2 text-xs font-bold text-cyan-200"><ExternalLink className="h-4 w-4" />Open secured Kasm</a></div>}
        {!pods.length && !loading && <div className="mt-5 rounded-2xl border border-dashed border-white/15 p-6 text-center"><Box className="mx-auto h-7 w-7 text-slate-500" /><p className="mt-2 text-sm text-slate-400">No verified RunPod machine found.</p></div>}
      </aside>
    </section>

    <section className="grid gap-6 xl:grid-cols-[330px_minmax(0,1fr)]">
      <aside className="surface-card rounded-[28px] p-4"><div className="px-2 pb-3"><p className="eyebrow">Production history</p><h2 className="mt-1 text-xl font-black text-white">Render jobs</h2></div><div className="space-y-2">{jobs.map((job) => <button key={job.id} onClick={() => setSelectedId(job.id)} aria-pressed={selected?.id === job.id} className={`w-full rounded-2xl border p-4 text-left transition ${selected?.id === job.id ? 'border-cyan-300/50 bg-cyan-300/10 ring-2 ring-cyan-300/15' : 'border-white/8 bg-white/[0.025] hover:border-white/20'}`}><div className="flex items-center justify-between gap-2"><strong className="truncate text-sm text-white">{job.source_path.split('/').at(-1)}</strong><span className={`rounded-full border px-2 py-1 text-[9px] font-black ${statusTone(job.status)}`}>{human(job.status)}</span></div><p className="mt-2 text-xs text-slate-400">{job.completed_frame_count}/{job.expected_frame_count || '—'} frames · {job.output_profile}</p></button>)}{!jobs.length && <p className="p-5 text-sm text-slate-400">No production render has been created.</p>}</div></aside>

      <div className="surface-card rounded-[28px] p-6 lg:p-8">
        {!selected ? <div className="grid min-h-80 place-items-center text-center"><div><FolderOpen className="mx-auto h-10 w-10 text-slate-600" /><p className="mt-3 text-slate-400">Create or select a render to inspect it.</p></div></div> : <div className="space-y-7">
          <div className="flex flex-col justify-between gap-4 lg:flex-row lg:items-start">
            <div><div className="flex flex-wrap items-center gap-2"><span className={`rounded-full border px-3 py-1 text-xs font-black ${statusTone(selected.status)}`}>{human(selected.status)}</span><span className="rounded-full border border-white/10 px-3 py-1 text-xs font-bold text-slate-300">{selected.render_mode === 'kasm_gui' ? 'Kasm Blender' : 'Automated headless'}</span></div><h2 className="mt-3 break-all text-2xl font-black text-white">{selected.source_path}</h2><p className="mt-2 text-sm text-slate-400">Stage: {human(selected.stage)}</p></div>
            <div className="flex flex-wrap gap-2">{selectedPod?.proxy_url && <a href={selectedPod.proxy_url} target="_blank" rel="noreferrer" className="inline-flex h-10 items-center gap-2 rounded-xl border border-cyan-300/25 px-3 text-xs font-bold text-cyan-100"><ExternalLink className="h-4 w-4" />Open Kasm Blender</a>}{selected.status === 'awaiting_benchmark_approval' && <button onClick={() => void renderAction('approve_benchmark')} disabled={!!busy} className="inline-flex h-10 items-center gap-2 rounded-xl bg-emerald-300 px-3 text-xs font-black text-[#04140d]"><MonitorPlay className="h-4 w-4" />{selected.render_mode === 'kasm_gui' ? 'Approve & arm Kasm' : 'Approve safe render'}</button>}{ACTIVE.has(selected.status) && <button onClick={() => void renderAction('pause')} disabled={!!busy} className="inline-flex h-10 items-center gap-2 rounded-xl bg-amber-300 px-3 text-xs font-black text-[#181004]"><Pause className="h-4 w-4" />Pause</button>}{selected.status === 'paused' && <button onClick={() => void renderAction('resume')} disabled={!!busy} className="inline-flex h-10 items-center gap-2 rounded-xl bg-cyan-300 px-3 text-xs font-black text-[#04111b]"><Play className="h-4 w-4" />Resume</button>}{selected.status === 'needs_frame_retry' && <button onClick={() => void renderAction('retry_failed_frames')} disabled={!!busy} className="inline-flex h-10 items-center gap-2 rounded-xl bg-cyan-300 px-3 text-xs font-black text-[#04111b]"><RotateCcw className="h-4 w-4" />Retry missing frames</button>}{selected.stage === 'render.deliver' && selected.status !== 'completed' && <button onClick={() => void renderAction('retry_delivery')} disabled={!!busy} className="inline-flex h-10 items-center gap-2 rounded-xl bg-cyan-300 px-3 text-xs font-black text-[#04111b]"><CloudUpload className="h-4 w-4" />Retry delivery</button>}{!['completed', 'cancelled'].includes(selected.status) && <button onClick={() => void renderAction('cancel')} disabled={!!busy} className="inline-flex h-10 items-center gap-2 rounded-xl border border-rose-300/25 px-3 text-xs font-bold text-rose-100"><XCircle className="h-4 w-4" />Cancel</button>}</div>
          </div>

          {selected.error && <div role="alert" className="rounded-2xl border border-rose-300/25 bg-rose-300/8 p-4 text-sm text-rose-100"><strong>Blocked:</strong> {selected.error}</div>}
          {selected.status === 'awaiting_kasm_render' && <div className="rounded-2xl border border-amber-300/25 bg-amber-300/8 p-5"><p className="font-bold text-amber-100">Waiting for the artist in Kasm</p><ol className="mt-2 list-decimal space-y-1 pl-5 text-sm text-amber-50/85"><li>Open Kasm Blender using the button above.</li><li>Open this exact scene.</li><li>Choose Render → Render Animation. Council OS applies the approved GPU/image-sequence settings in memory.</li></ol></div>}

          <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4"><div className="rounded-2xl border border-white/10 bg-white/[0.03] p-4"><p className="text-xs uppercase tracking-wider text-slate-500">Scene</p><p className="mt-2 font-bold text-white">{number(scene.resolution_x) ? `${number(scene.resolution_x)}×${number(scene.resolution_y)}` : 'Awaiting preflight'}</p><p className="mt-1 text-xs text-slate-400">{number(scene.fps) ? `${number(scene.fps).toFixed(2)} fps` : 'Frame rate unavailable'}</p></div><div className="rounded-2xl border border-white/10 bg-white/[0.03] p-4"><p className="text-xs uppercase tracking-wider text-slate-500">Frame range</p><p className="mt-2 font-bold text-white">{selected.frame_start ?? '—'}–{selected.frame_end ?? '—'}</p><p className="mt-1 text-xs text-slate-400">{selected.expected_frame_count || 0} expected</p></div><div className="rounded-2xl border border-white/10 bg-white/[0.03] p-4"><p className="text-xs uppercase tracking-wider text-slate-500">Estimate</p><p className="mt-2 font-bold text-white">{estimatedHours ? `${estimatedHours.toFixed(1)} GPU hr` : 'Awaiting benchmark'}</p><p className="mt-1 text-xs text-slate-400">{estimatedCost ? `≈ $${estimatedCost.toFixed(2)} at current rate` : 'No cost promise before samples'}</p></div><div className="rounded-2xl border border-white/10 bg-white/[0.03] p-4"><p className="text-xs uppercase tracking-wider text-slate-500">Storage projection</p><p className="mt-2 font-bold text-white">{bytes(number(benchmark.projected_output_bytes_with_margin))}</p><p className="mt-1 text-xs text-slate-400">Local safe free: {bytes(number(storage.safety_free_bytes))}</p></div></div>

          <div><div className="mb-3 flex items-end justify-between"><div><p className="eyebrow">Durable image sequence</p><h3 className="mt-1 text-lg font-black text-white">Frame completion</h3></div><strong className="text-sm text-cyan-200">{progress.toFixed(1)}%</strong></div><div className="mb-3 h-2 overflow-hidden rounded-full bg-white/7"><div className="h-full rounded-full bg-gradient-to-r from-cyan-300 to-emerald-300 transition-[width] duration-700 motion-reduce:transition-none" style={{ width: `${Math.min(100, progress)}%` }} /></div><FrameMap frames={frames} /></div>

          <div className="grid gap-5 lg:grid-cols-2"><TelemetryChart samples={telemetry} /><div className="rounded-2xl border border-white/10 bg-white/[0.03] p-5"><p className="eyebrow">Preflight gates</p><div className="mt-4 space-y-3 text-sm"><div className="flex items-center justify-between gap-4"><span className="text-slate-300">Kasm OpenGL</span><strong className={runtime.opengl_hardware_accelerated ? 'text-emerald-200' : 'text-slate-500'}>{text(runtime.opengl_renderer) || 'Not proven'}</strong></div><div className="flex items-center justify-between"><span className="text-slate-300">Cycles backend</span><strong className={text(evidence.cycles_backend_selected) ? 'text-emerald-200' : 'text-slate-500'}>{text(evidence.cycles_backend_selected) || text(record(preflight.gpu).backend) || 'Not proven'}</strong></div><div className="flex items-center justify-between"><span className="text-slate-300">Blender GPU process</span><strong className={evidence.gpu_process_observed ? 'text-emerald-200' : 'text-slate-500'}>{evidence.gpu_process_observed ? 'Observed' : 'Awaiting benchmark'}</strong></div><div className="flex items-center justify-between"><span className="text-slate-300">50-frame soak</span><strong className={soak.passed ? 'text-emerald-200' : 'text-slate-500'}>{soak.passed ? 'Passed' : 'Not approved'}</strong></div><div className="flex items-center justify-between"><span className="text-slate-300">Drive write probe</span><strong className={drive.status === 'ready' ? 'text-emerald-200' : drive.status === 'blocked' ? 'text-rose-200' : 'text-slate-500'}>{human(text(drive.status) || 'awaiting preflight')}</strong></div><div className="flex items-center justify-between"><span className="text-slate-300">Missing assets</span><strong className={missingAssets.length ? 'text-rose-200' : preflight.status ? 'text-emerald-200' : 'text-slate-500'}>{missingAssets.length || (preflight.status ? 'None' : 'Not checked')}</strong></div></div></div></div>

          {missingAssets.length > 0 && <details className="rounded-2xl border border-rose-300/20 bg-rose-300/7 p-5"><summary className="cursor-pointer font-bold text-rose-100">{missingAssets.length} missing resources block production</summary><div className="mt-4 max-h-56 space-y-2 overflow-auto text-xs text-rose-50/80">{missingAssets.slice(0, 200).map((item, index) => { const value = record(item); return <p key={`${text(value.stored_path)}-${index}`} className="break-all rounded-lg bg-black/20 p-2">{text(value.kind)}: {text(value.stored_path)}</p>; })}</div></details>}

          <div><p className="eyebrow">Outputs</p><h3 className="mt-1 text-lg font-black text-white">Validated artifacts</h3><div className="mt-3 grid gap-3 md:grid-cols-2">{artifacts.map((artifact) => <div key={artifact.id} className="rounded-2xl border border-white/10 bg-white/[0.03] p-4"><div className="flex items-center gap-3"><FileImage className="h-5 w-5 text-cyan-300" /><div className="min-w-0"><p className="font-bold text-white">{human(artifact.kind)}</p><p className="truncate text-xs text-slate-400">{artifact.path}</p></div></div><p className="mt-2 text-xs text-slate-500">{bytes(artifact.size_bytes)} · {artifact.status}</p></div>)}{!artifacts.length && <p className="text-sm text-slate-400">Preview frames and deliverables appear only after validation.</p>}</div></div>
        </div>}
      </div>
    </section>
  </div>;
}
