import { DebateMessage } from '../lib/types';
import { User, ShieldAlert, Cpu, Loader2, CheckCircle2, Sparkles, AlertCircle } from 'lucide-react';

export function DebateTrace({ 
  history = [], 
  isDebating = false 
}: { 
  history?: DebateMessage[];
  isDebating?: boolean;
}) {
  const hasHistory = Array.isArray(history) && history.length > 0;

  // Case 1: Empty history AND still waiting for first agent message
  if (!hasHistory && isDebating) {
    return (
      <div className="space-y-6">
        <div className="p-5 rounded-2xl bg-blue-50/90 border border-blue-200 text-blue-900 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <Loader2 className="w-5 h-5 text-blue-600 animate-spin shrink-0" />
            <div>
              <p className="font-bold text-sm text-blue-950">AI Council Debate in Progress</p>
              <p className="text-xs text-blue-700 mt-0.5">
                Specialized AI agents (Generator, Critic, Synthesizer) are evaluating and debating via OpenRouter...
              </p>
            </div>
          </div>
          <span className="text-xs font-bold px-3 py-1 bg-blue-600 text-white rounded-full animate-pulse">
            Live Stream
          </span>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <div className="bg-white border-2 border-blue-200 rounded-2xl p-5 shadow-sm space-y-3">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                <div className="w-8 h-8 rounded-xl bg-blue-600 text-white flex items-center justify-center font-bold text-xs shadow-sm">
                  <User className="w-4 h-4" />
                </div>
                <div>
                  <h4 className="text-sm font-bold text-zinc-900">Generator Agent</h4>
                  <p className="text-[11px] text-blue-600 font-medium">Drafting Initial Variant</p>
                </div>
              </div>
              <Loader2 className="w-4 h-4 text-blue-600 animate-spin" />
            </div>
            <p className="text-xs text-zinc-500 bg-blue-50/50 p-3 rounded-xl border border-blue-100 italic">
              Analyzing prompt constraints and drafting v1...
            </p>
          </div>

          <div className="bg-zinc-50 border border-zinc-200 rounded-2xl p-5 shadow-sm space-y-3 opacity-60">
            <div className="flex items-center gap-2">
              <div className="w-8 h-8 rounded-xl bg-amber-500 text-white flex items-center justify-center font-bold text-xs shadow-sm">
                <ShieldAlert className="w-4 h-4" />
              </div>
              <div>
                <h4 className="text-sm font-bold text-zinc-900">Critic Agent</h4>
                <p className="text-[11px] text-zinc-400 font-medium">Quality Audit & Scoring</p>
              </div>
            </div>
            <p className="text-xs text-zinc-400 bg-zinc-100 p-3 rounded-xl border border-zinc-200 italic">
              Awaiting draft to audit tone, personalization, and platform specs...
            </p>
          </div>
        </div>
      </div>
    );
  }

  // Case 2: Empty history and NOT debating
  if (!hasHistory && !isDebating) {
    return (
      <div className="py-10 text-center bg-zinc-50 rounded-2xl border border-zinc-200/80 p-6">
        <CheckCircle2 className="w-8 h-8 text-zinc-400 mx-auto mb-2" />
        <p className="text-sm font-bold text-zinc-700">Single-pass Output Generated</p>
        <p className="text-xs text-zinc-500 mt-1">No multi-step debate traces recorded for this item.</p>
      </div>
    );
  }

  // Case 3: WE HAVE REAL HISTORY MESSAGES!
  return (
    <div className="space-y-6">
      {/* Top Banner if still debating */}
      {isDebating && (
        <div className="p-4 rounded-2xl bg-blue-50 border border-blue-200 flex items-center justify-between">
          <div className="flex items-center gap-2.5">
            <Loader2 className="w-4 h-4 text-blue-600 animate-spin" />
            <span className="text-xs font-bold text-blue-900">Debate in Progress — Next AI agent is refining the output...</span>
          </div>
          <span className="text-[11px] font-bold text-blue-700 bg-blue-100 px-2.5 py-1 rounded-full">
            {history.length} round{history.length > 1 ? 's' : ''} completed
          </span>
        </div>
      )}

      {/* Cards list - full width horizontal/card layout */}
      <div className="flex flex-col gap-5">
        {history.map((msg, idx) => {
          const roleLower = msg.role.toLowerCase();
          const isGenerator = roleLower.includes('generator');
          const isCritic = roleLower.includes('critic');
          const isSynthesizer = roleLower.includes('synthesizer');

          const rawScore = msg.confidence_score || 0;
          const normalizedScore = rawScore > 1 ? rawScore : rawScore * 100;

          // Theme setup
          let theme: {
            cardBg: string;
            border: string;
            badgeBg: string;
            iconBg: string;
            icon: any;
            title: string;
            subtitle: string;
          } = {
            cardBg: 'bg-white',
            border: 'border-zinc-200',
            badgeBg: 'bg-zinc-100 text-zinc-700',
            iconBg: 'bg-zinc-900 text-white',
            icon: User,
            title: String(msg.role),
            subtitle: 'AI Council Member'
          };

          if (isGenerator) {
            theme = {
              cardBg: 'bg-gradient-to-r from-blue-50/40 via-white to-white',
              border: 'border-blue-200/80',
              badgeBg: 'bg-blue-100 text-blue-700 border border-blue-200',
              iconBg: 'bg-blue-600 text-white',
              icon: User,
              title: 'Generator Agent',
              subtitle: 'Draft Creation'
            };
          } else if (isCritic) {
            theme = {
              cardBg: 'bg-gradient-to-r from-amber-50/40 via-white to-white',
              border: 'border-amber-200/80',
              badgeBg: 'bg-amber-100 text-amber-800 border border-amber-200',
              iconBg: 'bg-amber-500 text-white',
              icon: ShieldAlert,
              title: 'Critic Agent',
              subtitle: 'Quality & Consistency Evaluation'
            };
          } else if (isSynthesizer) {
            theme = {
              cardBg: 'bg-gradient-to-r from-emerald-50/40 via-white to-white',
              border: 'border-emerald-200/80',
              badgeBg: 'bg-emerald-100 text-emerald-800 border border-emerald-200',
              iconBg: 'bg-emerald-600 text-white',
              icon: Cpu,
              title: 'Synthesizer Agent',
              subtitle: 'Consensus Resolution'
            };
          }

          const IconComp = theme.icon;

          return (
            <div 
              key={idx} 
              className={`rounded-2xl border ${theme.border} ${theme.cardBg} p-6 shadow-sm transition-all hover:shadow-md space-y-4`}
            >
              {/* Card Header */}
              <div className="flex items-center justify-between flex-wrap gap-3 pb-3 border-b border-zinc-100">
                <div className="flex items-center gap-3">
                  <div className={`w-9 h-9 rounded-xl ${theme.iconBg} flex items-center justify-center shadow-sm shrink-0`}>
                    <IconComp className="w-5 h-5" />
                  </div>
                  <div>
                    <div className="flex items-center gap-2">
                      <h4 className="text-sm font-bold text-zinc-900">{theme.title}</h4>
                      <span className="text-[11px] font-semibold text-zinc-400">• Step {idx + 1}</span>
                    </div>
                    <p className="text-xs text-zinc-500">{theme.subtitle}</p>
                  </div>
                </div>

                <div className="flex items-center gap-2">
                  <span className={`text-[11px] font-semibold px-2.5 py-1 rounded-lg ${theme.badgeBg}`}>
                    {msg.model || 'OpenRouter'}
                  </span>

                  {isCritic && normalizedScore > 0 && (
                    <span className={`text-xs font-bold px-3 py-1 rounded-full border shadow-sm ${
                      normalizedScore >= 80 ? 'bg-emerald-50 text-emerald-700 border-emerald-200' :
                      normalizedScore >= 60 ? 'bg-amber-50 text-amber-700 border-amber-200' :
                      'bg-red-50 text-red-700 border-red-200'
                    }`}>
                      {normalizedScore.toFixed(0)}% Confidence Score
                    </span>
                  )}

                  {msg.timestamp && (
                    <span className="text-[11px] font-medium text-zinc-400 bg-zinc-50 px-2.5 py-1 rounded-lg border border-zinc-200">
                      {new Date(msg.timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })}
                    </span>
                  )}
                </div>
              </div>

              {/* Content Body */}
              <div className="text-sm text-zinc-800 leading-relaxed font-medium whitespace-pre-wrap bg-white/80 p-5 rounded-xl border border-zinc-200/70 shadow-inner overflow-x-auto">
                {msg.content}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

