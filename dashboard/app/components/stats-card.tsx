import { ReactNode } from 'react';

interface StatsCardProps {
  title: string;
  value: string | number;
  subtitle?: string;
  icon: ReactNode;
  trend?: { value: number; positive: boolean };
}

export function StatsCard({ title, value, subtitle, icon, trend }: StatsCardProps) {
  return (
    <div className="bg-white p-6 rounded-lg border border-zinc-200 hover:border-zinc-300 transition-all duration-200 shadow-sm hover:shadow">
      <div className="flex items-start justify-between">
        <div>
          <p className="text-sm font-medium text-zinc-500">{title}</p>
          <h3 className="text-2xl font-semibold text-zinc-900 mt-2">{value}</h3>
          {(subtitle || trend) && (
            <div className="flex items-center space-x-2 mt-2">
              {trend && (
                <span className={`text-xs font-medium px-1.5 py-0.5 rounded ${
                  trend.positive ? 'text-green-700 bg-green-50' : 'text-red-700 bg-red-50'
                }`}>
                  {trend.positive ? '+' : '-'}{Math.abs(trend.value)}%
                </span>
              )}
              {subtitle && <p className="text-xs text-zinc-400">{subtitle}</p>}
            </div>
          )}
        </div>
        <div className="p-3 bg-zinc-50 rounded-full text-zinc-500">
          {icon}
        </div>
      </div>
    </div>
  );
}
