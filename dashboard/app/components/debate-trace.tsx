import { DebateMessage } from '../lib/types';
import { User, ShieldAlert, Cpu, Loader2, Sparkles, CheckCircle2 } from 'lucide-react';

export function DebateTrace({ 
  history, 
  isDebating = false 
}: { 
  history: DebateMessage[];
  isDebating?: boolean;
}) {
  if (history.length === 0 || isDebating) {
    return (
      <div className="space-y-6 pt-2">
        <div className="p-4 rounded-[16px] bg-blue-50/80 border border-blue-200/80 text-blue-900 text-xs flex items-start gap-3">
          <Loader2 className="w-4 h-4 text-blue-600 animate-spin shrink-0 mt-0.5" />
          <div>
            <p className="font-bold text-[13px] text-blue-950">AI Council Debate in Progress</p>
            <p className="text-blue-700/90 mt-0.5 leading-relaxed">
              Multiple specialized AI models are debating, critiquing, and synthesizing consensus output.
            </p>
          </div>
        </div>

        {/* Live Step Timeline */}
        <div className="relative pl-6 space-y-6 before:absolute before:inset-0 before:ml-[1.4rem] before:-translate-x-px before:h-full before:w-0.5 before:bg-blue-200/60">
          
          {/* Step 1: Generator */}
          <div className="relative flex items-start group">
            <div className="absolute -left-6 w-5 h-5 rounded-full bg-blue-600 text-white flex items-center justify-center ring-4 ring-white shadow-md z-10 animate-pulse">
              <User className="w-3 h-3" />
            </div>
            <div className="ml-4 w-full">
              <div className="flex items-center gap-2 mb-1">
                <span className="text-xs font-bold text-zinc-900">Generator Agent</span>
                <span className="px-1.5 py-0.5 bg-blue-100 text-blue-700 rounded text-[10px] font-bold">GPT-4o Mini</span>
                <span className="text-[10px] text-blue-600 font-semibold flex items-center gap-1">
                  <Loader2 className="w-2.5 h-2.5 animate-spin" /> Drafting V1
                </span>
              </div>
              <div className="bg-white border border-blue-200 rounded-[12px] p-3 text-xs text-zinc-600 shadow-sm animate-pulse">
                Analyzing request constraints and drafting initial multi-platform variant...
              </div>
            </div>
          </div>

          {/* Step 2: Critic */}
          <div className="relative flex items-start group opacity-75">
            <div className="absolute -left-6 w-5 h-5 rounded-full bg-amber-500 text-white flex items-center justify-center ring-4 ring-white shadow-sm z-10">
              <ShieldAlert className="w-3 h-3" />
            </div>
            <div className="ml-4 w-full">
              <div className="flex items-center gap-2 mb-1">
                <span className="text-xs font-bold text-zinc-900">Critic Agent</span>
                <span className="px-1.5 py-0.5 bg-amber-100 text-amber-800 rounded text-[10px] font-bold">GPT-4o</span>
                <span className="text-[10px] text-amber-600 font-semibold">Evaluating Quality</span>
              </div>
              <div className="bg-zinc-50 border border-zinc-200 rounded-[12px] p-3 text-xs text-zinc-500">
                Awaiting draft... Will review hook quality, platform fit, and assign confidence score.
              </div>
            </div>
          </div>

          {/* Step 3: Synthesizer */}
          <div className="relative flex items-start group opacity-50">
            <div className="absolute -left-6 w-5 h-5 rounded-full bg-emerald-500 text-white flex items-center justify-center ring-4 ring-white shadow-sm z-10">
              <Cpu className="w-3 h-3" />
            </div>
            <div className="ml-4 w-full">
              <div className="flex items-center gap-2 mb-1">
                <span className="text-xs font-bold text-zinc-900">Synthesizer Agent</span>
                <span className="px-1.5 py-0.5 bg-emerald-100 text-emerald-800 rounded text-[10px] font-bold">Consensus</span>
              </div>
              <div className="bg-zinc-50 border border-zinc-200 rounded-[12px] p-3 text-xs text-zinc-400">
                Merges generator draft & critic revisions into final approved output.
              </div>
            </div>
          </div>

        </div>
      </div>
    );
  }

  return (
    <div className="relative pl-6 space-y-6 before:absolute before:inset-0 before:ml-[1.4rem] before:-translate-x-px md:before:mx-auto md:before:translate-x-0 before:h-full before:w-0.5 before:bg-zinc-200 before:bg-gradient-to-b before:from-transparent before:via-zinc-200 before:to-transparent pt-2">
      {history.map((msg, idx) => {
        const isGenerator = msg.role === 'generator';
        const isCritic = msg.role === 'critic';
        const isSynthesizer = msg.role === 'synthesizer';

        const rawScore = msg.confidence_score || 0;
        const normalizedScore = rawScore > 1 ? rawScore : rawScore * 100;

        return (
          <div key={idx} className="relative flex items-start group">
            <div className={`absolute -left-6 w-5 h-5 rounded-full flex items-center justify-center ring-4 ring-white shadow-sm z-10 ${
              isGenerator ? 'bg-blue-600 text-white' : 
              isCritic ? 'bg-amber-500 text-white' : 
              'bg-emerald-600 text-white'
            }`}>
              {isGenerator ? <User className="w-3 h-3" /> : 
               isCritic ? <ShieldAlert className="w-3 h-3" /> : 
               <Cpu className="w-3 h-3" />}
            </div>
            
            <div className="ml-4 w-full">
              <div className="flex items-center space-x-2 mb-1.5 flex-wrap gap-1">
                <span className="text-xs font-bold capitalize text-zinc-900">{msg.role}</span>
                <span className="px-1.5 py-0.5 bg-zinc-100 text-zinc-600 rounded text-[10px] font-semibold tracking-wider">
                  {msg.model || 'OpenRouter'}
                </span>
                {isCritic && normalizedScore > 0 && (
                  <span className={`text-[10px] font-bold px-2 py-0.5 rounded-full ${
                    normalizedScore >= 80 ? 'bg-emerald-100 text-emerald-700' :
                    normalizedScore >= 60 ? 'bg-amber-100 text-amber-700' :
                    'bg-red-100 text-red-700'
                  }`}>
                    {normalizedScore.toFixed(0)}% Score
                  </span>
                )}
              </div>
              <div className="bg-white border border-zinc-200 rounded-[14px] p-4 text-xs text-zinc-700 shadow-sm leading-relaxed whitespace-pre-wrap">
                {msg.content}
              </div>
              <div className="text-[10px] text-zinc-400 mt-1.5 ml-1 font-medium">
                {msg.timestamp ? new Date(msg.timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' }) : ''}
              </div>
            </div>
          </div>
        );
      })}
    </div>
  );
}
