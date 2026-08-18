'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import { BookOpenCheck, Check, FileSearch, FileText, RefreshCw, Search, Sparkles, Trash2, UploadCloud } from 'lucide-react';
import { deleteKnowledgeDocument, fetchKnowledgeDocuments, searchKnowledge, uploadKnowledgeDocument } from '../lib/api';
import { KnowledgeDoc, KnowledgeSearchResult } from '../lib/types';

export default function KnowledgePage() {
  const inputRef = useRef<HTMLInputElement>(null);
  const [documents, setDocuments] = useState<KnowledgeDoc[]>([]);
  const [selected, setSelected] = useState<string[]>([]);
  const [results, setResults] = useState<KnowledgeSearchResult[]>([]);
  const [query, setQuery] = useState('');
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState('');
  const [error, setError] = useState('');

  const load = useCallback(async () => {
    try { setDocuments(await fetchKnowledgeDocuments()); setError(''); }
    catch (loadError) { setError(loadError instanceof Error ? loadError.message : 'Unable to load documents.'); }
    finally { setLoading(false); }
  }, []);

  useEffect(() => {
    let active = true;
    void fetchKnowledgeDocuments()
      .then((items) => { if (active) setDocuments(items); })
      .catch((loadError: unknown) => { if (active) setError(loadError instanceof Error ? loadError.message : 'Unable to load documents.'); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, []);

  async function upload(file: File) {
    setBusy('upload'); setError('');
    try { await uploadKnowledgeDocument(file); await load(); }
    catch (uploadError) { setError(uploadError instanceof Error ? uploadError.message : 'Unable to index this document.'); }
    finally { setBusy(''); if (inputRef.current) inputRef.current.value = ''; }
  }

  async function remove(document: KnowledgeDoc) {
    if (!window.confirm(`Delete “${document.filename}” and its retrieval index?`)) return;
    setBusy(document.id); setError('');
    try { await deleteKnowledgeDocument(document.id); setDocuments((current) => current.filter((item) => item.id !== document.id)); setSelected((current) => current.filter((hash) => hash !== document.doc_hash)); }
    catch (deleteError) { setError(deleteError instanceof Error ? deleteError.message : 'Unable to delete document.'); }
    finally { setBusy(''); }
  }

  async function search(event: React.FormEvent) {
    event.preventDefault(); if (!query.trim()) return;
    setBusy('search'); setError('');
    try { setResults(await searchKnowledge(query.trim(), selected)); }
    catch (searchError) { setError(searchError instanceof Error ? searchError.message : 'Knowledge retrieval failed.'); }
    finally { setBusy(''); }
  }

  const chunks = documents.reduce((sum, document) => sum + (document.chunk_count ?? 0), 0);

  return (
    <div className="space-y-7 pb-16">
      <div className="flex flex-wrap items-end justify-between gap-4"><div><p className="eyebrow">Grounded intelligence</p><h1 className="mt-2 text-3xl font-black tracking-tight text-slate-50">Knowledge Hub</h1><p className="mt-2 max-w-2xl text-sm text-slate-400">Parent-child indexing, hybrid semantic + keyword retrieval, reciprocal-rank fusion, and reranking—with visible source citations.</p></div><div className="flex gap-2"><button onClick={() => void load()} className="flex h-10 items-center gap-2 rounded-xl border border-white/10 bg-white/5 px-4 text-xs font-bold text-slate-300"><RefreshCw className={`h-4 w-4 ${loading ? 'animate-spin' : ''}`} />Refresh</button><button onClick={() => inputRef.current?.click()} disabled={busy === 'upload'} className="flex h-10 items-center gap-2 rounded-xl bg-cyan-300 px-4 text-xs font-black text-[#04111b] disabled:opacity-50"><UploadCloud className="h-4 w-4" />{busy === 'upload' ? 'Indexing…' : 'Upload source'}</button><input ref={inputRef} type="file" accept=".pdf,.docx,.txt,.md" className="hidden" onChange={(event) => { const file = event.target.files?.[0]; if (file) void upload(file); }} /></div></div>

      <section className="grid gap-4 sm:grid-cols-3">{[[documents.length,'Indexed sources',BookOpenCheck],[chunks,'Search passages',FileText],[selected.length || 'All','Current scope',FileSearch]].map(([value,label,Icon]) => { const IconComponent = Icon as typeof FileText; return <div key={String(label)} className="surface-card rounded-2xl p-5"><IconComponent className="h-5 w-5 text-cyan-300" /><p className="mt-5 text-3xl font-black text-slate-50">{String(value)}</p><p className="mt-1 text-xs font-bold uppercase tracking-wide text-slate-500">{String(label)}</p></div>; })}</section>
      {error && <p role="alert" className="rounded-2xl border border-rose-300/20 bg-rose-400/8 p-4 text-sm text-rose-200">{error}</p>}

      <div className="grid gap-5 xl:grid-cols-[.8fr_1.25fr]">
        <section className="surface-card h-fit rounded-2xl p-5"><div className="flex items-center justify-between"><div><p className="eyebrow">Source vault</p><h2 className="mt-1 font-bold text-slate-100">Retrieval scope</h2></div><span className="text-xs text-slate-600">PDF · DOCX · TXT · MD</span></div><p className="mt-3 text-xs leading-5 text-slate-500">Select sources to test the same strict scope used by Grant Council. Leave all unchecked to search the full library.</p><div className="mt-5 space-y-2">{loading && documents.length === 0 ? <div className="h-40 animate-pulse rounded-xl bg-white/5" /> : documents.length === 0 ? <p className="rounded-xl border border-dashed border-white/10 py-14 text-center text-xs text-slate-600">No source documents indexed.</p> : documents.map((document) => { const active = selected.includes(document.doc_hash); return <article key={document.id} className={`rounded-xl border p-3 ${active ? 'border-cyan-300/25 bg-cyan-300/7' : 'border-white/8 bg-white/[0.02]'}`}><div className="flex items-start gap-3"><button onClick={() => setSelected((current) => active ? current.filter((hash) => hash !== document.doc_hash) : [...current, document.doc_hash])} className={`mt-0.5 grid h-5 w-5 shrink-0 place-items-center rounded-md border ${active ? 'border-cyan-300 bg-cyan-300 text-[#04111b]' : 'border-white/15 text-transparent'}`} aria-label={`${active ? 'Remove' : 'Add'} ${document.filename} from search scope`}><Check className="h-3.5 w-3.5" /></button><div className="min-w-0 flex-1"><p className="truncate text-sm font-bold text-slate-200">{document.filename}</p><p className="mt-1 text-[11px] text-slate-600">{document.chunk_count ?? 0} passages · {document.status ?? 'ready'}</p>{document.warning && <p className="mt-1 text-[11px] text-amber-300">{document.warning}</p>}</div><button disabled={busy === document.id} onClick={() => void remove(document)} className="rounded-lg p-2 text-slate-600 hover:bg-rose-400/10 hover:text-rose-300"><Trash2 className="h-4 w-4" /></button></div></article>; })}</div></section>

        <section className="space-y-4"><form onSubmit={search} className="surface-card rounded-2xl p-4"><div className="flex items-center gap-3"><span className="jarvis-orb grid h-10 w-10 shrink-0 place-items-center rounded-full bg-cyan-300/8 text-cyan-300"><Sparkles className="h-4 w-4" /></span><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Ask a question across your selected evidence…" className="h-12 min-w-0 flex-1 bg-transparent text-sm text-slate-100 placeholder:text-slate-600 focus:outline-none" /><button disabled={busy === 'search' || !query.trim()} className="flex h-10 items-center gap-2 rounded-xl bg-cyan-300 px-4 text-xs font-black text-[#04111b] disabled:opacity-40"><Search className="h-4 w-4" />{busy === 'search' ? 'Searching…' : 'Search'}</button></div></form>
          <div className="space-y-3">{results.length === 0 ? <div className="surface-card rounded-2xl border-dashed py-24 text-center"><FileSearch className="mx-auto h-7 w-7 text-slate-700" /><p className="mt-3 text-sm text-slate-500">Run a search to inspect grounded passages and citations.</p></div> : results.map((result, index) => <article key={`${result.doc_hash}-${result.chunk_index ?? index}`} className="surface-card rounded-2xl p-5"><div className="flex items-center justify-between gap-4"><span className="rounded-lg border border-cyan-300/15 bg-cyan-300/8 px-2.5 py-1 text-[10px] font-black uppercase tracking-wide text-cyan-300">#{index + 1} source match</span><span className="text-[11px] font-mono text-slate-600">score {result.score.toFixed(4)}</span></div><p className="mt-4 whitespace-pre-wrap text-sm leading-6 text-slate-300">{result.text}</p><div className="mt-5 flex items-center gap-2 border-t border-white/8 pt-4 text-xs text-slate-500"><FileText className="h-4 w-4 text-emerald-300" /><span className="font-semibold text-slate-400">{result.citation || result.doc_name}</span></div></article>)}</div>
        </section>
      </div>
    </div>
  );
}
