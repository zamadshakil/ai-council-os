'use client';

import { useCallback, useEffect, useMemo, useState } from 'react';
import { Check, KeyRound, Link2, LockKeyhole, PlugZap, RefreshCw, Save, ShieldCheck, Trash2, X } from 'lucide-react';
import { fetchIntegrationCatalog, fetchWorkflowDetails, fetchWorkflows, removeIntegrationCredentials, saveIntegrationCredentials, updateCouncilIntegrations, updateWorkflowIntegrations, verifyConnection } from '../lib/api';
import { IntegrationConnection, WorkflowDefinition } from '../lib/types';
import { AppearanceControl } from '../components/appearance-control';

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

  const verifiedCount = integrations.filter((item) => item.status === 'verified').length;
  const linkedCount = useMemo(() => new Set(integrations.flatMap((item) => [
    ...item.linked_workflows.map((id) => `workflow:${id}`),
    ...item.linked_councils.map((id) => `council:${id}`),
  ])).size, [integrations]);

  function openEditor(connection: IntegrationConnection) { setSelected(connection); setValues({}); setError(''); setNotice(''); }

  async function save() {
    if (!selected) return;
    setBusy(`save:${selected.id}`); setError(''); setNotice('');
    try {
      await saveIntegrationCredentials(selected.id, values, selected.display_name);
      setValues({}); setNotice('Credentials encrypted and stored. Verify before linking or enabling workflows.'); await load();
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
      const linked = connection.linked_councils.includes(councilId);
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
          const hasLinks = connection.linked_workflows.length > 0 || connection.linked_councils.length > 0;
          return <article key={connection.id} className="surface-card group rounded-2xl p-5"><div className="flex items-start justify-between gap-3"><span className={`grid h-11 w-11 place-items-center rounded-2xl border ${verified ? 'border-emerald-300/20 bg-emerald-300/8 text-emerald-300' : 'border-white/10 bg-white/5 text-slate-400'}`}><PlugZap className="h-5 w-5" /></span><span className={`rounded-full border px-2.5 py-1 text-[10px] font-black uppercase tracking-wide ${verified ? 'border-emerald-300/20 bg-emerald-300/8 text-emerald-300' : connection.configured ? 'border-amber-300/20 bg-amber-300/8 text-amber-300' : 'border-white/10 bg-white/5 text-slate-500'}`}>{connection.status.replaceAll('_',' ')}</span></div><h2 className="mt-5 font-bold text-slate-100">{connection.display_name}</h2><p className="mt-1 min-h-10 text-sm leading-5 text-slate-500">{connection.description}</p><div className="mt-4 flex flex-wrap gap-1.5">{connection.linked_workflows.map((id) => <span key={`workflow:${id}`} className="rounded-lg bg-cyan-300/8 px-2 py-1 text-[10px] font-bold text-cyan-300">{workflows.find((item) => item.id === id)?.display_name ?? id}</span>)}{connection.linked_councils.map((id) => <span key={`council:${id}`} className="rounded-lg bg-violet-300/8 px-2 py-1 text-[10px] font-bold text-violet-200">{id === 'sales' ? 'Sales Council' : id}</span>)}{!hasLinks && <span className="text-xs text-slate-600">Not linked to a destination</span>}</div><button onClick={() => openEditor(connection)} className="mt-5 flex h-10 w-full items-center justify-center gap-2 rounded-xl border border-white/10 bg-white/5 text-xs font-bold text-slate-200 hover:border-cyan-300/20 hover:bg-cyan-300/8"><LockKeyhole className="h-4 w-4" />{connection.configured ? 'Manage securely' : 'Configure connection'}</button></article>;
        })}
      </section>

      {selected && <div role="dialog" aria-modal="true" className="fixed inset-0 z-[80] flex items-center justify-center bg-[#02050b]/78 p-4 backdrop-blur-md" onMouseDown={(event) => { if (event.target === event.currentTarget) setSelected(null); }}><div className="liquid-glass max-h-[88vh] w-full max-w-2xl overflow-y-auto rounded-[30px] p-6 lg:p-7"><div className="flex items-start justify-between"><div><p className="eyebrow">Encrypted connection</p><h2 className="mt-2 text-2xl font-black text-slate-50">{selected.display_name}</h2><p className="mt-2 text-sm text-slate-500">Existing values are never shown. Saving replaces the complete credential set and disables linked workflows until re-verified.</p></div><button onClick={() => setSelected(null)} className="rounded-xl p-2 text-slate-500 hover:bg-white/8 hover:text-white"><X className="h-5 w-5" /></button></div>
        <div className="mt-6 grid gap-4 sm:grid-cols-2">{selected.fields.map((field) => <label key={field.key} className="text-xs font-bold uppercase tracking-wide text-slate-400">{field.label}{field.required && <span className="text-cyan-300"> *</span>}<input type={field.secret ? 'password' : 'text'} autoComplete="off" value={values[field.key] ?? ''} onChange={(event) => setValues((current) => ({ ...current, [field.key]: event.target.value }))} placeholder={selected.configured_fields.includes(field.key) ? 'Stored — enter replacement' : 'Enter value'} className="mt-2 h-11 w-full input-shell rounded-xl px-3 text-sm font-normal normal-case tracking-normal text-slate-100 placeholder:text-slate-600 focus:border-cyan-300/40" />{field.help_text && <span className="mt-2 block text-[11px] font-normal normal-case leading-4 tracking-normal text-slate-500">{field.help_text}</span>}</label>)}</div>
        <div className="mt-6 flex flex-wrap gap-2"><button disabled={busy !== ''} onClick={() => void save()} className="flex h-10 items-center gap-2 rounded-xl bg-cyan-300 px-4 text-xs font-black text-[#031019] disabled:opacity-50"><Save className="h-4 w-4" />Encrypt & save</button><button disabled={!selected.configured || busy !== ''} onClick={() => void verify(selected.id)} className="flex h-10 items-center gap-2 rounded-xl border border-emerald-300/20 bg-emerald-300/8 px-4 text-xs font-bold text-emerald-300 disabled:opacity-40"><Check className="h-4 w-4" />Verify connection</button>{selected.configured && <button disabled={busy !== ''} onClick={() => void remove(selected.id)} className="ml-auto flex h-10 items-center gap-2 rounded-xl border border-rose-300/20 px-4 text-xs font-bold text-rose-300 disabled:opacity-50"><Trash2 className="h-4 w-4" />Remove</button>}</div>
        {(ALLOWED[selected.id] ?? []).length > 0 && <div className="mt-7 border-t border-white/8 pt-6"><h3 className="text-sm font-bold text-slate-200">Reusable automation links</h3><p className="mt-1 text-xs text-slate-400">A connection must be configured before it can be linked. Required connections cannot be removed from a workflow.</p><div className="mt-4 space-y-2">{(ALLOWED[selected.id] ?? []).map((workflowId) => { const definition = workflows.find((item) => item.id === workflowId); const linked = selected.linked_workflows.includes(workflowId); return <button key={workflowId} disabled={!selected.configured || busy !== ''} onClick={() => void toggleLink(selected, workflowId)} className="flex w-full items-center gap-3 rounded-xl border border-white/8 bg-white/[0.025] px-4 py-3 text-left disabled:opacity-40"><span className={`grid h-5 w-5 place-items-center rounded-md border ${linked ? 'border-cyan-300 bg-cyan-300 text-[#04111b]' : 'border-white/15'}`}>{linked && <Check className="h-3.5 w-3.5" />}</span><span className="flex-1 text-sm font-semibold text-slate-200">{definition?.display_name ?? workflowId}</span><span className="text-[10px] font-bold uppercase tracking-wide text-slate-400">{linked ? 'linked' : 'available'}</span></button>; })}</div></div>}
        {(COUNCIL_ALLOWED[selected.id] ?? []).length > 0 && <div className="mt-7 border-t border-white/8 pt-6"><h3 className="text-sm font-bold text-slate-200">Approval destinations</h3><p className="mt-1 text-xs text-slate-400">Verify the connection, then link HubSpot to Sales Council only when approved leads should be synchronized. A valid contact email is required on each run.</p><div className="mt-4 space-y-2">{(COUNCIL_ALLOWED[selected.id] ?? []).map((councilId) => { const linked = selected.linked_councils.includes(councilId); return <button key={councilId} disabled={selected.status !== 'verified' || busy !== ''} onClick={() => void toggleCouncilLink(selected, councilId)} className="flex w-full items-center gap-3 rounded-xl border border-white/8 bg-white/[0.025] px-4 py-3 text-left disabled:opacity-40"><span className={`grid h-5 w-5 place-items-center rounded-md border ${linked ? 'border-violet-300 bg-violet-300 text-[#04111b]' : 'border-white/15'}`}>{linked && <Check className="h-3.5 w-3.5" />}</span><span className="flex-1 text-sm font-semibold text-slate-200">Sales Council approved leads</span><span className="text-[10px] font-bold uppercase tracking-wide text-slate-400">{linked ? 'linked' : selected.status === 'verified' ? 'available' : 'verify first'}</span></button>; })}</div></div>}
      </div></div>}
    </div>
  );
}
