import { ReactNode } from 'react';

interface StatsCardProps {
  title: string;
  value: string | number;
  subtitle?: string;
  icon: ReactNode;
  iconClassName?: string;
  trend?: { value: number; positive: boolean };
}

export function StatsCard({ title, value, subtitle, icon, iconClassName, trend }: StatsCardProps) {
  return (
    <div className="bg-white p-8 rounded-[24px] shadow-[0_8px_30px_rgb(0,0,0,0.04)] hover:shadow-[0_8px_30px_rgb(0,0,0,0.08)] transition-all duration-500 flex flex-col justify-between relative overflow-hidden group">
      <div className="flex items-start justify-between relative z-10">
        <div>
          <p className="text-[15px] font-medium text-zinc-500 mb-2">{title}</p>
          <h3 className="text-[40px] font-bold tracking-tight text-[#111827] leading-none">{value}</h3>
        </div>
        <div className={`p-3 rounded-2xl transition-transform duration-500 group-hover:scale-110 ${iconClassName || 'bg-zinc-50 text-zinc-500'}`}>
          {icon}
        </div>
      </div>
      
      <div className="mt-8 flex items-end justify-between relative z-10">
        <div className="flex items-center space-x-2">
          {trend ? (
            <span className={`text-[13px] font-semibold flex items-center px-2 py-1 rounded-lg ${
              trend.positive ? 'bg-emerald-50 text-emerald-600' : 'bg-rose-50 text-rose-600'
            }`}>
              {trend.positive ? '↑' : '↓'} {Math.abs(trend.value)}%
              <span className="text-zinc-500 font-medium ml-2 opacity-80 font-normal">vs last week</span>
            </span>
          ) : (
            subtitle && <span className="text-[13px] text-zinc-500 font-medium">{subtitle}</span>
          )}
        </div>
      </div>

      {/* Decorative Premium Glow / Sparkline Area */}
      <div className="absolute bottom-0 left-0 w-full h-24 bg-gradient-to-t from-zinc-50/50 to-transparent opacity-0 group-hover:opacity-100 transition-opacity duration-500 pointer-events-none" />
      
      {trend && (
        <div className="absolute -bottom-2 -right-4 w-40 h-20 opacity-40 group-hover:opacity-80 transition-opacity duration-500 pointer-events-none">
          <svg viewBox="0 0 100 30" className="w-full h-full overflow-visible">
            <path 
              d={trend.positive ? "M0,25 C20,20 40,30 60,15 S80,5 100,2" : "M0,5 C20,10 40,0 60,15 S80,25 100,28"} 
              fill="none" 
              stroke={trend.positive ? "#10B981" : "#F43F5E"} 
              strokeWidth="2" 
              strokeLinecap="round" 
              strokeLinejoin="round" 
              className="drop-shadow-sm"
            />
          </svg>
        </div>
      )}
    </div>
  );
}
