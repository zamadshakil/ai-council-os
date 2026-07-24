'use client';

import { useState } from 'react';
import Link from 'next/link';
import { Task } from '../lib/types';
import { approveTask } from '../lib/api';
import { formatDistanceToNow } from 'date-fns';
import { 
  DollarSign, RotateCcw, Clock, Target, Users, BookOpen, Lightbulb, 
  ChevronDown, Check, X, ArrowRight, Sparkles, MessageCircle, Video,
  FileText, Share2, Loader2
} from 'lucide-react';

const councilConfig: Record<string, { bg: string, text: string, icon: any, border: string }> = {
  sales: { bg: 'bg-blue-50', text: 'text-blue-700', border: 'border-blue-200', icon: Target },
  content: { bg: 'bg-emerald-50', text: 'text-emerald-700', border: 'border-emerald-200', icon: BookOpen },
  grant: { bg: 'bg-amber-50', text: 'text-amber-700', border: 'border-amber-200', icon: Lightbulb },
  strategy: { bg: 'bg-violet-50', text: 'text-violet-700', border: 'border-violet-200', icon: Users },
  support: { bg: 'bg-red-50', text: 'text-red-700', border: 'border-red-200', icon: Video },
};

const workflowLabels: Record<string, { label: string; icon: any; color: string }> = {
  youtube_comments: { label: 'YouTube Reply', icon: Video, color: 'text-red-600' },
  reddit_prospector: { label: 'Reddit Lead', icon: MessageCircle, color: 'text-orange-600' },
  youtube_descriptions: { label: 'Description Update', icon: FileText, color: 'text-blue-600' },
  content_engine: { label: 'Content Engine', icon: Share2, color: 'text-violet-600' },
};

export function TaskCard({ task, onStatusChange }: { task: Task; onStatusChange?: () => void }) {
  const [expanded, setExpanded] = useState(false);
  const [actionLoading, setActionLoading] = useState<'approve' | 'reject' | null>(null);
  const [editedOutput, setEditedOutput] = useState('');
  const [localStatus, setLocalStatus] = useState(task.status);

  const councilKey = task.council.toLowerCase();
  const config = councilConfig[councilKey] || { bg: 'bg-zinc-100', text: 'text-zinc-700', border: 'border-zinc-200', icon: Users };
  const Icon = config.icon;
  
  const workflow = task.context?.workflow;
  const wfInfo = workflow ? workflowLabels[workflow] : null;

  // Circular Gauge
  const radius = 20;
  const circumference = 2 * Math.PI * radius;
  const offset = circumference - (task.confidence_score / 100) * circumference;
  const confidenceColor = task.confidence_score >= 80 ? 'text-emerald-600' : task.confidence_score >= 60 ? 'text-amber-500' : 'text-red-600';

  const handleApprove = async () => {
    setActionLoading('approve');
    try {
      await approveTask(task.task_id, { 
        approved: true, 
        edited_output: editedOutput || undefined,
        notes: '' 
      });
      setLocalStatus('approved');
      onStatusChange?.();
    } catch (e) {
      console.error('Approve failed:', e);
    } finally {
      setActionLoading(null);
    }
  };

  const handleReject = async () => {
    setActionLoading('reject');
    try {
      await approveTask(task.task_id, { approved: false, notes: 'Rejected from dashboard' });
      setLocalStatus('rejected');
      onStatusChange?.();
    } catch (e) {
      console.error('Reject failed:', e);
    } finally {
      setActionLoading(null);
    }
  };

  return (
    <div className={`bg-white rounded-[24px] p-6 lg:p-8 shadow-premium border transition-all duration-300 overflow-hidden relative group ${expanded ? 'border-zinc-300 shadow-floating' : 'border-zinc-200/50 hover:border-zinc-300 hover:shadow-floating'}`}>
      
      {/* Header */}
      <div 
        className="flex flex-col sm:flex-row sm:items-center justify-between gap-6 cursor-pointer rounded-[12px]" 
        onClick={() => setExpanded(!expanded)} 
        tabIndex={0} 
        role="button"
        aria-expanded={expanded}
      >
        <div className="flex items-start gap-6 flex-1 min-w-0">
          <div className={`w-14 h-14 rounded-[12px] ${config.bg} border ${config.border} flex items-center justify-center shrink-0 group-hover:scale-105 transition-transform duration-300`}>
            <Icon className={`w-6 h-6 ${config.text}`} />
          </div>
          
          <div className="flex flex-col gap-2 flex-1 min-w-0">
            <div className="flex items-center flex-wrap gap-2.5">
              <span className={`text-[12px] font-bold uppercase tracking-widest ${config.text} shrink-0`}>{task.council}</span>
              
              {wfInfo && (
                <>
                  <span className="w-1 h-1 rounded-full bg-zinc-300 shrink-0" />
                  <span className={`text-[11px] font-bold uppercase tracking-widest ${wfInfo.color} flex items-center gap-1`}>
                    <wfInfo.icon className="w-3 h-3" />
                    {wfInfo.label}
                  </span>
                </>
              )}
              
              {task.context?.platform_name && (
                <>
                  <span className="w-1 h-1 rounded-full bg-zinc-300 shrink-0" />
                  <span className="text-[11px] font-bold uppercase tracking-widest text-violet-600">
                    {task.context.platform_name}
                  </span>
                </>
              )}
              
              <span className="w-1 h-1 rounded-full bg-zinc-300 shrink-0" />
              <span className="text-[13px] font-medium text-zinc-500 shrink-0 truncate">
                {formatDistanceToNow(new Date(task.created_at))} ago
              </span>
            </div>
            
            <h4 className="text-[16px] font-semibold text-zinc-900 leading-snug group-hover:text-blue-700 transition-colors pr-4 line-clamp-2">
              {task.task_description}
            </h4>

            {/* Workflow context preview */}
            {task.context?.original_comment && (
              <p className="text-[13px] text-zinc-500 italic line-clamp-1 mt-1">
                Comment: &ldquo;{task.context.original_comment}&rdquo;
              </p>
            )}
            {task.context?.subreddit && (
              <p className="text-[13px] text-zinc-500 mt-1">
                r/{task.context.subreddit} · by u/{task.context.author}
              </p>
            )}
          </div>
        </div>

        {/* Right: Confidence */}
        <div className="flex items-center justify-between sm:justify-end gap-6 shrink-0 pt-4 sm:pt-0">
          <div className="flex items-center gap-4">
            <div className="text-right">
              <p className="text-[11px] font-semibold text-zinc-500 uppercase tracking-widest mb-0.5">Confidence</p>
              <p className="text-[20px] font-bold text-zinc-900 leading-none tracking-tight">{task.confidence_score.toFixed(1)}%</p>
            </div>
            <div className="relative w-12 h-12 flex items-center justify-center">
              <svg className="w-full h-full transform -rotate-90">
                <circle cx="24" cy="24" r={radius} stroke="currentColor" strokeWidth="4" fill="none" className="text-zinc-100" />
                <circle 
                  cx="24" cy="24" r={radius} 
                  stroke="currentColor" strokeWidth="4" fill="none" 
                  strokeDasharray={circumference} strokeDashoffset={offset}
                  strokeLinecap="round"
                  className={`${confidenceColor} transition-all duration-1000 ease-out`} 
                />
              </svg>
            </div>
          </div>
          <div className={`w-8 h-8 rounded-full border flex items-center justify-center transition-colors duration-200 ${expanded ? 'bg-zinc-900 border-zinc-900 text-white' : 'bg-white border-zinc-200 text-zinc-500 group-hover:bg-zinc-100'}`}>
            <ChevronDown className={`w-5 h-5 transition-transform duration-300 ${expanded ? 'rotate-180' : ''}`} />
          </div>
        </div>
      </div>

      {/* Expanded */}
      <div className={`grid transition-all duration-300 ease-out ${expanded ? 'grid-rows-[1fr] opacity-100 mt-8' : 'grid-rows-[0fr] opacity-0 mt-0'}`}>
        <div className="overflow-hidden">
          <div className="bg-zinc-50 rounded-[16px] border border-zinc-200/60 p-6 lg:p-8 flex flex-col gap-8">
            
            {/* Meta */}
            <div className="flex flex-wrap gap-10">
              <div className="flex flex-col gap-1.5">
                <p className="text-[11px] font-semibold text-zinc-500 uppercase tracking-widest">Iterations</p>
                <p className="text-[14px] font-semibold text-zinc-900 flex items-center"><RotateCcw className="w-4 h-4 mr-1.5 text-zinc-500" /> {task.iterations}</p>
              </div>
              <div className="flex flex-col gap-1.5">
                <p className="text-[11px] font-semibold text-zinc-500 uppercase tracking-widest">Cost</p>
                <p className="text-[14px] font-semibold text-zinc-900 flex items-center"><DollarSign className="w-4 h-4 mr-1 text-zinc-500" /> {task.total_cost_usd.toFixed(4)}</p>
              </div>
              {task.context?.intent_score && (
                <div className="flex flex-col gap-1.5">
                  <p className="text-[11px] font-semibold text-zinc-500 uppercase tracking-widest">Intent Score</p>
                  <p className="text-[14px] font-semibold text-zinc-900">{(task.context.intent_score * 100).toFixed(0)}%</p>
                </div>
              )}
            </div>

            <div className="h-px bg-zinc-200 w-full" />

            {/* Output */}
            <div className="flex flex-col gap-3">
              <p className="text-[12px] font-semibold text-zinc-500 uppercase tracking-widest">AI Generated Output</p>
              <div className="text-[15px] text-zinc-700 leading-relaxed font-medium whitespace-pre-wrap bg-white p-4 rounded-[12px] border border-zinc-200">
                {task.final_output}
              </div>
            </div>

            {/* Edit field */}
            {localStatus === 'awaiting_approval' && (
              <div className="flex flex-col gap-2">
                <p className="text-[12px] font-semibold text-zinc-500 uppercase tracking-widest">Edit Output (optional)</p>
                <textarea
                  value={editedOutput}
                  onChange={(e) => setEditedOutput(e.target.value)}
                  placeholder="Optionally edit the output before approving..."
                  className="w-full px-4 py-3 border border-zinc-200 rounded-[10px] text-[14px] text-zinc-900 placeholder:text-zinc-400 resize-none min-h-[80px] focus:outline-none focus:ring-2 focus:ring-blue-500 transition-all"
                />
              </div>
            )}

            <div className="h-px bg-zinc-200 w-full" />

            {/* Actions */}
            <div className="flex flex-col sm:flex-row items-center justify-between gap-4">
              <div className="flex items-center gap-3 w-full sm:w-auto">
                {localStatus === 'awaiting_approval' && (
                  <>
                    <button 
                      onClick={handleReject}
                      disabled={!!actionLoading}
                      className="flex-1 sm:flex-none h-10 px-6 rounded-[10px] text-[14px] font-semibold text-red-700 bg-white border border-red-200 shadow-sm hover:bg-red-50 active:scale-[0.98] transition-all flex items-center justify-center disabled:opacity-50"
                    >
                      {actionLoading === 'reject' ? <Loader2 className="w-4 h-4 mr-2 animate-spin" /> : <X className="w-4 h-4 mr-2" />}
                      Reject
                    </button>
                    <button 
                      onClick={handleApprove}
                      disabled={!!actionLoading}
                      className="flex-1 sm:flex-none h-10 px-6 rounded-[10px] text-[14px] font-semibold text-white bg-zinc-900 shadow-sm hover:bg-zinc-800 active:scale-[0.98] transition-all flex items-center justify-center disabled:opacity-50"
                    >
                      {actionLoading === 'approve' ? <Loader2 className="w-4 h-4 mr-2 animate-spin" /> : <Check className="w-4 h-4 mr-2" />}
                      Approve & Publish
                    </button>
                  </>
                )}
                {localStatus !== 'awaiting_approval' && (
                  <span className={`px-4 py-2 rounded-[8px] text-[12px] font-bold uppercase tracking-widest border shadow-sm ${
                    localStatus === 'approved' ? 'bg-emerald-50 text-emerald-800 border-emerald-200' 
                    : localStatus === 'rejected' ? 'bg-red-50 text-red-800 border-red-200'
                    : localStatus === 'failed' ? 'bg-red-50 text-red-800 border-red-200'
                    : 'bg-zinc-100 text-zinc-800 border-zinc-200'
                  }`}>
                    {localStatus.replace('_', ' ')}
                  </span>
                )}
              </div>
              <Link href={`/approvals/${task.task_id}`} className="text-[14px] font-semibold text-blue-600 hover:text-blue-800 flex items-center h-10 px-4 rounded-[10px] hover:bg-blue-50 transition-colors">
                View full details <ArrowRight className="w-4 h-4 ml-1.5" />
              </Link>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
