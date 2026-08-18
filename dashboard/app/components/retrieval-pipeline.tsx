'use client';

import { motion } from 'framer-motion';
import { BookOpenCheck, FileSearch, GitMerge, Quote, Sparkles } from 'lucide-react';

const STAGES = [
  { label: 'Scoped sources', helper: 'Selected evidence only', icon: BookOpenCheck },
  { label: 'Hybrid retrieval', helper: 'Semantic + keyword', icon: FileSearch },
  { label: 'Fusion & rerank', helper: 'RRF + relevance pass', icon: GitMerge },
  { label: 'Cited context', helper: 'Traceable passages', icon: Quote },
];

export function RetrievalPipeline({ searching, sourceCount, chunkCount }: { searching: boolean; sourceCount: number; chunkCount: number }) {
  return (
    <section className="retrieval-shell surface-card rounded-[28px] p-5 lg:p-6" aria-labelledby="retrieval-title">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <p className="eyebrow">Retrieval path</p>
          <h2 id="retrieval-title" className="mt-1 text-lg font-extrabold text-slate-100">How evidence reaches the council</h2>
        </div>
        <span className="topology-legend"><Sparkles className={`h-3.5 w-3.5 ${searching ? 'text-cyan-300' : 'text-slate-600'}`} />{searching ? 'Retrieval in progress' : `${sourceCount} sources · ${chunkCount} passages`}</span>
      </div>
      <div className="retrieval-track mt-6 grid gap-3 md:grid-cols-4">
        {STAGES.map((stage, index) => {
          const Icon = stage.icon;
          return (
            <div key={stage.label} className="retrieval-stage relative rounded-2xl p-4">
              {index < STAGES.length - 1 && <span className="retrieval-connector" aria-hidden="true" />}
              {searching && index < STAGES.length - 1 && (
                <motion.span
                  aria-hidden="true"
                  className="retrieval-pulse"
                  initial={{ left: '74%', opacity: 0 }}
                  animate={{ left: ['74%', '112%'], opacity: [0, 1, 0] }}
                  transition={{ duration: 1.15, repeat: Infinity, ease: 'linear', delay: index * 0.22 }}
                />
              )}
              <span className="grid h-9 w-9 place-items-center rounded-xl border border-cyan-300/15 bg-cyan-300/7 text-cyan-300"><Icon className="h-4 w-4" /></span>
              <p className="mt-4 text-sm font-extrabold text-slate-200">{stage.label}</p>
              <p className="mt-1 text-[11px] text-slate-500">{stage.helper}</p>
            </div>
          );
        })}
      </div>
    </section>
  );
}
