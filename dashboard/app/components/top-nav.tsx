'use client';

import { usePathname } from 'next/navigation';
import { useEffect, useState } from 'react';
import { CircleCheck, CircleHelp, Command, Search, TriangleAlert } from 'lucide-react';
import { fetchIntegrationsHealth } from '../lib/api';
import { IntegrationHealth } from '../lib/types';

const TITLES: Record<string, string> = {
  '/': 'Overview',
  '/approvals': 'Queue & Approvals',
  '/councils': 'Councils',
  '/workflows': 'Workflows',
  '/blender': 'Blender Manager',
  '/knowledge': 'Knowledge',
  '/analytics': 'History & Analytics',
  '/settings': 'Settings & Integrations',
};

export function TopNav({ onOpenCommand }: { onOpenCommand: () => void }) {
  const pathname = usePathname();
  const [integrations, setIntegrations] = useState<IntegrationHealth[]>([]);

  useEffect(() => {
    void fetchIntegrationsHealth().then(setIntegrations).catch(() => setIntegrations([]));
  }, []);

  const title = Object.entries(TITLES).find(([path]) => path === '/' ? pathname === '/' : pathname.startsWith(path))?.[1] ?? 'Council OS';
  const ready = integrations.filter((item) => item.status === 'ready' || item.status === 'verified' || item.status === 'connected').length;
  const unhealthy = integrations.filter((item) => item.status === 'invalid' || item.status === 'failed' || item.status === 'degraded').length;

  return (
    <header className="glass-topbar sticky top-3 z-40 mx-3 h-[72px] rounded-[26px]">
      <div className="flex h-full items-center justify-between gap-4 px-5 lg:px-8">
        <div>
          <p className="eyebrow">Command center</p>
          <p className="text-lg font-bold text-slate-100">{title}</p>
        </div>
        <button onClick={onOpenCommand} className="glass-control hidden h-11 min-w-80 items-center gap-3 rounded-full px-4 text-left text-sm text-slate-500 md:flex">
          <Search className="h-4 w-4" /><span className="flex-1">Search or jump to…</span><span className="flex items-center gap-1 rounded-lg border border-white/10 bg-white/5 px-2 py-1 text-[11px] text-slate-400"><Command className="h-3 w-3" />K</span>
        </button>
        <div className="glass-readout flex items-center gap-2 rounded-full px-3 py-2 text-xs font-semibold text-slate-400" title="Live integration health reported by the backend">
          {unhealthy > 0 ? <TriangleAlert className="h-4 w-4 text-amber-300" /> : integrations.length > 0 ? <CircleCheck className="h-4 w-4 text-emerald-300" /> : <CircleHelp className="h-4 w-4 text-slate-500" />}
          <span className="hidden sm:inline">{integrations.length > 0 ? `${ready}/${integrations.length} verified` : 'Health unavailable'}</span>
        </div>
      </div>
    </header>
  );
}
