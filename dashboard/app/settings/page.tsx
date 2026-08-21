'use client';

import { useCallback, useEffect, useMemo, useState } from 'react';
import { Check, ChevronRight, CircleHelp, ExternalLink, KeyRound, Link2, LockKeyhole, PlugZap, RefreshCw, Save, ShieldCheck, Sparkles, Trash2, X } from 'lucide-react';
import { fetchIntegrationCatalog, fetchWorkflowDetails, fetchWorkflows, removeIntegrationCredentials, saveIntegrationCredentials, updateCouncilIntegrations, updateWorkflowIntegrations, verifyConnection } from '../lib/api';
import { IntegrationConnection, WorkflowDefinition } from '../lib/types';
import { AppearanceControl } from '../components/appearance-control';
import { INTEGRATION_GUIDES } from './integration-guides';

type EditorPanel = 'guide' | 'credentials' | 'connections';

const ALLOWED: Record<string, string[]> = {
  openrouter: ['telegram_control', 'youtube_comments', 'reddit_prospector', 'youtube_descriptions', 'content_engine', 'instagram_comments'],
  telegram: ['telegram_control'], youtube: ['youtube_comments', 'youtube_descriptions'], reddit: ['reddit_prospector'],
  x: ['content_engine'], linkedin: ['content_engine'], meta: ['content_engine', 'instagram_comments'], discord: ['content_engine'], runpod: [], hubspot: ['reddit_prospector'],
};
const COUNCIL_ALLOWED: Record<string, string[]> = { hubspot: ['sales'] };
const REQUIRED: Record<string, string[]> = {
  telegram_control: ['telegram'], youtube_comments: ['youtube', 'openrouter'],
  reddit_prospector: ['reddit', 'openrouter'], youtube_descriptions: ['youtube', 'openrouter'],
  content_engine: ['openrouter'],
  instagram_comments: ['meta', 'openrouter'],
};

export default function SettingsPage() {
  const [integrations, setIntegrations] = useState<IntegrationConnection[]>([]);
  const [workflows, setWorkflows] = useState<WorkflowDefinition[]>([]);
  const [selected, setSelected] = useState<IntegrationConnection | null>(null);
  const [values, setValues] = useState<Record<string, string>>({});
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState('');
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [editorPanel, setEditorPanel] = useState<EditorPanel>('guide');
  const [showAdvanced, setShowAdvanced] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [catalog, definitions] = await Promise.all([fetchIntegrationCatalog(), fetchWorkflows()]);
      setIntegrations(catalog); setWorkflows(definitions); setError('');
      if (selected) setSelected(catalog.find((item) => item.id === selected.id) ?? null);
    } catch (loadError) {
      setError(loadError instanceof Error ? loadError.message : 'Unable to load the secure integration catalog.');
    } finally { setLoading(false); }
  }, [selected]);

  useEffect(() => {
    void Promise.all([fetchIntegrationCatalog(), fetchWorkflows()])
      .then(([catalog, definitions]) => { setIntegrations(catalog); setWorkflows(definitions); })
      .catch((loadError: unknown) => setError(loadError instanceof Error ? loadError.message : 'Unable to load integrations.'))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    if (!selected) return;
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setSelected(null);
    };
    document.addEventListener('keydown', closeOnEscape);
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    return () => {
      document.removeEventListener('keydown', closeOnEscape);
      document.body.style.overflow = previousOverflow;
    };
  }, [selected]);

  const verifiedCount = integrations.filter((item) => item.status === 'verified').length;
  const linkedCount = useMemo(() => new Set(integrations.flatMap((item) => [
    ...(item.linked_workflows ?? []).map((id) => `workflow:${id}`),
    ...(item.linked_councils ?? []).map((id) => `council:${id}`),
  ])).size, [integrations]);

  function openEditor(connection: IntegrationConnection) {
    setSelected(connection);
    setValues({});
    setError('');
    setNotice('');
    setShowAdvanced(false);
    setEditorPanel(connection.configured ? 'connections' : 'guide');
  }

  async function save() {
    if (!selected) return;
    setBusy(`save:${selected.id}`); setError(''); setNotice('');
    try {
      await saveIntegrationCredentials(selected.id, values, selected.display_name);
      setValues({}); setNotice('Credentials encrypted and stored. Verify the real provider connection next.'); await load(); setEditorPanel('connections');
    } catch (saveError) { setError(saveError instanceof Error ? saveError.message : 'Unable to store credentials.'); }
    finally { setBusy(''); }
  }

  async function verify(provider: string) {
    setBusy(`verify:${provider}`); setError(''); setNotice('');
    try { await verifyConnection(provider); setNotice('Connection verified with the provider.'); await load(); }
    catch (verifyError) { setError(verifyError instanceof Error ? verifyError.message : 'Verification failed.'); }
    finally { setBusy(''); }
  }

  async function remove(provider: string) {
    if (!window.confirm('Remove this encrypted connection? Linked workflows will be disabled.')) return;
    setBusy(`remove:${provider}`); setError('');
    try { await removeIntegrationCredentials(provider); setSelected(null); await load(); }
    catch (removeError) { setError(removeError instanceof Error ? removeError.message : 'Unable to remove credentials.'); }
    finally { setBusy(''); }
  }

  async function toggleLink(connection: IntegrationConnection, workflowId: string) {
    setBusy(`link:${connection.id}:${workflowId}`); setError(''); setNotice('');
    try {
      const details = await fetchWorkflowDetails(workflowId);
      const current = Array.isArray(details.integration_providers) ? details.integration_providers.filter((item): item is string => typeof item === 'string') : [];
      const linked = connection.linked_workflows.includes(workflowId);
      const desired = linked
        ? current.filter((item) => item !== connection.id)
        : [...new Set([...current, connection.id, ...(REQUIRED[workflowId] ?? [])])];
      await updateWorkflowIntegrations(workflowId, desired);
      setNotice(`${connection.display_name} ${linked ? 'unlinked from' : 'linked to'} ${details.display_name}.`); await load();
    } catch (linkError) { setError(linkError instanceof Error ? linkError.message : 'Unable to update the workflow link.'); }
    finally { setBusy(''); }
  }

  async function toggleCouncilLink(connection: IntegrationConnection, councilId: string) {
    setBusy(`council-link:${connection.id}:${councilId}`); setError(''); setNotice('');
    try {
      const linked = (connection.linked_councils ?? []).includes(councilId);
      const desired = linked ? [] : [connection.id];
      await updateCouncilIntegrations(councilId, desired);
      setNotice(`${connection.display_name} ${linked ? 'unlinked from' : 'linked to'} ${councilId === 'sales' ? 'Sales Council approvals' : councilId}.`);
      await load();
    } catch (linkError) { setError(linkError instanceof Error ? linkError.message : 'Unable to update the council link.'); }
    finally { setBusy(''); }
  }

  return (
    <div className="space-y-7 pb-16">
      <div className="flex flex-wrap items-end justify-between gap-4"><div><p className="eyebrow">Secure connection fabric</p><h1 className="mt-2 text-3xl font-black tracking-tight text-slate-50">Integrations</h1><p className="mt-2 max-w-2xl text-sm text-slate-400">Add a provider once, verify it, then link it to compatible automations. Secret values are write-only, encrypted on the server, and never returned to this browser.</p></div><button onClick={() => void load()} className="flex h-10 items-center gap-2 rounded-xl border border-white/10 bg-white/5 px-4 text-sm font-bold text-slate-300 hover:bg-white/8"><RefreshCw className={`h-4 w-4 ${loading ? 'animate-spin' : ''}`} />Refresh</button></div>

      <section className="grid gap-4 sm:grid-cols-3">
        {[['Providers configured', integrations.filter((item) => item.configured).length, KeyRound], ['Connections verified', verifiedCount, ShieldCheck], ['Automations linked', linkedCount, Link2]].map(([label, value, Icon]) => { const IconComponent = Icon as typeof KeyRound; return <div key={String(label)} className="surface-card rounded-2xl p-5"><IconComponent className="h-5 w-5 text-cyan-300" /><p className="mt-5 text-3xl font-black text-slate-50">{String(value)}</p><p className="mt-1 text-xs font-bold uppercase tracking-wide text-slate-500">{String(label)}</p></div>; })}
      </section>
      {error && <p role="alert" className="rounded-2xl border border-rose-300/20 bg-rose-400/8 p-4 text-sm text-rose-200">{error}</p>}
      {notice && <p className="rounded-2xl border border-emerald-300/20 bg-emerald-300/8 p-4 text-sm text-emerald-200">{notice}</p>}
      <AppearanceControl />

      <section className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
        {integrations.map((connection) => {
          const verified = connection.status === 'verified';
          const hasLinks = (connection.linked_workflows ?? []).length > 0 || (connection.linked_councils ?? []).length > 0;
          const guide = INTEGRATION_GUIDES[connection.id];
          return <article key={connection.id} className="surface-card group flex min-h-[300px] flex-col rounded-2xl p-5 transition duration-200 hover:-translate-y-0.5 hover:border-cyan-300/20"><div className="flex items-start justify-between gap-3"><span className={`grid h-11 w-11 place-items-center rounded-2xl border ${verified ? 'border-emerald-300/20 bg-emerald-300/8 text-emerald-300' : 'border-white/10 bg-white/5 text-slate-400'}`}><PlugZap className="h-5 w-5" /></span><span className={`rounded-full border px-2.5 py-1 text-[10px] font-black uppercase tracking-wide ${verified ? 'border-emerald-300/20 bg-emerald-300/8 text-emerald-300' : connection.configured ? 'border-amber-300/20 bg-amber-300/8 text-amber-300' : 'border-white/10 bg-white/5 text-slate-500'}`}>{connection.status.replaceAll('_',' ')}</span></div><h2 className="mt-5 font-bold text-slate-100">{connection.display_name}</h2><p className="mt-1 text-sm leading-5 text-slate-500">{connection.description}</p>{guide && <div className="mt-4 flex items-center gap-2 text-[11px] font-semibold text-slate-400"><Sparkles className="h-3.5 w-3.5 text-cyan-300" /><span>{guide.time}</span><span aria-hidden="true">·</span><span>{connection.fields.filter((field) => field.required).length} required {connection.fields.filter((field) => field.required).length === 1 ? 'value' : 'values'}</span></div>}<div className="mt-4 flex flex-wrap gap-1.5">{(connection.linked_workflows ?? []).map((id) => <span key={`workflow:${id}`} className="rounded-lg bg-cyan-300/8 px-2 py-1 text-[10px] font-bold text-cyan-300">{workflows.find((item) => item.id === id)?.display_name ?? id}</span>)}{(connection.linked_councils ?? []).map((id) => <span key={`council:${id}`} className="rounded-lg bg-violet-300/8 px-2 py-1 text-[10px] font-bold text-violet-200">{id === 'sales' ? 'Sales Council' : id}</span>)}{!hasLinks && <span className="text-xs text-slate-600">Not linked yet</span>}</div><button onClick={() => openEditor(connection)} className="mt-auto flex h-11 w-full items-center justify-between rounded-xl border border-white/10 bg-white/5 px-4 text-xs font-bold text-slate-200 transition hover:border-cyan-300/25 hover:bg-cyan-300/8"><span className="flex items-center gap-2">{connection.configured ? <LockKeyhole className="h-4 w-4" /> : <CircleHelp className="h-4 w-4 text-cyan-300" />}{connection.configured ? 'Manage connection' : 'Start guided setup'}</span><ChevronRight className="h-4 w-4" /></button></article>;
        })}
      </section>

      {selected && (() => {
        const guide = INTEGRATION_GUIDES[selected.id];
        const advanced = new Set(guide?.advancedFields ?? []);
        const visibleFields = selected.fields.filter((field) => showAdvanced || !advanced.has(field.key));
        const requiredComplete = selected.fields.filter((field) => field.required).every((field) => Boolean(values[field.key]?.trim()));
        const panelButton = (panel: EditorPanel, label: string, number: number) => <button type="button" onClick={() => setEditorPanel(panel)} aria-current={editorPanel === panel ? 'step' : undefined} className={`flex min-w-0 flex-1 items-center gap-2 rounded-xl px-3 py-2.5 text-left text-xs font-bold transition ${editorPanel === panel ? 'bg-cyan-300 text-[#031019]' : 'text-slate-400 hover:bg-white/5 hover:text-slate-100'}`}><span className={`grid h-5 w-5 shrink-0 place-items-center rounded-full text-[10px] ${editorPanel === panel ? 'bg-[#031019]/12' : 'bg-white/7'}`}>{number}</span><span className="truncate">{label}</span></button>;
        return <div role="dialog" aria-modal="true" aria-labelledby="integration-title" className="fixed inset-0 z-[80] flex items-center justify-center bg-[#02050b]/82 p-3 backdrop-blur-md sm:p-5" onMouseDown={(event) => { if (event.target === event.currentTarget) setSelected(null); }}><div className="liquid-glass flex max-h-[92vh] w-full max-w-5xl flex-col overflow-hidden rounded-[30px]"><header className="border-b border-white/8 px-5 py-5 sm:px-7"><div className="flex items-start justify-between gap-4"><div className="min-w-0"><p className="eyebrow">Guided secure connection</p><h2 id="integration-title" className="mt-2 truncate text-2xl font-black text-slate-50">{selected.display_name}</h2><p className="mt-1 text-sm text-slate-400">{guide?.summary ?? selected.description}</p></div><button aria-label="Close integration setup" onClick={() => setSelected(null)} className="shrink-0 rounded-xl p-2 text-slate-400 hover:bg-white/8 hover:text-white"><X className="h-5 w-5" /></button></div><nav aria-label="Integration setup steps" className="mt-5 flex gap-1 rounded-2xl border border-white/8 bg-[#06111d]/70 p-1">{panelButton('guide', 'Get access', 1)}{panelButton('credentials', selected.configured ? 'Replace credentials' : 'Enter credentials', 2)}{panelButton('connections', 'Verify & link', 3)}</nav></header>

          <div className="min-h-0 flex-1 overflow-y-auto px-5 py-6 sm:px-7">
            {error && <p role="alert" className="mb-5 rounded-2xl border border-rose-300/20 bg-rose-400/8 p-4 text-sm text-rose-200">{error}</p>}
            {notice && <p role="status" className="mb-5 rounded-2xl border border-emerald-300/20 bg-emerald-300/8 p-4 text-sm text-emerald-200">{notice}</p>}
            {editorPanel === 'guide' && <div className="grid gap-6 lg:grid-cols-[0.8fr_1.4fr]"><aside className="space-y-4"><section className="rounded-2xl border border-cyan-300/15 bg-cyan-300/[0.055] p-4"><p className="text-[11px] font-black uppercase tracking-[0.18em] text-cyan-300">Before you start</p><p className="mt-2 text-xs font-semibold text-slate-300">{guide?.time}</p><ul className="mt-3 space-y-2">{(guide?.prerequisites ?? ['An account with this provider']).map((item) => <li key={item} className="flex gap-2 text-sm text-slate-300"><Check className="mt-0.5 h-4 w-4 shrink-0 text-emerald-300" />{item}</li>)}</ul></section>{guide?.warning && <section className="rounded-2xl border border-amber-300/15 bg-amber-300/[0.055] p-4"><p className="text-[11px] font-black uppercase tracking-[0.18em] text-amber-300">Important</p><p className="mt-2 text-sm leading-6 text-slate-300">{guide.warning}</p></section>}</aside><section><h3 className="text-base font-black text-slate-100">Follow these steps</h3><div className="mt-4 space-y-3">{(guide?.steps ?? []).map((step, index) => <article key={`${index}-${step.title}`} className="rounded-2xl border border-white/8 bg-white/[0.025] p-4"><div className="flex gap-3"><span className="grid h-7 w-7 shrink-0 place-items-center rounded-full border border-cyan-300/25 bg-cyan-300/8 text-xs font-black text-cyan-300">{index + 1}</span><div><h4 className="text-sm font-bold text-slate-100">{step.title}</h4><p className="mt-1 text-sm leading-6 text-slate-400">{step.detail}</p>{step.url && <a href={step.url} target="_blank" rel="noreferrer" className="mt-3 inline-flex items-center gap-1.5 text-xs font-bold text-cyan-300 hover:text-cyan-200">{step.linkLabel ?? 'Open official setup page'}<ExternalLink className="h-3.5 w-3.5" /></a>}</div></div></article>)}</div><button type="button" onClick={() => setEditorPanel('credentials')} className="mt-5 flex h-11 w-full items-center justify-center gap-2 rounded-xl bg-cyan-300 px-4 text-sm font-black text-[#031019]">I have the required access<ChevronRight className="h-4 w-4" /></button></section></div>}

            {editorPanel === 'credentials' && <div><div className="flex flex-wrap items-start justify-between gap-3"><div><h3 className="text-base font-black text-slate-100">Enter the values securely</h3><p className="mt-1 max-w-2xl text-sm leading-6 text-slate-400">Secrets are encrypted on the server and are never returned to this browser. {selected.configured && 'To replace this connection, enter the complete required set again.'}</p></div>{advanced.size > 0 && <button type="button" onClick={() => setShowAdvanced((value) => !value)} className="rounded-xl border border-white/10 px-3 py-2 text-xs font-bold text-slate-300 hover:bg-white/5">{showAdvanced ? 'Hide advanced settings' : `Show ${advanced.size} advanced ${advanced.size === 1 ? 'field' : 'fields'}`}</button>}</div><div className="mt-6 grid gap-4 lg:grid-cols-2">{visibleFields.map((field) => { const fieldGuide = guide?.fields[field.key]; return <div key={field.key} className="rounded-2xl border border-white/8 bg-white/[0.025] p-4"><label className="block text-xs font-bold uppercase tracking-wide text-slate-300">{field.label}<span className={`ml-2 rounded-md px-1.5 py-0.5 text-[9px] ${field.required ? 'bg-cyan-300/10 text-cyan-300' : 'bg-white/5 text-slate-500'}`}>{field.required ? 'Required' : 'Optional'}</span><input type={field.secret ? 'password' : 'text'} autoComplete="off" value={values[field.key] ?? ''} onChange={(event) => setValues((current) => ({ ...current, [field.key]: event.target.value }))} placeholder={selected.configured_fields.includes(field.key) ? 'Stored securely — enter replacement' : fieldGuide?.example ?? 'Paste value'} className="mt-3 h-12 w-full input-shell rounded-xl px-3 text-sm font-normal normal-case tracking-normal text-slate-100 placeholder:text-slate-600 focus:border-cyan-300/50 focus:outline-none focus:ring-2 focus:ring-cyan-300/20" /></label>{fieldGuide && <details className="mt-3 rounded-xl border border-white/7 bg-[#06111d]/55 px-3 py-2 text-xs text-slate-400"><summary className="cursor-pointer font-bold text-cyan-200 marker:text-cyan-300">Where do I get this?</summary><p className="mt-2 leading-5">{fieldGuide.where}</p>{fieldGuide.note && <p className="mt-2 leading-5 text-amber-100/75">{fieldGuide.note}</p>}</details>}{field.help_text && !fieldGuide && <p className="mt-2 text-xs leading-5 text-slate-500">{field.help_text}</p>}</div>; })}</div><div className="mt-6 flex flex-wrap items-center gap-3"><button disabled={busy !== '' || !requiredComplete} onClick={() => void save()} className="flex h-11 items-center gap-2 rounded-xl bg-cyan-300 px-5 text-sm font-black text-[#031019] disabled:cursor-not-allowed disabled:opacity-35"><Save className="h-4 w-4" />Encrypt & save</button>{!requiredComplete && <p className="text-xs text-slate-500">Complete every Required field to save.</p>}{selected.configured && <button disabled={busy !== ''} onClick={() => void remove(selected.id)} className="ml-auto flex h-10 items-center gap-2 rounded-xl border border-rose-300/20 px-4 text-xs font-bold text-rose-300 disabled:opacity-50"><Trash2 className="h-4 w-4" />Remove connection</button>}</div></div>}

            {editorPanel === 'connections' && <div className="grid gap-6 lg:grid-cols-[0.8fr_1.2fr]"><section className="rounded-2xl border border-white/8 bg-white/[0.025] p-5"><div className="flex items-start justify-between gap-3"><div><p className="text-[11px] font-black uppercase tracking-[0.18em] text-cyan-300">Connection status</p><h3 className="mt-2 text-xl font-black capitalize text-slate-100">{selected.status.replaceAll('_', ' ')}</h3></div><ShieldCheck className={`h-7 w-7 ${selected.status === 'verified' ? 'text-emerald-300' : 'text-slate-500'}`} /></div>{selected.last_error && <p role="alert" className="mt-4 rounded-xl border border-rose-300/15 bg-rose-300/7 p-3 text-sm leading-5 text-rose-200">{selected.last_error}</p>}<p className="mt-4 text-sm leading-6 text-slate-400">Verification makes a small real request to {selected.display_name}. It does not publish content or start paid GPU resources.</p><button disabled={!selected.configured || busy !== ''} onClick={() => void verify(selected.id)} className="mt-5 flex h-11 w-full items-center justify-center gap-2 rounded-xl border border-emerald-300/25 bg-emerald-300/10 px-4 text-sm font-black text-emerald-300 disabled:opacity-35"><Check className="h-4 w-4" />{busy === `verify:${selected.id}` ? 'Checking…' : selected.status === 'verified' ? 'Verify again' : 'Verify connection'}</button>{!selected.configured && <button type="button" onClick={() => setEditorPanel('credentials')} className="mt-3 h-10 w-full rounded-xl border border-white/10 text-xs font-bold text-slate-300">Enter credentials first</button>}</section><section><h3 className="text-base font-black text-slate-100">Choose where it is used</h3><p className="mt-1 text-sm leading-6 text-slate-400">A verified connection can be reused without copying its secret again. Toggle only the destinations you want active.</p>{(ALLOWED[selected.id] ?? []).length === 0 && (COUNCIL_ALLOWED[selected.id] ?? []).length === 0 && <div className="mt-4 rounded-2xl border border-white/8 bg-white/[0.025] p-4 text-sm text-slate-400">This connection is controlled from its dedicated workspace. {selected.id === 'runpod' ? 'Open Blender Manager after verification.' : ''}</div>}<div className="mt-4 space-y-2">{(ALLOWED[selected.id] ?? []).map((workflowId) => { const definition = workflows.find((item) => item.id === workflowId); const linked = selected.linked_workflows.includes(workflowId); return <button key={workflowId} disabled={selected.status !== 'verified' || busy !== ''} onClick={() => void toggleLink(selected, workflowId)} className="flex w-full items-center gap-3 rounded-xl border border-white/8 bg-white/[0.025] px-4 py-3 text-left transition hover:bg-white/5 disabled:opacity-35"><span className={`grid h-5 w-5 place-items-center rounded-md border ${linked ? 'border-cyan-300 bg-cyan-300 text-[#04111b]' : 'border-white/15'}`}>{linked && <Check className="h-3.5 w-3.5" />}</span><span className="flex-1 text-sm font-semibold text-slate-200">{definition?.display_name ?? workflowId}</span><span className="text-[10px] font-bold uppercase tracking-wide text-slate-400">{linked ? 'linked' : selected.status === 'verified' ? 'available' : 'verify first'}</span></button>; })}{(COUNCIL_ALLOWED[selected.id] ?? []).map((councilId) => { const linked = (selected.linked_councils ?? []).includes(councilId); return <button key={councilId} disabled={selected.status !== 'verified' || busy !== ''} onClick={() => void toggleCouncilLink(selected, councilId)} className="flex w-full items-center gap-3 rounded-xl border border-white/8 bg-white/[0.025] px-4 py-3 text-left transition hover:bg-white/5 disabled:opacity-35"><span className={`grid h-5 w-5 place-items-center rounded-md border ${linked ? 'border-violet-300 bg-violet-300 text-[#04111b]' : 'border-white/15'}`}>{linked && <Check className="h-3.5 w-3.5" />}</span><span className="flex-1 text-sm font-semibold text-slate-200">{councilId === 'sales' ? 'Sales Council approved leads' : councilId}</span><span className="text-[10px] font-bold uppercase tracking-wide text-slate-400">{linked ? 'linked' : selected.status === 'verified' ? 'available' : 'verify first'}</span></button>; })}</div></section></div>}
          </div>
        </div></div>;
      })()}
    </div>
  );
}
