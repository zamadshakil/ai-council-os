'use client';

import { useEffect, useState } from 'react';
import { useRouter, useSearchParams } from 'next/navigation';
import { ArrowRight, BookOpen, Check, FileText, Lightbulb, Send, Target, Users, Workflow } from 'lucide-react';
import { fetchKnowledgeDocuments, runCouncil } from '../lib/api';
import { CouncilName, KnowledgeDoc, MutationEnvelope, Priority, Task } from '../lib/types';

const COUNCILS: Array<{ id: CouncilName; name: string; description: string; threshold: number; icon: typeof Target }> = [
  { id: 'grant', name: 'Grant Council', description: 'Draft and review grant sections using selected knowledge.', threshold: 88, icon: Lightbulb },
  { id: 'sales', name: 'Sales Council', description: 'Score prospects and draft personalized outreach.', threshold: 85, icon: Target },
  { id: 'content', name: 'Content Council', description: 'Create platform-specific content variants.', threshold: 85, icon: BookOpen },
];

function extractTask(result: MutationEnvelope<Task> | Task): Task {
  return 'resource' in result ? result.resource : result;
}

export default function CouncilsPage() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const requested = searchParams.get('select');
  const initialCouncil = COUNCILS.some((item) => item.id === requested) ? requested as CouncilName : 'grant';
  const [selected, setSelected] = useState<CouncilName>(initialCouncil);
  const [taskDescription, setTaskDescription] = useState('');
  const [priority, setPriority] = useState<Priority>('normal');
  const [documents, setDocuments] = useState<KnowledgeDoc[]>([]);
  const [selectedDocuments, setSelectedDocuments] = useState<string[]>([]);
  const [contactEmail, setContactEmail] = useState('');
  const [contactFirstName, setContactFirstName] = useState('');
  const [contactLastName, setContactLastName] = useState('');
  const [contactCompany, setContactCompany] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState('');

  const isContentAutomation = selected === 'content';

  function openContentAutomation() {
    window.sessionStorage.setItem('council-os:content-engine-draft', JSON.stringify({
      title: taskDescription.trim().slice(0, 100) || 'Multi-platform content request',
      transcript: taskDescription,
      sourceId: `manual-${Date.now()}`,
    }));
    router.push('/workflows/content_engine?from=council');
  }

  useEffect(() => {
    void fetchKnowledgeDocuments().then(setDocuments).catch(() => setDocuments([]));
  }, []);

  async function submit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (selected === 'content') {
      openContentAutomation();
      return;
    }
    setSubmitting(true);
    setError('');
    try {
      const task = extractTask(await runCouncil({
        council: selected,
        task_description: taskDescription,
        context: selected === 'sales' ? {
          contact_email: contactEmail.trim(),
          contact_first_name: contactFirstName.trim(),
          contact_last_name: contactLastName.trim(),
          company: contactCompany.trim(),
        } : {},
        priority,
        selected_document_hashes: selected === 'grant' ? selectedDocuments : [],
      }));
      router.push(`/approvals/${task.task_id}`);
    } catch (submitError) {
      setError(submitError instanceof Error ? submitError.message : 'Unable to start the council run.');
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="mx-auto max-w-5xl space-y-8 pb-16">
      <div>
        <p className="eyebrow">Draft and review workspace</p><h1 className="mt-2 text-3xl font-black tracking-tight text-slate-50">Run a council</h1>
        <p className="mt-2 text-sm text-slate-400">Councils produce reviewed drafts. They do not publish to social accounts; use Workflows for destination automation.</p>
      </div>

      <form onSubmit={submit} className="space-y-8">
        <div className="grid gap-4 md:grid-cols-3">
          {COUNCILS.map((council) => {
            const Icon = council.icon;
            const active = selected === council.id;
            return (
              <button
                key={council.id}
                type="button"
                onClick={() => setSelected(council.id)}
                aria-pressed={active}
                data-selected={active}
                className="choice-card surface-card interactive-surface min-h-56 rounded-2xl border p-5 text-left"
              >
                <div className="flex items-center justify-between">
                  <Icon className={`h-6 w-6 ${active ? 'text-cyan-300' : 'text-slate-500'}`} />
                  <span className={`rounded-full border px-2.5 py-1 text-xs font-bold ${active ? 'border-cyan-200/40 bg-cyan-200/15 text-cyan-100' : 'border-white/5 bg-white/5 text-slate-400'}`}>{active ? 'Selected' : `Threshold ${council.threshold}`}</span>
                </div>
                <h2 className="mt-4 text-lg font-bold text-slate-50">{council.name}</h2>
                <p className={`mt-2 text-sm leading-6 ${active ? 'text-slate-200' : 'text-slate-300'}`}>{council.description}</p>
                <p className={`mt-4 flex items-center gap-1.5 text-xs font-semibold ${active ? 'text-cyan-100' : 'text-slate-400'}`}><Users className="h-3.5 w-3.5" /> Generator + critic, up to 3 drafts</p>
              </button>
            );
          })}
        </div>

        <div className="surface-card rounded-2xl p-6">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <label htmlFor="task-description" className="font-bold text-slate-100">Task instructions</label>
            <label className="flex items-center gap-2 text-sm font-medium text-slate-400">
              Priority
              <select value={priority} onChange={(event) => setPriority(event.target.value as Priority)} className="input-shell rounded-lg px-3 py-2 text-slate-100">
                <option value="normal">Normal</option>
                <option value="high">High</option>
              </select>
            </label>
          </div>
          <textarea
            id="task-description"
            required
            minLength={3}
            maxLength={50_000}
            value={taskDescription}
            onChange={(event) => setTaskDescription(event.target.value)}
            placeholder="Describe the exact output, audience, constraints, and source information."
            className="mt-4 min-h-56 w-full resize-y input-shell rounded-xl p-4 text-sm leading-6 text-slate-100 outline-none focus:border-cyan-300/40 focus:ring-2 focus:ring-cyan-300/10"
          />

          {isContentAutomation && (
            <div role="alert" className="mt-4 flex flex-col gap-4 rounded-2xl border border-cyan-300/25 bg-cyan-300/8 p-5 sm:flex-row sm:items-center sm:justify-between">
              <div>
                <p className="flex items-center gap-2 font-bold text-cyan-100"><Workflow className="h-4 w-4" /> Content Council runs through the Content Engine</p>
                <p className="mt-1 max-w-2xl text-sm leading-6 text-slate-300">Your source is handed to six independent platform lanes. Each gets its own critique, approval, delivery state, retry history, and verified integration; Reddit remains manual.</p>
              </div>
              <button type="button" disabled={taskDescription.trim().length < 3} onClick={openContentAutomation} className="flex h-11 shrink-0 items-center justify-center gap-2 rounded-xl bg-cyan-300 px-5 text-sm font-black text-[#04111b] disabled:opacity-40">Build automation run <ArrowRight className="h-4 w-4" /></button>
            </div>
          )}

          {selected === 'grant' && (
            <div className="mt-5 border-t border-white/8 pt-5">
              <div className="flex items-center gap-2">
                <FileText className="h-4 w-4 text-cyan-300" />
                <h3 className="text-sm font-bold text-slate-200">Allowed knowledge documents</h3>
              </div>
              <p className="mt-1 text-xs text-slate-500">Only selected documents can be retrieved for this Grant Council run.</p>
              {documents.length === 0 ? (
                <p className="mt-3 rounded-lg bg-white/5 p-3 text-sm text-slate-500">No ready documents are available in Knowledge.</p>
              ) : (
                <div className="mt-3 grid gap-2 md:grid-cols-2">
                  {documents.map((document) => {
                    const active = selectedDocuments.includes(document.doc_hash);
                    return (
                      <button
                        key={document.doc_hash}
                        type="button"
                        onClick={() => setSelectedDocuments((current) => active ? current.filter((hash) => hash !== document.doc_hash) : [...current, document.doc_hash])}
                        className={`flex items-center gap-3 rounded-xl border p-3 text-left text-sm ${active ? 'border-cyan-300/30 bg-cyan-300/8 text-cyan-100' : 'border-white/10 text-slate-400'}`}
                      >
                        <span className={`flex h-5 w-5 shrink-0 items-center justify-center rounded border ${active ? 'border-cyan-300 bg-cyan-300' : 'border-white/20'}`}>{active && <Check className="h-3.5 w-3.5 text-[#04111b]" />}</span>
                        <span className="truncate font-medium">{document.filename}</span>
                      </button>
                    );
                  })}
                </div>
              )}
            </div>
          )}

          {selected === 'sales' && (
            <fieldset className="mt-5 border-t border-white/8 pt-5">
              <legend className="flex items-center gap-2 text-sm font-bold text-slate-200">
                <Target className="h-4 w-4 text-cyan-300" /> Optional CRM contact
              </legend>
              <p className="mt-1 text-xs leading-5 text-slate-500">If HubSpot is linked in Settings &amp; Integrations, an approved draft uses these explicit fields to update the contact and attach the outreach note. Without a valid email, approval still succeeds and CRM sync is safely skipped.</p>
              <div className="mt-4 grid gap-4 md:grid-cols-2">
                <label className="text-xs font-bold uppercase tracking-wide text-slate-400">Email
                  <input type="email" autoComplete="email" maxLength={320} value={contactEmail} onChange={(event) => setContactEmail(event.target.value)} placeholder="prospect@example.com" className="mt-2 h-11 w-full input-shell rounded-xl px-3 text-sm font-normal normal-case tracking-normal text-slate-100 placeholder:text-slate-600" />
                </label>
                <label className="text-xs font-bold uppercase tracking-wide text-slate-400">Company
                  <input type="text" autoComplete="organization" maxLength={200} value={contactCompany} onChange={(event) => setContactCompany(event.target.value)} placeholder="Company name" className="mt-2 h-11 w-full input-shell rounded-xl px-3 text-sm font-normal normal-case tracking-normal text-slate-100 placeholder:text-slate-600" />
                </label>
                <label className="text-xs font-bold uppercase tracking-wide text-slate-400">First name
                  <input type="text" autoComplete="given-name" maxLength={100} value={contactFirstName} onChange={(event) => setContactFirstName(event.target.value)} placeholder="First name" className="mt-2 h-11 w-full input-shell rounded-xl px-3 text-sm font-normal normal-case tracking-normal text-slate-100 placeholder:text-slate-600" />
                </label>
                <label className="text-xs font-bold uppercase tracking-wide text-slate-400">Last name
                  <input type="text" autoComplete="family-name" maxLength={100} value={contactLastName} onChange={(event) => setContactLastName(event.target.value)} placeholder="Last name" className="mt-2 h-11 w-full input-shell rounded-xl px-3 text-sm font-normal normal-case tracking-normal text-slate-100 placeholder:text-slate-600" />
                </label>
              </div>
            </fieldset>
          )}

          {error && <p role="alert" className="mt-4 rounded-lg border border-rose-300/20 bg-rose-400/8 p-3 text-sm text-rose-200">{error}</p>}
          <div className="mt-6 flex justify-end">
            <button disabled={submitting || taskDescription.trim().length < 3} className="flex h-11 items-center gap-2 rounded-xl bg-cyan-300 px-6 text-sm font-black text-[#04111b] hover:bg-cyan-200 disabled:cursor-not-allowed disabled:opacity-50">
              {submitting ? 'Queueing…' : isContentAutomation ? 'Continue to automation' : 'Run council'}
              {!submitting && (isContentAutomation ? <ArrowRight className="h-4 w-4" /> : <Send className="h-4 w-4" />)}
            </button>
          </div>
        </div>
      </form>
    </div>
  );
}
