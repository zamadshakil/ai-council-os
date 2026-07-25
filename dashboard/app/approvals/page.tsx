'use client';

import { useState, useEffect, useCallback } from 'react';
import { TaskCard } from '../components/task-card';
import { fetchTasks } from '../lib/api';
import { Task } from '../lib/types';
import { Loader2 } from 'lucide-react';

const TABS = [
  { id: 'all', label: 'All Tasks' },
  { id: 'awaiting_approval', label: 'Pending' },
  { id: 'approved', label: 'Approved' },
  { id: 'rejected', label: 'Rejected' },
];

export default function ApprovalsPage() {
  const [filter, setFilter] = useState('awaiting_approval');
  const [tasks, setTasks] = useState<Task[]>([]);
  const [loading, setLoading] = useState(true);

  const loadTasks = useCallback(async () => {
    try {
      // Fetch all tasks and filter in memory so pending/debating tasks also show up
      const data = await fetchTasks();
      let filtered = data;

      if (filter === 'awaiting_approval') {
        filtered = data.filter(t => 
          t.status === 'awaiting_approval' || 
          t.status === 'pending' || 
          t.status === 'generating' || 
          t.status === 'critiquing' || 
          t.status === 'refining'
        );
      } else if (filter !== 'all') {
        filtered = data.filter(t => t.status === filter);
      }

      setTasks(filtered);
    } catch (err) {
      console.error('Failed to fetch tasks:', err);
    } finally {
      setLoading(false);
    }
  }, [filter]);

  useEffect(() => {
    setLoading(true);
    loadTasks();
  }, [loadTasks]);

  // Fast auto-refresh (every 3 seconds) when tasks are in progress/debating
  useEffect(() => {
    const hasActiveDebate = tasks.some(t => 
      t.status === 'pending' || t.status === 'generating' || t.status === 'critiquing' || t.status === 'refining'
    );
    const intervalTime = hasActiveDebate ? 3000 : 10000;
    const interval = setInterval(loadTasks, intervalTime);
    return () => clearInterval(interval);
  }, [tasks, loadTasks]);


  return (
    <div className="space-y-12 pb-20 animate-in fade-in duration-300 ease-out fill-mode-both">
      <div className="mb-8">
        <h1 className="text-[40px] font-bold text-[#111827] tracking-tight leading-none mb-3">Approval Queue</h1>
        <p className="text-[15px] text-zinc-500 font-medium">Review, edit, and approve/reject AI council outputs before they go live.</p>
      </div>

      <div className="flex space-x-2">
        {TABS.map((tab) => {
          const isActive = filter === tab.id;
          const count = tab.id === 'all' ? tasks.length : 
            tab.id === filter ? tasks.length : undefined;
          return (
            <button
              key={tab.id}
              onClick={() => setFilter(tab.id)}
              className={`px-5 py-2.5 text-[14px] font-bold rounded-full transition-all duration-200 active:scale-[0.98] ${
                isActive
                  ? 'bg-zinc-900 text-white shadow-md'
                  : 'bg-white text-zinc-600 hover:bg-zinc-100 hover:text-zinc-900 shadow-sm border border-zinc-200/80'
              }`}
            >
              {tab.label}
              {isActive && count !== undefined && (
                <span className="ml-2 text-[12px] opacity-70">{count}</span>
              )}
            </button>
          );
        })}
      </div>

      {loading ? (
        <div className="flex flex-col gap-4">
          {[1, 2, 3].map(i => (
            <div key={i} className="h-32 bg-zinc-200/50 rounded-[24px] animate-pulse" />
          ))}
        </div>
      ) : tasks.length === 0 ? (
        <div className="py-32 text-center bg-transparent rounded-[24px] border border-zinc-200/60 border-dashed">
          <p className="text-[15px] text-zinc-500 font-medium">No tasks found in this view.</p>
        </div>
      ) : (
        <div className="flex flex-col gap-4 animate-in fade-in duration-500">
          {tasks.map((task) => (
            <TaskCard key={task.task_id} task={task} onStatusChange={loadTasks} />
          ))}
        </div>
      )}
    </div>
  );
}
