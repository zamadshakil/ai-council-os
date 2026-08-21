'use client';

import { useState } from 'react';
import { Bot, CheckCircle2, ChevronLeft, ChevronRight, MessageSquareWarning, Sparkles } from 'lucide-react';
import { DebateMessage } from '../lib/types';
import { StructuredMessageView } from './structured-output';

function roleLabel(role: DebateMessage['role']) {
  if (role === 'critic') return 'Critique';
  if (role === 'synthesizer') return 'Synthesis';
  return 'Draft';
}

export function DebateTrace({ messages }: { messages: DebateMessage[] }) {
  const [selected, setSelected] = useState(Math.max(0, messages.length - 1));

  if (messages.length === 0) {
    return <p className="rounded-xl border border-dashed border-white/10 p-6 text-center text-sm text-slate-500">No model steps have been recorded yet.</p>;
  }

  const safeIndex = Math.min(selected, messages.length - 1);
  const message = messages[safeIndex];
  const Icon = message.role === 'critic' ? MessageSquareWarning : message.role === 'synthesizer' ? Sparkles : Bot;

  return (
    <div>
      <div className="overflow-x-auto pb-2" aria-label="Model execution steps">
        <ol className="flex min-w-max gap-2">
          {messages.map((step, index) => {
            const active = index === safeIndex;
            return (
              <li key={`${step.timestamp}-${index}`}>
                <button
                  type="button"
                  onClick={() => setSelected(index)}
                  aria-current={active ? 'step' : undefined}
                  className={`flex min-h-11 items-center gap-2 rounded-xl border px-3 text-left transition ${active ? 'border-cyan-300/45 bg-cyan-300/12 text-cyan-100 shadow-[0_0_20px_rgba(34,211,238,0.08)]' : 'border-white/8 bg-white/[0.025] text-slate-400 hover:border-white/15 hover:text-slate-200'}`}
                >
                  <span className={`grid h-6 w-6 place-items-center rounded-full text-[10px] font-black ${active ? 'bg-cyan-300 text-[#04111b]' : 'bg-white/8 text-slate-400'}`}>{index + 1}</span>
                  <span><span className="block text-xs font-bold">{roleLabel(step.role)}</span><span className="block max-w-32 truncate text-[10px] opacity-65">{step.model}</span></span>
                </button>
              </li>
            );
          })}
        </ol>
      </div>

      <article className="mt-3 overflow-hidden rounded-2xl border border-white/10 bg-[#071422]/70">
        <header className="flex flex-wrap items-center justify-between gap-3 border-b border-white/8 px-4 py-3">
          <div className="flex items-center gap-2">
            <Icon className="h-4 w-4 text-cyan-300" />
            <span className="text-sm font-bold text-slate-100">{roleLabel(message.role)}</span>
            <code className="rounded bg-white/5 px-2 py-0.5 text-[10px] text-slate-500">{message.model}</code>
          </div>
          <div className="flex items-center gap-2">
            <span className="hidden text-xs text-slate-600 sm:inline">{new Date(message.timestamp).toLocaleString()}</span>
            <button type="button" disabled={safeIndex === 0} onClick={() => setSelected((value) => Math.max(0, value - 1))} className="grid h-8 w-8 place-items-center rounded-lg border border-white/10 text-slate-400 disabled:opacity-25" aria-label="Previous model step"><ChevronLeft className="h-4 w-4" /></button>
            <span className="min-w-12 text-center text-xs font-bold text-slate-400">{safeIndex + 1}/{messages.length}</span>
            <button type="button" disabled={safeIndex === messages.length - 1} onClick={() => setSelected((value) => Math.min(messages.length - 1, value + 1))} className="grid h-8 w-8 place-items-center rounded-lg border border-white/10 text-slate-400 disabled:opacity-25" aria-label="Next model step"><ChevronRight className="h-4 w-4" /></button>
          </div>
        </header>
        <div className="max-h-[38rem] overflow-y-auto p-4">
          <StructuredMessageView message={message} />
          {message.score_breakdown && (
            <div className="mt-4 flex flex-wrap gap-2">
              {Object.entries(message.score_breakdown).map(([name, score]) => (
                <span key={name} className="inline-flex items-center gap-1 rounded-full bg-white/5 px-2.5 py-1 text-xs font-medium text-slate-400">
                  <CheckCircle2 className="h-3 w-3 text-emerald-300" /> {name.replaceAll('_', ' ')}: {score}
                </span>
              ))}
            </div>
          )}
        </div>
      </article>
    </div>
  );
}
