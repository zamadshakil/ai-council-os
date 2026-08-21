'use client';

import { useState } from 'react';
import { Check, Clipboard, ExternalLink } from 'lucide-react';
import { DebateMessage } from '../lib/types';

const PLATFORM_CONFIG = [
  ['twitter', 'X', 280],
  ['linkedin', 'LinkedIn', 3000],
  ['facebook', 'Facebook', 2000],
  ['instagram', 'Instagram', 2200],
  ['reddit', 'Reddit', 10000],
  ['discord', 'Discord', 2000],
] as const;

export type PlatformKey = typeof PLATFORM_CONFIG[number][0];
export type ContentVariants = Record<PlatformKey, string>;

function record(value: unknown): Record<string, unknown> | null {
  return value && typeof value === 'object' && !Array.isArray(value)
    ? value as Record<string, unknown>
    : null;
}

function stringList(value: unknown): string[] {
  return Array.isArray(value) ? value.filter((item): item is string => typeof item === 'string') : [];
}

export function readContentVariants(value: unknown): ContentVariants | null {
  let candidate = value;
  if (typeof candidate === 'string') {
    try { candidate = JSON.parse(candidate); } catch { return null; }
  }
  const data = record(candidate);
  if (!data) return null;
  const normalized: Record<string, unknown> = { ...data, twitter: data.twitter ?? data.x };
  if (!PLATFORM_CONFIG.every(([key]) => typeof normalized[key] === 'string')) return null;
  return Object.fromEntries(
    PLATFORM_CONFIG.map(([key]) => [key, String(normalized[key])]),
  ) as ContentVariants;
}

function CopyButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false);
  async function copy() {
    await navigator.clipboard.writeText(text);
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1500);
  }
  return (
    <button type="button" onClick={() => void copy()} className="inline-flex min-h-9 items-center gap-1.5 rounded-lg border border-white/10 px-2.5 text-xs font-bold text-slate-300 hover:border-cyan-300/30 hover:text-cyan-200" aria-label="Copy platform post">
      {copied ? <Check className="h-3.5 w-3.5 text-emerald-300" /> : <Clipboard className="h-3.5 w-3.5" />}
      {copied ? 'Copied' : 'Copy'}
    </button>
  );
}

export function ContentVariantGrid({ variants, editable = false, onChange }: { variants: ContentVariants; editable?: boolean; onChange?: (next: ContentVariants) => void }) {
  return (
    <div className="grid gap-4 lg:grid-cols-2">
      {PLATFORM_CONFIG.map(([key, label, limit]) => {
        const text = variants[key];
        const overLimit = text.length > limit;
        return (
          <article key={key} className="overflow-hidden rounded-2xl border border-white/10 bg-[#071422]/70">
            <header className="flex items-center justify-between gap-3 border-b border-white/8 px-4 py-3">
              <div>
                <p className="font-bold text-slate-100">{label}</p>
                <p className={`mt-0.5 text-xs ${overLimit ? 'text-rose-300' : 'text-slate-500'}`}>{text.length.toLocaleString()} / {limit.toLocaleString()} characters</p>
              </div>
              <CopyButton text={text} />
            </header>
            {editable ? (
              <textarea
                aria-label={`${label} post`}
                value={text}
                maxLength={limit}
                onChange={(event) => onChange?.({ ...variants, [key]: event.target.value })}
                className="min-h-56 w-full resize-y bg-transparent p-4 text-sm leading-6 text-slate-200 outline-none focus:bg-cyan-300/[0.025]"
              />
            ) : (
              <p className="whitespace-pre-wrap p-4 text-sm leading-6 text-slate-300">{text}</p>
            )}
          </article>
        );
      })}
    </div>
  );
}

function CritiqueSummary({ output }: { output: Record<string, unknown> }) {
  const strengths = stringList(output.strengths);
  const weaknesses = stringList(output.weaknesses);
  const edits = stringList(output.required_edits);
  return (
    <div className="grid gap-3 md:grid-cols-3">
      {[
        ['What works', strengths, 'text-emerald-200'],
        ['What needs work', weaknesses, 'text-amber-200'],
        ['Required changes', edits, 'text-cyan-200'],
      ].map(([title, items, color]) => (
        <section key={title as string} className="rounded-xl border border-white/8 bg-white/[0.025] p-4">
          <h4 className={`text-xs font-black uppercase tracking-wide ${color}`}>{title as string}</h4>
          {(items as string[]).length ? <ul className="mt-2 space-y-2 text-xs leading-5 text-slate-300">{(items as string[]).map((item, index) => <li key={`${item}-${index}`}>• {item}</li>)}</ul> : <p className="mt-2 text-xs text-slate-500">Nothing recorded.</p>}
        </section>
      ))}
    </div>
  );
}

export function StructuredMessageView({ message }: { message: DebateMessage }) {
  const output = record(message.structured_output);
  const variants = readContentVariants(output ?? message.content);
  const prose = output && typeof output.content === 'string' ? output.content : '';
  const isCritique = message.role === 'critic' && output;

  return (
    <div className="mt-3">
      {variants ? <ContentVariantGrid variants={variants} /> : isCritique ? <CritiqueSummary output={output} /> : prose ? <p className="whitespace-pre-wrap text-sm leading-6 text-slate-300">{prose}</p> : <p className="whitespace-pre-wrap text-sm leading-6 text-slate-300">{message.content}</p>}
      {output && (
        <details className="mt-3 rounded-lg border border-white/8 bg-black/10 px-3 py-2 text-xs text-slate-500">
          <summary className="flex cursor-pointer list-none items-center gap-2 font-semibold hover:text-slate-300"><ExternalLink className="h-3.5 w-3.5" /> Technical details</summary>
          <pre className="mt-3 max-h-72 overflow-auto whitespace-pre-wrap break-words text-[11px] leading-5">{JSON.stringify(output, null, 2)}</pre>
        </details>
      )}
    </div>
  );
}
