'use client';

import { useEffect, useMemo, useState } from 'react';
import { fetchTasks } from '../lib/api';
import { CouncilName, Task } from '../lib/types';

const COUNCILS: CouncilName[] = ['grant', 'sales', 'content'];

export default function AnalyticsPage() {
  const [tasks, setTasks] = useState<Task[]>([]);
  const [error, setError] = useState('');

  useEffect(() => {
    void fetchTasks().then(setTasks).catch((loadError: unknown) => setError(loadError instanceof Error ? loadError.message : 'Unable to load history.'));
  }, []);

  const scored = useMemo(() => tasks.filter((task) => task.confidence_score !== null), [tasks]);
  const totalCost = useMemo(() => tasks.reduce((sum, task) => sum + task.total_cost_usd, 0), [tasks]);
  const costsComplete = useMemo(() => tasks.every((task) => task.cost_metrics_complete), [tasks]);
  const averageScore = scored.length ? scored.reduce((sum, task) => sum + (task.confidence_score ?? 0), 0) / scored.length : null;
  const published = tasks.filter((task) => task.status === 'published').length;

  return (
    <div className="space-y-7 pb-16">
      <div><p className="eyebrow">Evidence, not estimates</p><h1 className="mt-2 text-3xl font-black tracking-tight text-slate-50">History & analytics</h1><p className="mt-2 text-sm text-slate-400">Metrics are calculated from persisted task records. Missing scores and incomplete costs stay visibly unavailable.</p></div>
      {error && <p role="alert" className="rounded-xl border border-rose-300/20 bg-rose-400/8 p-4 text-sm text-rose-200">{error}</p>}
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        {[['Total runs', tasks.length.toString()], ['Published', published.toString()], ['Recorded cost', costsComplete ? `$${totalCost.toFixed(4)}` : 'Partial'], ['Average score', averageScore === null ? 'Unavailable' : averageScore.toFixed(1)]].map(([label, value]) => (
          <div key={label} className="surface-card rounded-2xl p-5"><p className="text-xs font-bold uppercase tracking-wide text-slate-500">{label}</p><p className="mt-2 text-2xl font-black text-slate-50">{value}</p></div>
        ))}
      </div>
      <div className="grid gap-4 md:grid-cols-3">
        {COUNCILS.map((council) => {
          const councilTasks = tasks.filter((task) => task.council === council);
          const councilCost = councilTasks.reduce((sum, task) => sum + task.total_cost_usd, 0);
          const complete = councilTasks.every((task) => task.cost_metrics_complete);
          return <div key={council} className="surface-card rounded-2xl p-5"><h2 className="font-bold capitalize text-slate-100">{council} Council</h2><p className="mt-3 text-sm text-slate-500">{councilTasks.length} runs · {complete ? `$${councilCost.toFixed(4)}` : 'cost partial'}</p></div>;
        })}
      </div>
      <section className="surface-card overflow-hidden rounded-2xl">
        <div className="border-b border-white/8 p-5"><h2 className="font-bold text-slate-100">Task history</h2></div>
        {tasks.length === 0 ? <p className="p-10 text-center text-sm text-slate-500">No persisted task history.</p> : (
          <div className="divide-y divide-white/8">{tasks.map((task) => (
            <div key={task.task_id} className="grid gap-2 p-5 text-sm md:grid-cols-[8rem_1fr_10rem_7rem] md:items-center">
              <span className="font-semibold capitalize text-slate-300">{task.council}</span><span className="truncate text-slate-300">{task.task_description}</span><span className="capitalize text-slate-500">{task.status.replaceAll('_', ' ')}</span><span className="text-right font-mono text-xs text-slate-500">{task.cost_metrics_complete ? `$${task.total_cost_usd.toFixed(4)}` : 'partial'}</span>
            </div>
          ))}</div>
        )}
      </section>
    </div>
  );
}
