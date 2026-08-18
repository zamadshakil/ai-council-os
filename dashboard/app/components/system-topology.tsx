'use client';

import Link from 'next/link';
import { motion } from 'framer-motion';
import { ArrowUpRight, BookOpen, CheckCircle2, Lightbulb, Radio, Sparkles, Target, Users } from 'lucide-react';
import { Task, WorkflowDefinition } from '../lib/types';

const ACTIVE_TASK_STATES = new Set(['queued', 'running', 'publishing']);
const REVIEW_TASK_STATES = new Set(['awaiting_approval', 'needs_manual_review']);

const COUNCILS = [
  { id: 'grant', label: 'Grant', icon: Lightbulb, color: '#a78bfa' },
  { id: 'sales', label: 'Sales', icon: Target, color: '#59e1f7' },
  { id: 'content', label: 'Content', icon: BookOpen, color: '#fb7185' },
] as const;

function FlowPath({ d, active, color }: { d: string; active: boolean; color: string }) {
  return (
    <>
      <path d={d} className="topology-path-base" />
      <motion.path
        d={d}
        className="topology-path-signal"
        style={{ stroke: color }}
        initial={false}
        animate={active ? { strokeDashoffset: [0, -40], opacity: [0.38, 0.95, 0.38] } : { strokeDashoffset: [0, -40], opacity: [0.1, 0.24, 0.1] }}
        transition={active
          ? { strokeDashoffset: { duration: 1.8, repeat: Infinity, ease: 'linear' }, opacity: { duration: 2.2, repeat: Infinity } }
          : { strokeDashoffset: { duration: 8, repeat: Infinity, ease: 'linear' }, opacity: { duration: 4.8, repeat: Infinity, ease: 'easeInOut' } }}
      />
    </>
  );
}

function TopologyNode({
  href,
  label,
  value,
  helper,
  color,
  active,
  icon: Icon,
}: {
  href: string;
  label: string;
  value: string;
  helper: string;
  color: string;
  active: boolean;
  icon: typeof Target;
}) {
  return (
    <Link
      href={href}
      className="topology-node group"
      data-active={active}
      style={{ '--node-accent': color } as React.CSSProperties}
    >
      <span className="topology-node-icon"><Icon className="h-4 w-4" /></span>
      <span className="min-w-0 flex-1">
        <span className="block text-[10px] font-black uppercase tracking-[.17em] text-slate-500">{label}</span>
        <span className="mt-0.5 block truncate text-sm font-extrabold text-slate-100">{value}</span>
        <span className="mt-0.5 block truncate text-[11px] text-slate-500">{helper}</span>
      </span>
      <ArrowUpRight className="h-3.5 w-3.5 text-slate-600 transition group-hover:text-slate-200" />
    </Link>
  );
}

export function SystemTopology({
  tasks,
  workflows,
  integrationReady,
  integrationTotal,
  knowledgeCount,
}: {
  tasks: Task[];
  workflows: WorkflowDefinition[];
  integrationReady: number;
  integrationTotal: number;
  knowledgeCount: number;
}) {
  const activeTasks = tasks.filter((task) => ACTIVE_TASK_STATES.has(task.status));
  const decisions = tasks.filter((task) => REVIEW_TASK_STATES.has(task.status)).length;
  const onlineWorkflows = workflows.filter((workflow) => workflow.is_enabled && !workflow.is_paused).length;
  const coreActive = activeTasks.length > 0 || onlineWorkflows > 0;

  return (
    <section className="topology-shell surface-card overflow-hidden rounded-[28px]" aria-labelledby="topology-title">
      <header className="flex flex-wrap items-center justify-between gap-4 border-b border-white/8 px-5 py-4 lg:px-6">
        <div>
          <p className="eyebrow">Live system map</p>
          <h2 id="topology-title" className="mt-1 text-lg font-extrabold text-slate-100">Council command topology</h2>
        </div>
        <div className="flex flex-wrap items-center gap-2 text-[11px] font-bold">
          <span className="topology-legend"><span className={`status-dot ${coreActive ? 'text-emerald-300' : 'text-cyan-300'}`} />{coreActive ? 'Live traffic' : 'Ambient monitoring'}</span>
          <span className="topology-legend">{integrationReady}/{integrationTotal} integrations verified</span>
        </div>
      </header>

      <div className="topology-canvas">
        <svg className="topology-wiring" viewBox="0 0 1000 480" preserveAspectRatio="none" aria-hidden="true">
          <FlowPath d="M 238 88 C 360 88, 348 210, 455 232" active={activeTasks.some((task) => task.council === 'grant')} color="#a78bfa" />
          <FlowPath d="M 238 240 C 350 240, 370 240, 455 240" active={activeTasks.some((task) => task.council === 'sales')} color="#59e1f7" />
          <FlowPath d="M 238 392 C 360 392, 348 270, 455 248" active={activeTasks.some((task) => task.council === 'content')} color="#fb7185" />
          <FlowPath d="M 545 232 C 650 205, 648 88, 762 88" active={onlineWorkflows > 0} color="#48e3a2" />
          <FlowPath d="M 545 240 C 660 240, 650 240, 762 240" active={decisions > 0} color="#f5c96b" />
          <FlowPath d="M 545 248 C 650 275, 648 392, 762 392" active={knowledgeCount > 0} color="#60a5fa" />
        </svg>

        <div className="topology-layout">
          <div className="topology-stack topology-councils">
            {COUNCILS.map((council) => {
              const councilTasks = tasks.filter((task) => task.council === council.id);
              const councilActive = councilTasks.filter((task) => ACTIVE_TASK_STATES.has(task.status)).length;
              return (
                <TopologyNode
                  key={council.id}
                  href={`/councils?select=${council.id}`}
                  label={`${council.label} council`}
                  value={`${councilTasks.length} persisted run${councilTasks.length === 1 ? '' : 's'}`}
                  helper={councilActive > 0 ? `${councilActive} currently in motion` : 'Ready for a new brief'}
                  color={council.color}
                  active={councilActive > 0}
                  icon={council.icon}
                />
              );
            })}
          </div>

          <div className="topology-core-wrap">
            <div className="topology-core" data-active={coreActive}>
              <motion.span
                aria-hidden="true"
                className="topology-core-orbit"
                animate={{ rotate: 360 }}
                transition={{ duration: coreActive ? 18 : 42, repeat: Infinity, ease: 'linear' }}
              >
                <i /><i /><i />
              </motion.span>
              <motion.span
                className="jarvis-orb grid h-14 w-14 place-items-center rounded-full bg-cyan-300/10 text-cyan-200"
                animate={{ scale: coreActive ? [1, 1.06, 1] : [1, 1.025, 1], boxShadow: coreActive ? ['0 0 0 rgba(89,225,247,0)', '0 0 32px rgba(89,225,247,.2)', '0 0 0 rgba(89,225,247,0)'] : ['0 0 0 rgba(89,225,247,0)', '0 0 18px rgba(89,225,247,.1)', '0 0 0 rgba(89,225,247,0)'] }}
                transition={{ duration: coreActive ? 2.4 : 5.5, repeat: Infinity, ease: 'easeInOut' }}
              ><Sparkles className="h-5 w-5" /></motion.span>
              <p className="mt-4 text-[10px] font-black uppercase tracking-[.2em] text-cyan-300">Council OS</p>
              <p className="mt-1 text-xl font-black text-slate-50">Orchestrator</p>
              <div className="mt-4 flex items-center justify-center gap-2">
                <span className="topology-core-stat"><strong>{activeTasks.length}</strong> active</span>
                <span className="topology-core-stat"><strong>{onlineWorkflows}</strong> online</span>
              </div>
            </div>
          </div>

          <div className="topology-stack topology-operations">
            <TopologyNode href="/workflows" label="Automation fabric" value={`${onlineWorkflows}/${workflows.length} online`} helper="Durable jobs and schedules" color="#48e3a2" active={onlineWorkflows > 0} icon={Radio} />
            <TopologyNode href="/approvals" label="Human control" value={`${decisions} decision${decisions === 1 ? '' : 's'} waiting`} helper="Nothing publishes without approval" color="#f5c96b" active={decisions > 0} icon={CheckCircle2} />
            <TopologyNode href="/knowledge" label="Knowledge core" value={`${knowledgeCount} indexed source${knowledgeCount === 1 ? '' : 's'}`} helper="Scoped evidence for grounded work" color="#60a5fa" active={knowledgeCount > 0} icon={Users} />
          </div>
        </div>
      </div>
    </section>
  );
}
