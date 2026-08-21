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
  ChevronRight,
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

const NAV_GROUPS = [
  { label: 'Command', items: [
    { href: '/', label: 'Overview', icon: LayoutDashboard },
    { href: '/approvals', label: 'Queue & Approvals', icon: CheckCircle2 },
    { href: '/councils', label: 'Councils', icon: Users },
    { href: '/workflows', label: 'Workflows', icon: Zap },
  ] },
  { label: 'Systems', items: [
    { href: '/blender', label: 'Blender Manager', icon: Box },
    { href: '/knowledge', label: 'Knowledge', icon: BookOpen },
    { href: '/analytics', label: 'History & Analytics', icon: BarChart3 },
    { href: '/settings', label: 'Settings & Integrations', icon: Settings },
  ] },
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
    <aside className={`glass-sidebar fixed inset-y-3 left-3 z-50 flex flex-col overflow-hidden rounded-[28px] transition-[width] duration-300 ${isCollapsed ? 'w-[80px]' : 'w-[80px] md:w-[252px]'}`}>
      <div className={`flex h-[76px] shrink-0 items-center border-b border-white/8 ${isCollapsed ? 'justify-center px-2' : 'justify-between px-4'}`}>
        {isCollapsed ? (
          <button type="button" onClick={toggleSidebar} aria-label="Expand navigation" title="Expand navigation" className="group relative grid h-12 w-12 place-items-center rounded-2xl border border-cyan-200/20 bg-cyan-300/8 text-cyan-100 shadow-[inset_0_1px_rgba(255,255,255,.14)] hover:border-cyan-200/40 hover:bg-cyan-300/12">
            <span className="text-sm font-black">C</span>
            <span className="absolute -right-1 -bottom-1 grid h-5 w-5 place-items-center rounded-full border border-white/15 bg-[#102235] text-slate-300"><ChevronRight className="h-3 w-3" /></span>
          </button>
        ) : (
          <>
            <Link href="/" className="flex min-w-0 items-center gap-3 overflow-hidden">
              <span className="jarvis-orb flex h-10 w-10 shrink-0 items-center justify-center rounded-2xl bg-cyan-300/10 text-xs font-black text-cyan-200">C</span>
              <span className="hidden min-w-0 md:block"><span className="block whitespace-nowrap text-base font-bold text-slate-100">Council OS</span><span className="block text-[9px] font-bold uppercase tracking-[.22em] text-cyan-400/70">Autonomy console</span></span>
            </Link>
            <button type="button" onClick={toggleSidebar} aria-label="Collapse navigation" title="Collapse navigation" className="grid h-9 w-9 place-items-center rounded-xl border border-white/8 text-slate-400 hover:border-white/15 hover:bg-white/8 hover:text-slate-100"><ChevronLeft className="h-4 w-4" /></button>
          </>
        )}
      </div>

      <nav className="flex flex-1 flex-col overflow-y-auto px-3 py-4" aria-label="Primary navigation">
        {NAV_GROUPS.map((group, groupIndex) => <div key={group.label} className={groupIndex ? 'mt-5 border-t border-white/8 pt-4' : ''}>
          {!isCollapsed && <p className="mb-2 hidden px-3 text-[9px] font-black uppercase tracking-[.22em] text-slate-600 md:block">{group.label}</p>}
          <div className="space-y-1.5">
            {group.items.map((item) => {
              const Icon = item.icon;
              const active = item.href === '/' ? pathname === '/' : pathname.startsWith(item.href);
              return <Link key={item.href} href={item.href} title={isCollapsed ? item.label : undefined} aria-label={item.label} aria-current={active ? 'page' : undefined} className={`relative flex h-12 items-center rounded-2xl text-sm font-semibold transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-cyan-300 ${isCollapsed ? 'justify-center px-0' : 'px-3'} ${active ? 'text-white' : 'text-slate-400 hover:bg-white/6 hover:text-slate-100'}`}>
                {active && <motion.span layoutId="sidebar-selection" className="liquid-nav-selection absolute inset-0 rounded-2xl" />}
                {active && <span className="absolute left-0 top-3 bottom-3 z-10 w-[3px] rounded-r-full bg-cyan-300 shadow-[0_0_12px_rgba(103,232,249,.7)]" />}
                <Icon className={`relative z-10 h-5 w-5 shrink-0 ${active ? 'text-cyan-200 drop-shadow-[0_0_8px_rgba(103,232,249,.35)]' : ''}`} />
                {!isCollapsed && <span className="nav-label relative z-10 ml-3 hidden truncate md:block">{item.label}</span>}
              </Link>;
            })}
          </div>
        </div>)}
      </nav>

      <div className="system-control shrink-0 border-t border-white/8 p-3">
        <button onClick={toggleKillSwitch} disabled={killActive === null || killBusy} title={killError || (killActive ? 'System stopped' : 'System active')} aria-label={killActive ? 'System stopped. Activate system' : 'System active. Stop system'} className={`flex h-12 w-full items-center rounded-2xl border text-sm font-semibold disabled:cursor-not-allowed disabled:opacity-60 ${isCollapsed ? 'justify-center px-0' : 'px-3'} ${killActive ? 'border-rose-400/30 bg-rose-400/10 text-rose-300' : 'border-emerald-300/20 bg-emerald-300/8 text-emerald-300'}`}>
          {killActive ? <ShieldOff className="h-5 w-5 shrink-0" /> : <Shield className="h-5 w-5 shrink-0" />}
          {!isCollapsed && <span className="ml-3 hidden md:block">{killBusy ? 'Updating…' : killActive === null ? 'Status unavailable' : killActive ? 'System stopped' : 'System active'}</span>}
        </button>
        {!isCollapsed && killError && <p className="mt-2 px-2 text-xs text-rose-300">{killError}</p>}
      </div>

      <div className={`sidebar-footer shrink-0 border-t border-white/8 p-3 ${isCollapsed ? 'space-y-2' : ''}`}>
        {!isCollapsed && (
          <div className="mb-2 hidden items-center gap-3 px-2 md:flex">
            <span className="grid h-9 w-9 shrink-0 place-items-center rounded-xl border border-white/10 bg-white/6 text-xs font-black text-cyan-200">{(user?.name || user?.username || 'A').slice(0, 1).toUpperCase()}</span>
            <div className="min-w-0"><p className="truncate text-sm font-semibold text-slate-200">{user?.name || user?.username}</p><p className="text-xs capitalize text-slate-500">{user?.role}</p></div>
          </div>
        )}
        {logoutError && !isCollapsed && <p role="alert" className="mb-2 px-2 text-xs text-rose-300">{logoutError}</p>}
        <button disabled={logoutBusy} onClick={() => void handleLogout()} className={`flex h-11 w-full items-center rounded-xl text-sm font-semibold text-slate-400 hover:bg-rose-400/10 hover:text-rose-200 disabled:opacity-50 ${isCollapsed ? 'justify-center px-0' : 'px-3'}`} title="Sign out" aria-label="Sign out">
          <LogOut className="h-5 w-5 shrink-0" />
          {!isCollapsed && <span className="ml-3 hidden md:block">{logoutBusy ? 'Signing out…' : 'Sign out'}</span>}
        </button>
      </div>
    </aside>
  );
}
