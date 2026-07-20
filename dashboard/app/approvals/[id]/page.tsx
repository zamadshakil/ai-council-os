'use client';

import { useEffect, useState } from 'react';
import { useParams, useRouter } from 'next/navigation';
import { fetchTask, approveTask } from '../../lib/api';
import { Task } from '../../lib/types';
import { DebateTrace } from '../../components/debate-trace';
import { ArrowLeft, Check, X } from 'lucide-react';
import Link from 'next/link';

export default function TaskDetail() {
  const { id } = useParams();
  const router = useRouter();
  const [task, setTask] = useState<Task | null>(null);
  const [loading, setLoading] = useState(true);
  const [feedback, setFeedback] = useState('');
  const [isSubmitting, setIsSubmitting] = useState(false);

  useEffect(() => {
    async function loadTask() {
      try {
        const data = await fetchTask(id as string);
        setTask(data);
      } catch (error) {
        console.error('Failed to load task', error);
      } finally {
        setLoading(false);
      }
    }
    loadTask();
  }, [id]);

  const handleAction = async (approved: boolean) => {
    setIsSubmitting(true);
    try {
      await approveTask(id as string, { approved, feedback });
      router.push('/approvals');
    } catch (error) {
      console.error('Failed to approve/reject task', error);
      setIsSubmitting(false);
    }
  };

  if (loading || !task) return <div className="p-8 animate-pulse">Loading task details...</div>;

  return (
    <div className="space-y-6 animate-in fade-in duration-500">
      <div>
        <Link href="/approvals" className="inline-flex items-center text-sm text-zinc-500 hover:text-zinc-900 mb-4 transition-colors">
          <ArrowLeft className="w-4 h-4 mr-1" /> Back to Queue
        </Link>
        <div className="flex items-center justify-between">
          <h1 className="text-2xl font-semibold text-zinc-900 tracking-tight">Task Details</h1>
          <span className={`px-2.5 py-1 rounded-full text-xs font-medium border uppercase ${
            task.status === 'awaiting_approval' ? 'bg-amber-100 text-amber-700 border-amber-200' :
            task.status === 'approved' ? 'bg-green-100 text-green-700 border-green-200' :
            'bg-zinc-100 text-zinc-700 border-zinc-200'
          }`}>
            {task.status.replace('_', ' ')}
          </span>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-8">
        <div className="lg:col-span-2 space-y-6">
          <div className="bg-white p-6 rounded-lg border border-zinc-200 shadow-sm">
            <h3 className="text-sm font-medium text-zinc-500 mb-2">Description</h3>
            <p className="text-zinc-900">{task.task_description}</p>
          </div>
          
          <div className="bg-white p-6 rounded-lg border border-zinc-200 shadow-sm">
            <h3 className="text-sm font-medium text-zinc-500 mb-4">Final Output</h3>
            <div className="prose prose-sm max-w-none text-zinc-800 p-4 bg-zinc-50 rounded border border-zinc-100 whitespace-pre-wrap">
              {task.final_output}
            </div>
          </div>

          {task.status === 'awaiting_approval' && (
            <div className="bg-white p-6 rounded-lg border border-blue-200 shadow-sm bg-blue-50/30">
              <h3 className="text-sm font-medium text-zinc-900 mb-2">Approval Decision</h3>
              <textarea
                value={feedback}
                onChange={(e) => setFeedback(e.target.value)}
                placeholder="Optional feedback..."
                className="w-full text-sm p-3 border border-zinc-300 rounded-md mb-4 focus:ring-2 focus:ring-blue-500 focus:border-blue-500 outline-none"
                rows={3}
              />
              <div className="flex space-x-3">
                <button
                  onClick={() => handleAction(false)}
                  disabled={isSubmitting}
                  className="flex items-center px-4 py-2 border border-red-200 text-red-600 bg-white rounded-md hover:bg-red-50 font-medium text-sm transition-colors"
                >
                  <X className="w-4 h-4 mr-2" /> Reject
                </button>
                <button
                  onClick={() => handleAction(true)}
                  disabled={isSubmitting}
                  className="flex items-center px-4 py-2 bg-blue-600 text-white rounded-md hover:bg-blue-700 font-medium text-sm transition-colors"
                >
                  <Check className="w-4 h-4 mr-2" /> Approve
                </button>
              </div>
            </div>
          )}
        </div>

        <div className="space-y-6">
          <div className="bg-white p-5 rounded-lg border border-zinc-200 shadow-sm">
            <h3 className="text-sm font-medium text-zinc-900 mb-4 border-b border-zinc-100 pb-2">Execution Metrics</h3>
            <div className="space-y-3 text-sm">
              <div className="flex justify-between">
                <span className="text-zinc-500">Council</span>
                <span className="font-medium capitalize text-zinc-900">{task.council}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-zinc-500">Cost</span>
                <span className="font-medium text-zinc-900">${task.total_cost_usd.toFixed(4)}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-zinc-500">Iterations</span>
                <span className="font-medium text-zinc-900">{task.iterations}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-zinc-500">Confidence</span>
                <span className="font-medium text-green-600">{task.confidence_score.toFixed(1)}%</span>
              </div>
            </div>
          </div>

          <div className="bg-white p-5 rounded-lg border border-zinc-200 shadow-sm">
            <h3 className="text-sm font-medium text-zinc-900 mb-4 border-b border-zinc-100 pb-2">Debate Trace</h3>
            <DebateTrace history={task.debate_history} />
          </div>
        </div>
      </div>
    </div>
  );
}
