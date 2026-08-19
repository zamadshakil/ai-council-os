'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { useEffect, useState } from 'react';
import {
  BarChart3,
  BookOpen,
  Box,
  CheckCircle2,
  ChevronLeft,
  LayoutDashboard,
  LogOut,
  Settings,
  Shield,
  ShieldOff,
  Users,
  Zap,
} from 'lucide-react';
import { useAuth } from '../contexts/AuthContext';
import { fetchKillSwitch, updateKillSwitch } from '../lib/api';
import { useSidebar } from '../contexts/SidebarContext';
import { motion } from 'framer-motion';

const NAV_ITEMS = [
  { href: '/', label: 'Overview', icon: LayoutDashboard },
  { href: '/approvals', label: 'Queue & Approvals', icon: CheckCircle2 },
  { href: '/councils', label: 'Councils', icon: Users },
  { href: '/workflows', label: 'Workflows', icon: Zap },
  { href: '/blender', label: 'Blender Manager', icon: Box },
  { href: '/knowledge', label: 'Knowledge', icon: BookOpen },
  { href: '/analytics', label: 'History & Analytics', icon: BarChart3 },
  { href: '/settings', label: 'Settings & Integrations', icon: Settings },
];

export function Sidebar() {
  const pathname = usePathname();
  const { isCollapsed, toggleSidebar } = useSidebar();
  const { user, logout } = useAuth();
  const [killActive, setKillActive] = useState<boolean | null>(null);
  const [killBusy, setKillBusy] = useState(false);
  const [killError, setKillError] = useState('');
  const [logoutBusy, setLogoutBusy] = useState(false);
  const [logoutError, setLogoutError] = useState('');

  useEffect(() => {
    void fetchKillSwitch()
      .then((status) => setKillActive(status.is_active))
      .catch(() => setKillError('Kill switch unavailable'));
  }, []);

  async function toggleKillSwitch() {
    if (killActive === null || killBusy) return;
    setKillBusy(true);
    setKillError('');
    try {
      const result = await updateKillSwitch(!killActive, !killActive ? 'Activated from dashboard' : '');
      const status = 'resource' in result ? result.resource : result;
      setKillActive(status.is_active);
    } catch (error) {
      setKillError(error instanceof Error ? error.message : 'Unable to update kill switch.');
    } finally {
      setKillBusy(false);
    }
  }

  async function handleLogout() {
    if (logoutBusy) return;
    setLogoutBusy(true);
    setLogoutError('');
    try {
      await logout();
    } catch (error) {
      setLogoutError(error instanceof Error ? error.message : 'Sign out failed.');
    } finally {
      setLogoutBusy(false);
    }
  }

  return (
    <aside className={`glass-sidebar fixed inset-y-3 left-3 z-50 flex w-[84px] flex-col overflow-hidden rounded-[30px] transition-[width] duration-300 ${isCollapsed ? '' : 'md:w-[248px]'}`}>
      <div className={`flex h-[72px] items-center justify-between border-b border-white/8 ${isCollapsed ? 'px-2' : 'px-4'}`}>
        <Link href="/" className="flex items-center gap-3 overflow-hidden">
          <span className="jarvis-orb flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-cyan-300/10 text-xs font-black text-cyan-200">C</span>
          {!isCollapsed && <span className="hidden md:block"><span className="block whitespace-nowrap text-base font-bold text-slate-100">Council OS</span><span className="block text-[9px] font-bold uppercase tracking-[.22em] text-cyan-400/70">Autonomy console</span></span>}
        </Link>
        <button onClick={toggleSidebar} aria-label={isCollapsed ? 'Expand sidebar' : 'Collapse sidebar'} className="rounded-lg p-1.5 text-slate-500 hover:bg-white/8 hover:text-slate-100">
          <ChevronLeft className={`h-5 w-5 transition-transform ${isCollapsed ? 'rotate-180' : ''}`} />
        </button>
      </div>

      <nav className="flex flex-1 flex-col gap-1 overflow-y-auto p-3">
        {NAV_ITEMS.map((item) => {
          const Icon = item.icon;
          const active = item.href === '/' ? pathname === '/' : pathname.startsWith(item.href);
          return (
            <Link
              key={item.href}
              href={item.href}
              title={isCollapsed ? item.label : undefined}
              aria-label={item.label}
              aria-current={active ? 'page' : undefined}
              className={`relative flex h-11 items-center rounded-[15px] px-3 text-sm font-semibold transition-colors ${active ? 'text-white' : 'text-slate-300 hover:bg-white/7 hover:text-white'}`}
            >
              {active && <motion.span layoutId="sidebar-selection" className="liquid-nav-selection absolute inset-0 rounded-[15px]" />}
              <Icon className={`relative z-10 h-5 w-5 shrink-0 ${active ? 'text-cyan-200' : ''}`} />
              {!isCollapsed && <span className="nav-label relative z-10 ml-3 hidden truncate md:block">{item.label}</span>}
            </Link>
          );
        })}

        <div className="system-control mt-auto pt-4">
          <button
            onClick={toggleKillSwitch}
            disabled={killActive === null || killBusy}
            title={killError || undefined}
            className={`flex h-11 w-full items-center rounded-xl border px-3 text-sm font-semibold disabled:cursor-not-allowed disabled:opacity-60 ${killActive ? 'border-rose-400/30 bg-rose-400/10 text-rose-300' : 'border-emerald-300/20 bg-emerald-300/8 text-emerald-300'}`}
          >
            {killActive ? <ShieldOff className="h-5 w-5 shrink-0" /> : <Shield className="h-5 w-5 shrink-0" />}
            {!isCollapsed && <span className="ml-3 hidden md:block">{killBusy ? 'Updating…' : killActive === null ? 'Status unavailable' : killActive ? 'System stopped' : 'System active'}</span>}
          </button>
          {!isCollapsed && killError && <p className="mt-2 px-2 text-xs text-rose-300">{killError}</p>}
        </div>
      </nav>

      <div className="sidebar-footer border-t border-white/8 p-3">
        {!isCollapsed && (
          <div className="mb-2 hidden px-2 md:block">
            <p className="truncate text-sm font-semibold text-slate-200">{user?.name || user?.username}</p>
            <p className="text-xs capitalize text-slate-500">{user?.role}</p>
          </div>
        )}
        {logoutError && !isCollapsed && <p role="alert" className="mb-2 px-2 text-xs text-rose-300">{logoutError}</p>}
        <button disabled={logoutBusy} onClick={() => void handleLogout()} className="flex h-10 w-full items-center rounded-lg px-3 text-sm font-semibold text-slate-300 hover:bg-rose-400/10 hover:text-rose-200 disabled:opacity-50" title="Sign out">
          <LogOut className="h-5 w-5 shrink-0" />
          {!isCollapsed && <span className="ml-3 hidden md:block">{logoutBusy ? 'Signing out…' : 'Sign out'}</span>}
        </button>
      </div>
    </aside>
  );
}
