'use client';

import { useEffect, useState } from 'react';
import { fetchStats } from '../lib/api';
import { Stats } from '../lib/types';

export default function AnalyticsPage() {
  const [stats, setStats] = useState<Stats | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetchStats()
      .then(setStats)
      .finally(() => setLoading(false));
  }, []);

  if (loading || !stats) {
    return <div className="p-8 animate-pulse">Loading analytics...</div>;
  }

  return (
    <div className="space-y-8 animate-in fade-in duration-500">
      <div>
        <h1 className="text-2xl font-semibold text-zinc-900 tracking-tight">Analytics</h1>
        <p className="text-sm text-zinc-500 mt-1">Performance and cost tracking across councils.</p>
      </div>

      <div className="bg-white rounded-lg border border-zinc-200 overflow-hidden shadow-sm">
        <div className="px-6 py-4 border-b border-zinc-200">
          <h2 className="text-sm font-semibold text-zinc-900">Council Performance</h2>
        </div>
        <table className="w-full text-sm text-left">
          <thead className="text-xs text-zinc-500 bg-zinc-50 uppercase tracking-wider">
            <tr>
              <th className="px-6 py-3 font-medium">Council</th>
              <th className="px-6 py-3 font-medium">Tasks Executed</th>
              <th className="px-6 py-3 font-medium">Avg Confidence</th>
              <th className="px-6 py-3 font-medium text-right">Total Cost</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-zinc-200">
            {Object.entries(stats.councils || {}).map(([name, data]) => (
              <tr key={name} className="hover:bg-zinc-50 transition-colors">
                <td className="px-6 py-4 font-medium capitalize text-zinc-900">{name}</td>
                <td className="px-6 py-4 text-zinc-600">{data.tasks}</td>
                <td className="px-6 py-4 text-zinc-600">
                  <div className="flex items-center space-x-2">
                    <span className={data.avg_confidence > 0.8 ? 'text-green-600' : 'text-amber-600'}>
                      {(data.avg_confidence * 100).toFixed(1)}%
                    </span>
                    <div className="w-16 h-1.5 bg-zinc-100 rounded-full overflow-hidden">
                      <div className="h-full bg-blue-500" style={{ width: `${data.avg_confidence * 100}%` }} />
                    </div>
                  </div>
                </td>
                <td className="px-6 py-4 text-right font-medium text-zinc-700">
                  ${data.cost.toFixed(2)}
                </td>
              </tr>
            ))}
            {Object.keys(stats.councils || {}).length === 0 && (
              <tr>
                <td colSpan={4} className="px-6 py-8 text-center text-zinc-500">
                  No council data available yet.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
