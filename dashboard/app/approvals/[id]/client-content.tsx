'use client';

import { useState } from 'react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { fetchTask, approveTask } from '../../lib/api';
import { ArrowLeft, Check, X, Clock, Target, DollarSign, RotateCcw } from 'lucide-react';
import { DebateTrace } from '../../components/debate-trace';
import { Task } from '../../lib/types';
import { formatDistanceToNow } from 'date-fns';

export function TaskDetailContent({ id }: { id: string }) {
  const router = useRouter();
  const [task, setTask] = useState<Task | null>(null);
  const [feedback, setFeedback] = useState('');
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [loading, setLoading] = useState(true);

  // Using useEffect instead of async server component due to PPR issues with client components internally
  useState(() => {
    fetchTask(id)
      .then(setTask)
      .finally(() => setLoading(false));
  });

  if (loading || !task) {
    return <div className="p-8 animate-pulse text-zinc-400">Loading task details...</div>;
  }

  const handleAction = async (approved: boolean) => {
    setIsSubmitting(true);
    try {
      await approveTask(id, { approved, notes: feedback });
      router.push('/approvals');
    } catch (error) {
      console.error('Failed to submit approval', error);
      setIsSubmitting(false);
    }
  };

  const confidenceColor = task.confidence_score >= 80 ? 'text-[#10B981]' : task.confidence_score >= 60 ? 'text-[#F59E0B]' : 'text-[#F43F5E]';

  return (
    <div className="space-y-8 animate-in fade-in duration-700 ease-out fill-mode-both pb-20 max-w-[1200px] mx-auto">
      
      <div className="flex items-center justify-between mb-8">
        <div>
          <Link href="/approvals" className="inline-flex items-center text-[13px] font-bold text-zinc-400 hover:text-[#111827] mb-4 transition-colors uppercase tracking-wider">
            <ArrowLeft className="w-4 h-4 mr-1.5" /> Back to Queue
          </Link>
          <div className="flex items-center space-x-4">
            <h1 className="text-[32px] font-bold text-[#111827] tracking-tight leading-none">Task Details</h1>
            <span className={`px-4 py-1.5 rounded-full text-[12px] font-bold uppercase tracking-wider shadow-sm ${
              task.status === 'awaiting_approval' ? 'bg-amber-100 text-amber-700' :
              task.status === 'approved' ? 'bg-emerald-100 text-emerald-700' :
              'bg-zinc-100 text-zinc-700'
            }`}>
              {task.status.replace('_', ' ')}
            </span>
          </div>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-12">
        <div className="lg:col-span-2 space-y-8">
          
          <div className="bg-white p-10 rounded-[32px] shadow-[0_8px_30px_rgb(0,0,0,0.03)] hover:shadow-[0_12px_40px_rgb(0,0,0,0.06)] transition-shadow duration-500">
            <h3 className="text-[16px] font-bold text-[#111827] mb-4 flex items-center">
              <Target className="w-5 h-5 mr-2 text-zinc-400" /> Original Request
            </h3>
            <p className="text-zinc-600 leading-relaxed text-[16px] p-6 bg-[#F8FAFC] rounded-[20px]">{task.task_description}</p>
          </div>
          
          <div className="bg-white p-10 rounded-[32px] shadow-[0_8px_30px_rgb(0,0,0,0.03)] hover:shadow-[0_12px_40px_rgb(0,0,0,0.06)] transition-shadow duration-500">
            <h3 className="text-[16px] font-bold text-[#111827] mb-4 flex items-center">
              <Check className="w-5 h-5 mr-2 text-zinc-400" /> Final Output
            </h3>
            <div className="prose prose-zinc max-w-none text-[15px] p-6 bg-[#F8FAFC] rounded-[20px] whitespace-pre-wrap leading-relaxed shadow-inner">
              {task.final_output}
            </div>
          </div>

          {task.status === 'awaiting_approval' && (
            <div className="bg-white p-10 rounded-[32px] shadow-[0_12px_40px_rgb(37,99,235,0.08)] ring-1 ring-[#2563EB]/10 transition-shadow duration-500">
              <h3 className="text-[18px] font-bold text-[#111827] mb-4">Approval Decision</h3>
              <textarea
                value={feedback}
                onChange={(e) => setFeedback(e.target.value)}
                placeholder="Add feedback for the council (optional)..."
                className="w-full text-[16px] p-6 bg-[#F8FAFC] rounded-[20px] mb-6 focus:ring-2 focus:ring-[#2563EB] focus:bg-white outline-none transition-all duration-300 resize-none min-h-[120px]"
              />
              <div className="flex space-x-4">
                <button
                  onClick={() => handleAction(false)}
                  disabled={isSubmitting}
                  className="flex-1 flex items-center justify-center px-6 py-4 bg-zinc-100 text-zinc-600 rounded-[16px] hover:bg-zinc-200 hover:text-zinc-900 font-bold text-[15px] transition-all duration-300"
                >
                  <X className="w-5 h-5 mr-2" /> Reject Output
                </button>
                <button
                  onClick={() => handleAction(true)}
                  disabled={isSubmitting}
                  className="flex-[2] flex items-center justify-center px-6 py-4 bg-[#111827] text-white rounded-[16px] shadow-[0_8px_20px_rgb(0,0,0,0.15)] hover:bg-[#1f2937] hover:-translate-y-0.5 active:scale-95 font-bold text-[15px] transition-all duration-300"
                >
                  <Check className="w-5 h-5 mr-2" /> Approve & Deploy
                </button>
              </div>
            </div>
          )}
        </div>

        <div className="space-y-8">
          <div className="bg-white p-8 rounded-[32px] shadow-[0_8px_30px_rgb(0,0,0,0.03)]">
            <h3 className="text-[16px] font-bold text-[#111827] mb-6">Execution Metrics</h3>
            <div className="space-y-5 text-[14px]">
              <div className="flex justify-between items-center p-4 bg-[#F8FAFC] rounded-[16px]">
                <span className="text-zinc-500 font-medium flex items-center"><Target className="w-4 h-4 mr-2" /> Council</span>
                <span className="font-bold uppercase tracking-wide text-xs text-[#2563EB]">{task.council}</span>
              </div>
              <div className="flex justify-between items-center p-4 bg-[#F8FAFC] rounded-[16px]">
                <span className="text-zinc-500 font-medium flex items-center"><DollarSign className="w-4 h-4 mr-2" /> Cost</span>
                <span className="font-bold text-[#111827]">${task.total_cost_usd.toFixed(4)}</span>
              </div>
              <div className="flex justify-between items-center p-4 bg-[#F8FAFC] rounded-[16px]">
                <span className="text-zinc-500 font-medium flex items-center"><RotateCcw className="w-4 h-4 mr-2" /> Iterations</span>
                <span className="font-bold text-[#111827]">{task.iterations}</span>
              </div>
              <div className="flex justify-between items-center p-4 bg-[#F8FAFC] rounded-[16px]">
                <span className="text-zinc-500 font-medium flex items-center"><Clock className="w-4 h-4 mr-2" /> Confidence</span>
                <span className={`font-bold ${confidenceColor}`}>{task.confidence_score.toFixed(1)}%</span>
              </div>
              <div className="text-center pt-2">
                 <span className="text-[12px] font-semibold text-zinc-400">Created {formatDistanceToNow(new Date(task.created_at))} ago</span>
              </div>
            </div>
          </div>

          <div className="bg-white p-8 rounded-[32px] shadow-[0_8px_30px_rgb(0,0,0,0.03)]">
            <h3 className="text-[16px] font-bold text-[#111827] mb-6">Debate Trace</h3>
            <DebateTrace history={task.debate_history} />
          </div>
        </div>
      </div>
    </div>
  );
}
