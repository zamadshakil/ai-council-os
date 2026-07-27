'use client';

import { useState, useEffect } from 'react';
import { 
  Zap, Play, Radio, Video, MessageCircle, FileText, 
  Share2, Loader2, CheckCircle2, XCircle, Shield, ShieldOff,
  Clock, TrendingUp, AlertTriangle
} from 'lucide-react';
import { triggerWorkflow, fetchKillSwitch, fetchStats } from '../lib/api';
import { KillSwitchStatus, Stats } from '../lib/types';

interface WorkflowDef {
  id: string;
  name: string;
  description: string;
  icon: any;
  endpoint: string;
  schedule: string;
  color: string;
  bgColor: string;
  borderColor: string;
  requiresInput?: boolean;
  inputFields?: { key: string; label: string; placeholder: string; type?: string }[];
}

const WORKFLOWS: WorkflowDef[] = [
  {
    id: 'instagram-comments',
    name: 'Instagram Comment Auto-Reply',
    description: 'Fetches recent posts/reels from @zamdev.me, reads comments, and uses Support Council to generate and post contextual AI replies (deduplicated).',
    icon: MessageCircle,
    endpoint: 'instagram-comments',
    schedule: 'Every 30 min',
    color: 'text-pink-600',
    bgColor: 'bg-pink-50',
    borderColor: 'border-pink-200',
  },
  {
    id: 'reddit',
    name: 'Reddit Lead Prospector',
    description: 'Scans 45+ subreddits for prospects asking questions we can answer. AI scores intent and drafts contextual replies.',
    icon: MessageCircle,
    endpoint: 'reddit-prospector',
    schedule: 'Every 60 min',
    color: 'text-orange-600',
    bgColor: 'bg-orange-50',
    borderColor: 'border-orange-200',
  },
  {
    id: 'youtube-comments',
    name: 'YouTube Comment Auto-Reply',
    description: 'Fetches new comments across all channel videos and drafts context-aware replies referencing the video topic.',
    icon: Video,
    endpoint: 'youtube-comments',
    schedule: 'Every 30 min',
    color: 'text-red-600',
    bgColor: 'bg-red-50',
    borderColor: 'border-red-200',
  },
  {
    id: 'youtube-descriptions',
    name: 'Bulk Description Updater',
    description: 'Rewrites video descriptions: preserves video-specific opening, replaces only boilerplate blocks. Two-phase: generate → review → publish.',
    icon: FileText,
    endpoint: 'youtube-descriptions',
    schedule: 'Manual only',
    color: 'text-blue-600',
    bgColor: 'bg-blue-50',
    borderColor: 'border-blue-200',
  },
  {
    id: 'content-engine',
    name: 'Multi-Platform Content Engine',
    description: 'Takes one video transcript and produces 6 unique, platform-optimized posts for X, LinkedIn, Facebook, Instagram, Reddit, and Discord.',
    icon: Share2,
    endpoint: 'content-engine',
    schedule: 'Manual only',
    color: 'text-violet-600',
    bgColor: 'bg-violet-50',
    borderColor: 'border-violet-200',
    requiresInput: true,
    inputFields: [
      { key: 'video_title', label: 'Video Title', placeholder: 'Enter the source video title...' },
      { key: 'transcript', label: 'Video Transcript', placeholder: 'Paste the video transcript here...', type: 'textarea' },
      { key: 'video_id', label: 'Video ID (optional)', placeholder: 'e.g., dQw4w9WgXcQ' },
    ],
  },
];

interface RunResult {
  workflowId: string;
  status: 'success' | 'error' | 'running';
  message: string;
  data?: any;
}

export default function WorkflowsPage() {
  const [killSwitch, setKillSwitch] = useState<KillSwitchStatus | null>(null);
  const [stats, setStats] = useState<Stats | null>(null);
  const [runningWorkflows, setRunningWorkflows] = useState<Set<string>>(new Set());
  const [results, setResults] = useState<Record<string, RunResult>>({});
  const [expandedWorkflow, setExpandedWorkflow] = useState<string | null>(null);
  const [inputData, setInputData] = useState<Record<string, string>>({});

  useEffect(() => {
    fetchKillSwitch().then(setKillSwitch).catch(() => {});
    fetchStats().then(setStats).catch(() => {});
  }, []);

  const handleRun = async (workflow: WorkflowDef) => {
    if (killSwitch?.is_active) {
      setResults(prev => ({
        ...prev,
        [workflow.id]: { workflowId: workflow.id, status: 'error', message: 'Kill switch is active. Deactivate it first.' }
      }));
      return;
    }

    if (workflow.requiresInput && !inputData.video_title) {
      setExpandedWorkflow(workflow.id);
      return;
    }

    setRunningWorkflows(prev => new Set([...prev, workflow.id]));
    setResults(prev => ({
      ...prev,
      [workflow.id]: { workflowId: workflow.id, status: 'running', message: 'Running...' }
    }));

    try {
      const body = workflow.requiresInput ? inputData : undefined;
      const result = await triggerWorkflow(workflow.endpoint, body);
      setResults(prev => ({
        ...prev,
        [workflow.id]: {
          workflowId: workflow.id,
          status: result.status === 'error' ? 'error' : 'success',
          message: result.status === 'error'
            ? result.error || 'Workflow failed'
            : `Completed: ${JSON.stringify(result).slice(0, 120)}`,
          data: result,
        }
      }));
    } catch (err: any) {
      setResults(prev => ({
        ...prev,
        [workflow.id]: { workflowId: workflow.id, status: 'error', message: err.message || 'Failed' }
      }));
    } finally {
      setRunningWorkflows(prev => {
        const next = new Set(prev);
        next.delete(workflow.id);
        return next;
      });
    }
  };

  return (
    <div className="max-w-[1080px] mx-auto flex flex-col gap-8 animate-in fade-in duration-300 ease-out fill-mode-both pb-16">
      {/* Header */}
      <div className="flex items-center justify-between pt-2">
        <div>
          <h1 className="text-[28px] font-bold text-zinc-900 tracking-tight">Automation Workflows</h1>
          <p className="text-[15px] text-zinc-500 mt-1">Trigger, monitor, and control all automation pipelines from here.</p>
        </div>
        {killSwitch && (
          <div className={`flex items-center gap-2 px-4 py-2 rounded-[10px] border text-[13px] font-semibold ${
            killSwitch.is_active
              ? 'bg-red-50 border-red-200 text-red-700'
              : 'bg-emerald-50 border-emerald-200 text-emerald-700'
          }`}>
            {killSwitch.is_active ? <ShieldOff className="w-4 h-4" /> : <Shield className="w-4 h-4" />}
            {killSwitch.is_active ? 'System KILLED' : 'System Active'}
          </div>
        )}
      </div>

      {/* Kill Switch Warning */}
      {killSwitch?.is_active && (
        <div className="flex items-center gap-3 p-4 bg-red-50 border border-red-200 rounded-[16px]">
          <AlertTriangle className="w-5 h-5 text-red-600 shrink-0" />
          <div>
            <p className="text-[14px] font-semibold text-red-800">Kill Switch is Active</p>
            <p className="text-[13px] text-red-600 mt-0.5">
              All workflows are paused. Deactivate from the sidebar toggle to resume operations.
              {killSwitch.reason && ` Reason: ${killSwitch.reason}`}
            </p>
          </div>
        </div>
      )}

      {/* Quick Stats */}
      {stats && (
        <div className="grid grid-cols-4 gap-4">
          {[
            { label: 'Pending Review', value: stats.pending, icon: Clock, color: 'text-amber-600' },
            { label: 'Approved', value: stats.approved, icon: CheckCircle2, color: 'text-emerald-600' },
            { label: 'Total Tasks', value: stats.total_tasks, icon: TrendingUp, color: 'text-blue-600' },
            { label: 'Total Cost', value: `$${stats.total_cost_usd.toFixed(2)}`, icon: Zap, color: 'text-violet-600' },
          ].map((stat) => (
            <div key={stat.label} className="bg-white border border-zinc-200 rounded-[14px] p-4 shadow-sm">
              <div className="flex items-center gap-2 mb-2">
                <stat.icon className={`w-4 h-4 ${stat.color}`} />
                <span className="text-[12px] font-semibold text-zinc-500 uppercase tracking-wider">{stat.label}</span>
              </div>
              <p className="text-[24px] font-bold text-zinc-900">{stat.value}</p>
            </div>
          ))}
        </div>
      )}

      {/* Workflow Cards */}
      <div className="flex flex-col gap-4">
        {WORKFLOWS.map((wf) => {
          const Icon = wf.icon;
          const isRunning = runningWorkflows.has(wf.id);
          const result = results[wf.id];
          const isExpanded = expandedWorkflow === wf.id;

          return (
            <div
              key={wf.id}
              className={`bg-white border rounded-[20px] shadow-sm transition-all duration-200 overflow-hidden ${
                isRunning ? 'border-blue-300 shadow-[0_0_0_3px_rgba(59,130,246,0.1)]' : 'border-zinc-200 hover:shadow-floating'
              }`}
            >
              <div className="p-6 flex items-center gap-5">
                {/* Icon */}
                <div className={`p-4 rounded-[14px] ${wf.bgColor} border ${wf.borderColor} shrink-0`}>
                  <Icon className={`w-6 h-6 ${wf.color}`} />
                </div>

                {/* Info */}
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-3 mb-1">
                    <h3 className="text-[16px] font-bold text-zinc-900">{wf.name}</h3>
                    <span className="px-2 py-0.5 text-[11px] font-semibold text-zinc-500 bg-zinc-100 rounded-[6px]">
                      {wf.schedule}
                    </span>
                  </div>
                  <p className="text-[14px] text-zinc-500 leading-relaxed">{wf.description}</p>
                </div>

                {/* Action */}
                <button
                  onClick={() => wf.requiresInput ? setExpandedWorkflow(isExpanded ? null : wf.id) : handleRun(wf)}
                  disabled={isRunning}
                  className={`shrink-0 flex items-center gap-2 h-10 px-6 rounded-[10px] text-[14px] font-semibold transition-all duration-200 active:scale-[0.97] disabled:opacity-50 disabled:cursor-not-allowed ${
                    isRunning
                      ? 'bg-blue-100 text-blue-700 border border-blue-200'
                      : 'bg-zinc-900 text-white hover:bg-zinc-800 shadow-sm'
                  }`}
                >
                  {isRunning ? (
                    <><Loader2 className="w-4 h-4 animate-spin" /> Running...</>
                  ) : (
                    <><Play className="w-4 h-4" /> {wf.requiresInput ? 'Configure' : 'Run Now'}</>
                  )}
                </button>
              </div>

              {/* Content Engine Input Form */}
              {isExpanded && wf.requiresInput && wf.inputFields && (
                <div className="px-6 pb-6 border-t border-zinc-100 pt-4">
                  <div className="flex flex-col gap-4">
                    {wf.inputFields.map((field) => (
                      <div key={field.key}>
                        <label className="block text-[13px] font-semibold text-zinc-700 mb-1.5">{field.label}</label>
                        {field.type === 'textarea' ? (
                          <textarea
                            value={inputData[field.key] || ''}
                            onChange={(e) => setInputData(prev => ({ ...prev, [field.key]: e.target.value }))}
                            placeholder={field.placeholder}
                            className="w-full px-4 py-3 border border-zinc-200 rounded-[10px] text-[14px] text-zinc-900 placeholder:text-zinc-400 resize-none min-h-[120px] focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent transition-all"
                          />
                        ) : (
                          <input
                            type="text"
                            value={inputData[field.key] || ''}
                            onChange={(e) => setInputData(prev => ({ ...prev, [field.key]: e.target.value }))}
                            placeholder={field.placeholder}
                            className="w-full px-4 py-2.5 border border-zinc-200 rounded-[10px] text-[14px] text-zinc-900 placeholder:text-zinc-400 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent transition-all"
                          />
                        )}
                      </div>
                    ))}
                    <button
                      onClick={() => handleRun(wf)}
                      disabled={isRunning || !inputData.video_title}
                      className="self-end h-10 px-8 bg-zinc-900 text-white rounded-[10px] text-[14px] font-semibold hover:bg-zinc-800 active:scale-[0.97] disabled:opacity-50 transition-all shadow-sm"
                    >
                      Generate 6 Platform Variants
                    </button>
                  </div>
                </div>
              )}

              {/* Result Banner */}
              {result && !isRunning && (
                <div className={`px-6 py-3 border-t text-[13px] font-medium flex items-center gap-2 ${
                  result.status === 'success'
                    ? 'bg-emerald-50 border-emerald-100 text-emerald-700'
                    : 'bg-red-50 border-red-100 text-red-700'
                }`}>
                  {result.status === 'success' ? <CheckCircle2 className="w-4 h-4 shrink-0" /> : <XCircle className="w-4 h-4 shrink-0" />}
                  {result.message}
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
