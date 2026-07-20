'use client';

import { useEffect, useState } from 'react';
import { StatsCard } from './components/stats-card';
import { TaskCard } from './components/task-card';
import { fetchStats, fetchTasks } from './lib/api';
import { Stats, Task } from './lib/types';
import { Clock, CheckCircle2, DollarSign, Activity } from 'lucide-react';

export default function Overview() {
  const [stats, setStats] = useState<Stats | null>(null);
  const [pendingTasks, setPendingTasks] = useState<Task[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    async function loadData() {
      try {
        const [statsData, tasksData] = await Promise.all([
          fetchStats(),
          fetchTasks('awaiting_approval'),
        ]);
        setStats(statsData);
        setPendingTasks(tasksData.slice(0, 4));
      } catch (error) {
        console.error('Failed to load overview data', error);
      } finally {
        setLoading(false);
      }
    }
    loadData();
  }, []);

  if (loading) {
    return <div className="animate-pulse space-y-8">
      <div className="h-8 w-48 bg-zinc-200 rounded"></div>
      <div className="grid grid-cols-4 gap-6">
        {[1,2,3,4].map(i => <div key={i} className="h-32 bg-zinc-200 rounded-lg"></div>)}
      </div>
    </div>;
  }

  return (
    <div className="space-y-8 animate-in fade-in duration-500">
      <div>
        <h1 className="text-2xl font-semibold text-zinc-900 tracking-tight">Overview</h1>
        <p className="text-sm text-zinc-500 mt-1">System status and pending actions.</p>
      </div>

      {stats && (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6">
          <StatsCard
            title="Pending Approvals"
            value={stats.pending}
            icon={<Clock className="w-5 h-5" />}
          />
          <StatsCard
            title="Tasks Approved"
            value={stats.approved}
            icon={<CheckCircle2 className="w-5 h-5 text-green-600" />}
          />
          <StatsCard
            title="Total Cost"
            value={`$${stats.total_cost_usd.toFixed(2)}`}
            icon={<DollarSign className="w-5 h-5" />}
          />
          <StatsCard
            title="Avg Confidence"
            value={`${stats.avg_confidence.toFixed(1)}%`}
            icon={<Activity className="w-5 h-5 text-blue-600" />}
          />
        </div>
      )}

      <div>
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-lg font-semibold text-zinc-900">Recent Pending Approvals</h2>
        </div>
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
          {pendingTasks.map((task) => (
            <TaskCard key={task.task_id} task={task} />
          ))}
          {pendingTasks.length === 0 && (
            <div className="col-span-full py-12 text-center text-zinc-500 bg-white rounded-lg border border-zinc-200 border-dashed">
              No pending tasks to approve.
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
