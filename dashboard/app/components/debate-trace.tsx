import { DebateMessage } from '../lib/types';
import { User, ShieldAlert, Cpu } from 'lucide-react';

export function DebateTrace({ history }: { history: DebateMessage[] }) {
  return (
    <div className="relative pl-6 space-y-6 before:absolute before:inset-0 before:ml-[1.4rem] before:-translate-x-px md:before:mx-auto md:before:translate-x-0 before:h-full before:w-0.5 before:bg-zinc-200 before:bg-gradient-to-b before:from-transparent before:via-zinc-200 before:to-transparent pt-2">
      {history.map((msg, idx) => {
        const isGenerator = msg.role === 'generator';
        const isCritic = msg.role === 'critic';
        const isSynthesizer = msg.role === 'synthesizer';

        return (
          <div key={idx} className="relative flex items-start group">
            <div className={`absolute -left-6 w-5 h-5 rounded-full flex items-center justify-center ring-4 ring-white shadow-sm z-10 ${
              isGenerator ? 'bg-blue-100 text-blue-600' : 
              isCritic ? 'bg-amber-100 text-amber-600' : 
              'bg-emerald-100 text-emerald-600'
            }`}>
              {isGenerator ? <User className="w-3 h-3" /> : 
               isCritic ? <ShieldAlert className="w-3 h-3" /> : 
               <Cpu className="w-3 h-3" />}
            </div>
            
            <div className="ml-4 w-full">
              <div className="flex items-center space-x-2 mb-1">
                <span className="text-xs font-semibold capitalize text-zinc-900">{msg.role}</span>
                <span className="px-1.5 py-0.5 bg-zinc-100 text-zinc-500 rounded text-[10px] font-medium tracking-wider">
                  {msg.model}
                </span>
                {isCritic && msg.confidence_score && (
                  <span className={`text-[10px] font-medium px-1.5 py-0.5 rounded ${
                    msg.confidence_score >= 0.8 ? 'bg-green-50 text-green-700' :
                    msg.confidence_score >= 0.6 ? 'bg-amber-50 text-amber-700' :
                    'bg-red-50 text-red-700'
                  }`}>
                    {Math.round(msg.confidence_score * 100)}% Match
                  </span>
                )}
              </div>
              <div className="bg-white border border-zinc-200 rounded-md p-3 text-sm text-zinc-600 shadow-sm">
                {msg.content}
              </div>
              <div className="text-[10px] text-zinc-400 mt-1 ml-1">
                {new Date(msg.timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })}
              </div>
            </div>
          </div>
        );
      })}
    </div>
  );
}
