'use client';

import Link from 'next/link';
import { useParams } from 'next/navigation';
import { useCallback, useEffect, useMemo, useState } from 'react';
import { ArrowLeft, Check, Clock3, Play, RefreshCw, Save } from 'lucide-react';
import { fetchKnowledgeBinding, fetchKnowledgeCollections, fetchWorkflowDetails, triggerWorkflow, updateKnowledgeBinding, updateWorkflow } from '../../lib/api';
import { JsonObject, KnowledgeCollection, SchedulePreset, WorkflowDefinition, WorkflowDetails } from '../../lib/types';

interface ScheduleChoice {
  id: SchedulePreset;
  label: string;
  description: string;
  recommended?: boolean;
}

const SCHEDULE_OPTIONS: Partial<Record<string, ScheduleChoice[]>> = {
  instagram_comments: [
    { id: 'every_5_minutes', label: 'Quick replies', description: 'Check for new comments every 5 minutes', recommended: true },
    { id: 'every_15_minutes', label: 'Balanced', description: 'Check every 15 minutes' },
    { id: 'every_30_minutes', label: 'Light', description: 'Check every 30 minutes' },
    { id: 'hourly', label: 'Hourly', description: 'Check once an hour' },
    { id: 'manual', label: 'Manual only', description: 'Run only when you press Queue run' },
  ],
  youtube_comments: [
    { id: 'every_15_minutes', label: 'Active', description: 'Check for comments every 15 minutes', recommended: true },
    { id: 'every_30_minutes', label: 'Balanced', description: 'Check every 30 minutes' },
    { id: 'hourly', label: 'Hourly', description: 'Check once an hour' },
    { id: 'every_6_hours', label: 'Occasional', description: 'Check every 6 hours' },
    { id: 'manual', label: 'Manual only', description: 'Run only when you press Queue run' },
  ],
  reddit_prospector: [
    { id: 'hourly', label: 'Hourly', description: 'Scan for new leads once an hour', recommended: true },
    { id: 'every_3_hours', label: 'Every 3 hours', description: 'A balanced lead scan' },
    { id: 'every_6_hours', label: 'Every 6 hours', description: 'A lighter lead scan' },
    { id: 'every_12_hours', label: 'Twice daily', description: 'Scan every 12 hours' },
    { id: 'daily', label: 'Daily', description: 'Scan once each day' },
    { id: 'manual', label: 'Manual only', description: 'Run only when you press Queue run' },
  ],
};

function selectedSchedule(workflowId: string, schedule: JsonObject): SchedulePreset {
  const options = SCHEDULE_OPTIONS[workflowId] ?? [];
  const storedPreset = schedule.preset;
  if (typeof storedPreset === 'string') {
    const match = options.find((option) => option.id === storedPreset);
    if (match) return match.id;
  }
  if (schedule.type === 'interval' && typeof schedule.seconds === 'number') {
    const bySeconds: Partial<Record<number, SchedulePreset>> = {
      300: 'every_5_minutes', 900: 'every_15_minutes', 1800: 'every_30_minutes',
      3600: 'hourly', 10800: 'every_3_hours', 21600: 'every_6_hours',
      43200: 'every_12_hours', 86400: 'daily',
    };
    const match = bySeconds[schedule.seconds];
    if (match && options.some((option) => option.id === match)) return match;
  }
  return options.find((option) => option.recommended)?.id ?? options[0]?.id ?? 'manual';
}

function fixedScheduleCopy(workflow: WorkflowDetails): { title: string; description: string } {
  if (workflow.id === 'telegram_control') {
    return {
      title: 'Always listening while enabled',
      description: 'Telegram responds continuously after its connection is verified. No schedule is needed.',
    };
  }
  return {
    title: 'Runs when you start it',
    description: 'This automation needs your content first, so it starts only when you press Queue run.',
  };
}

function unwrapWorkflow(result: { resource: WorkflowDefinition } | WorkflowDefinition): WorkflowDefinition {
  return 'resource' in result ? result.resource : result;
}

export default function WorkflowDetailPage() {
  const params = useParams<{ id: string }>();
  const workflowId = params.id;
  const [workflow, setWorkflow] = useState<WorkflowDetails | null>(null);
  const [collections, setCollections] = useState<KnowledgeCollection[]>([]);
  const [collectionIds, setCollectionIds] = useState<string[]>([]);
  const [bindingVersion, setBindingVersion] = useState(1);
  const [schedulePreset, setSchedulePreset] = useState<SchedulePreset>('manual');
  const [customPrompt, setCustomPrompt] = useState('');
  const [videoTitle, setVideoTitle] = useState('');
  const [videoId, setVideoId] = useState('');
  const [transcript, setTranscript] = useState('');
  const [mediaUrl, setMediaUrl] = useState('');
  const [boilerplate, setBoilerplate] = useState('');
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');

  const load = useCallback(async () => {
    try {
      const [details, knowledgeCollections, binding] = await Promise.all([
        fetchWorkflowDetails(workflowId), fetchKnowledgeCollections(), fetchKnowledgeBinding('workflow', workflowId),
      ]);
      setWorkflow(details);
      setCollections(knowledgeCollections);
      setCollectionIds(binding.collection_ids); setBindingVersion(binding.version);
      setSchedulePreset(selectedSchedule(details.id, details.schedule));
      const prompt = details.settings.custom_prompt;
      setCustomPrompt(typeof prompt === 'string' ? prompt : '');
      setError('');
    } catch (loadError) {
      setError(loadError instanceof Error ? loadError.message : 'Unable to load workflow.');
    } finally {
      setLoading(false);
    }
  }, [workflowId]);

  useEffect(() => {
    let active = true;
    void Promise.all([fetchWorkflowDetails(workflowId), fetchKnowledgeCollections(), fetchKnowledgeBinding('workflow', workflowId)])
      .then(([details, knowledgeCollections, binding]) => {
        if (!active) return;
        setWorkflow(details);
        setCollections(knowledgeCollections);
        setCollectionIds(binding.collection_ids); setBindingVersion(binding.version);
        setSchedulePreset(selectedSchedule(details.id, details.schedule));
        const prompt = details.settings.custom_prompt;
        setCustomPrompt(typeof prompt === 'string' ? prompt : '');
        setError('');
      })
      .catch((loadError: unknown) => { if (active) setError(loadError instanceof Error ? loadError.message : 'Unable to load workflow.'); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [workflowId]);

  useEffect(() => {
    if (workflowId !== 'content_engine') return;
    const raw = window.sessionStorage.getItem('council-os:content-engine-draft');
    if (!raw) return;
    try {
      const draft = JSON.parse(raw) as { title?: string; transcript?: string; sourceId?: string };
      window.sessionStorage.removeItem('council-os:content-engine-draft');
      const timer = window.setTimeout(() => {
        setVideoTitle(draft.title ?? '');
        setTranscript(draft.transcript ?? '');
        setVideoId(draft.sourceId ?? '');
        setNotice('Your draft request was moved here. Review the source, then queue the six-destination automation.');
      }, 0);
      return () => window.clearTimeout(timer);
    } catch {
      window.sessionStorage.removeItem('council-os:content-engine-draft');
    }
  }, [workflowId]);

  const verified = useMemo(() => workflow?.credential_status === 'connected' || workflow?.credential_status === 'verified', [workflow]);
  const scheduleEditable = workflow?.id === 'youtube_comments' || workflow?.id === 'reddit_prospector' || workflow?.id === 'instagram_comments';

  async function save() {
    if (!workflow) return;
    setBusy(true);
    setError('');
    setNotice('');
    try {
      const result = unwrapWorkflow(await updateWorkflow(workflow.id, {
        custom_prompt: customPrompt,
        ...(scheduleEditable ? { schedule_preset: schedulePreset } : {}),
      }));
      await updateKnowledgeBinding('workflows', workflow.id, collectionIds, bindingVersion);
      setBindingVersion((current) => current + 1);
      setWorkflow((current) => current ? { ...current, ...result } : null);
      setSchedulePreset(selectedSchedule(result.id, result.schedule));
      const choice = SCHEDULE_OPTIONS[workflow.id]?.find((option) => option.id === schedulePreset);
      setNotice(choice ? `Changes saved. ${choice.description}.` : 'Changes saved.');
    } catch (saveError) {
      setError(saveError instanceof Error ? saveError.message : 'Unable to save workflow settings.');
    } finally {
      setBusy(false);
    }
  }

  async function run() {
    if (!workflow) return;
    setBusy(true);
    setError('');
    setNotice('');
    const payload: JsonObject = workflow.id === 'content_engine'
      ? { video_title: videoTitle, transcript, video_id: videoId, metadata: { media_url: mediaUrl } }
      : workflow.id === 'youtube_descriptions'
        ? { boilerplate }
        : {};
    try {
      await triggerWorkflow(workflow.id, payload);
      setNotice('A durable workflow run was queued.');
      await load();
    } catch (runError) {
      setError(runError instanceof Error ? runError.message : 'Unable to queue workflow.');
    } finally {
      setBusy(false);
    }
  }

  if (loading && !workflow) return <div className="flex min-h-96 items-center justify-center text-sm text-slate-500"><RefreshCw className="mr-2 h-5 w-5 animate-spin" /> Loading workflow…</div>;
  if (!workflow) return <div className="rounded-xl border border-rose-300/20 bg-rose-400/8 p-6 text-sm text-rose-200">{error || 'Workflow not found.'}</div>;

  const canRun = Boolean(verified && workflow.is_enabled && !workflow.is_paused && workflow.id !== 'telegram_control' && (workflow.id !== 'content_engine' || (videoTitle.trim() && videoId.trim() && transcript.trim().length >= 20)));
  const scheduleOptions = SCHEDULE_OPTIONS[workflow.id] ?? [];
  const activeSchedule = scheduleOptions.find((option) => option.id === schedulePreset);
  const fixedSchedule = fixedScheduleCopy(workflow);
  const needsSimpleSchedule = workflow.schedule.type === 'needs_update';

  return (
    <div className="mx-auto max-w-5xl space-y-7 pb-16">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <Link href="/workflows" className="flex items-center gap-2 text-sm font-semibold text-slate-400"><ArrowLeft className="h-4 w-4" /> Back to workflows</Link>
        <button onClick={() => void load()} className="flex items-center gap-2 rounded-lg border border-white/10 bg-white/5 px-3 py-2 text-sm font-semibold text-slate-300"><RefreshCw className="h-4 w-4" /> Refresh</button>
      </div>

      <section className="surface-card rounded-2xl p-6">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div><p className="eyebrow">Automation setup</p><h1 className="mt-2 text-2xl font-bold text-slate-50">{workflow.display_name}</h1><p className="mt-2 text-sm text-slate-400">Choose when it runs and add any guidance you want it to follow.</p></div>
          <span className="rounded-full bg-emerald-300/8 px-3 py-1.5 text-xs font-bold capitalize text-emerald-300">{verified ? 'Connection ready' : 'Connection needs setup'}</span>
        </div>
        <div className="mt-6 space-y-6">
          {scheduleEditable ? (
            <fieldset>
              <legend className="flex items-center gap-2 text-sm font-bold text-slate-200"><Clock3 className="h-4 w-4 text-cyan-300" /> How often should this run?</legend>
              <p className="mt-1 text-xs leading-5 text-slate-400">Pick the pace that fits you. The system handles the timing automatically.</p>
              {needsSimpleSchedule && <p className="mt-3 rounded-lg border border-amber-300/20 bg-amber-300/8 px-3 py-2 text-xs text-amber-100">A previous advanced schedule was found. Choose an option below and save to replace it.</p>}
              <div className="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
                {scheduleOptions.map((option) => {
                  const selected = option.id === schedulePreset;
                  return (
                    <button
                      key={option.id}
                      type="button"
                      aria-pressed={selected}
                      data-selected={selected}
                      onClick={() => setSchedulePreset(option.id)}
                      className="choice-card min-h-24 rounded-xl border border-white/10 bg-white/[0.025] p-4 text-left transition hover:border-cyan-300/30 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyan-300"
                    >
                      <span className="flex items-center justify-between gap-3">
                        <span className="font-bold text-slate-100">{option.label}</span>
                        {selected ? <span className="flex h-6 w-6 items-center justify-center rounded-full bg-cyan-300 text-[#04111b]"><Check className="h-4 w-4" /></span> : option.recommended ? <span className="rounded-full bg-emerald-300/10 px-2 py-1 text-[10px] font-bold uppercase tracking-wide text-emerald-200">Recommended</span> : null}
                      </span>
                      <span className="mt-2 block text-xs leading-5 text-slate-400">{option.description}</span>
                    </button>
                  );
                })}
              </div>
              {activeSchedule && <p aria-live="polite" className="mt-3 text-xs font-semibold text-cyan-200">Selected: {activeSchedule.label} — {activeSchedule.description.toLowerCase()}.</p>}
            </fieldset>
          ) : (
            <div className="rounded-xl border border-white/8 bg-white/[0.025] p-4"><p className="flex items-center gap-2 text-sm font-semibold text-slate-200"><Clock3 className="h-4 w-4 text-cyan-300" /> {fixedSchedule.title}</p><p className="mt-2 text-xs leading-5 text-slate-400">{fixedSchedule.description}</p></div>
          )}
          <label className="text-sm font-semibold text-slate-300">Custom instructions
            <span className="mt-1 block text-xs font-normal text-slate-500">Optional guidance this automation should follow each time it runs.</span>
            <textarea value={customPrompt} onChange={(event) => setCustomPrompt(event.target.value)} maxLength={20_000} className="mt-2 min-h-24 w-full input-shell rounded-xl p-3 text-sm font-normal text-slate-100 outline-none focus:border-cyan-300/40" />
          </label>
          <fieldset>
            <legend className="text-sm font-semibold text-slate-300">Knowledge collections</legend>
            <p className="mt-1 text-xs leading-5 text-slate-500">Only checked collections can ground this automation. Source IDs cannot be injected from a manual trigger.</p>
            {collections.length === 0 ? <p className="mt-3 rounded-xl border border-white/8 bg-white/[.025] p-4 text-xs text-slate-500">Create a collection in Knowledge before binding evidence here.</p> : <div className="mt-3 grid gap-2 sm:grid-cols-2">{collections.map((collection) => { const selected = collectionIds.includes(collection.id); return <button type="button" key={collection.id} aria-pressed={selected} onClick={() => setCollectionIds((current) => selected ? current.filter((id) => id !== collection.id) : [...current, collection.id])} className={`choice-card flex items-center gap-3 rounded-xl border p-3 text-left ${selected ? 'border-cyan-300/35 bg-cyan-300/10' : 'border-white/10 bg-white/[.025]'}`}><span className={`grid h-6 w-6 shrink-0 place-items-center rounded-lg border ${selected ? 'border-cyan-300 bg-cyan-300 text-[#04111b]' : 'border-white/15 text-transparent'}`}><Check className="h-3.5 w-3.5" /></span><span><span className="block text-sm font-bold text-slate-200">{collection.name}</span><span className="text-xs text-slate-500">{collection.document_count} sources</span></span></button>; })}</div>}
          </fieldset>
        </div>
        <button disabled={busy} onClick={() => void save()} className="mt-5 flex h-10 items-center gap-2 rounded-xl bg-cyan-300 px-4 text-sm font-black text-[#04111b] disabled:opacity-50"><Save className="h-4 w-4" /> Save changes</button>
      </section>

      {workflow.id === 'content_engine' && (
        <section className="surface-card rounded-2xl p-6">
          <h2 className="font-bold text-slate-100">Content source</h2>
          <p className="mt-1 text-sm text-slate-500">Each platform variant receives its own generator/critic validation and approval record.</p>
          <div className="mt-4 grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-6">
            {['LinkedIn', 'X', 'Instagram', 'Facebook', 'Reddit', 'Discord'].map((platform) => <div key={platform} className="rounded-xl border border-white/10 bg-white/[0.025] px-3 py-3 text-center text-xs font-bold text-slate-300"><span className="mb-1 block text-cyan-300">1 approval</span>{platform}</div>)}
          </div>
          <input value={videoTitle} onChange={(event) => setVideoTitle(event.target.value)} placeholder="Video or source title" className="mt-4 h-11 w-full input-shell rounded-xl px-3 text-sm text-slate-100" />
          <input required value={videoId} onChange={(event) => setVideoId(event.target.value)} placeholder="Stable source ID or YouTube video ID" className="mt-3 h-11 w-full input-shell rounded-xl px-3 text-sm text-slate-100" />
          <input type="url" value={mediaUrl} onChange={(event) => setMediaUrl(event.target.value)} placeholder="Public image/video URL (required before Instagram approval)" className="mt-3 h-11 w-full input-shell rounded-xl px-3 text-sm text-slate-100" />
          <textarea value={transcript} onChange={(event) => setTranscript(event.target.value)} placeholder="Transcript (minimum 20 characters)" className="mt-3 min-h-64 w-full input-shell rounded-xl p-3 text-sm leading-6 text-slate-100" />
        </section>
      )}

      {workflow.id === 'youtube_descriptions' && (
        <section className="surface-card rounded-2xl p-6">
          <label className="text-sm font-bold text-slate-200">Description boilerplate
            <textarea value={boilerplate} onChange={(event) => setBoilerplate(event.target.value)} className="mt-2 min-h-32 w-full input-shell rounded-xl p-3 text-sm font-normal text-slate-100" />
          </label>
        </section>
      )}

      {workflow.id === 'telegram_control' && (
        <section className="surface-card rounded-2xl p-6">
          <h2 className="text-lg font-bold text-white">Telegram administrator controls</h2>
          <p className="mt-2 text-sm leading-6 text-slate-300">When the verified workflow is enabled, the worker listens only to the configured private administrator chat and sends approval cards and workflow alerts.</p>
          <div className="mt-5 grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {[
              ['/task', 'Submit work to Grant, Sales, or Content Council'],
              ['/status', 'Read backend and kill-switch state'],
              ['/kill', 'Stop workflow execution immediately'],
              ['/resume', 'Release the global stop'],
              ['/help', 'Show the available commands'],
              ['/cancel', 'Cancel an unfinished task entry'],
            ].map(([command, description]) => <div key={command} className="rounded-xl border border-white/8 bg-white/[0.025] p-4"><code className="font-bold text-cyan-200">{command}</code><p className="mt-2 text-xs leading-5 text-slate-300">{description}</p></div>)}
          </div>
          <p className="mt-4 text-xs text-slate-400">Approve, Reject, and Retry buttons use the same versioned backend actions as this dashboard, preventing duplicate decisions.</p>
        </section>
      )}

      {workflow.id === 'instagram_comments' && (
        <section className="surface-card rounded-2xl p-6">
          <h2 className="text-lg font-bold text-white">Approval-first Instagram replies</h2>
          <p className="mt-2 text-sm leading-6 text-slate-300">The scan checks recent professional-account comments, ignores already staged items, drafts a contextual reply, and places it in Queue & Approvals. Approval is required before Meta receives a reply.</p>
        </section>
      )}

      {error && <p role="alert" className="rounded-xl border border-rose-300/20 bg-rose-400/8 p-4 text-sm text-rose-200">{error}</p>}
      {notice && <p className="rounded-xl border border-emerald-300/20 bg-emerald-300/8 p-4 text-sm text-emerald-200">{notice}</p>}

      {workflow.id !== 'telegram_control' && <div className="flex justify-end">
        <button disabled={busy || !canRun} onClick={() => void run()} className="flex h-11 items-center gap-2 rounded-xl bg-cyan-300 px-6 text-sm font-black text-[#04111b] disabled:cursor-not-allowed disabled:opacity-40"><Play className="h-4 w-4" /> {busy ? 'Working…' : 'Queue run'}</button>
      </div>}

      <section className="surface-card rounded-2xl">
        <div className="border-b border-white/8 p-5"><h2 className="font-bold text-slate-100">Persisted run history</h2></div>
        {workflow.runs.length === 0 ? <p className="p-8 text-center text-sm text-slate-500">No workflow runs have been recorded.</p> : (
          <div className="divide-y divide-white/8">{workflow.runs.map((runItem) => (
            <div key={runItem.id} className="grid gap-2 p-5 text-sm md:grid-cols-[1fr_auto_auto] md:items-center">
              <div><p className="font-mono text-xs text-slate-600">{runItem.id}</p><p className="mt-1 text-slate-400">{new Date(runItem.created_at).toLocaleString()}</p></div>
              <span className="font-semibold capitalize text-slate-300">{runItem.status.replaceAll('_', ' ')}</span>
              <span className="text-xs text-slate-500">Attempt {runItem.attempts}/{runItem.max_attempts}</span>
              {runItem.error && <p className="text-xs text-rose-300 md:col-span-3">{runItem.error}</p>}
            </div>
          ))}</div>
        )}
      </section>
    </div>
  );
}
