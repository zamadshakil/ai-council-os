'use client';

import { useEffect, useState } from 'react';
import { fetchStats } from '../lib/api';
import { Stats } from '../lib/types';
import { Target, Users, BookOpen, Lightbulb, TrendingUp } from 'lucide-react';

const councilIcons: Record<string, any> = {
  sales: Target,
  content: BookOpen,
  grant: Lightbulb,
  strategy: Users
};

export default function AnalyticsPage() {
  const [stats, setStats] = useState<Stats | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetchStats()
      .then(setStats)
      .finally(() => setLoading(false));
  }, []);

  if (loading || !stats) {
    return (
      <div className="space-y-12 animate-pulse">
        <div className="h-12 w-48 bg-zinc-100 rounded-lg"></div>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-8">
          <div className="h-64 bg-zinc-100 rounded-[24px]"></div>
          <div className="h-64 bg-zinc-100 rounded-[24px]"></div>
        </div>
      </div>
    );
  }

  const councils = Object.entries(stats.councils || {});
  const maxTasks = Math.max(...councils.map(([, data]) => data.tasks), 1);

  return (
    <div className="space-y-12 animate-in fade-in duration-700 ease-out fill-mode-both pb-20">
      <div>
        <h1 className="text-[40px] font-bold text-[#111827] tracking-tight leading-none mb-3">Analytics</h1>
        <p className="text-[15px] text-zinc-500">Performance and cost tracking across AI councils.</p>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-8">
        
        {/* Council Volume Comparison */}
        <div className="bg-white p-8 rounded-[24px] shadow-[0_8px_30px_rgb(0,0,0,0.04)] ring-1 ring-transparent hover:shadow-[0_20px_40px_rgb(0,0,0,0.06)] transition-shadow duration-500">
          <div className="flex items-center justify-between mb-8">
            <h2 className="text-[20px] font-semibold text-[#111827] tracking-tight">Execution Volume</h2>
            <div className="p-2 rounded-xl bg-blue-50 text-[#2563EB]">
              <TrendingUp className="w-5 h-5" />
            </div>
          </div>
          
          <div className="space-y-6">
            {councils.length === 0 && <div className="text-zinc-400 text-sm py-4">No data available.</div>}
            {councils.map(([name, data]) => {
              const Icon = councilIcons[name.toLowerCase()] || Users;
              const width = `${Math.max((data.tasks / maxTasks) * 100, 5)}%`;
              return (
                <div key={name} className="space-y-2 group">
                  <div className="flex justify-between text-[14px] font-semibold text-[#111827]">
                    <span className="capitalize flex items-center">
                      <Icon className="w-4 h-4 mr-2 text-zinc-400 group-hover:text-[#2563EB] transition-colors" />
                      {name}
                    </span>
                    <span className="text-zinc-500">{data.tasks} tasks</span>
                  </div>
                  <div className="h-3 w-full bg-zinc-100 rounded-full overflow-hidden">
                    <div 
                      className="h-full bg-gradient-to-r from-[#2563EB] to-violet-500 rounded-full transition-all duration-1000 ease-out" 
                      style={{ width }} 
                    />
                  </div>
                </div>
              );
            })}
          </div>
        </div>

        {/* Confidence Rings */}
        <div className="bg-white p-8 rounded-[24px] shadow-[0_8px_30px_rgb(0,0,0,0.04)] ring-1 ring-transparent hover:shadow-[0_20px_40px_rgb(0,0,0,0.06)] transition-shadow duration-500">
          <div className="flex items-center justify-between mb-8">
            <h2 className="text-[20px] font-semibold text-[#111827] tracking-tight">Average Confidence</h2>
          </div>
          
          <div className="grid grid-cols-2 gap-8">
            {councils.length === 0 && <div className="text-zinc-400 text-sm py-4 col-span-2">No data available.</div>}
            {councils.map(([name, data]) => {
              const confidence = data.avg_confidence > 1 ? data.avg_confidence : data.avg_confidence * 100;
              const radius = 36;
              const circumference = 2 * Math.PI * radius;
              const offset = circumference - (confidence / 100) * circumference;
              const color = confidence >= 80 ? 'text-[#10B981]' : confidence >= 60 ? 'text-[#F59E0B]' : 'text-[#F43F5E]';

              return (
                <div key={name} className="flex flex-col items-center justify-center p-6 rounded-[20px] bg-[#F8FAFC] group hover:bg-white hover:shadow-[0_4px_20px_rgb(0,0,0,0.05)] transition-all duration-300">
                  <div className="relative w-24 h-24 mb-4 flex items-center justify-center">
                    <svg className="w-full h-full transform -rotate-90">
                      <circle cx="48" cy="48" r={radius} stroke="currentColor" strokeWidth="8" fill="none" className="text-zinc-200" />
                      <circle 
                        cx="48" cy="48" r={radius} 
                        stroke="currentColor" strokeWidth="8" fill="none" 
                        strokeDasharray={circumference} strokeDashoffset={offset}
                        strokeLinecap="round"
                        className={`${color} transition-all duration-1000 ease-out drop-shadow-sm`} 
                      />
                    </svg>
                    <span className="absolute text-[18px] font-bold text-[#111827]">{confidence.toFixed(0)}%</span>
                  </div>
                  <h3 className="text-[14px] font-bold text-[#111827] capitalize">{name}</h3>
                  <p className="text-[12px] font-medium text-zinc-400 mt-1">${data.cost.toFixed(2)} total cost</p>
                </div>
              );
            })}
          </div>
        </div>

      </div>
    </div>
  );
}
