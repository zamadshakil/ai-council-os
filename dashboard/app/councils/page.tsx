'use client';

import { useState } from 'react';
import { useRouter } from 'next/navigation';
import { runCouncil } from '../lib/api';
import { Target, Users, BookOpen, Lightbulb, Paperclip, Send, Sparkles } from 'lucide-react';

const COUNCILS = [
  { id: 'sales', name: 'Sales Council', icon: Target, desc: 'Outbound emails & pitch decks.', agents: 3, cost: '~$0.12', time: '45s', recommended: true },
  { id: 'content', name: 'Content Council', icon: BookOpen, desc: 'SEO blogs & social media.', agents: 4, cost: '~$0.18', time: '1m 20s' },
  { id: 'grant', name: 'Grant Council', icon: Lightbulb, desc: 'Proposals & applications.', agents: 5, cost: '~$0.30', time: '2m 15s' },
  { id: 'strategy', name: 'Strategy Council', icon: Users, desc: 'Market analysis & planning.', agents: 6, cost: '~$0.45', time: '3m 30s' },
];

const SUGGESTIONS = [
  "Draft a cold email sequence for VP of Engineering regarding our new API...",
  "Analyze the recent Q3 earnings report and extract 3 key marketing angles...",
  "Write a 1500-word SEO optimized blog post about AI in supply chain..."
];

export default function CouncilsPage() {
  const router = useRouter();
  const [selected, setSelected] = useState(COUNCILS[0].id);
  const [taskDesc, setTaskDesc] = useState('');
  const [priority, setPriority] = useState('medium');
  const [loading, setLoading] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);
    try {
      await runCouncil({
        council: selected,
        task_description: taskDesc,
        context: { priority }
      });
      router.push('/approvals');
    } catch (error) {
      console.error('Failed to run council', error);
      setLoading(false);
    }
  };

  return (
    <div className="max-w-[960px] mx-auto flex flex-col gap-10 animate-in fade-in duration-300 ease-out fill-mode-both pb-16">
      <div className="text-center pt-6 flex flex-col gap-3">
        <h1 className="text-[32px] font-bold text-zinc-900 tracking-tight leading-none">Select Council</h1>
        <p className="text-[15px] text-zinc-600 max-w-md mx-auto leading-relaxed">Choose a specialized AI council to route your task. Each council is optimized with specific agent roles.</p>
      </div>

      <form onSubmit={handleSubmit} className="flex flex-col gap-10">
        <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
          {COUNCILS.map((c, idx) => {
            const Icon = c.icon;
            const isSelected = selected === c.id;
            return (
              <div
                key={c.id}
                onClick={() => setSelected(c.id)}
                role="button"
                tabIndex={0}
                onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); setSelected(c.id); } }}
                className={`relative p-6 rounded-[20px] cursor-pointer transition-all duration-200 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-offset-2 focus-visible:ring-blue-600 ${
                  isSelected 
                    ? 'bg-white border-2 border-blue-600 shadow-[0_8px_30px_rgb(37,99,235,0.12)] scale-[1.01]' 
                    : 'bg-white border border-zinc-200 hover:border-zinc-300 shadow-sm hover:shadow-floating hover:-translate-y-[2px]'
                }`}
              >
                {c.recommended && (
                  <span className="absolute -top-3 right-6 px-3 py-1 bg-gradient-to-r from-blue-600 to-violet-600 text-white text-[11px] font-bold tracking-widest uppercase rounded-[6px] shadow-sm flex items-center">
                    <Sparkles className="w-3 h-3 mr-1.5" /> Recommended
                  </span>
                )}
                <div className="flex items-start gap-5">
                  <div className={`p-4 rounded-[12px] border transition-colors duration-200 ${isSelected ? 'bg-blue-50 text-blue-700 border-blue-200' : 'bg-zinc-50 text-zinc-600 border-zinc-200'}`}>
                    <Icon className="w-6 h-6" />
                  </div>
                  <div className="flex flex-col gap-1 flex-1 pt-1">
                    <h3 className={`text-[16px] font-bold transition-colors ${isSelected ? 'text-zinc-900' : 'text-zinc-800'}`}>{c.name}</h3>
                    <p className="text-[14px] text-zinc-600 mb-2">{c.desc}</p>
                    <div className="flex items-center gap-4 text-[13px] font-semibold text-zinc-500">
                      <span className="flex items-center"><Users className="w-4 h-4 mr-1.5 text-zinc-400"/> {c.agents} Agents</span>
                      <span className="flex items-center"><Target className="w-4 h-4 mr-1.5 text-zinc-400"/> {c.cost}</span>
                    </div>
                  </div>
                </div>
              </div>
            );
          })}
        </div>

        <div className="flex flex-col gap-4">
          <div className="flex items-center justify-between px-1">
            <h2 className="text-[18px] font-semibold text-zinc-900 tracking-tight">Task Prompt</h2>
            <div className="flex items-center gap-2">
              <span className="text-[13px] font-semibold text-zinc-600 px-3 py-1 rounded-[6px] bg-white border border-zinc-200 shadow-sm">
                Priority: Normal
              </span>
            </div>
          </div>
          
          <div className="bg-white p-2 rounded-[24px] shadow-premium ring-1 ring-zinc-200 focus-within:ring-2 focus-within:ring-blue-600 focus-within:shadow-floating transition-all duration-200 relative">
            <textarea
              value={taskDesc}
              onChange={(e) => setTaskDesc(e.target.value)}
              required
              placeholder="What would you like the council to execute? Be as specific as possible..."
              className="w-full bg-transparent text-[16px] p-6 pb-20 min-h-[240px] resize-none outline-none placeholder:text-zinc-500 text-zinc-900 leading-relaxed font-medium"
            />
            
            <div className="absolute bottom-4 left-4 right-4 flex items-center justify-between">
              <div className="flex gap-2">
                <button 
                  type="button" 
                  className="p-3 text-zinc-500 hover:text-zinc-900 hover:bg-zinc-100 active:scale-[0.98] rounded-[10px] transition-all focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-offset-2 focus-visible:ring-zinc-800"
                  aria-label="Attach file"
                >
                  <Paperclip className="w-5 h-5" />
                </button>
              </div>
              <button
                type="submit"
                disabled={loading || !taskDesc}
                className="h-11 px-8 bg-zinc-900 text-white font-semibold text-[14px] rounded-[12px] shadow-[0_4px_12px_rgba(24,24,27,0.1)] hover:bg-zinc-800 active:scale-[0.98] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-offset-2 focus-visible:ring-zinc-800 disabled:opacity-50 disabled:cursor-not-allowed transition-all flex items-center"
              >
                {loading ? 'Dispatching...' : 'Run Council'}
                {!loading && <Send className="w-4 h-4 ml-2" />}
              </button>
            </div>
          </div>

          <div className="flex flex-wrap items-center gap-2 px-1">
            <span className="text-[13px] font-semibold text-zinc-500 py-1 mr-2">Suggestions:</span>
            {SUGGESTIONS.map((suggestion, idx) => (
              <button
                key={idx}
                type="button"
                onClick={() => setTaskDesc(suggestion)}
                className="text-[13px] font-semibold text-zinc-600 bg-white border border-zinc-200 shadow-sm hover:shadow-floating hover:border-zinc-300 hover:-translate-y-[1px] hover:text-zinc-900 active:scale-[0.98] h-8 px-4 rounded-[8px] transition-all duration-200 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-offset-2 focus-visible:ring-zinc-800"
              >
                {suggestion.slice(0, 35)}...
              </button>
            ))}
          </div>
        </div>
      </form>
    </div>
  );
}
