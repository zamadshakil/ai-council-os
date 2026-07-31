'use client';

import { useState, useEffect } from 'react';
import { fetchStats, fetchTasks, fetchKillSwitch, fetchIntegrationsStatus } from './lib/api';
import { Task, Stats, KillSwitchStatus } from './lib/types';
import { 
  Clock, ArrowRight, Brain, Zap, Target, BookOpen, Activity, 
  Shield, ShieldOff, TrendingUp, DollarSign, CheckCircle2, AlertCircle,
  MessageCircle, Video, FileText, Share2, Plug, PlugZap
} from 'lucide-react';
import Link from 'next/link';
import { formatDistanceToNow } from 'date-fns';

const workflowIcons: Record<string, any> = {
  youtube_comments: Video,
  reddit_prospector: MessageCircle,
  youtube_descriptions: FileText,
  content_engine: Share2,
};

export default function OverviewPage() {
  const [stats, setStats] = useState<Stats | null>(null);
  const [tasks, setTasks] = useState<Task[]>([]);
  const [killSwitch, setKillSwitch] = useState<KillSwitchStatus | null>(null);
  const [integrations, setIntegrations] = useState<{ hubspot: { configured: boolean }; publishing: Record<string, boolean> } | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    async function load() {
      try {
        const [s, t, k, i] = await Promise.all([
          fetchStats(),
          fetchTasks('awaiting_approval'),
          fetchKillSwitch(),
          fetchIntegrationsStatus().catch(() => null),
        ]);
        setStats(s);
        setTasks(t.slice(0, 6));
        setKillSwitch(k);
        setIntegrations(i);
      } catch (e) {
        console.error('Failed to load overview:', e);
      } finally {
        setLoading(false);
      }
    }
    load();
    const interval = setInterval(load, 20000);
    return () => clearInterval(interval);
  }, []);

  if (loading) {
    return (
      <div className="flex flex-col gap-8 animate-pulse">
        <div className="h-32 bg-zinc-200/50 rounded-[24px]" />
        <div className="grid grid-cols-4 gap-4">
          {[1,2,3,4].map(i => <div key={i} className="h-28 bg-zinc-200/50 rounded-[16px]" />)}
        </div>
        <div className="h-64 bg-zinc-200/50 rounded-[24px]" />
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-8 animate-in fade-in duration-300 ease-out fill-mode-both pb-16">
      
      {/* Hero Status Banner */}
      <div className={`p-6 rounded-[20px] border flex items-center justify-between ${
        killSwitch?.is_active 
          ? 'bg-gradient-to-r from-red-50 to-red-100/50 border-red-200' 
          : 'bg-gradient-to-r from-emerald-50 to-blue-50 border-emerald-200'
      }`}>
        <div className="flex items-center gap-4">
          <div className={`w-12 h-12 rounded-[14px] flex items-center justify-center ${
            killSwitch?.is_active ? 'bg-red-100' : 'bg-emerald-100'
          }`}>
            {killSwitch?.is_active ? <ShieldOff className="w-6 h-6 text-red-600" /> : <Shield className="w-6 h-6 text-emerald-600" />}
          </div>
          <div>
            <h2 className={`text-[18px] font-bold ${killSwitch?.is_active ? 'text-red-800' : 'text-emerald-800'}`}>
              {killSwitch?.is_active ? 'System Paused — Kill Switch Active' : 'AI Council OS — All Systems Operational'}
            </h2>
            <p className={`text-[14px] mt-0.5 ${killSwitch?.is_active ? 'text-red-600' : 'text-emerald-600'}`}>
              {killSwitch?.is_active 
                ? `Paused by ${killSwitch.toggled_by}. No workflows will run until resumed.`
                : `${stats?.pending || 0} tasks awaiting your review`
              }
            </p>
          </div>
        </div>
        <Link href="/workflows" className="h-10 px-6 bg-zinc-900 text-white rounded-[10px] text-[14px] font-semibold flex items-center gap-2 hover:bg-zinc-800 active:scale-[0.98] transition-all shadow-sm">
          <Zap className="w-4 h-4" /> Workflows
        </Link>
      </div>

      {/* Stats Grid */}
      {stats && (
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
          {[
            { label: 'Pending Review', value: stats.pending, icon: AlertCircle, color: 'text-amber-600', bg: 'bg-amber-50', border: 'border-amber-200' },
            { label: 'Approved', value: stats.approved, icon: CheckCircle2, color: 'text-emerald-600', bg: 'bg-emerald-50', border: 'border-emerald-200' },
            { label: 'Total Tasks', value: stats.total_tasks, icon: TrendingUp, color: 'text-blue-600', bg: 'bg-blue-50', border: 'border-blue-200' },
            { label: 'Total Cost', value: `$${stats.total_cost_usd.toFixed(2)}`, icon: DollarSign, color: 'text-violet-600', bg: 'bg-violet-50', border: 'border-violet-200' },
          ].map((stat) => (
            <div key={stat.label} className="bg-white border border-zinc-200 rounded-[16px] p-5 shadow-sm hover:shadow-floating transition-all duration-200">
              <div className="flex items-center gap-2.5 mb-3">
                <div className={`w-8 h-8 rounded-[8px] ${stat.bg} border ${stat.border} flex items-center justify-center`}>
                  <stat.icon className={`w-4 h-4 ${stat.color}`} />
                </div>
                <span className="text-[12px] font-semibold text-zinc-500 uppercase tracking-wider">{stat.label}</span>
              </div>
              <p className="text-[28px] font-bold text-zinc-900 tracking-tight">{stat.value}</p>
            </div>
          ))}
        </div>
      )}

      {/* Council Performance */}
      {stats && Object.keys(stats.councils).length > 0 && (
        <div className="bg-white border border-zinc-200 rounded-[20px] p-6 shadow-sm">
          <h3 className="text-[16px] font-bold text-zinc-900 mb-4">Council Performance</h3>
          <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
            {Object.entries(stats.councils).map(([name, data]) => (
              <div key={name} className="p-4 bg-zinc-50 rounded-[12px] border border-zinc-100">
                <p className="text-[12px] font-bold text-zinc-500 uppercase tracking-widest mb-2">{name}</p>
                <p className="text-[20px] font-bold text-zinc-900">{data.tasks} <span className="text-[13px] font-medium text-zinc-500">tasks</span></p>
                <div className="flex items-center gap-3 mt-2 text-[12px] font-medium text-zinc-500">
                  <span>${data.cost.toFixed(3)}</span>
                  <span>·</span>
                  <span>{data.avg_confidence.toFixed(0)}% avg</span>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Integration Status — real connection state, never assumed */}
      {integrations && (
        <div className="bg-white border border-zinc-200 rounded-[20px] p-6 shadow-sm">
          <h3 className="text-[16px] font-bold text-zinc-900 mb-4">CRM & Publishing Integrations</h3>
          <div className="grid grid-cols-2 lg:grid-cols-5 gap-3">
            {[
              { label: 'HubSpot CRM', connected: integrations.hubspot?.configured },
              { label: 'Instagram', connected: integrations.publishing?.instagram },
              { label: 'LinkedIn', connected: integrations.publishing?.linkedin },
              { label: 'Facebook', connected: integrations.publishing?.facebook },
              { label: 'X / Twitter', connected: integrations.publishing?.twitter },
            ].map((item) => (
              <div
                key={item.label}
                className={`flex items-center gap-2 p-3 rounded-[12px] border text-[13px] font-semibold ${
                  item.connected
                    ? 'bg-emerald-50 border-emerald-200 text-emerald-700'
                    : 'bg-zinc-50 border-zinc-200 text-zinc-500'
                }`}
              >
                {item.connected ? <PlugZap className="w-4 h-4" /> : <Plug className="w-4 h-4" />}
                <span>{item.label}</span>
              </div>
            ))}
          </div>
          {!integrations.hubspot?.configured && (
            <p className="text-[12.5px] text-zinc-400 mt-3">
              HubSpot not connected yet — add HUBSPOT_ACCESS_TOKEN to enable automatic contact/deal sync on approved Sales Council outreach.
            </p>
          )}
        </div>
      )}

      {/* Pending Tasks */}
      <div className="bg-white border border-zinc-200 rounded-[20px] p-6 shadow-sm">
        <div className="flex items-center justify-between mb-6">
          <h3 className="text-[16px] font-bold text-zinc-900">Pending Approvals</h3>
          <Link href="/approvals" className="text-[13px] font-semibold text-blue-600 hover:text-blue-800 flex items-center transition-colors">
            View all <ArrowRight className="w-4 h-4 ml-1" />
          </Link>
        </div>
        
        {tasks.length === 0 ? (
          <div className="py-16 text-center border border-dashed border-zinc-200 rounded-[16px]">
            <CheckCircle2 className="w-8 h-8 text-emerald-400 mx-auto mb-3" />
            <p className="text-[15px] text-zinc-500 font-medium">All clear! No tasks pending.</p>
          </div>
        ) : (
          <div className="flex flex-col gap-3">
            {tasks.map((task) => {
              const WfIcon = workflowIcons[task.context?.workflow] || Brain;
              return (
                <Link
                  key={task.task_id}
                  href={`/approvals/${task.task_id}`}
                  className="flex items-center gap-4 p-4 rounded-[14px] hover:bg-zinc-50 border border-transparent hover:border-zinc-200 transition-all group"
                >
                  <div className="w-10 h-10 rounded-[10px] bg-zinc-100 border border-zinc-200 flex items-center justify-center shrink-0 group-hover:scale-105 transition-transform">
                    <WfIcon className="w-5 h-5 text-zinc-600" />
                  </div>
                  <div className="flex-1 min-w-0">
                    <p className="text-[14px] font-semibold text-zinc-900 truncate group-hover:text-blue-700 transition-colors">
                      {task.task_description}
                    </p>
                    <p className="text-[13px] text-zinc-500 mt-0.5">
                      {task.council} council · {task.confidence_score.toFixed(0)}% confidence · {formatDistanceToNow(new Date(task.created_at))} ago
                    </p>
                  </div>
                  <div className="shrink-0">
                    <span className="px-3 py-1 text-[11px] font-bold uppercase tracking-widest text-amber-700 bg-amber-50 border border-amber-200 rounded-[6px]">
                      Review
                    </span>
                  </div>
                </Link>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}
