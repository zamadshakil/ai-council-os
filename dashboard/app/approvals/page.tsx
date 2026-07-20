'use client';

import { useEffect, useState } from 'react';
import { TaskCard } from '../components/task-card';
import { fetchTasks } from '../lib/api';
import { Task } from '../lib/types';

export default function ApprovalsPage() {
  const [tasks, setTasks] = useState<Task[]>([]);
  const [loading, setLoading] = useState(true);
  const [filter, setFilter] = useState<'all' | 'awaiting_approval' | 'approved' | 'rejected'>('awaiting_approval');

  useEffect(() => {
    async function loadTasks() {
      setLoading(true);
      try {
        const data = await fetchTasks(filter === 'all' ? undefined : filter);
        setTasks(data);
      } catch (error) {
        console.error('Failed to fetch tasks', error);
      } finally {
        setLoading(false);
      }
    }
    loadTasks();
  }, [filter]);

  return (
    <div className="space-y-8 animate-in fade-in duration-500">
      <div>
        <h1 className="text-2xl font-semibold text-zinc-900 tracking-tight">Approval Queue</h1>
        <p className="text-sm text-zinc-500 mt-1">Review and manage council outputs.</p>
      </div>

      <div className="flex space-x-1 border-b border-zinc-200 pb-px">
        {[
          { id: 'all', label: 'All Tasks' },
          { id: 'awaiting_approval', label: 'Pending' },
          { id: 'approved', label: 'Approved' },
          { id: 'rejected', label: 'Rejected' },
        ].map((tab) => (
          <button
            key={tab.id}
            onClick={() => setFilter(tab.id as any)}
            className={`px-4 py-2 text-sm font-medium border-b-2 transition-colors ${
              filter === tab.id
                ? 'border-blue-600 text-blue-600'
                : 'border-transparent text-zinc-500 hover:text-zinc-700 hover:border-zinc-300'
            }`}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {loading ? (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
          {[1,2,3,4,5,6].map(i => <div key={i} className="h-48 bg-zinc-100 rounded-lg animate-pulse"></div>)}
        </div>
      ) : tasks.length > 0 ? (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
          {tasks.map((task) => (
            <TaskCard key={task.task_id} task={task} />
          ))}
        </div>
      ) : (
        <div className="py-24 text-center bg-white border border-zinc-200 rounded-lg border-dashed">
          <p className="text-zinc-500">No tasks found for this filter.</p>
        </div>
      )}
    </div>
  );
}
