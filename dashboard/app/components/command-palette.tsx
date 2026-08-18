'use client';

import { useEffect, useMemo, useState } from 'react';
import { useRouter } from 'next/navigation';
import { Bot, BookOpen, CheckCircle2, Command, Gauge, Search, Settings, Workflow, X } from 'lucide-react';
import { fetchTasks, fetchWorkflows } from '../lib/api';
import { Task, WorkflowDefinition } from '../lib/types';
import { AnimatePresence, motion } from 'framer-motion';

const destinations = [
  { label: 'Operations overview', hint: 'Live system state', href: '/', icon: Gauge },
  { label: 'Queue & approvals', hint: 'Review staged work', href: '/approvals', icon: CheckCircle2 },
  { label: 'Councils', hint: 'Start a Grant, Sales, or Content run', href: '/councils', icon: Bot },
  { label: 'Automations', hint: 'Configure and monitor workflows', href: '/workflows', icon: Workflow },
  { label: 'Knowledge', hint: 'Search selected Grant sources', href: '/knowledge', icon: BookOpen },
  { label: 'Integrations', hint: 'Secure reusable connections', href: '/settings', icon: Settings },
];

export function CommandPalette({ open, onClose }: { open: boolean; onClose: () => void }) {
  const router = useRouter();
  const [query, setQuery] = useState('');
  const [tasks, setTasks] = useState<Task[]>([]);
  const [workflows, setWorkflows] = useState<WorkflowDefinition[]>([]);

  useEffect(() => {
    if (!open) return;
    void Promise.all([fetchTasks(), fetchWorkflows()])
      .then(([nextTasks, nextWorkflows]) => { setTasks(nextTasks); setWorkflows(nextWorkflows); })
      .catch(() => { setTasks([]); setWorkflows([]); });
  }, [open]);

  useEffect(() => {
    if (!open) return;
    const close = (event: KeyboardEvent) => { if (event.key === 'Escape') onClose(); };
    window.addEventListener('keydown', close);
    return () => window.removeEventListener('keydown', close);
  }, [onClose, open]);

  const results = useMemo(() => {
    const needle = query.trim().toLowerCase();
    const pages = destinations.filter((item) => `${item.label} ${item.hint}`.toLowerCase().includes(needle));
    const taskItems = tasks
      .filter((task) => `${task.council} ${task.task_description} ${task.status}`.toLowerCase().includes(needle))
      .slice(0, 5)
      .map((task) => ({ label: task.task_description, hint: `${task.council} · ${task.status.replaceAll('_', ' ')}`, href: `/approvals/${task.task_id}`, icon: CheckCircle2 }));
    const workflowItems = workflows
      .filter((workflow) => `${workflow.display_name} ${workflow.id}`.toLowerCase().includes(needle))
      .slice(0, 5)
      .map((workflow) => ({ label: workflow.display_name, hint: workflow.is_enabled ? workflow.is_paused ? 'Paused' : 'Enabled' : 'Disabled', href: `/workflows/${workflow.id}`, icon: Workflow }));
    return [...pages, ...workflowItems, ...taskItems].slice(0, 12);
  }, [query, tasks, workflows]);

  function navigate(href: string) {
    router.push(href);
    onClose();
  }

  return (
    <AnimatePresence>
      {open && <motion.div
        role="dialog"
        aria-modal="true"
        aria-label="Command palette"
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        exit={{ opacity: 0 }}
        transition={{ duration: 0.16 }}
        className="fixed inset-0 z-[90] flex items-start justify-center bg-[#02050b]/80 px-4 pt-[12vh] backdrop-blur-md"
        onMouseDown={(event) => { if (event.currentTarget === event.target) onClose(); }}
      >
      <motion.div
        initial={{ opacity: 0, y: -10, scale: 0.975 }}
        animate={{ opacity: 1, y: 0, scale: 1 }}
        exit={{ opacity: 0, y: -6, scale: 0.985 }}
        transition={{ duration: 0.2, ease: [0.22, 1, 0.36, 1] }}
        className="liquid-glass w-full max-w-2xl overflow-hidden rounded-[30px] border-cyan-200/20 shadow-[0_35px_100px_rgba(0,0,0,.55)]"
      >
        <div className="flex items-center gap-3 border-b border-white/8 px-5">
          <Search className="h-5 w-5 text-cyan-300" />
          <input autoFocus value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search tasks, workflows, or go to…" className="h-16 flex-1 bg-transparent text-sm text-slate-100 placeholder:text-slate-500 focus:outline-none" />
          <button onClick={onClose} aria-label="Close command palette" className="rounded-lg p-2 text-slate-500 hover:bg-white/8 hover:text-white"><X className="h-4 w-4" /></button>
        </div>
        <div className="max-h-[55vh] overflow-y-auto p-2">
          {results.length ? results.map((item, index) => {
            const Icon = item.icon;
            return <button key={`${item.href}-${index}`} onClick={() => navigate(item.href)} className="flex w-full items-center gap-3 rounded-2xl px-4 py-3 text-left hover:bg-cyan-300/8"><span className="grid h-9 w-9 place-items-center rounded-xl border border-white/8 bg-white/5 text-cyan-300"><Icon className="h-4 w-4" /></span><span className="min-w-0 flex-1"><span className="block truncate text-sm font-semibold text-slate-100">{item.label}</span><span className="block truncate text-xs text-slate-500">{item.hint}</span></span><Command className="h-3.5 w-3.5 text-slate-600" /></button>;
          }) : <p className="px-5 py-12 text-center text-sm text-slate-500">No matching records.</p>}
        </div>
        <div className="border-t border-white/8 px-5 py-3 text-xs text-slate-600">Results come from the current database, not a demo index.</div>
      </motion.div>
    </motion.div>}
    </AnimatePresence>
  );
}
