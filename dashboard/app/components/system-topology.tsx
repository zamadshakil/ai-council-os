'use client';

import Link from 'next/link';
import { AnimatePresence, motion, useReducedMotion } from 'framer-motion';
import { ArrowUpRight, Bot, Focus, Minus, Network, Plus, Radio, RefreshCw, ShieldCheck, Sparkles } from 'lucide-react';
import { useMemo, useState } from 'react';
import { Task, WorkflowDefinition } from '../lib/types';

const ACTIVE_TASK_STATES = new Set(['queued', 'running', 'publishing']);
const REVIEW_TASK_STATES = new Set(['awaiting_approval', 'needs_manual_review']);
const GRAPH_SIZE = { width: 1000, height: 580, centerX: 500, centerY: 286 };

type GraphView = 'system' | 'councils' | 'automations';
type GraphNode = {
  id: string; label: string; category: string; value: string; helper: string;
  status: string; color: string; href: string; active: boolean; x: number;
  y: number; glyph: string;
};

const COUNCILS = [
  { id: 'grant', label: 'Grant Council', color: '#a78bfa', glyph: 'G' },
  { id: 'sales', label: 'Sales Council', color: '#59e1f7', glyph: 'S' },
  { id: 'content', label: 'Content Council', color: '#fb7185', glyph: 'C' },
] as const;

const WORKFLOW_META: Record<string, { short: string; glyph: string; color: string }> = {
  telegram_control: { short: 'Telegram control', glyph: 'TG', color: '#5eead4' },
  youtube_comments: { short: 'YouTube replies', glyph: 'YT', color: '#fb7185' },
  reddit_prospector: { short: 'Reddit prospects', glyph: 'RD', color: '#fb923c' },
  youtube_descriptions: { short: 'Video descriptions', glyph: 'YD', color: '#f87171' },
  content_engine: { short: 'Content engine', glyph: 'CE', color: '#60a5fa' },
  instagram_comments: { short: 'Instagram replies', glyph: 'IG', color: '#f472b6' },
};

const SYSTEM_POSITIONS = [
  { x: 185, y: 112 }, { x: 120, y: 286 }, { x: 185, y: 460 },
  { x: 815, y: 112 }, { x: 880, y: 286 }, { x: 815, y: 460 },
  { x: 500, y: 520 },
];
const RADIAL_POSITIONS = [
  { x: 500, y: 84 }, { x: 770, y: 158 }, { x: 830, y: 380 },
  { x: 500, y: 492 }, { x: 170, y: 380 }, { x: 230, y: 158 },
];
const CORE_PARTICLES = Array.from({ length: 58 }, (_, index) => {
  const angle = index * 2.399963229728653;
  const radius = 14 + ((index * 17) % 61);
  return {
    x: GRAPH_SIZE.centerX + Math.cos(angle) * radius,
    y: GRAPH_SIZE.centerY + Math.sin(angle) * radius,
    radius: 1.1 + (index % 4) * 0.42,
    delay: (index % 13) * 0.12,
  };
});

function edgePath(node: GraphNode) {
  const { centerX, centerY } = GRAPH_SIZE;
  const horizontal = Math.abs(node.x - centerX) > Math.abs(node.y - centerY);
  if (horizontal) {
    const bend = centerX + (node.x - centerX) * 0.55;
    return `M ${centerX} ${centerY} C ${bend} ${centerY}, ${bend} ${node.y}, ${node.x} ${node.y}`;
  }
  const bend = centerY + (node.y - centerY) * 0.55;
  return `M ${centerX} ${centerY} C ${centerX} ${bend}, ${node.x} ${bend}, ${node.x} ${node.y}`;
}

function GraphNodeShape({ node, selected, onSelect, reduceMotion }: {
  node: GraphNode; selected: boolean; onSelect: () => void; reduceMotion: boolean;
}) {
  return (
    <motion.g
      className="command-graph-node"
      role="button"
      tabIndex={0}
      aria-label={`${node.label}: ${node.value}. ${node.status}`}
      aria-pressed={selected}
      onClick={onSelect}
      onKeyDown={(event) => {
        if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); onSelect(); }
      }}
      initial={reduceMotion ? false : { opacity: 0, scale: 0.82 }}
      animate={{ opacity: 1, scale: 1, x: node.x, y: node.y }}
      exit={reduceMotion ? undefined : { opacity: 0, scale: 0.88 }}
      transition={{ type: 'spring', stiffness: 210, damping: 24 }}
      style={{ '--graph-accent': node.color } as React.CSSProperties}
      data-active={node.active}
      data-selected={selected}
    >
      <rect x="-98" y="-37" width="196" height="74" rx="19" className="command-graph-node-panel" />
      <circle cx="-70" cy="0" r="18" className="command-graph-node-icon" />
      <text x="-70" y="4" textAnchor="middle" className="command-graph-node-glyph">{node.glyph}</text>
      <text x="-43" y="-11" className="command-graph-node-label">{node.label}</text>
      <text x="-43" y="9" className="command-graph-node-value">{node.value}</text>
      <text x="-43" y="26" className="command-graph-node-status">{node.status}</text>
      {node.active && <motion.circle cx="83" cy="-21" r="3.5" fill={node.color}
        animate={reduceMotion ? undefined : { opacity: [0.35, 1, 0.35], r: [3.2, 4.3, 3.2] }}
        transition={{ duration: 1.8, repeat: Infinity, ease: 'easeInOut' }} />}
    </motion.g>
  );
}

export function SystemTopology({ tasks, workflows, integrationReady, integrationTotal, knowledgeCount }: {
  tasks: Task[]; workflows: WorkflowDefinition[]; integrationReady: number;
  integrationTotal: number; knowledgeCount: number;
}) {
  const reduceMotion = Boolean(useReducedMotion());
  const [view, setView] = useState<GraphView>('system');
  const [selectedId, setSelectedId] = useState('grant');
  const [zoom, setZoom] = useState(1);
  const activeTasks = tasks.filter((task) => ACTIVE_TASK_STATES.has(task.status));
  const decisions = tasks.filter((task) => REVIEW_TASK_STATES.has(task.status)).length;
  const onlineWorkflows = workflows.filter((workflow) => workflow.is_enabled && !workflow.is_paused).length;
  const coreActive = activeTasks.length > 0 || onlineWorkflows > 0;

  const nodes = useMemo<GraphNode[]>(() => {
    if (view === 'automations') {
      return workflows.map((workflow, index) => {
        const meta = WORKFLOW_META[workflow.id] ?? { short: workflow.display_name, glyph: 'AI', color: '#59e1f7' };
        const online = workflow.is_enabled && !workflow.is_paused;
        const ready = ['connected', 'verified'].includes(workflow.credential_status);
        return {
          id: workflow.id, label: meta.short, category: 'Automation channel',
          value: online ? 'Online' : workflow.is_paused ? 'Paused' : 'Offline',
          helper: ready ? 'Credentials verified' : `Connection ${workflow.credential_status}`,
          status: workflow.last_run ? `Last run: ${workflow.last_run.status.replaceAll('_', ' ')}` : 'No runs yet',
          color: meta.color, href: `/workflows/${workflow.id}`, active: online,
          ...(RADIAL_POSITIONS[index] ?? RADIAL_POSITIONS[index % RADIAL_POSITIONS.length]), glyph: meta.glyph,
        };
      });
    }
    if (view === 'councils') {
      const positions = [RADIAL_POSITIONS[5], RADIAL_POSITIONS[1], RADIAL_POSITIONS[3]];
      return COUNCILS.map((council, index) => {
        const councilTasks = tasks.filter((task) => task.council === council.id);
        const active = councilTasks.filter((task) => ACTIVE_TASK_STATES.has(task.status)).length;
        const review = councilTasks.filter((task) => REVIEW_TASK_STATES.has(task.status)).length;
        const scored = councilTasks.filter((task) => task.confidence_score !== null);
        const average = scored.length > 0 ? scored.reduce((sum, task) => sum + (task.confidence_score ?? 0), 0) / scored.length : null;
        return {
          id: council.id, label: council.label, category: 'Generator + critic council',
          value: `${councilTasks.length} persisted run${councilTasks.length === 1 ? '' : 's'}`,
          helper: average === null ? 'No scored outputs yet' : `${average.toFixed(0)}% average critic score`,
          status: active > 0 ? `${active} currently running` : review > 0 ? `${review} awaiting approval` : 'Ready for a new brief',
          color: council.color, href: `/councils?select=${council.id}`, active: active > 0,
          ...positions[index], glyph: council.glyph,
        };
      });
    }
    const councilNodes = COUNCILS.map((council, index): GraphNode => {
      const councilTasks = tasks.filter((task) => task.council === council.id);
      const active = councilTasks.filter((task) => ACTIVE_TASK_STATES.has(task.status)).length;
      return {
        id: council.id, label: council.label, category: 'AI council',
        value: `${councilTasks.length} run${councilTasks.length === 1 ? '' : 's'}`,
        helper: 'Generator, critic, human gate', status: active > 0 ? `${active} in motion` : 'Standing by',
        color: council.color, href: `/councils?select=${council.id}`, active: active > 0,
        ...SYSTEM_POSITIONS[index], glyph: council.glyph,
      };
    });
    return [
      ...councilNodes,
      { id: 'automation', label: 'Automation Fabric', category: 'Durable execution', value: `${onlineWorkflows}/${workflows.length} online`, helper: 'Jobs, schedules, and delivery', status: onlineWorkflows > 0 ? 'Processing enabled' : 'No channels enabled', color: '#48e3a2', href: '/workflows', active: onlineWorkflows > 0, ...SYSTEM_POSITIONS[3], glyph: 'AU' },
      { id: 'approvals', label: 'Human Control', category: 'Approval gate', value: `${decisions} waiting`, helper: 'Review before external writes', status: decisions > 0 ? 'Decision required' : 'Queue clear', color: '#f5c96b', href: '/approvals', active: decisions > 0, ...SYSTEM_POSITIONS[4], glyph: 'OK' },
      { id: 'knowledge', label: 'Knowledge Core', category: 'Grounded retrieval', value: `${knowledgeCount} source${knowledgeCount === 1 ? '' : 's'}`, helper: 'Hybrid search and citations', status: knowledgeCount > 0 ? 'Evidence indexed' : 'No sources indexed', color: '#60a5fa', href: '/knowledge', active: knowledgeCount > 0, ...SYSTEM_POSITIONS[5], glyph: 'KB' },
      { id: 'integrations', label: 'Connections', category: 'Secure integration vault', value: `${integrationReady}/${integrationTotal} verified`, helper: 'Reusable provider credentials', status: integrationReady > 0 ? 'Verified services available' : 'Setup required', color: '#22d3ee', href: '/settings', active: integrationReady > 0, ...SYSTEM_POSITIONS[6], glyph: 'IN' },
    ];
  }, [decisions, integrationReady, integrationTotal, knowledgeCount, onlineWorkflows, tasks, view, workflows]);

  const selected = nodes.find((node) => node.id === selectedId) ?? nodes[0];
  const title = view === 'system' ? 'Council command constellation' : view === 'councils' ? 'Council intelligence network' : 'Automation execution network';
  const coreLabel = view === 'system' ? 'Council OS' : view === 'councils' ? 'Council Engine' : 'Automation Fabric';
  const coreValue = view === 'system' ? 'Orchestrator' : view === 'councils' ? `${tasks.length} total runs` : `${onlineWorkflows} online`;
  const viewBox = `${GRAPH_SIZE.centerX - GRAPH_SIZE.width / (2 * zoom)} ${GRAPH_SIZE.centerY - GRAPH_SIZE.height / (2 * zoom)} ${GRAPH_SIZE.width / zoom} ${GRAPH_SIZE.height / zoom}`;

  return (
    <section className="topology-shell command-graph-shell surface-card overflow-hidden rounded-[28px]" aria-labelledby="topology-title">
      <header className="command-graph-header">
        <div><p className="eyebrow">Live intelligence map</p><h2 id="topology-title" className="mt-1 text-lg font-extrabold text-slate-100">{title}</h2></div>
        <div className="flex flex-wrap items-center gap-2 text-[11px] font-bold">
          <span className="topology-legend"><span className={`status-dot ${coreActive ? 'text-emerald-300' : 'text-cyan-300'}`} />{coreActive ? 'Live traffic' : 'Standing by'}</span>
          <span className="topology-legend">{integrationReady}/{integrationTotal} integrations verified</span>
        </div>
      </header>
      <div className="command-graph-toolbar" aria-label="Graph controls">
        <div className="command-graph-tabs" role="tablist" aria-label="Graph view">
          {([['system', 'System', Network], ['councils', 'Councils', Bot], ['automations', 'Automations', Radio]] as const).map(([id, label, Icon]) => (
            <button key={id} type="button" role="tab" aria-selected={view === id} className="command-graph-tab" data-selected={view === id} onClick={() => setView(id)}><Icon className="h-3.5 w-3.5" />{label}</button>
          ))}
        </div>
        <div className="command-graph-zoom">
          <button type="button" onClick={() => setZoom((current) => Math.max(0.8, current - 0.1))} aria-label="Zoom out"><Minus className="h-4 w-4" /></button>
          <button type="button" onClick={() => setZoom(1)} aria-label="Reset graph zoom"><Focus className="h-4 w-4" /><span>{Math.round(zoom * 100)}%</span></button>
          <button type="button" onClick={() => setZoom((current) => Math.min(1.25, current + 0.1))} aria-label="Zoom in"><Plus className="h-4 w-4" /></button>
        </div>
      </div>
      <div className="command-graph-body">
        <div className="command-graph-stage">
          <svg className="command-graph-svg" viewBox={viewBox} role="group" aria-label={`${title}. Select a node to inspect its live persisted state.`}>
            <defs>
              <radialGradient id="graph-core-fill" cx="36%" cy="30%"><stop offset="0" stopColor="#8ff3ff" stopOpacity=".34" /><stop offset=".45" stopColor="#0d7490" stopOpacity=".22" /><stop offset="1" stopColor="#020914" stopOpacity=".96" /></radialGradient>
              <filter id="graph-glow" x="-100%" y="-100%" width="300%" height="300%"><feGaussianBlur stdDeviation="5" result="blur" /><feMerge><feMergeNode in="blur" /><feMergeNode in="SourceGraphic" /></feMerge></filter>
            </defs>
            <AnimatePresence mode="popLayout">
              {nodes.map((node) => { const path = edgePath(node); return <motion.g key={`edge-${view}-${node.id}`} initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}><path d={path} className="command-graph-edge" /><motion.path d={path} className="command-graph-signal" style={{ stroke: node.color }} animate={reduceMotion ? { opacity: node.active ? 0.72 : 0.18 } : { strokeDashoffset: [0, -66], opacity: node.active ? [0.3, 0.95, 0.3] : [0.08, 0.2, 0.08] }} transition={{ strokeDashoffset: { duration: node.active ? 2.2 : 9, repeat: Infinity, ease: 'linear' }, opacity: { duration: node.active ? 2.4 : 5.5, repeat: Infinity } }} /></motion.g>; })}
            </AnimatePresence>
            <circle cx={GRAPH_SIZE.centerX} cy={GRAPH_SIZE.centerY} r="108" className="command-graph-core-halo" />
            <motion.circle cx={GRAPH_SIZE.centerX} cy={GRAPH_SIZE.centerY} r="84" fill="url(#graph-core-fill)" className="command-graph-core" animate={reduceMotion ? undefined : { r: coreActive ? [82, 87, 82] : [83, 85, 83] }} transition={{ duration: coreActive ? 3 : 6, repeat: Infinity, ease: 'easeInOut' }} />
            {CORE_PARTICLES.map((particle, index) => <motion.circle key={index} cx={particle.x} cy={particle.y} r={particle.radius} fill={index % 5 === 0 ? '#a78bfa' : index % 3 === 0 ? '#48e3a2' : '#59e1f7'} filter={index % 7 === 0 ? 'url(#graph-glow)' : undefined} animate={reduceMotion ? { opacity: 0.65 } : { opacity: [0.22, 0.95, 0.22], r: [particle.radius * 0.72, particle.radius * 1.25, particle.radius * 0.72] }} transition={{ duration: 2.2 + (index % 6) * 0.32, delay: particle.delay, repeat: Infinity, ease: 'easeInOut' }} />)}
            <text x={GRAPH_SIZE.centerX} y={GRAPH_SIZE.centerY - 10} textAnchor="middle" className="command-graph-core-label">{coreLabel}</text>
            <text x={GRAPH_SIZE.centerX} y={GRAPH_SIZE.centerY + 14} textAnchor="middle" className="command-graph-core-value">{coreValue}</text>
            <text x={GRAPH_SIZE.centerX} y={GRAPH_SIZE.centerY + 34} textAnchor="middle" className="command-graph-core-status">{coreActive ? `${activeTasks.length} jobs · ${onlineWorkflows} channels` : 'Ready for instruction'}</text>
            <AnimatePresence>{nodes.map((node) => <GraphNodeShape key={`${view}-${node.id}`} node={node} selected={selected?.id === node.id} onSelect={() => setSelectedId(node.id)} reduceMotion={reduceMotion} />)}</AnimatePresence>
          </svg>
          <div className="command-graph-hint"><Sparkles className="h-3.5 w-3.5" />Select any node to inspect live state</div>
        </div>
        <aside className="command-graph-inspector" aria-live="polite">
          <div className="command-graph-inspector-head"><div><p className="eyebrow">Live inspector</p><p className="mt-1 text-sm font-extrabold text-slate-100">{selected?.label ?? 'Select a node'}</p></div><ShieldCheck className="h-4 w-4 text-cyan-300" /></div>
          {selected && <motion.div key={`${view}-${selected.id}`} initial={reduceMotion ? false : { opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }}><div className="command-graph-readout"><span style={{ color: selected.color }}>{selected.category}</span><strong>{selected.value}</strong><p>{selected.helper}</p></div><div className="command-graph-state"><span className="status-dot" style={{ color: selected.active ? selected.color : '#64748b' }} />{selected.status}</div><Link href={selected.href} className="command-graph-open">Open control surface <ArrowUpRight className="h-4 w-4" /></Link></motion.div>}
          <div className="command-graph-directory"><div className="flex items-center justify-between"><p className="eyebrow">Directory</p><span>{nodes.length} nodes</span></div><div className="mt-3 space-y-1.5">{nodes.map((node) => <button key={node.id} type="button" onClick={() => setSelectedId(node.id)} data-selected={selected?.id === node.id}><i style={{ color: node.color }} /><span>{node.label}</span><small>{node.active ? 'Live' : 'Idle'}</small></button>)}</div></div>
          <button type="button" className="command-graph-refresh" onClick={() => setZoom(1)}><RefreshCw className="h-3.5 w-3.5" />Center graph</button>
        </aside>
      </div>
    </section>
  );
}
