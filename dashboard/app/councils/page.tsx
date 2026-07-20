'use client';

import { useState } from 'react';
import { useRouter } from 'next/navigation';
import { runCouncil } from '../lib/api';
import { Target, Users, BookOpen, Lightbulb } from 'lucide-react';

const COUNCILS = [
  { id: 'sales', name: 'Sales Council', icon: Target, desc: 'Outbound emails, pitch decks' },
  { id: 'content', name: 'Content Council', icon: BookOpen, desc: 'Blog posts, social media' },
  { id: 'grant', name: 'Grant Council', icon: Lightbulb, desc: 'Proposals, applications' },
  { id: 'strategy', name: 'Strategy Council', icon: Users, desc: 'Market analysis, planning' },
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
    <div className="space-y-8 max-w-3xl animate-in fade-in duration-500">
      <div>
        <h1 className="text-2xl font-semibold text-zinc-900 tracking-tight">Run a Council</h1>
        <p className="text-sm text-zinc-500 mt-1">Dispatch a new task to a specialized agent council.</p>
      </div>

      <form onSubmit={handleSubmit} className="space-y-8">
        <div className="space-y-3">
          <label className="text-sm font-medium text-zinc-900">Select Council</label>
          <div className="grid grid-cols-2 gap-4">
            {COUNCILS.map((c) => {
              const Icon = c.icon;
              const isSelected = selected === c.id;
              return (
                <div
                  key={c.id}
                  onClick={() => setSelected(c.id)}
                  className={`p-4 rounded-lg border-2 cursor-pointer transition-all duration-200 ${
                    isSelected ? 'border-blue-600 bg-blue-50/50' : 'border-zinc-200 hover:border-zinc-300 bg-white'
                  }`}
                >
                  <div className="flex items-center space-x-3 mb-1">
                    <Icon className={`w-5 h-5 ${isSelected ? 'text-blue-600' : 'text-zinc-500'}`} />
                    <h3 className={`font-medium ${isSelected ? 'text-blue-900' : 'text-zinc-900'}`}>{c.name}</h3>
                  </div>
                  <p className="text-xs text-zinc-500 ml-8">{c.desc}</p>
                </div>
              );
            })}
          </div>
        </div>

        <div className="space-y-3">
          <label className="text-sm font-medium text-zinc-900">Task Description</label>
          <textarea
            value={taskDesc}
            onChange={(e) => setTaskDesc(e.target.value)}
            required
            placeholder="Describe what the council needs to accomplish..."
            className="w-full text-sm p-4 border border-zinc-200 rounded-lg min-h-[120px] focus:ring-2 focus:ring-blue-500 focus:border-blue-500 outline-none"
          />
        </div>

        <div className="space-y-3 border-t border-zinc-200 pt-6">
          <div className="flex justify-between items-center">
            <label className="text-sm font-medium text-zinc-900">Priority</label>
            <span className="text-xs text-zinc-500">Estimated Cost: {
              priority === 'low' ? '~$0.05' : priority === 'medium' ? '~$0.10' : priority === 'high' ? '~$0.25' : '~$0.50'
            }</span>
          </div>
          <select 
            value={priority}
            onChange={(e) => setPriority(e.target.value)}
            className="w-full text-sm p-3 border border-zinc-200 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500 outline-none"
          >
            <option value="low">Low - 1 Iteration</option>
            <option value="medium">Medium - 2 Iterations</option>
            <option value="high">High - 3 Iterations</option>
            <option value="critical">Critical - Until 95% Confidence</option>
          </select>
        </div>

        <button
          type="submit"
          disabled={loading || !taskDesc}
          className="w-full py-3 bg-blue-600 text-white font-medium rounded-lg hover:bg-blue-700 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
        >
          {loading ? 'Dispatching...' : 'Dispatch Council Task'}
        </button>
      </form>
    </div>
  );
}
