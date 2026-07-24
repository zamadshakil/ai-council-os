'use client';

import { useState, useEffect } from 'react';
import { usePathname } from 'next/navigation';
import Link from 'next/link';
import { 
  Home, 
  CheckCircle2, 
  Users, 
  BarChart3, 
  Settings, 
  Plus,
  ChevronDown,
  Sparkles,
  Zap,
  Shield,
  ShieldOff
} from 'lucide-react';
import { useSidebar } from '../contexts/SidebarContext';
import { fetchKillSwitch, activateKillSwitch, deactivateKillSwitch } from '../lib/api';

const NAV_ITEMS = [
  { href: '/', label: 'Overview', icon: Home },
  { href: '/approvals', label: 'Approvals', icon: CheckCircle2, badge: 3 },
  { href: '/councils', label: 'Councils', icon: Users },
  { href: '/workflows', label: 'Workflows', icon: Zap },
  { href: '/analytics', label: 'Analytics', icon: BarChart3 },
];

export function Sidebar() {
  const pathname = usePathname();
  const { isCollapsed } = useSidebar();
  const [killActive, setKillActive] = useState(false);

  useEffect(() => {
    fetchKillSwitch().then(s => setKillActive(s.is_active)).catch(() => {});
  }, []);

  return (
    <aside
      className={`fixed top-0 left-0 h-screen bg-[var(--bg-sidebar)] border-r border-black/[0.08] transition-all duration-200 ease-[cubic-bezier(0.2,0.8,0.2,1)] z-50 flex flex-col ${
        isCollapsed ? 'w-[72px]' : 'w-[280px]'
      }`}
    >
      {/* Workspace Switcher */}
      <div className="h-20 flex items-center px-6">
        <button className={`flex items-center w-full py-2 group cursor-pointer rounded-[8px] hover:bg-zinc-200/50 active:scale-[0.98] transition-all focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-offset-2 focus-visible:ring-zinc-800 ${isCollapsed ? 'justify-center px-0' : 'justify-between px-2 -mx-2'}`}>
          <div className="flex items-center">
            <div className="w-8 h-8 rounded-[8px] bg-[#111827] flex items-center justify-center shadow-sm shrink-0 transition-transform group-hover:scale-105">
              <Sparkles className="w-4 h-4 text-white" />
            </div>
            {!isCollapsed && (
              <div className="ml-3 text-left">
                <p className="text-[14px] font-semibold text-zinc-900 leading-none tracking-tight">Council OS</p>
                <p className="text-[13px] text-zinc-600 mt-1">Acme Corp</p>
              </div>
            )}
          </div>
          {!isCollapsed && <ChevronDown className="w-4 h-4 text-zinc-500 group-hover:text-zinc-900 transition-colors" />}
        </button>
      </div>

      <div className="flex-1 overflow-y-auto py-8 px-4 scrollbar-hide flex flex-col gap-8">
        
        {/* Quick Action */}
        <div className="px-2">
          <Link href="/councils" className={`flex items-center justify-center h-10 rounded-[8px] bg-[#111827] text-white shadow-premium hover:bg-zinc-800 hover:shadow-floating hover:-translate-y-[1px] active:scale-[0.98] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-offset-2 focus-visible:ring-zinc-800 transition-all duration-200 group`}>
            <Plus className="w-4 h-4" />
            {!isCollapsed && <span className="ml-2 text-[14px] font-medium">New Council</span>}
          </Link>
        </div>

        {/* Main Navigation */}
        <nav className="flex flex-col gap-1">
          {!isCollapsed && <p className="px-4 text-[12px] font-semibold text-zinc-500 uppercase tracking-widest mb-2">Platform</p>}
          {NAV_ITEMS.map((item) => {
            const isActive = pathname === item.href;
            const Icon = item.icon;
            return (
              <Link
                key={item.href}
                href={item.href}
                className={`relative flex items-center h-10 px-4 rounded-[8px] transition-all duration-200 group focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-offset-2 focus-visible:ring-zinc-800 active:scale-[0.98] ${
                  isActive
                    ? 'bg-zinc-200 text-zinc-900 shadow-[inset_0_1px_0_rgba(255,255,255,0.5)]'
                    : 'text-zinc-600 hover:text-zinc-900 hover:bg-zinc-200/50'
                }`}
              >
                <Icon className={`shrink-0 ${isCollapsed ? 'w-[18px] h-[18px] mx-auto' : 'w-[18px] h-[18px] mr-3'} ${isActive ? 'text-zinc-900' : 'text-zinc-500 group-hover:text-zinc-900'} transition-colors`} />
                {!isCollapsed && (
                  <span className={`text-[14px] ${isActive ? 'font-semibold' : 'font-medium'}`}>{item.label}</span>
                )}
                {!isCollapsed && item.badge && (
                  <span className={`ml-auto px-2 py-0.5 text-[12px] font-semibold rounded-[6px] ${isActive ? 'bg-[#111827] text-white shadow-sm' : 'bg-zinc-200 text-zinc-700 group-hover:bg-zinc-300'}`}>
                    {item.badge}
                  </span>
                )}
              </Link>
            );
          })}
        </nav>

        {/* Pinned Councils */}
        {!isCollapsed && (
          <div className="flex flex-col gap-1">
            <p className="px-4 text-[12px] font-semibold text-zinc-500 uppercase tracking-widest mb-2">Pinned Councils</p>
            {['Sales Team', 'Marketing Blog', 'Grant Writer'].map((team, idx) => (
              <button key={idx} className="w-full flex items-center h-9 px-4 rounded-[8px] text-zinc-600 hover:text-zinc-900 hover:bg-zinc-200/50 active:scale-[0.98] transition-all cursor-pointer group focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-offset-2 focus-visible:ring-zinc-800">
                <div className={`w-2 h-2 rounded-full mr-3 shadow-sm ${idx === 0 ? 'bg-blue-600' : idx === 1 ? 'bg-emerald-600' : 'bg-amber-600'}`} />
                <span className="text-[14px] font-medium">{team}</span>
              </button>
            ))}
          </div>
        )}

        {/* Kill Switch */}
        {!isCollapsed && (
          <div className="px-4 mt-auto">
            <button
              onClick={async () => {
                try {
                  if (killActive) {
                    await deactivateKillSwitch();
                    setKillActive(false);
                  } else {
                    await activateKillSwitch('Manual kill from Dashboard');
                    setKillActive(true);
                  }
                } catch (e) { console.error(e); }
              }}
              className={`w-full flex items-center justify-between p-3 rounded-[12px] border transition-all duration-200 active:scale-[0.98] ${
                killActive
                  ? 'bg-red-50 border-red-200 hover:bg-red-100'
                  : 'bg-emerald-50 border-emerald-200 hover:bg-emerald-100'
              }`}
            >
              <div className="flex items-center">
                {killActive ? (
                  <ShieldOff className="w-4 h-4 text-red-600 mr-2" />
                ) : (
                  <Shield className="w-4 h-4 text-emerald-600 mr-2" />
                )}
                <span className={`text-[13px] font-semibold ${killActive ? 'text-red-700' : 'text-emerald-700'}`}>
                  {killActive ? 'System KILLED' : 'System Active'}
                </span>
              </div>
              <div className={`w-8 h-[18px] rounded-full p-[2px] transition-colors duration-200 ${
                killActive ? 'bg-red-500' : 'bg-emerald-500'
              }`}>
                <div className={`w-[14px] h-[14px] bg-white rounded-full shadow-sm transition-transform duration-200 ${
                  killActive ? 'translate-x-[14px]' : 'translate-x-0'
                }`} />
              </div>
            </button>
          </div>
        )}
      </div>

      {/* User Profile */}
      <div className="p-4 border-t border-black/[0.08]">
        <button className={`w-full flex items-center p-2 rounded-[8px] hover:bg-zinc-200/50 active:scale-[0.98] transition-all group cursor-pointer focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-offset-2 focus-visible:ring-zinc-800 ${isCollapsed ? 'justify-center' : 'justify-between'}`}>
          <div className="flex items-center relative">
            <div className="w-9 h-9 rounded-full bg-zinc-300 shrink-0 shadow-sm" />
            <div className="absolute -bottom-0.5 -right-0.5 w-3.5 h-3.5 bg-emerald-500 border-2 border-[var(--bg-sidebar)] rounded-full" />
            {!isCollapsed && (
              <div className="ml-3 text-left">
                <p className="text-[14px] font-semibold text-zinc-900 leading-none tracking-tight">Zakaria</p>
                <p className="text-[13px] text-zinc-600 mt-1">Admin</p>
              </div>
            )}
          </div>
          {!isCollapsed && <Settings className="w-[18px] h-[18px] text-zinc-500 group-hover:text-zinc-900 transition-colors" />}
        </button>
      </div>
    </aside>
  );
}
