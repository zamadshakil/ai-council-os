'use client';

import { useState, useEffect, useCallback } from 'react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { fetchTask, approveTask, getTaskDocxExportUrl } from '../../lib/api';
import { ArrowLeft, Check, X, Clock, Target, DollarSign, RotateCcw, Loader2, Sparkles, FileDown } from 'lucide-react';
import { DebateTrace } from '../../components/debate-trace';
import { Task } from '../../lib/types';
import { formatDistanceToNow } from 'date-fns';

import { Toast } from '../../components/toast';

function parseTaskDate(dateStr: string): Date {
  if (!dateStr) return new Date();
  let s = dateStr.trim();
  if (!s.endsWith('Z') && !s.includes('+') && !s.includes('-', 10)) {
    s += 'Z';
  }
  const d = new Date(s);
  return isNaN(d.getTime()) ? new Date() : d;
}

export function TaskDetailContent({ id }: { id: string }) {
  const router = useRouter();
  const [task, setTask] = useState<Task | null>(null);
  const [feedback, setFeedback] = useState('');
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [loading, setLoading] = useState(true);
  const [fetchError, setFetchError] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const [toast, setToast] = useState<{ show: boolean; type?: 'success' | 'error' | 'info'; title: string; message?: string }>({
    show: false,
    title: '',
  });

  const showToast = (title: string, message?: string, type: 'success' | 'error' | 'info' = 'success') => {
    setToast({ show: true, type, title, message });
  };

  const loadTaskData = useCallback(async () => {
    try {
      const data = await fetchTask(id);
      if (data && data.task_id) {
        setTask(data);
        setFetchError(null);
      }
    } catch (err: any) {
      console.error('Failed to fetch task details:', err);
      setFetchError(err.message || 'Task not found or server busy.');
    } finally {
      setLoading(false);
    }
  }, [id]);

  useEffect(() => {
    loadTaskData();
  }, [loadTaskData]);

  // Fast auto-polling every 2 seconds while AI debate is active OR while task is initializing
  useEffect(() => {
    const isDebating = !task || task.status === 'pending' || task.status === 'generating' || task.status === 'critiquing' || task.status === 'refining';
    if (!isDebating) return;

    const interval = setInterval(loadTaskData, 2000);
    return () => clearInterval(interval);
  }, [task, loadTaskData]);

  if (loading && !task) {
    return (
      <div className="min-h-[400px] flex flex-col items-center justify-center gap-3 text-zinc-400">
        <Loader2 className="w-8 h-8 text-blue-600 animate-spin" />
        <p className="text-sm font-semibold">Loading task details...</p>
      </div>
    );
  }

  if (!task) {
    return (
      <div className="min-h-[400px] flex flex-col items-center justify-center gap-4 text-center max-w-md mx-auto p-8 bg-white rounded-3xl border border-zinc-200 shadow-sm my-12">
        <div className="w-12 h-12 rounded-full bg-amber-50 text-amber-600 flex items-center justify-center">
          <Loader2 className="w-6 h-6 animate-spin text-amber-600" />
        </div>
        <div>
          <h3 className="text-base font-bold text-zinc-900">Task Initializing...</h3>
          <p className="text-xs text-zinc-500 mt-1">
            {fetchError || 'Connecting to Council OS backend server. Stand by...'}
          </p>
        </div>
        <div className="flex gap-3">
          <button
            onClick={loadTaskData}
            className="px-4 py-2 bg-blue-600 hover:bg-blue-700 text-white font-semibold text-xs rounded-xl shadow-sm transition-all active:scale-95 cursor-pointer"
          >
            Retry Loading
          </button>
          <Link
            href="/approvals"
            className="px-4 py-2 bg-zinc-100 hover:bg-zinc-200 text-zinc-700 font-semibold text-xs rounded-xl transition-all active:scale-95"
          >
            Back to Queue
          </Link>
        </div>
      </div>
    );
  }

  const handleAction = async (approved: boolean) => {
    setIsSubmitting(true);
    try {
      await approveTask(id, { approved, notes: feedback });
      router.push('/approvals');
    } catch (error) {
      console.error('Failed to submit approval', error);
      setIsSubmitting(false);
      showToast('Action Failed', 'Could not update task approval status.', 'error');
    }
  };

  const isDebating = task.status === 'pending' || task.status === 'generating' || task.status === 'critiquing' || task.status === 'refining';
  const confidenceColor = task.confidence_score >= 80 ? 'text-[#10B981]' : task.confidence_score >= 60 ? 'text-[#F59E0B]' : 'text-[#F43F5E]';

  return (
    <div className="space-y-8 animate-in fade-in duration-700 ease-out fill-mode-both pb-20 max-w-[1200px] mx-auto">
      <Toast
        show={toast.show}
        type={toast.type}
        title={toast.title}
        message={toast.message}
        onClose={() => setToast((prev) => ({ ...prev, show: false }))}
      />
      
      <div className="flex items-center justify-between mb-8">
        <div>
          <Link href="/approvals" className="inline-flex items-center text-[13px] font-bold text-zinc-400 hover:text-[#111827] mb-4 transition-colors uppercase tracking-wider">
            <ArrowLeft className="w-4 h-4 mr-1.5" /> Back to Queue
          </Link>
          <div className="flex items-center space-x-4">
            <h1 className="text-[32px] font-bold text-[#111827] tracking-tight leading-none">Task Details</h1>
            <span className={`px-4 py-1.5 rounded-full text-[12px] font-bold uppercase tracking-wider shadow-sm flex items-center gap-2 ${
              isDebating ? 'bg-blue-100 text-blue-700 animate-pulse' :
              task.status === 'awaiting_approval' ? 'bg-amber-100 text-amber-700' :
              task.status === 'approved' ? 'bg-emerald-100 text-emerald-700' :
              'bg-zinc-100 text-zinc-700'
            }`}>
              {isDebating && <Loader2 className="w-3.5 h-3.5 animate-spin" />}
              <span>{isDebating ? 'AI DEBATE IN PROGRESS' : task.status.replace('_', ' ')}</span>
            </span>
          </div>
        </div>
      </div>

      {/* TOP SECTION: DEBATE TRACE (FULL WIDTH ON TOP) */}
      <div className="bg-white p-8 lg:p-10 rounded-[32px] shadow-[0_8px_30px_rgb(0,0,0,0.03)] border border-zinc-200/80">
        <div className="flex items-center justify-between mb-6 pb-4 border-b border-zinc-100">
          <div>
            <h2 className="text-[20px] font-bold text-[#111827] flex items-center gap-2">
              <Sparkles className="w-5 h-5 text-blue-600" />
              AI Council Debate Trace & Consensus History
            </h2>
            <p className="text-xs text-zinc-500 font-medium mt-1">
              Real-time multi-agent debate trace showing outputs, critiques, and scores from Generator, Critic, and Synthesizer agents.
            </p>
          </div>
          {isDebating && (
            <span className="text-xs font-bold text-blue-600 bg-blue-50 border border-blue-200 px-3 py-1 rounded-full animate-pulse flex items-center gap-1.5 shadow-sm">
              <Loader2 className="w-3.5 h-3.5 animate-spin" /> Live Debate Stream
            </span>
          )}
        </div>
        <DebateTrace history={task.debate_history || []} isDebating={isDebating} />
      </div>

      {/* BOTTOM SECTION: TASK OUTPUT & EXECUTION METRICS */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-8">
        <div className="lg:col-span-2 space-y-8">
          
          <div className="bg-white p-8 lg:p-10 rounded-[32px] shadow-[0_8px_30px_rgb(0,0,0,0.03)] border border-zinc-200/80">
            <h3 className="text-[16px] font-bold text-[#111827] mb-4 flex items-center">
              <Target className="w-5 h-5 mr-2 text-zinc-400" /> Original Request
            </h3>
            <p className="text-zinc-600 leading-relaxed text-[15px] p-6 bg-[#F8FAFC] rounded-[20px] border border-zinc-200/60 font-medium">{task.task_description}</p>
          </div>
          
          <div className="bg-white p-8 lg:p-10 rounded-[32px] shadow-[0_8px_30px_rgb(0,0,0,0.03)] border border-zinc-200/80">
            <div className="flex items-center justify-between mb-4">
              <h3 className="text-[16px] font-bold text-[#111827] flex items-center">
                <Check className="w-5 h-5 mr-2 text-zinc-400" /> Final Output
              </h3>
              {task.final_output && (
                <div className="flex items-center gap-2">
                  <a
                    href={getTaskDocxExportUrl(task.task_id)}
                    className="px-3.5 py-1.5 font-semibold text-[13px] rounded-[10px] transition-all flex items-center gap-1.5 active:scale-95 cursor-pointer bg-blue-50 hover:bg-blue-100 text-blue-700 border border-blue-200 shadow-sm"
                  >
                    <FileDown className="w-3.5 h-3.5" />
                    <span>Download DOCX</span>
                  </a>
                  <button
                    onClick={() => {
                      navigator.clipboard.writeText(task.final_output);
                      setCopied(true);
                      showToast('Copied to Clipboard!', 'Final output copied to clipboard.');
                      setTimeout(() => setCopied(false), 2500);
                    }}
                    className={`px-3.5 py-1.5 font-semibold text-[13px] rounded-[10px] transition-all flex items-center gap-1.5 active:scale-95 cursor-pointer shadow-sm ${
                      copied
                        ? 'bg-emerald-50 text-emerald-700 border border-emerald-200'
                        : 'bg-zinc-100 hover:bg-zinc-200 text-zinc-700 border border-zinc-200'
                    }`}
                  >
                    <Check className={`w-3.5 h-3.5 ${copied ? 'text-emerald-600' : 'text-zinc-500'}`} />
                    <span>{copied ? 'Copied!' : 'Copy Output'}</span>
                  </button>
                </div>
              )}
            </div>

            {task.status === 'failed' || task.error ? (
              <div className="p-8 bg-red-50 border border-red-200 rounded-[20px] flex flex-col items-center justify-center gap-4 text-center">
                <div className="w-10 h-10 rounded-full bg-red-100 text-red-600 flex items-center justify-center">
                  <X className="w-5 h-5" />
                </div>
                <div className="space-y-1">
                  <p className="text-sm font-bold text-red-950">AI Council Execution Failed</p>
                  <p className="text-xs text-red-700 max-w-md font-mono bg-red-100/60 p-2.5 rounded-lg border border-red-200/60 text-left overflow-x-auto">
                    {task.error || 'The OpenRouter API call or debate loop encountered an error.'}
                  </p>
                </div>
                <button
                  onClick={async () => {
                    setLoading(true);
                    try {
                      const { runCouncil } = await import('../../lib/api');
                      await runCouncil({
                        council: task.council,
                        task_description: task.task_description,
                        context: task.context || {}
                      });
                      showToast('Task Resubmitted', 'AI debate loop has restarted.', 'info');
                      loadTaskData();
                    } catch (e) {
                      showToast('Retry Failed', 'Failed to resubmit task.', 'error');
                      setLoading(false);
                    }
                  }}
                  className="px-5 py-2 bg-red-600 hover:bg-red-700 text-white font-semibold text-xs rounded-xl shadow-sm transition-all active:scale-95 cursor-pointer"
                >
                  Retry Task Execution
                </button>
              </div>
            ) : isDebating || !task.final_output ? (
              <div className="p-8 bg-blue-50/50 border border-blue-100 rounded-[20px] flex flex-col items-center justify-center gap-3 text-center">
                <div className="w-10 h-10 rounded-full bg-blue-100 text-blue-600 flex items-center justify-center animate-pulse">
                  <Sparkles className="w-5 h-5" />
                </div>
                <div>
                  <p className="text-sm font-bold text-zinc-900">AI Council is executing multi-agent debate...</p>
                  <p className="text-xs text-zinc-500 mt-1">Generator, Critic, and Synthesizer agents are working. Results will appear automatically in ~15-20s.</p>
                </div>
              </div>
            ) : (
              <div className="prose prose-zinc max-w-none text-[15px] p-6 bg-[#F8FAFC] rounded-[20px] whitespace-pre-wrap leading-relaxed border border-zinc-200/60 font-medium">
                {task.final_output}
              </div>
            )}
          </div>

          {task.status === 'awaiting_approval' && (
            <div className="bg-white p-8 lg:p-10 rounded-[32px] shadow-[0_12px_40px_rgb(37,99,235,0.08)] border border-[#2563EB]/20 transition-shadow duration-500">
              <h3 className="text-[18px] font-bold text-[#111827] mb-4">Approval Decision</h3>
              <textarea
                value={feedback}
                onChange={(e) => setFeedback(e.target.value)}
                placeholder="Add feedback for the council (optional)..."
                className="w-full text-[15px] p-5 bg-[#F8FAFC] rounded-[20px] mb-6 focus:ring-2 focus:ring-[#2563EB] focus:bg-white outline-none transition-all duration-300 resize-none min-h-[100px] border border-zinc-200/80"
              />
              <div className="flex space-x-4">
                <button
                  onClick={() => handleAction(false)}
                  disabled={isSubmitting}
                  className="flex-1 flex items-center justify-center px-6 py-4 bg-zinc-100 text-zinc-600 rounded-[16px] hover:bg-zinc-200 hover:text-zinc-900 font-bold text-[15px] transition-all duration-300 border border-zinc-200"
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
          <div className="bg-white p-8 rounded-[32px] shadow-[0_8px_30px_rgb(0,0,0,0.03)] border border-zinc-200/80">
            <h3 className="text-[16px] font-bold text-[#111827] mb-6">Execution Metrics</h3>
            <div className="space-y-4 text-[14px]">
              <div className="flex justify-between items-center p-4 bg-[#F8FAFC] rounded-[16px] border border-zinc-200/60">
                <span className="text-zinc-500 font-medium flex items-center"><Target className="w-4 h-4 mr-2" /> Council</span>
                <span className="font-bold uppercase tracking-wide text-xs text-[#2563EB]">{task.council}</span>
              </div>
              <div className="flex justify-between items-center p-4 bg-[#F8FAFC] rounded-[16px] border border-zinc-200/60">
                <span className="text-zinc-500 font-medium flex items-center"><DollarSign className="w-4 h-4 mr-2" /> Cost</span>
                <span className="font-bold text-[#111827]">${task.total_cost_usd.toFixed(4)}</span>
              </div>
              <div className="flex justify-between items-center p-4 bg-[#F8FAFC] rounded-[16px] border border-zinc-200/60">
                <span className="text-zinc-500 font-medium flex items-center"><RotateCcw className="w-4 h-4 mr-2" /> Iterations</span>
                <span className="font-bold text-[#111827]">{task.iterations}</span>
              </div>
              <div className="flex justify-between items-center p-4 bg-[#F8FAFC] rounded-[16px] border border-zinc-200/60">
                <span className="text-zinc-500 font-medium flex items-center"><Clock className="w-4 h-4 mr-2" /> Confidence</span>
                <span className={`font-bold ${confidenceColor}`}>{task.confidence_score.toFixed(1)}%</span>
              </div>
              <div className="text-center pt-2">
                 <span className="text-[12px] font-semibold text-zinc-400">Created {formatDistanceToNow(parseTaskDate(task.created_at))} ago</span>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
