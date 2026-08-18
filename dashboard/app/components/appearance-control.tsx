'use client';

import { Droplets } from 'lucide-react';
import { useEffect, useState } from 'react';

const STORAGE_KEY = 'council-os-reduce-transparency';

export function AppearanceControl() {
  const [reduced, setReduced] = useState(false);

  useEffect(() => {
    const stored = window.localStorage.getItem(STORAGE_KEY) === 'true';
    document.documentElement.toggleAttribute('data-reduce-transparency', stored);
    const frame = window.requestAnimationFrame(() => setReduced(stored));
    return () => window.cancelAnimationFrame(frame);
  }, []);

  function toggle() {
    const next = !reduced;
    setReduced(next);
    window.localStorage.setItem(STORAGE_KEY, String(next));
    document.documentElement.toggleAttribute('data-reduce-transparency', next);
  }

  return (
    <section className="surface-card flex flex-col justify-between gap-5 rounded-[22px] p-5 sm:flex-row sm:items-center">
      <div className="flex items-start gap-3">
        <span className="grid h-10 w-10 shrink-0 place-items-center rounded-[14px] border border-white/10 bg-white/5 text-cyan-200">
          <Droplets className="h-5 w-5" />
        </span>
        <div>
          <h2 className="font-bold text-slate-100">Visual comfort</h2>
          <p className="mt-1 max-w-2xl text-sm leading-6 text-slate-400">Turn off translucent materials if glass effects reduce readability or feel distracting. Motion also follows your device&apos;s Reduce Motion preference.</p>
        </div>
      </div>
      <button
        type="button"
        role="switch"
        aria-checked={reduced}
        onClick={toggle}
        className={`relative h-8 w-14 shrink-0 rounded-full border transition-colors ${reduced ? 'border-cyan-200/50 bg-cyan-300' : 'border-white/20 bg-white/8'}`}
      >
        <span className={`absolute left-0 top-1 h-6 w-6 rounded-full bg-white shadow-md transition-transform ${reduced ? 'translate-x-7' : 'translate-x-1'}`} />
        <span className="sr-only">Reduce transparency</span>
      </button>
    </section>
  );
}
