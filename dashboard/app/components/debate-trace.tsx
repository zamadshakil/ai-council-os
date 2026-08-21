import { Bot, CheckCircle2, MessageSquareWarning, Sparkles } from 'lucide-react';
import { DebateMessage } from '../lib/types';
import { StructuredMessageView } from './structured-output';

export function DebateTrace({ messages }: { messages: DebateMessage[] }) {
  if (messages.length === 0) {
    return <p className="rounded-xl border border-dashed border-white/10 p-6 text-center text-sm text-slate-500">No model steps have been recorded yet.</p>;
  }

  return (
    <ol className="space-y-4">
      {messages.map((message, index) => {
        const Icon = message.role === 'critic' ? MessageSquareWarning : message.role === 'synthesizer' ? Sparkles : Bot;
        return (
          <li key={`${message.timestamp}-${index}`} className="surface-card rounded-xl p-4">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div className="flex items-center gap-2">
                <Icon className="h-4 w-4 text-cyan-300" />
                <span className="text-sm font-bold capitalize text-slate-100">{message.role}</span>
                <code className="rounded bg-white/5 px-2 py-0.5 text-xs text-slate-500">{message.model}</code>
              </div>
              <span className="text-xs text-slate-600">{new Date(message.timestamp).toLocaleString()}</span>
            </div>
            <StructuredMessageView message={message} />
            {message.score_breakdown && (
              <div className="mt-3 flex flex-wrap gap-2">
                {Object.entries(message.score_breakdown).map(([name, score]) => (
                  <span key={name} className="inline-flex items-center gap-1 rounded-full bg-white/5 px-2.5 py-1 text-xs font-medium text-slate-400">
                    <CheckCircle2 className="h-3 w-3 text-emerald-300" /> {name}: {score}
                  </span>
                ))}
              </div>
            )}
          </li>
        );
      })}
    </ol>
  );
}
