'use client';

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  AlertTriangle, BookOpenCheck, Boxes, BrainCircuit, Check, Download,
  FileSearch, FileText, GitBranch, History, Lightbulb, List, Network, Plus,
  RefreshCw, RotateCcw, Search, ShieldCheck, Sparkles, Trash2, UploadCloud,
  ZoomIn, ZoomOut,
} from 'lucide-react';
import {
  activateSkillRevision, actOnLearningSuggestion, createKnowledgeCollection, deleteKnowledgeDocument,
  fetchBrainConflicts, fetchBrainGaps, fetchBrainGraph, fetchKnowledgeCollections,
  fetchKnowledgeBinding, fetchKnowledgeDocuments, fetchLearningSuggestions,
  fetchSkillRevisions, fetchSkills, getKnowledgeMarkdownExportUrl, importMarkdownDocuments,
  inspectKnowledge, reviewBrainResource, updateKnowledgeBinding, uploadKnowledgeDocument,
} from '../lib/api';
import {
  BrainConflict, BrainGap, BrainGraph, CouncilSkill, KnowledgeCollection,
  KnowledgeDoc, KnowledgeSearchResponse, LearningSuggestion, SkillRevision,
} from '../lib/types';
import { RetrievalPipeline } from '../components/retrieval-pipeline';

type Tab = 'library' | 'search' | 'graph' | 'reviews' | 'skills';
const tabs: Array<{ id: Tab; label: string; icon: typeof FileText }> = [
  { id: 'library', label: 'Library & collections', icon: BookOpenCheck },
  { id: 'search', label: 'Search inspector', icon: FileSearch },
  { id: 'graph', label: 'Entity graph', icon: Network },
  { id: 'reviews', label: 'Reviews & gaps', icon: AlertTriangle },
  { id: 'skills', label: 'Skills & learning', icon: Sparkles },
];

export default function KnowledgePage() {
  const inputRef = useRef<HTMLInputElement>(null);
  const markdownInputRef = useRef<HTMLInputElement>(null);
  const [tab, setTab] = useState<Tab>('library');
  const [documents, setDocuments] = useState<KnowledgeDoc[]>([]);
  const [collections, setCollections] = useState<KnowledgeCollection[]>([]);
  const [graph, setGraph] = useState<BrainGraph>({ nodes: [], edges: [], facts: [] });
  const [conflicts, setConflicts] = useState<BrainConflict[]>([]);
  const [gaps, setGaps] = useState<BrainGap[]>([]);
  const [skills, setSkills] = useState<CouncilSkill[]>([]);
  const [suggestions, setSuggestions] = useState<LearningSuggestion[]>([]);
  const [selectedDocuments, setSelectedDocuments] = useState<string[]>([]);
  const [selectedCollections, setSelectedCollections] = useState<string[]>([]);
  const [query, setQuery] = useState('');
  const [searchResponse, setSearchResponse] = useState<KnowledgeSearchResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState('');
  const [error, setError] = useState('');
  const [graphList, setGraphList] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [docs, collectionItems, graphData, conflictItems, gapItems, skillItems, learningItems] = await Promise.all([
        fetchKnowledgeDocuments(), fetchKnowledgeCollections(), fetchBrainGraph(),
        fetchBrainConflicts(), fetchBrainGaps(), fetchSkills(), fetchLearningSuggestions(),
      ]);
      setDocuments(docs); setCollections(collectionItems); setGraph(graphData);
      setConflicts(conflictItems); setGaps(gapItems); setSkills(skillItems); setSuggestions(learningItems);
      setError('');
    } catch (loadError) {
      setError(loadError instanceof Error ? loadError.message : 'Unable to load Council Brain state.');
    } finally { setLoading(false); }
  }, []);

  useEffect(() => {
    const timer = window.setTimeout(() => void load(), 0);
    return () => window.clearTimeout(timer);
  }, [load]);
  useEffect(() => {
    if (!documents.some((document) => ['pending', 'indexing'].includes(document.status ?? ''))) return;
    const timer = window.setInterval(() => void load(), 5000);
    return () => window.clearInterval(timer);
  }, [documents, load]);

  async function upload(file: File) {
    setBusy('upload'); setError('');
    try { await uploadKnowledgeDocument(file); await load(); }
    catch (uploadError) { setError(uploadError instanceof Error ? uploadError.message : 'Unable to queue this source.'); }
    finally { setBusy(''); if (inputRef.current) inputRef.current.value = ''; }
  }

  async function importMarkdown(files: FileList) {
    setBusy('markdown-import'); setError('');
    try {
      const documents = await Promise.all(Array.from(files).map(async (file) => ({
        path: file.webkitRelativePath || file.name, content: await file.text(),
      })));
      await importMarkdownDocuments(documents);
      await load();
    } catch (importError) {
      setError(importError instanceof Error ? importError.message : 'Unable to import Markdown notes.');
    } finally {
      setBusy('');
      if (markdownInputRef.current) markdownInputRef.current.value = '';
    }
  }

  async function remove(document: KnowledgeDoc) {
    if (!window.confirm(`Delete “${document.filename}”, its graph provenance, and retrieval index?`)) return;
    setBusy(document.id);
    try { await deleteKnowledgeDocument(document.id, document.version ?? 1); await load(); }
    catch (deleteError) { setError(deleteError instanceof Error ? deleteError.message : 'Unable to delete source.'); }
    finally { setBusy(''); }
  }

  async function runSearch(event: React.FormEvent) {
    event.preventDefault(); if (!query.trim()) return;
    setBusy('search'); setError('');
    try {
      setSearchResponse(await inspectKnowledge({
        query: query.trim(), document_ids: selectedDocuments,
        collection_ids: selectedCollections, graph_expansion: true, top_k: 8,
      }));
    } catch (searchError) { setError(searchError instanceof Error ? searchError.message : 'Knowledge retrieval failed.'); }
    finally { setBusy(''); }
  }

  const chunks = documents.reduce((sum, document) => sum + (document.chunk_count ?? 0), 0);
  const openReviews = conflicts.filter((item) => item.status === 'open').length
    + gaps.filter((item) => item.status === 'open').length
    + suggestions.filter((item) => item.status === 'pending').length;

  return (
    <div className="space-y-6 pb-16">
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div><p className="eyebrow">Native Council Brain</p><h1 className="mt-2 text-3xl font-black tracking-tight text-slate-50">Knowledge & learning</h1><p className="mt-2 max-w-3xl text-sm leading-6 text-slate-400">PostgreSQL-authoritative evidence, provenance graph, human-reviewed learning, and inspectable hybrid retrieval. No external memory service.</p></div>
        <div className="flex flex-wrap gap-2"><button onClick={() => void load()} className="control-button"><RefreshCw className={`h-4 w-4 ${loading ? 'animate-spin' : ''}`} />Refresh</button><a href={getKnowledgeMarkdownExportUrl()} download className="control-button"><Download className="h-4 w-4" />Export Markdown</a><button onClick={() => markdownInputRef.current?.click()} disabled={busy === 'markdown-import'} className="control-button"><BookOpenCheck className="h-4 w-4" />{busy === 'markdown-import' ? 'Importing…' : 'Import Markdown'}</button><button onClick={() => inputRef.current?.click()} disabled={busy === 'upload'} className="primary-button"><UploadCloud className="h-4 w-4" />{busy === 'upload' ? 'Queueing…' : 'Upload source'}</button><input ref={markdownInputRef} type="file" accept=".md,text/markdown" multiple className="hidden" onChange={(event) => { if (event.target.files?.length) void importMarkdown(event.target.files); }} /><input ref={inputRef} type="file" accept=".pdf,.docx,.txt,.md" className="hidden" onChange={(event) => { const file = event.target.files?.[0]; if (file) void upload(file); }} /></div>
      </header>

      <section className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4" aria-label="Brain summary">
        <Metric icon={BookOpenCheck} value={documents.length} label="Sources" />
        <Metric icon={FileText} value={chunks} label="Indexed passages" />
        <Metric icon={GitBranch} value={graph.nodes.filter((node) => node.type !== 'fact').length} label="Persisted entities" />
        <Metric icon={ShieldCheck} value={openReviews} label="Human reviews" tone={openReviews ? 'amber' : 'emerald'} />
      </section>

      <nav className="surface-card flex gap-1 overflow-x-auto rounded-2xl p-1.5" aria-label="Knowledge sections">
        {tabs.map((item) => { const Icon = item.icon; const active = tab === item.id; return <button key={item.id} onClick={() => setTab(item.id)} aria-current={active ? 'page' : undefined} className={`flex min-w-max items-center gap-2 rounded-xl px-4 py-2.5 text-xs font-bold transition ${active ? 'bg-cyan-300 text-[#04111b] shadow-[0_0_28px_rgba(103,232,249,.18)]' : 'text-slate-400 hover:bg-white/5 hover:text-slate-100'}`}><Icon className="h-4 w-4" />{item.label}</button>; })}
      </nav>
      {error && <p role="alert" className="rounded-2xl border border-rose-300/20 bg-rose-400/8 p-4 text-sm text-rose-200">{error}</p>}

      {tab === 'library' && <Library documents={documents} collections={collections} busy={busy} selected={selectedDocuments} setSelected={setSelectedDocuments} remove={remove} reload={load} setError={setError} />}
      {tab === 'search' && <SearchInspector documents={documents} collections={collections} selectedDocuments={selectedDocuments} setSelectedDocuments={setSelectedDocuments} selectedCollections={selectedCollections} setSelectedCollections={setSelectedCollections} query={query} setQuery={setQuery} response={searchResponse} searching={busy === 'search'} runSearch={runSearch} chunks={chunks} />}
      {tab === 'graph' && <GraphPanel graph={graph} listMode={graphList} setListMode={setGraphList} />}
      {tab === 'reviews' && <ReviewPanel graph={graph} conflicts={conflicts} gaps={gaps} suggestions={suggestions} reload={load} setError={setError} />}
      {tab === 'skills' && <SkillsPanel skills={skills} suggestions={suggestions} reload={load} setError={setError} />}
    </div>
  );
}

function Metric({ icon: Icon, value, label, tone = 'cyan' }: { icon: typeof FileText; value: number; label: string; tone?: 'cyan' | 'amber' | 'emerald' }) {
  const color = tone === 'amber' ? 'text-amber-300' : tone === 'emerald' ? 'text-emerald-300' : 'text-cyan-300';
  return <div className="surface-card rounded-2xl p-5"><Icon className={`h-5 w-5 ${color}`} /><p className="mt-4 text-3xl font-black text-slate-50">{value}</p><p className="mt-1 text-xs font-bold uppercase tracking-wide text-slate-500">{label}</p></div>;
}

function Library({ documents, collections, busy, selected, setSelected, remove, reload, setError }: { documents: KnowledgeDoc[]; collections: KnowledgeCollection[]; busy: string; selected: string[]; setSelected: React.Dispatch<React.SetStateAction<string[]>>; remove: (document: KnowledgeDoc) => Promise<void>; reload: () => Promise<void>; setError: (value: string) => void }) {
  const [name, setName] = useState(''); const [description, setDescription] = useState(''); const [saving, setSaving] = useState(false); const [savingBinding, setSavingBinding] = useState('');
  async function create(event: React.FormEvent) { event.preventDefault(); if (!name.trim()) return; setSaving(true); try { await createKnowledgeCollection({ name: name.trim(), description, document_ids: selected }); setName(''); setDescription(''); setSelected([]); await reload(); } finally { setSaving(false); } }
  async function toggleCouncil(collection: KnowledgeCollection, council: 'grant' | 'sales' | 'content') {
    const key = `${collection.id}:${council}`; setSavingBinding(key); setError('');
    try {
      const current = await fetchKnowledgeBinding('council', council);
      const currentlyBound = current.collection_ids.includes(collection.id);
      const next = currentlyBound ? current.collection_ids.filter((id) => id !== collection.id) : [...current.collection_ids, collection.id];
      await updateKnowledgeBinding('councils', council, next, current.version); await reload();
    }
    catch (bindingError) { setError(bindingError instanceof Error ? bindingError.message : 'Unable to update council evidence binding.'); }
    finally { setSavingBinding(''); }
  }
  return <div className="grid gap-5 xl:grid-cols-[1.25fr_.75fr]">
    <section className="surface-card rounded-2xl p-5"><div><p className="eyebrow">Source library</p><h2 className="mt-1 text-lg font-bold text-slate-100">Durable ingestion</h2><p className="mt-2 text-xs leading-5 text-slate-500">Uploads return immediately, then move through pending → indexing → ready or failed. Select sources to create a reusable collection.</p></div><div className="mt-5 space-y-2">{documents.length === 0 ? <Empty icon={FileText} text="No sources uploaded." /> : documents.map((document) => { const active = selected.includes(document.id); return <article key={document.id} className={`rounded-xl border p-4 ${active ? 'border-cyan-300/30 bg-cyan-300/8' : 'border-white/8 bg-white/[.025]'}`}><div className="flex items-start gap-3"><button onClick={() => setSelected((current) => active ? current.filter((id) => id !== document.id) : [...current, document.id])} className={`mt-0.5 grid h-6 w-6 shrink-0 place-items-center rounded-lg border ${active ? 'border-cyan-300 bg-cyan-300 text-[#04111b]' : 'border-white/15 text-transparent'}`} aria-label={`${active ? 'Remove' : 'Add'} ${document.filename} ${active ? 'from' : 'to'} collection selection`}><Check className="h-3.5 w-3.5" /></button><div className="min-w-0 flex-1"><div className="flex flex-wrap items-center gap-2"><p className="truncate text-sm font-bold text-slate-200">{document.filename}</p><Status value={document.status ?? 'pending'} /></div><p className="mt-1 text-[11px] text-slate-500">{document.chunk_count ?? 0} passages · index v{document.index_version ?? 0} · {document.embedding_model || 'embedding pending'}</p>{document.warning && <p className="mt-2 text-xs text-amber-200">{document.warning}</p>}{document.error && <p className="mt-2 text-xs text-rose-200">{document.error}</p>}</div><button disabled={busy === document.id} onClick={() => void remove(document)} className="rounded-lg p-2 text-slate-600 hover:bg-rose-400/10 hover:text-rose-300" aria-label={`Delete ${document.filename}`}><Trash2 className="h-4 w-4" /></button></div></article>; })}</div></section>
    <aside className="space-y-4"><form onSubmit={create} className="surface-card rounded-2xl p-5"><p className="eyebrow">New collection</p><h2 className="mt-1 font-bold text-slate-100">Bind evidence once</h2><label className="field-label mt-5">Collection name<input className="field-input mt-2" value={name} onChange={(event) => setName(event.target.value)} placeholder="Brand & product truth" /></label><label className="field-label mt-4">Description<textarea className="field-input mt-2 min-h-24 resize-y py-3" value={description} onChange={(event) => setDescription(event.target.value)} placeholder="When councils should use these sources" /></label><button disabled={saving || !name.trim()} className="primary-button mt-4 w-full justify-center"><Plus className="h-4 w-4" />Create with {selected.length} source{selected.length === 1 ? '' : 's'}</button></form><div className="space-y-2">{collections.map((collection) => <article key={collection.id} className="surface-card rounded-2xl p-4"><div className="flex items-center gap-3"><Boxes className="h-5 w-5 text-violet-300" /><div><p className="text-sm font-bold text-slate-200">{collection.name}</p><p className="text-xs text-slate-500">{collection.document_count} sources · v{collection.version}</p></div></div>{collection.description && <p className="mt-3 text-xs leading-5 text-slate-400">{collection.description}</p>}<fieldset className="mt-4"><legend className="text-[10px] font-black uppercase tracking-[.14em] text-slate-600">Allowed councils</legend><div className="mt-2 flex flex-wrap gap-2">{(['grant', 'sales', 'content'] as const).map((council) => { const active = collection.bindings?.some((item) => item.target_type === 'council' && item.target_id === council) ?? false; const key = `${collection.id}:${council}`; return <button key={council} type="button" disabled={Boolean(savingBinding)} aria-pressed={active} onClick={() => void toggleCouncil(collection, council)} className={`rounded-lg border px-3 py-2 text-xs font-bold capitalize transition ${active ? 'border-cyan-300/40 bg-cyan-300/15 text-cyan-100' : 'border-white/10 bg-white/[.025] text-slate-500 hover:text-slate-200'}`}>{savingBinding === key ? 'Saving…' : council}</button>; })}</div></fieldset></article>)}</div></aside>
  </div>;
}

function SearchInspector({ documents, collections, selectedDocuments, setSelectedDocuments, selectedCollections, setSelectedCollections, query, setQuery, response, searching, runSearch, chunks }: { documents: KnowledgeDoc[]; collections: KnowledgeCollection[]; selectedDocuments: string[]; setSelectedDocuments: React.Dispatch<React.SetStateAction<string[]>>; selectedCollections: string[]; setSelectedCollections: React.Dispatch<React.SetStateAction<string[]>>; query: string; setQuery: (value: string) => void; response: KnowledgeSearchResponse | null; searching: boolean; runSearch: (event: React.FormEvent) => Promise<void>; chunks: number }) {
  return <div className="space-y-4"><RetrievalPipeline searching={searching} sourceCount={selectedDocuments.length || documents.length} chunkCount={chunks} /><div className="grid gap-5 xl:grid-cols-[.72fr_1.28fr]"><aside className="surface-card h-fit rounded-2xl p-5"><p className="eyebrow">Strict scope</p><h2 className="mt-1 font-bold text-slate-100">Evidence allowed in this inspection</h2><ScopeGroup title="Collections" items={collections.map((item) => ({ id: item.id, label: item.name, detail: `${item.document_count} sources` }))} selected={selectedCollections} setSelected={setSelectedCollections} /><ScopeGroup title="Individual sources" items={documents.filter((item) => item.status === 'ready').map((item) => ({ id: item.id, label: item.filename, detail: `${item.chunk_count ?? 0} passages` }))} selected={selectedDocuments} setSelected={setSelectedDocuments} /></aside><section className="space-y-3"><form onSubmit={(event) => void runSearch(event)} className="surface-card rounded-2xl p-4"><div className="flex items-center gap-3"><span className="jarvis-orb grid h-10 w-10 shrink-0 place-items-center rounded-full bg-cyan-300/8 text-cyan-300"><BrainCircuit className="h-4 w-4" /></span><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Ask across the allowed evidence…" className="h-12 min-w-0 flex-1 bg-transparent text-sm text-slate-100 placeholder:text-slate-600 focus:outline-none" aria-label="Knowledge search question" /><button disabled={searching || !query.trim()} className="primary-button"><Search className="h-4 w-4" />{searching ? 'Inspecting…' : 'Inspect'}</button></div></form>{response?.warnings.map((warning) => <p key={warning} role="status" className="rounded-xl border border-amber-300/15 bg-amber-300/5 p-3 text-xs text-amber-200">{warning}</p>)}{response && <div className="flex flex-wrap gap-2 text-[10px] font-bold uppercase tracking-wide text-slate-500"><span className="status-pill">{response.cached ? 'cache hit' : 'fresh query'}</span><span className="status-pill">{response.pipeline}</span><span className="status-pill">index v{response.index_version}</span>{Object.entries(response.candidate_counts).map(([key, value]) => <span key={key} className="status-pill">{key} {value}</span>)}</div>}{!response ? <Empty icon={FileSearch} text="Run a search to inspect candidates, scores, spans, and citations." /> : response.results.map((result, index) => <article key={result.id ?? `${result.doc_hash}-${index}`} className="surface-card rounded-2xl p-5"><div className="flex flex-wrap items-center justify-between gap-3"><span className="rounded-lg border border-cyan-300/15 bg-cyan-300/8 px-2.5 py-1 text-[10px] font-black uppercase tracking-wide text-cyan-300">#{index + 1} grounded match</span><span className="font-mono text-[11px] text-slate-500">{result.score.toFixed(4)}</span></div><p className="mt-4 whitespace-pre-wrap text-sm leading-6 text-slate-300">{result.text}</p><div className="mt-4 grid gap-2 sm:grid-cols-3">{Object.entries(result.score_breakdown ?? {}).filter(([, value]) => value !== null && value !== undefined).map(([key, value]) => <div key={key} className="rounded-lg bg-white/[.035] px-3 py-2"><p className="text-[10px] uppercase text-slate-600">{key}</p><p className="mt-1 font-mono text-xs text-slate-300">{Number(value).toFixed(key === 'rank' ? 0 : 4)}</p></div>)}</div><p className="mt-4 flex items-center gap-2 border-t border-white/8 pt-4 text-xs text-emerald-200"><FileText className="h-4 w-4" />{result.citation}</p></article>)}</section></div></div>;
}

function ScopeGroup({ title, items, selected, setSelected }: { title: string; items: Array<{ id: string; label: string; detail: string }>; selected: string[]; setSelected: React.Dispatch<React.SetStateAction<string[]>> }) { return <div className="mt-5"><p className="text-[10px] font-black uppercase tracking-[.16em] text-slate-600">{title}</p><div className="mt-2 space-y-2">{items.map((item) => { const active = selected.includes(item.id); return <button key={item.id} onClick={() => setSelected((current) => active ? current.filter((id) => id !== item.id) : [...current, item.id])} className={`flex w-full items-center gap-3 rounded-xl border p-3 text-left ${active ? 'border-cyan-300/25 bg-cyan-300/7' : 'border-white/8 bg-white/[.02]'}`}><span className={`grid h-5 w-5 place-items-center rounded-md border ${active ? 'border-cyan-300 bg-cyan-300 text-[#04111b]' : 'border-white/15 text-transparent'}`}><Check className="h-3 w-3" /></span><span className="min-w-0"><span className="block truncate text-xs font-bold text-slate-300">{item.label}</span><span className="text-[10px] text-slate-600">{item.detail}</span></span></button>; })}</div></div>; }

function GraphPanel({ graph, listMode, setListMode }: { graph: BrainGraph; listMode: boolean; setListMode: (value: boolean) => void }) {
  const [nodeFilter, setNodeFilter] = useState<'all' | 'entity' | 'fact'>('all');
  const [zoom, setZoom] = useState(1);
  const visibleNodes = useMemo(() => graph.nodes.filter((node) => (
    nodeFilter === 'all' || (nodeFilter === 'fact' ? node.type === 'fact' : node.type !== 'fact')
  )), [graph.nodes, nodeFilter]);
  const positioned = useMemo(() => {
    const entities = visibleNodes.filter((node) => node.type !== 'fact').slice(0, 14);
    const facts = visibleNodes.filter((node) => node.type === 'fact').slice(0, 14);
    const visible = [...entities, ...facts];
    return visible.map((node, index, nodes) => ({ ...node, x: 50 + 37 * Math.cos((index / Math.max(nodes.length, 1)) * Math.PI * 2), y: 50 + 37 * Math.sin((index / Math.max(nodes.length, 1)) * Math.PI * 2) }));
  }, [visibleNodes]);
  const positions = new Map(positioned.map((node) => [node.id, node]));
  const viewSize = 100 / zoom;
  const viewOrigin = (100 - viewSize) / 2;
  return <section className="surface-card overflow-hidden rounded-2xl"><div className="flex flex-wrap items-center justify-between gap-3 border-b border-white/8 p-5"><div><p className="eyebrow">Persisted topology</p><h2 className="mt-1 text-lg font-bold text-slate-100">Entities, facts & provenance</h2><p className="mt-1 text-xs text-slate-500">Relationships are persisted; motion appears only on paths used by retrieval in the last 20 minutes. Use list view or reduced motion for a static representation.</p></div><div className="flex rounded-xl border border-white/10 p-1" role="group" aria-label="Graph display mode"><button onClick={() => setListMode(false)} aria-pressed={!listMode} className={`rounded-lg p-2 ${!listMode ? 'bg-cyan-300 text-[#04111b]' : 'text-slate-500'}`}><Network className="h-4 w-4" /><span className="sr-only">Graph view</span></button><button onClick={() => setListMode(true)} aria-pressed={listMode} className={`rounded-lg p-2 ${listMode ? 'bg-cyan-300 text-[#04111b]' : 'text-slate-500'}`}><List className="h-4 w-4" /><span className="sr-only">List view</span></button></div></div><div className="flex flex-wrap items-center justify-between gap-3 border-b border-white/8 px-5 py-3"><label className="flex items-center gap-2 text-xs font-bold text-slate-400">Show<select value={nodeFilter} onChange={(event) => setNodeFilter(event.target.value as 'all' | 'entity' | 'fact')} className="rounded-lg border border-white/10 bg-[#071522] px-3 py-2 text-slate-200"><option value="all">Entities and facts</option><option value="entity">Entities only</option><option value="fact">Facts only</option></select></label>{!listMode && <div className="flex items-center gap-2" role="group" aria-label="Graph zoom"><button onClick={() => setZoom((value) => Math.max(1, value - 0.25))} disabled={zoom <= 1} className="control-button" aria-label="Zoom out"><ZoomOut className="h-4 w-4" /></button><span className="min-w-12 text-center text-xs text-slate-400">{Math.round(zoom * 100)}%</span><button onClick={() => setZoom((value) => Math.min(2, value + 0.25))} disabled={zoom >= 2} className="control-button" aria-label="Zoom in"><ZoomIn className="h-4 w-4" /></button></div>}</div>{graph.nodes.length === 0 ? <Empty icon={Network} text="No graph records yet. Ready documents are extracted by the durable worker." /> : visibleNodes.length === 0 ? <Empty icon={Network} text="No records match this graph filter." /> : listMode ? <div className="grid gap-2 p-5 md:grid-cols-2">{visibleNodes.map((node) => <article key={node.id} tabIndex={0} className="rounded-xl border border-white/8 bg-white/[.025] p-4 focus:outline-none focus:ring-2 focus:ring-cyan-300"><div className="flex items-center justify-between"><p className="font-bold text-slate-200">{node.label}</p><Status value={node.status} /></div><p className="mt-1 text-xs text-slate-500">{node.type} · {(node.confidence * 100).toFixed(0)}%{node.active ? ' · recently retrieved' : ''}</p></article>)}</div> : <div className="relative aspect-[16/8] min-h-[420px] bg-[radial-gradient(circle_at_center,rgba(34,211,238,.09),transparent_46%)]"><svg viewBox={`${viewOrigin} ${viewOrigin} ${viewSize} ${viewSize}`} className="absolute inset-0 h-full w-full" role="img" aria-label={`${visibleNodes.length} persisted entities and facts connected by provenance relationships`}><g>{graph.edges.map((edge) => { const source = positions.get(edge.source); const target = positions.get(edge.target); if (!source || !target) return null; return <line key={edge.id} x1={source.x} y1={source.y} x2={target.x} y2={target.y} data-active={edge.active} className="brain-edge" vectorEffect="non-scaling-stroke" />; })}</g>{positioned.map((node) => <g key={node.id} tabIndex={0} role="button" data-active={node.active} data-node-type={node.type} aria-label={`${node.label}, ${node.type}, ${node.status}${node.active ? ', recently retrieved' : ''}`} className="brain-node focus:outline-none"><circle cx={node.x} cy={node.y} r={node.type === 'fact' ? '3.1' : '3.8'} /><text x={node.x} y={node.y + 7} textAnchor="middle">{node.label.slice(0, 18)}</text></g>)}</svg><div className="pointer-events-none absolute left-1/2 top-1/2 grid h-28 w-28 -translate-x-1/2 -translate-y-1/2 place-items-center rounded-full border border-cyan-300/25 bg-[#071522]/90 shadow-[0_0_70px_rgba(34,211,238,.17)]"><div className="text-center"><BrainCircuit className="mx-auto h-6 w-6 text-cyan-300" /><p className="mt-2 text-[10px] font-black uppercase tracking-widest text-cyan-200">Council Brain</p></div></div></div>}</section>;
}

function ReviewPanel({ graph, conflicts, gaps, suggestions, reload, setError }: { graph: BrainGraph; conflicts: BrainConflict[]; gaps: BrainGap[]; suggestions: LearningSuggestion[]; reload: () => Promise<void>; setError: (value: string) => void }) {
  async function review(resource_type: 'entity' | 'fact' | 'relationship' | 'conflict' | 'gap', resource_id: string, action: 'verify' | 'reject' | 'resolve', expected_version: number) { try { await reviewBrainResource({ resource_type, resource_id, action, expected_version, notes: action === 'resolve' ? 'Resolved by administrator.' : 'Reviewed by administrator.' }); await reload(); } catch (error) { setError(error instanceof Error ? error.message : 'Review failed.'); } }
  const proposedFacts = graph.facts.filter((item) => item.status === 'proposed');
  const proposedEntities = graph.nodes.filter((item) => item.type !== 'fact' && item.status === 'proposed');
  const proposedRelationships = graph.edges.filter((item) => !item.id.startsWith('fact-subject:') && item.status === 'proposed');
  return <div className="grid gap-5 xl:grid-cols-2"><ReviewColumn title="Proposed facts" icon={ShieldCheck} empty="No extracted facts require administrator review.">{proposedFacts.map((item) => <article key={item.id} className="rounded-xl border border-white/8 bg-white/[.025] p-4"><div className="flex items-start justify-between gap-3"><div><p className="font-bold text-slate-200">{item.predicate}</p><p className="mt-2 text-sm leading-6 text-slate-400">{item.value}</p>{item.citation && <p className="mt-2 text-xs text-emerald-200">Citation: “{item.citation}”</p>}</div><Status value={item.status} /></div><div className="mt-3 flex gap-2"><button onClick={() => void review('fact', item.id, 'verify', item.version)} className="primary-button">Verify</button><button onClick={() => void review('fact', item.id, 'reject', item.version)} className="control-button">Reject</button></div></article>)}</ReviewColumn><ReviewColumn title="Proposed graph records" icon={Network} empty="No entities or relationships require review.">{[...proposedEntities.map((item) => ({ id: item.id, type: 'entity' as const, title: item.label, detail: item.type, version: item.version })), ...proposedRelationships.map((item) => ({ id: item.id, type: 'relationship' as const, title: item.label, detail: 'Persisted entity relationship', version: item.version }))].map((item) => <article key={`${item.type}:${item.id}`} className="rounded-xl border border-white/8 bg-white/[.025] p-4"><div className="flex items-center justify-between gap-3"><div><p className="font-bold text-slate-200">{item.title}</p><p className="mt-1 text-xs capitalize text-slate-500">{item.type} · {item.detail}</p></div><Status value="proposed" /></div><div className="mt-3 flex gap-2"><button onClick={() => void review(item.type, item.id, 'verify', item.version)} className="primary-button">Verify</button><button onClick={() => void review(item.type, item.id, 'reject', item.version)} className="control-button">Reject</button></div></article>)}</ReviewColumn><ReviewColumn title="Contradictions" icon={AlertTriangle} empty="No contradictions detected.">{conflicts.map((item) => <ReviewCard key={item.id} title={`${item.severity} conflict`} detail={item.reason} status={item.status} action={item.status === 'open' ? () => void review('conflict', item.id, 'resolve', item.version) : undefined} />)}</ReviewColumn><ReviewColumn title="Knowledge gaps" icon={Lightbulb} empty="No missing-evidence findings.">{gaps.map((item) => <ReviewCard key={item.id} title="Evidence needed" detail={item.question} status={item.status} action={item.status === 'open' ? () => void review('gap', item.id, 'resolve', item.version) : undefined} />)}</ReviewColumn><ReviewColumn title="Learning suggestions" icon={Sparkles} empty="No administrator edits have produced reusable learning suggestions.">{suggestions.map((item) => <article key={item.id} className="rounded-xl border border-white/8 bg-white/[.025] p-4"><div className="flex flex-wrap items-start justify-between gap-3"><div><p className="font-bold text-slate-200">{item.title}</p><p className="mt-1 text-xs text-slate-500">{item.scope_type}: {item.scope_id || 'global'} · evidence task {item.source_task_id}</p></div><Status value={item.status} /></div><p className="mt-3 text-sm leading-6 text-slate-400">{item.rationale}</p><pre className="mt-3 overflow-x-auto rounded-xl bg-black/20 p-3 text-xs leading-5 text-cyan-100 whitespace-pre-wrap">{item.diff || item.proposed_instructions}</pre>{item.status === 'pending' && <div className="mt-3 flex gap-2"><button onClick={async () => { await actOnLearningSuggestion(item.id, 'approve', item.version); await reload(); }} className="primary-button">Approve revision</button><button onClick={async () => { await actOnLearningSuggestion(item.id, 'reject', item.version); await reload(); }} className="control-button">Reject</button></div>}</article>)}</ReviewColumn></div>;
}

function SkillsPanel({ skills, suggestions, reload, setError }: { skills: CouncilSkill[]; suggestions: LearningSuggestion[]; reload: () => Promise<void>; setError: (value: string) => void }) {
  const pending = suggestions.filter((item) => item.status === 'pending').length;
  const [selectedSkillId, setSelectedSkillId] = useState('');
  const [revisions, setRevisions] = useState<SkillRevision[]>([]);
  const [historyBusy, setHistoryBusy] = useState('');
  const selectedSkill = skills.find((skill) => skill.id === selectedSkillId);

  async function openHistory(skill: CouncilSkill) {
    setSelectedSkillId(skill.id); setHistoryBusy('load'); setError('');
    try { setRevisions(await fetchSkillRevisions(skill.id)); }
    catch (error) { setError(error instanceof Error ? error.message : 'Unable to load revision history.'); }
    finally { setHistoryBusy(''); }
  }

  async function activate(revision: SkillRevision) {
    if (!selectedSkill || selectedSkill.active_revision_id === revision.id) return;
    setHistoryBusy(revision.id); setError('');
    try {
      await activateSkillRevision(selectedSkill.id, revision.id, selectedSkill.version);
      await reload();
      setRevisions(await fetchSkillRevisions(selectedSkill.id));
    } catch (error) { setError(error instanceof Error ? error.message : 'Unable to activate this revision.'); }
    finally { setHistoryBusy(''); }
  }

  return <div className="grid gap-5 xl:grid-cols-[1fr_.45fr]">
    <section className="surface-card rounded-2xl p-5"><p className="eyebrow">Immutable procedures</p><h2 className="mt-1 text-lg font-bold text-slate-100">Active skill library</h2><p className="mt-2 text-xs leading-5 text-slate-500">Only active administrator-approved revisions enter prompts. Rollback changes the active pointer; revision history is never rewritten.</p><div className="mt-5 grid gap-3 md:grid-cols-2">{skills.length === 0 ? <div className="md:col-span-2"><Empty icon={Sparkles} text="No approved skills yet." /></div> : skills.map((skill) => <article key={skill.id} className={`rounded-xl border p-4 ${selectedSkillId === skill.id ? 'border-cyan-300/30 bg-cyan-300/8' : 'border-white/8 bg-white/[.025]'}`}><div className="flex items-start justify-between gap-3"><div className="grid h-9 w-9 place-items-center rounded-xl border border-violet-300/20 bg-violet-300/8 text-violet-200"><Sparkles className="h-4 w-4" /></div><span className="status-pill">resource v{skill.version}</span></div><p className="mt-4 font-bold text-slate-200">{skill.name}</p><p className="mt-1 text-xs text-slate-500">{skill.scope_type}: {skill.scope_id || 'global'}</p><p className="mt-3 text-xs leading-5 text-slate-400">{skill.description}</p><div className="mt-3 flex flex-wrap gap-1">{skill.tags.map((tag) => <span key={tag} className="status-pill">{tag}</span>)}</div><button type="button" onClick={() => void openHistory(skill)} className="control-button mt-4 w-full justify-center"><History className="h-4 w-4" />Revision history</button></article>)}</div>
      {selectedSkill && <section className="mt-5 rounded-2xl border border-cyan-300/15 bg-black/15 p-4" aria-label={`${selectedSkill.name} revision history`}><div className="flex flex-wrap items-center justify-between gap-2"><div><p className="eyebrow">Revision history</p><h3 className="mt-1 font-bold text-slate-100">{selectedSkill.name}</h3></div><button type="button" onClick={() => { setSelectedSkillId(''); setRevisions([]); }} className="control-button">Close</button></div><div className="mt-4 space-y-2">{historyBusy === 'load' ? <p className="text-sm text-slate-500">Loading immutable revisions…</p> : revisions.map((revision) => { const active = selectedSkill.active_revision_id === revision.id; return <article key={revision.id} className={`rounded-xl border p-4 ${active ? 'border-emerald-300/25 bg-emerald-300/7' : 'border-white/8 bg-white/[.02]'}`}><div className="flex flex-wrap items-start justify-between gap-3"><div><p className="font-bold text-slate-200">Revision {revision.revision_number}</p><p className="mt-1 text-[11px] text-slate-500">{revision.token_count} tokens · {revision.created_by} · {new Date(revision.created_at).toLocaleString()}</p></div>{active ? <Status value="active" /> : <button type="button" disabled={Boolean(historyBusy)} onClick={() => void activate(revision)} className="control-button"><RotateCcw className="h-4 w-4" />{historyBusy === revision.id ? 'Activating…' : 'Activate revision'}</button>}</div><pre className="mt-3 whitespace-pre-wrap rounded-xl bg-black/20 p-3 text-xs leading-5 text-slate-300">{revision.instructions}</pre></article>; })}</div></section>}
    </section>
    <aside className="surface-card h-fit rounded-2xl p-5"><Lightbulb className="h-5 w-5 text-amber-300" /><p className="mt-4 text-3xl font-black text-slate-50">{pending}</p><p className="mt-1 text-xs font-bold uppercase tracking-wide text-slate-500">Suggestions awaiting review</p><button onClick={() => { void reload().catch((error: unknown) => setError(error instanceof Error ? error.message : 'Refresh failed.')); }} className="control-button mt-5 w-full justify-center">Refresh learning queue</button></aside>
  </div>;
}

function ReviewColumn({ title, icon: Icon, empty, children }: { title: string; icon: typeof FileText; empty: string; children: React.ReactNode }) { const count = Array.isArray(children) ? children.length : 0; return <section className="surface-card rounded-2xl p-5"><div className="flex items-center gap-3"><Icon className="h-5 w-5 text-amber-300" /><h2 className="font-bold text-slate-100">{title}</h2></div><div className="mt-4 space-y-3">{count === 0 ? <p className="rounded-xl border border-dashed border-white/10 py-10 text-center text-xs text-slate-600">{empty}</p> : children}</div></section>; }
function ReviewCard({ title, detail, status, action }: { title: string; detail: string; status: string; action?: () => void }) { return <article className="rounded-xl border border-white/8 bg-white/[.025] p-4"><div className="flex items-center justify-between gap-3"><p className="font-bold text-slate-200">{title}</p><Status value={status} /></div><p className="mt-2 text-sm leading-6 text-slate-400">{detail}</p>{action && <button onClick={action} className="control-button mt-3">Mark resolved</button>}</article>; }
function Status({ value }: { value: string }) { const tone = value === 'ready' || value === 'verified' || value === 'approved' || value === 'resolved' || value === 'active' ? 'border-emerald-300/20 bg-emerald-300/8 text-emerald-200' : value === 'failed' || value === 'rejected' ? 'border-rose-300/20 bg-rose-300/8 text-rose-200' : 'border-amber-300/20 bg-amber-300/8 text-amber-200'; return <span className={`rounded-full border px-2 py-1 text-[9px] font-black uppercase tracking-wide ${tone}`}>{value.replaceAll('_', ' ')}</span>; }
function Empty({ icon: Icon, text }: { icon: typeof FileText; text: string }) { return <div className="surface-card rounded-2xl border-dashed py-20 text-center"><Icon className="mx-auto h-7 w-7 text-slate-700" /><p className="mt-3 text-sm text-slate-500">{text}</p></div>; }
