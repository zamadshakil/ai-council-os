'use client';

import Link from 'next/link';
import { motion } from 'framer-motion';
import { ArrowUpRight, Bot, CheckCircle2, Radio, Send, Sparkles } from 'lucide-react';
import { WorkflowDefinition } from '../lib/types';

const FLOW_META: Record<string, { source: string; council: string; destination: string }> = {
  telegram_control: { source: 'Telegram', council: 'Control plane', destination: 'Admin chat' },
  youtube_comments: { source: 'YouTube comments', council: 'Content Council', destination: 'YouTube reply' },
  reddit_prospector: { source: '45 communities', council: 'Sales Council', destination: 'Manual-ready reply' },
  youtube_descriptions: { source: 'YouTube videos', council: 'Content Council', destination: 'Description update' },
  content_engine: { source: 'Transcript', council: 'Content Council', destination: '6 platform variants' },
  instagram_comments: { source: 'Instagram comments', council: 'Content Council', destination: 'Instagram reply' },
};

function scheduleLabel(workflow: WorkflowDefinition) {
  const preset = typeof workflow.schedule.preset === 'string' ? workflow.schedule.preset : '';
  if (preset) return preset === 'manual' ? 'Manual trigger' : preset.replaceAll('_', ' ');
  const seconds = typeof workflow.schedule.seconds === 'number' ? workflow.schedule.seconds : 0;
  if (seconds >= 86_400) return 'Daily';
  if (seconds >= 3_600) return `Every ${seconds / 3_600}h`;
  if (seconds >= 60) return `Every ${seconds / 60}m`;
  return 'Manual trigger';
}

export function WorkflowFabric({ workflows }: { workflows: WorkflowDefinition[] }) {
  const online = workflows.filter((workflow) => workflow.is_enabled && !workflow.is_paused).length;

  return (
    <section className="fabric-shell surface-card overflow-hidden rounded-[28px]" aria-labelledby="fabric-title">
      <header className="flex flex-wrap items-center justify-between gap-3 border-b border-white/8 px-5 py-4 lg:px-6">
        <div>
          <p className="eyebrow">Execution map</p>
          <h2 id="fabric-title" className="mt-1 text-lg font-extrabold text-slate-100">Approval-first automation fabric</h2>
        </div>
        <span className="topology-legend"><span className={`status-dot ${online > 0 ? 'text-emerald-300' : 'text-cyan-300'}`} />{online}/{workflows.length} channels online</span>
      </header>

      <div className="overflow-x-auto px-5 pb-5 pt-4 lg:px-6">
        <div className="fabric-canvas min-w-[820px]">
          <div className="fabric-headings grid grid-cols-[1.2fr_1fr_.9fr_1.2fr] gap-10 px-4 pb-3 text-[10px] font-black uppercase tracking-[.17em] text-slate-600">
            <span className="flex items-center gap-2"><Radio className="h-3.5 w-3.5" />Signal</span>
            <span className="flex items-center gap-2"><Bot className="h-3.5 w-3.5" />AI council</span>
            <span className="flex items-center gap-2"><CheckCircle2 className="h-3.5 w-3.5" />Human gate</span>
            <span className="flex items-center gap-2"><Send className="h-3.5 w-3.5" />Destination</span>
          </div>
          <div className="space-y-2">
            {workflows.map((workflow) => {
              const meta = FLOW_META[workflow.id] ?? { source: workflow.display_name, council: 'Council', destination: 'Configured destination' };
              const isOnline = workflow.is_enabled && !workflow.is_paused;
              const ready = ['connected', 'verified'].includes(workflow.credential_status);
              return (
                <Link
                  key={workflow.id}
                  href={`/workflows/${workflow.id}`}
                  aria-label={`Open ${workflow.display_name} configuration`}
                  className="fabric-row group relative grid grid-cols-[1.2fr_1fr_.9fr_1.2fr] items-center gap-10 rounded-2xl px-4 pb-3 pt-9"
                  data-active={isOnline}
                >
                  <span className="fabric-row-name">{workflow.display_name}<small>{scheduleLabel(workflow)}</small></span>
                  <span className="fabric-row-badges">
                    <span className={ready ? 'text-emerald-300' : 'text-amber-300'}>{ready ? 'Ready' : workflow.credential_status}</span>
                    <span className={isOnline ? 'text-emerald-300' : 'text-slate-500'}>{isOnline ? 'Live' : workflow.is_paused ? 'Paused' : 'Off'}</span>
                    <ArrowUpRight className="h-3.5 w-3.5 text-slate-600 transition group-hover:text-cyan-200" />
                  </span>
                  <span className="fabric-rail" aria-hidden="true" />
                  {isOnline && (
                    <motion.span
                      aria-hidden="true"
                      className="fabric-packet"
                      initial={{ left: '7%', opacity: 0 }}
                      animate={{ left: ['7%', '91%'], opacity: [0, 1, 1, 0] }}
                      transition={{ duration: 3.2, repeat: Infinity, ease: 'linear', delay: (workflow.id.length % 5) * 0.22 }}
                    />
                  )}
                  <span className="fabric-stage"><i />{meta.source}</span>
                  <span className="fabric-stage"><i />{meta.council}</span>
                  <span className="fabric-stage fabric-human"><i />Approve</span>
                  <span className="fabric-stage"><i />{meta.destination}</span>
                </Link>
              );
            })}
          </div>
          {workflows.length === 0 && <div className="rounded-2xl border border-dashed border-white/10 py-14 text-center text-xs text-slate-600"><Sparkles className="mx-auto mb-2 h-5 w-5" />No persisted workflow definitions.</div>}
        </div>
      </div>
    </section>
  );
}
