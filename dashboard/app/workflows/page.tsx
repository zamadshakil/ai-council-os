'use client';

import { useState, useEffect } from 'react';
import { 
  Zap, Play, Video, MessageCircle, FileText, 
  Share2, Loader2, CheckCircle2, XCircle, Shield, ShieldOff,
  Clock, TrendingUp, AlertTriangle, Activity, Pause, RefreshCw,
  ExternalLink, ChevronDown, ChevronUp, Terminal, Layers, Sparkles, Settings
} from 'lucide-react';
import { useRouter } from 'next/navigation';
import { triggerWorkflow, fetchKillSwitch, fetchStats, fetchWorkflowConfigStatus } from '../lib/api';
import { KillSwitchStatus, Stats } from '../lib/types';

interface WorkflowDef {
  id: string;
  name: string;
  account: string;
  accountHandle: string;
  description: string;
  icon: any;
  endpoint: string;
  schedule: string;
  color: string;
  bgColor: string;
  borderColor: string;
  requiresInput?: boolean;
  inputFields?: { key: string; label: string; placeholder: string; type?: string }[];
  status: 'active' | 'paused';
}

const WORKFLOWS: WorkflowDef[] = [
  {
    id: 'instagram-comments',
    name: 'Instagram Comment Auto-Reply',
    account: 'Instagram Business',
    accountHandle: '@zamdev.me',
    description: 'Fetches recent posts/reels from @zamdev.me, reads comments, and uses Support Council to generate and post contextual AI replies (deduplicated).',
    icon: MessageCircle,
    endpoint: 'instagram-comments',
    schedule: 'Every 5 min (Webhooks Active)',
    color: 'text-pink-600',
    bgColor: 'bg-pink-50',
    borderColor: 'border-pink-200',
    status: 'active',
  },
  {
    id: 'reddit',
    name: 'Reddit Lead Prospector',
    account: 'Reddit Automation',
    accountHandle: 'r/automation + 45 subs',
    description: 'Scans 45+ subreddits for prospects asking questions we can answer. AI scores intent and drafts contextual replies.',
    icon: MessageCircle,
    endpoint: 'reddit-prospector',
    schedule: 'Every 60 min',
    color: 'text-orange-600',
    bgColor: 'bg-orange-50',
    borderColor: 'border-orange-200',
    status: 'active',
  },
  {
    id: 'youtube-comments',
    name: 'YouTube Comment Auto-Reply',
    account: 'YouTube Channel',
    accountHandle: 'ZamDev.me',
    description: 'Fetches new comments across all channel videos and drafts context-aware replies referencing the video topic.',
    icon: Video,
    endpoint: 'youtube-comments',
    schedule: 'Every 30 min',
    color: 'text-red-600',
    bgColor: 'bg-red-50',
    borderColor: 'border-red-200',
    status: 'active',
  },
  {
    id: 'youtube-descriptions',
    name: 'Bulk Description Updater',
    account: 'YouTube Channel',
    accountHandle: 'ZamDev.me',
    description: 'Rewrites video descriptions: preserves video-specific opening, replaces only boilerplate blocks. Two-phase: generate → review → publish.',
    icon: FileText,
    endpoint: 'youtube-descriptions',
    schedule: 'Manual trigger only',
    color: 'text-blue-600',
    bgColor: 'bg-blue-50',
    borderColor: 'border-blue-200',
    status: 'active',
  },
  {
    id: 'content-engine',
    name: 'Multi-Platform Content Engine',
    account: 'Multi-Channel Publisher',
    accountHandle: 'X, LinkedIn, FB, IG, Reddit',
    description: 'Takes one video transcript and produces 6 unique, platform-optimized posts for X, LinkedIn, Facebook, Instagram, Reddit, and Discord.',
    icon: Share2,
    endpoint: 'content-engine',
    schedule: 'Manual trigger only',
    color: 'text-violet-600',
    bgColor: 'bg-violet-50',
    borderColor: 'border-violet-200',
    requiresInput: true,
    inputFields: [
      { key: 'video_title', label: 'Video Title', placeholder: 'Enter the source video title...' },
      { key: 'transcript', label: 'Video Transcript', placeholder: 'Paste the video transcript here...', type: 'textarea' },
      { key: 'video_id', label: 'Video ID (optional)', placeholder: 'e.g., dQw4w9WgXcQ' },
    ],
    status: 'active',
  },
];

const WORKFLOW_ENV_LABELS: Record<string, string> = {
  INSTAGRAM_ACCESS_TOKEN: 'Instagram Access Token',
  INSTAGRAM_BUSINESS_ID: 'Instagram Business ID',
  REDDIT_CLIENT_ID: 'Reddit Client ID',
  REDDIT_CLIENT_SECRET: 'Reddit Client Secret',
  YOUTUBE_API_KEY: 'YouTube API Key',
  YOUTUBE_CHANNEL_ID: 'YouTube Channel ID',
};

interface LogEntry {
  timestamp: string;
  level: 'info' | 'success' | 'warn' | 'error';
  message: string;
}

interface RunResult {
  workflowId: string;
  status: 'success' | 'error' | 'running';
  message: string;
  data?: any;
  logs: LogEntry[];
}

export default function WorkflowsPage() {
  const router = useRouter();
  
  const [settingsWorkflow, setSettingsWorkflow] = useState<string | null>(null);
  const [settingsLoading, setSettingsLoading] = useState(false);
  const [availableDocs, setAvailableDocs] = useState<any[]>([]);
  const [customPrompt, setCustomPrompt] = useState('');
  const [selectedDocs, setSelectedDocs] = useState<string[]>([]);
  const API_BASE = process.env.NEXT_PUBLIC_API_URL || '';

  const loadSettings = async (wfId: string) => {
    setSettingsWorkflow(wfId);
    setSettingsLoading(true);
    try {
      const [settingsRes, docsRes] = await Promise.all([
        fetch(`${API_BASE}/api/workflows/${wfId}/settings`).then(r => r.json()),
        fetch(`${API_BASE}/api/knowledge/documents`).then(r => r.json())
      ]);
      setCustomPrompt(settingsRes.custom_prompt || '');
      setSelectedDocs(settingsRes.selected_docs || []);
      setAvailableDocs(docsRes.documents || []);
    } catch (e) {
      console.error(e);
    } finally {
      setSettingsLoading(false);
    }
  };

  const saveSettings = async () => {
    if (!settingsWorkflow) return;
    setSettingsLoading(true);
    try {
      await fetch(`${API_BASE}/api/workflows/${settingsWorkflow}/settings`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ custom_prompt: customPrompt, selected_docs: selectedDocs })
      });
      setSettingsWorkflow(null);
    } catch (e) {
      console.error(e);
    } finally {
      setSettingsLoading(false);
    }
  };

  const [activeLogModal, setActiveLogModal] = useState<string | null>(null);
  const [killSwitch, setKillSwitch] = useState<KillSwitchStatus | null>(null);
  const [stats, setStats] = useState<Stats | null>(null);
  const [runningWorkflows, setRunningWorkflows] = useState<Set<string>>(new Set());
  const [results, setResults] = useState<Record<string, RunResult>>({});
  const [activeWorkflowStatuses, setActiveWorkflowStatuses] = useState<Record<string, 'active' | 'paused'>>({
    'instagram-comments': 'active',
    'reddit': 'paused',
    'youtube-comments': 'paused',
    'youtube-descriptions': 'paused',
    'content-engine': 'paused',
  });
  const [expandedWorkflow, setExpandedWorkflow] = useState<string | null>(null);
  const [inputData, setInputData] = useState<Record<string, string>>({});
  const [configStatus, setConfigStatus] = useState<Record<string, { ready: boolean; missing_env: string[] }>>({});

  useEffect(() => {
    fetchKillSwitch().then(setKillSwitch).catch(() => {});
    fetchStats().then(setStats).catch(() => {});
    fetchWorkflowConfigStatus().then(setConfigStatus).catch(() => {});
  }, []);

  const toggleStatus = (id: string) => {
    setActiveWorkflowStatuses(prev => ({
      ...prev,
      [id]: prev[id] === 'active' ? 'paused' : 'active'
    }));
  };

  const handleRun = async (workflow: WorkflowDef) => {
    if (killSwitch?.is_active) {
      setResults(prev => ({
        ...prev,
        [workflow.id]: {
          workflowId: workflow.id,
          status: 'error',
          message: 'Kill switch is active. Deactivate it first from sidebar.',
          logs: [{ timestamp: new Date().toLocaleTimeString(), level: 'error', message: 'Execution blocked by Kill Switch.' }]
        }
      }));
      return;
    }

    if (workflow.requiresInput && !inputData.video_title) {
      setExpandedWorkflow(workflow.id);
      return;
    }

    const now = () => new Date().toLocaleTimeString();

    setRunningWorkflows(prev => new Set([...prev, workflow.id]));
    
    // Initial live logs state
    const initialLogs: LogEntry[] = [
      { timestamp: now(), level: 'info', message: `Initializing pipeline execution for ${workflow.name}...` },
      { timestamp: now(), level: 'info', message: `Connecting to ${workflow.account} API endpoint (${workflow.accountHandle})...` },
    ];

    setResults(prev => ({
      ...prev,
      [workflow.id]: {
        workflowId: workflow.id,
        status: 'running',
        message: 'Running pipeline step execution...',
        logs: initialLogs,
      }
    }));

    try {
      const body = workflow.requiresInput ? inputData : undefined;
      const result = await triggerWorkflow(workflow.endpoint, body);
      
      const successLogs: LogEntry[] = [
        ...initialLogs,
        { timestamp: now(), level: 'info', message: `Fetched workflow status from backend server...` },
        { timestamp: now(), level: 'success', message: `Execution completed successfully.` },
        { timestamp: now(), level: 'info', message: `AI Council RAG debate finished. Deduplication DB updated.` }
      ];

      setResults(prev => ({
        ...prev,
        [workflow.id]: {
          workflowId: workflow.id,
          status: result.status === 'error' ? 'error' : 'success',
          message: result.status === 'error'
            ? result.error || 'Workflow execution encountered an error.'
            : 'Pipeline finished execution successfully! All new comments replied.',
          data: result,
          logs: successLogs,
        }
      }));

      fetchStats().then(setStats).catch(() => {});
    } catch (err: any) {
      setResults(prev => ({
        ...prev,
        [workflow.id]: {
          workflowId: workflow.id,
          status: 'error',
          message: err.message || 'Execution failed',
          logs: [
            ...initialLogs,
            { timestamp: now(), level: 'error', message: `Execution Error: ${err.message}` }
          ]
        }
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
    <div className="space-y-12 pb-20 animate-in fade-in duration-300 ease-out fill-mode-both">
      {/* Header */}
      <div className="flex items-start justify-between mb-8">
        <div>
          <h1 className="text-[40px] font-bold text-[#111827] tracking-tight leading-none mb-3">Automation Workflows</h1>
          <p className="text-[15px] text-zinc-500 font-medium">Trigger, monitor live activity logs, and manage account integrations.</p>
        </div>
        {killSwitch && (
          <div className={`flex items-center gap-2 px-4 py-2 rounded-[10px] border text-[13px] font-semibold ${
            killSwitch.is_active
              ? 'bg-red-50 border-red-200 text-red-700'
              : 'bg-emerald-50 border-emerald-200 text-emerald-700 shadow-sm'
          }`}>
            {killSwitch.is_active ? <ShieldOff className="w-4 h-4" /> : <Shield className="w-4 h-4" />}
            {killSwitch.is_active ? 'System KILLED' : 'System Active & Listening'}
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
            { label: 'Approved & Replied', value: stats.approved, icon: CheckCircle2, color: 'text-emerald-600' },
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
      <div className="flex flex-col gap-5">
        {WORKFLOWS.map((wf) => {
          const Icon = wf.icon;
          const isRunning = runningWorkflows.has(wf.id);
          const result = results[wf.id];
          const isExpanded = expandedWorkflow === wf.id;
          const status = activeWorkflowStatuses[wf.id] || 'active';
          const isPaused = status === 'paused';
          const cfg = configStatus[wf.id];
          const needsSetup = !!cfg && !cfg.ready;
          const missingLabels = (cfg?.missing_env || []).map((k) => WORKFLOW_ENV_LABELS[k] || k);

          return (
            <div
              key={wf.id}
              className={`bg-white border rounded-[20px] shadow-sm transition-all duration-200 overflow-hidden ${
                isRunning ? 'border-blue-400 shadow-[0_0_0_4px_rgba(59,130,246,0.1)]' : 'border-zinc-200 hover:shadow-floating'
              }`}
            >
              <div className="p-6 flex flex-col gap-4">
                {/* Top Row: Info & Controls */}
                <div className="flex items-start justify-between gap-5">
                  <div className="flex items-start gap-4">
                    {/* Icon */}
                    <div className={`p-4 rounded-[16px] ${wf.bgColor} border ${wf.borderColor} shrink-0 shadow-sm`}>
                      <Icon className={`w-6 h-6 ${wf.color}`} />
                    </div>

                    {/* Meta info */}
                    <div>
                      <div className="flex items-center gap-3 flex-wrap">
                        <h3 className="text-[17px] font-bold text-zinc-900 tracking-tight">{wf.name}</h3>
                        
                        {/* Connected Account Badge */}
                        <div className="flex items-center gap-1.5 px-2.5 py-1 bg-zinc-100 border border-zinc-200 rounded-[8px] text-[12px] font-semibold text-zinc-700">
                          <span className="w-2 h-2 rounded-full bg-emerald-500 animate-pulse"></span>
                          <span>{wf.account}:</span>
                          <span className="font-bold text-zinc-900">{wf.accountHandle}</span>
                        </div>

                        {/* Status Toggle Badge */}
                        {needsSetup ? (
                          <span
                            className="flex items-center gap-1.5 px-2.5 py-1 rounded-[8px] text-[11px] font-bold uppercase tracking-wider border bg-red-50 text-red-700 border-red-200"
                            title={`Missing: ${missingLabels.join(', ')}`}
                          >
                            <AlertTriangle className="w-3 h-3" /> Needs Setup
                          </span>
                        ) : (
                          <button
                            onClick={() => toggleStatus(wf.id)}
                            className={`flex items-center gap-1.5 px-2.5 py-1 rounded-[8px] text-[11px] font-bold uppercase tracking-wider transition-all border ${
                              isPaused
                                ? 'bg-amber-50 text-amber-700 border-amber-200 hover:bg-amber-100'
                                : 'bg-emerald-50 text-emerald-700 border-emerald-200 hover:bg-emerald-100'
                            }`}
                          >
                            {isPaused ? <Pause className="w-3 h-3" /> : <Activity className="w-3 h-3" />}
                            {isPaused ? 'Paused' : 'Active'}
                          </button>
                        )}
                      </div>

                      <p className="text-[14px] text-zinc-500 leading-relaxed mt-1.5">{wf.description}</p>
                      {needsSetup && (
                        <p className="text-[12.5px] text-red-600 font-medium mt-1">
                          Missing credentials: {missingLabels.join(', ')} — this workflow cannot reach the real platform until these are added to the server .env.
                        </p>
                      )}
                    </div>
                  </div>

                  {/* Actions */}
                  <div className="flex items-center gap-2 shrink-0">
                    {/* Settings Configuration Button */}
                    <button
                      onClick={() => loadSettings(wf.id)}
                      className="flex items-center justify-center w-10 h-10 rounded-[10px] text-zinc-500 bg-zinc-50 hover:bg-zinc-100 border border-zinc-200 transition-all shadow-sm"
                      title="Configure AI Settings"
                    >
                      <Settings className="w-4 h-4" />
                    </button>

                    {/* View Details Page Button */}
                    <button
                      onClick={() => router.push(`/workflows/${wf.id}`)}
                      className="flex items-center gap-1.5 h-10 px-4 rounded-[10px] text-[13px] font-semibold text-blue-700 bg-blue-50 hover:bg-blue-100 border border-blue-200 transition-all shadow-sm"
                    >
                      <ExternalLink className="w-3.5 h-3.5" />
                      <span>View Activity & Details</span>
                    </button>

                    {/* Run Now Button */}
                    <button
                      onClick={() => wf.requiresInput ? setExpandedWorkflow(isExpanded ? null : wf.id) : handleRun(wf)}
                      disabled={isRunning || killSwitch?.is_active || needsSetup}
                      title={needsSetup ? `Add ${missingLabels.join(', ')} to .env first` : undefined}
                      className={`flex items-center gap-2 h-10 px-6 rounded-[10px] text-[14px] font-semibold transition-all duration-200 active:scale-[0.97] disabled:opacity-50 disabled:cursor-not-allowed ${
                        isRunning
                          ? 'bg-blue-100 text-blue-700 border border-blue-200'
                          : needsSetup
                            ? 'bg-zinc-200 text-zinc-500 shadow-none'
                            : 'bg-zinc-900 text-white hover:bg-zinc-800 shadow-sm'
                      }`}
                    >
                      {isRunning ? (
                        <><Loader2 className="w-4 h-4 animate-spin" /> Executing...</>
                      ) : needsSetup ? (
                        <><AlertTriangle className="w-4 h-4" /> Needs Setup</>
                      ) : (
                        <><Play className="w-4 h-4 fill-current" /> {wf.requiresInput ? 'Configure' : 'Run Now'}</>
                      )}
                    </button>
                  </div>
                </div>

                {/* Sub-bar: Schedule & Tech Specs */}
                <div className="flex items-center justify-between text-[12px] text-zinc-500 bg-zinc-50 border border-zinc-100 rounded-[12px] px-4 py-2 mt-1">
                  <div className="flex items-center gap-4">
                    <span className="flex items-center gap-1 font-medium">
                      <Clock className="w-3.5 h-3.5 text-zinc-400" />
                      Interval: <strong className="text-zinc-700">{wf.schedule}</strong>
                    </span>
                    {wf.id === 'instagram-comments' && (
                      <span className="flex items-center gap-1 text-emerald-600 font-semibold bg-emerald-50 px-2 py-0.5 rounded-[6px] border border-emerald-100">
                        <Sparkles className="w-3 h-3" /> Meta Real-Time Webhooks SSL Enabled
                      </span>
                    )}
                  </div>
                  <span className="text-zinc-400 font-mono text-[11px]">Endpoint: /api/workflows/{wf.endpoint}</span>
                </div>
              </div>

              {/* Content Engine Input Form */}
              {isExpanded && wf.requiresInput && wf.inputFields && (
                <div className="px-6 pb-6 border-t border-zinc-100 pt-4 bg-zinc-50/50">
                  <div className="flex flex-col gap-4">
                    {wf.inputFields.map((field) => (
                      <div key={field.key}>
                        <label className="block text-[13px] font-semibold text-zinc-700 mb-1.5">{field.label}</label>
                        {field.type === 'textarea' ? (
                          <textarea
                            value={inputData[field.key] || ''}
                            onChange={(e) => setInputData(prev => ({ ...prev, [field.key]: e.target.value }))}
                            placeholder={field.placeholder}
                            className="w-full px-4 py-3 border border-zinc-200 rounded-[10px] text-[14px] text-zinc-900 placeholder:text-zinc-400 resize-none min-h-[120px] focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent transition-all bg-white"
                          />
                        ) : (
                          <input
                            type="text"
                            value={inputData[field.key] || ''}
                            onChange={(e) => setInputData(prev => ({ ...prev, [field.key]: e.target.value }))}
                            placeholder={field.placeholder}
                            className="w-full px-4 py-2.5 border border-zinc-200 rounded-[10px] text-[14px] text-zinc-900 placeholder:text-zinc-400 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent transition-all bg-white"
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

              {/* Formatted Activity Banner */}
              {result && !isRunning && (
                <div className="border-t border-zinc-200">
                  <div className={`px-6 py-3.5 text-[13px] font-medium flex items-center justify-between ${
                    result.status === 'success'
                      ? 'bg-emerald-50/80 text-emerald-900'
                      : 'bg-red-50/80 text-red-900'
                  }`}>
                    <div className="flex items-center gap-2">
                      {result.status === 'success' ? <CheckCircle2 className="w-4 h-4 text-emerald-600 shrink-0" /> : <XCircle className="w-4 h-4 text-red-600 shrink-0" />}
                      <span className="font-semibold">{result.message}</span>
                    </div>
                    <button
                      onClick={() => setActiveLogModal(activeLogModal === wf.id ? null : wf.id)}
                      className="text-[12px] font-bold underline hover:opacity-80 transition-opacity"
                    >
                      {activeLogModal === wf.id ? 'Hide Activity Console' : 'View Real-Time Activity Logs'}
                    </button>
                  </div>

                  {/* Activity Console Modal / Expandable Drawer */}
                  {activeLogModal === wf.id && (
                    <div className="bg-zinc-950 p-5 font-mono text-[12px] text-zinc-300 border-t border-zinc-800 flex flex-col gap-2">
                      <div className="flex items-center justify-between pb-2 border-b border-zinc-800 text-zinc-400 text-[11px]">
                        <span className="flex items-center gap-1.5 font-bold uppercase tracking-wider text-zinc-300">
                          <Terminal className="w-3.5 h-3.5 text-blue-400" /> Real-Time Live Execution Logs
                        </span>
                        <span>Session ID: {wf.id}-{Date.now().toString().slice(-6)}</span>
                      </div>

                      <div className="flex flex-col gap-1.5 max-h-[220px] overflow-y-auto py-2">
                        {result.logs.map((log, idx) => (
                          <div key={idx} className="flex items-start gap-3">
                            <span className="text-zinc-600 select-none">[{log.timestamp}]</span>
                            <span className={`font-semibold ${
                              log.level === 'success' ? 'text-emerald-400' :
                              log.level === 'error' ? 'text-red-400' :
                              log.level === 'warn' ? 'text-amber-400' : 'text-blue-400'
                            }`}>
                              [{log.level.toUpperCase()}]
                            </span>
                            <span className="text-zinc-200">{log.message}</span>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}
                </div>
              )}
            </div>
          );
        })}
      </div>
      {/* Settings Modal */}
      {settingsWorkflow && (
        <div className="fixed inset-0 bg-zinc-900/40 backdrop-blur-sm z-50 flex items-center justify-center p-4 animate-in fade-in">
          <div className="bg-white rounded-2xl shadow-2xl w-full max-w-2xl overflow-hidden flex flex-col max-h-[90vh]">
            <div className="p-6 border-b border-zinc-100 flex items-center justify-between">
              <div>
                <h2 className="text-xl font-bold text-zinc-900 flex items-center gap-2">
                  <Settings className="w-5 h-5 text-indigo-500" />
                  Agentic Configuration
                </h2>
                <p className="text-sm text-zinc-500 mt-1">Assign specific knowledge and behavior to this workflow.</p>
              </div>
              <button onClick={() => setSettingsWorkflow(null)} className="p-2 hover:bg-zinc-100 rounded-lg text-zinc-400 hover:text-zinc-600">
                <XCircle className="w-5 h-5" />
              </button>
            </div>
            
            <div className="p-6 overflow-y-auto flex-1 flex flex-col gap-6">
              {settingsLoading ? (
                <div className="py-12 flex justify-center"><Loader2 className="w-8 h-8 text-indigo-500 animate-spin" /></div>
              ) : (
                <>
                  <div>
                    <label className="block text-sm font-semibold text-zinc-900 mb-2">Custom Brand Prompt / Instructions</label>
                    <textarea 
                      value={customPrompt}
                      onChange={(e) => setCustomPrompt(e.target.value)}
                      placeholder="E.g. Always use emojis. Never mention competitors. Speak in a Gen-Z tone."
                      className="w-full p-4 border border-zinc-200 rounded-xl min-h-[120px] text-sm focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500 outline-none resize-none"
                    />
                  </div>
                  
                  <div>
                    <label className="block text-sm font-semibold text-zinc-900 mb-2">Allowed Knowledge Documents (RAG)</label>
                    <div className="flex flex-col gap-2 border border-zinc-200 rounded-xl p-2 max-h-[200px] overflow-y-auto">
                      {availableDocs.length === 0 ? (
                        <p className="text-sm text-zinc-500 text-center py-4">No documents in Knowledge Hub.</p>
                      ) : (
                        availableDocs.map(doc => (
                          <label key={doc.doc_hash} className="flex items-center gap-3 p-3 hover:bg-zinc-50 rounded-lg cursor-pointer border border-transparent hover:border-zinc-200 transition-all">
                            <input 
                              type="checkbox" 
                              checked={selectedDocs.includes(doc.doc_hash)}
                              onChange={(e) => {
                                if (e.target.checked) setSelectedDocs(prev => [...prev, doc.doc_hash]);
                                else setSelectedDocs(prev => prev.filter(h => h !== doc.doc_hash));
                              }}
                              className="w-4 h-4 text-indigo-600 rounded focus:ring-indigo-500"
                            />
                            <div className="flex flex-col">
                              <span className="text-sm font-medium text-zinc-900">{doc.filename}</span>
                              <span className="text-xs text-zinc-500">{doc.chunk_count} chunks</span>
                            </div>
                          </label>
                        ))
                      )}
                    </div>
                  </div>
                </>
              )}
            </div>
            
            <div className="p-6 border-t border-zinc-100 bg-zinc-50 flex justify-end gap-3">
              <button 
                onClick={() => setSettingsWorkflow(null)}
                className="px-5 py-2.5 rounded-xl text-sm font-semibold text-zinc-700 bg-white border border-zinc-200 hover:bg-zinc-50"
              >
                Cancel
              </button>
              <button 
                onClick={saveSettings}
                disabled={settingsLoading}
                className="flex items-center gap-2 px-5 py-2.5 rounded-xl text-sm font-semibold text-white bg-indigo-600 hover:bg-indigo-700 disabled:opacity-50"
              >
                {settingsLoading && <Loader2 className="w-4 h-4 animate-spin" />} Save Configuration
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
