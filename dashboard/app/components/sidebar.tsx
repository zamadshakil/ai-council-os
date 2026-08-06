'use client';

import { useState, useEffect } from 'react';
import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { 
  LayoutDashboard, CheckCircle2, Users, BarChart3, Settings, 
  ChevronLeft, Shield, ShieldOff, Zap, LogOut, User as UserIcon, X, Check, BookOpen, Box
} from 'lucide-react';
import { useSidebar } from '../contexts/SidebarContext';
import { useAuth } from '../contexts/AuthContext';
import { fetchKillSwitch, activateKillSwitch, deactivateKillSwitch } from '../lib/api';

const NAV_ITEMS = [
  { href: '/', label: 'Overview', icon: LayoutDashboard },
  { href: '/approvals', label: 'Approvals', icon: CheckCircle2 },
  { href: '/councils', label: 'Councils', icon: Users },
  { href: '/render-studio', label: 'Render & CAD Studio', icon: Box },
  { href: '/knowledge', label: 'Knowledge Hub', icon: BookOpen },
  { href: '/workflows', label: 'Workflows', icon: Zap },
  { href: '/analytics', label: 'Analytics', icon: BarChart3 },
];

export function Sidebar() {
  const pathname = usePathname();
  const { isCollapsed, toggleSidebar } = useSidebar();
  const { user, logout } = useAuth();
  
  const [killActive, setKillActive] = useState(false);
  const [showProfileMenu, setShowProfileMenu] = useState(false);

  useEffect(() => {
    fetchKillSwitch().then(s => setKillActive(s.is_active)).catch(() => {});
  }, []);

  return (
    <>
      <aside
        className={`fixed top-0 left-0 bottom-0 z-50 transition-all duration-500 ease-[cubic-bezier(0.2,0.8,0.2,1)] flex flex-col bg-[#F4F4F5] border-r border-black/[0.08] shadow-[1px_0_0_0_rgba(0,0,0,0.03)] ${
          isCollapsed ? 'w-[72px]' : 'w-[280px]'
        }`}
      >
        {/* Header / Logo */}
        <div className="h-20 flex items-center justify-between px-6 border-b border-black/[0.08] shrink-0">
          <Link href="/" className="flex items-center gap-3 group">
            <div className="w-8 h-8 rounded-[10px] bg-zinc-900 flex items-center justify-center text-white font-bold text-sm shadow-md group-hover:scale-105 transition-transform">
              C
            </div>
            {!isCollapsed && (
              <span className="text-[17px] font-bold tracking-tight text-zinc-900">
                Council OS
              </span>
            )}
          </Link>

          <button
            onClick={toggleSidebar}
            className="p-1.5 rounded-[8px] text-zinc-400 hover:text-zinc-900 hover:bg-zinc-200/60 transition-all active:scale-[0.98]"
            title={isCollapsed ? "Expand Sidebar" : "Collapse Sidebar"}
          >
            <ChevronLeft className={`w-5 h-5 transition-transform duration-300 ${isCollapsed ? 'rotate-180' : ''}`} />
          </button>
        </div>

        {/* Navigation & Kill Switch */}
        <div className="flex-1 overflow-y-auto py-6 px-3 flex flex-col gap-6">
          <nav className="flex flex-col gap-1">
            {NAV_ITEMS.map((item) => {
              const Icon = item.icon;
              const isActive = pathname === item.href;

              return (
                <Link
                  key={item.href}
                  href={item.href}
                  className={`flex items-center h-10 px-3 rounded-[10px] text-[14px] font-medium transition-all duration-200 active:scale-[0.98] ${
                    isActive
                      ? 'bg-white text-zinc-900 shadow-sm border border-black/[0.06]'
                      : 'text-zinc-600 hover:text-zinc-900 hover:bg-zinc-200/50'
                  }`}
                  title={isCollapsed ? item.label : undefined}
                >
                  <Icon className={`w-5 h-5 shrink-0 ${isActive ? 'text-blue-600' : 'text-zinc-500'}`} />
                  {!isCollapsed && <span className="ml-3 tracking-tight">{item.label}</span>}
                </Link>
              );
            })}
          </nav>

          {/* Pinned Councils */}
          {!isCollapsed && (
            <div className="flex flex-col gap-1">
              <p className="px-3 text-[11px] font-bold text-zinc-600 uppercase tracking-widest mb-1">Pinned Councils</p>
              {['Sales Team', 'Marketing Blog', 'Grant Writer'].map((team, idx) => (
                <Link 
                  key={idx} 
                  href={`/councils?select=${idx === 0 ? 'sales' : idx === 1 ? 'content' : 'grant'}`}
                  className="w-full flex items-center h-9 px-3 rounded-[8px] text-zinc-600 hover:text-zinc-900 hover:bg-zinc-200/50 transition-all text-left"
                >
                  <div className={`w-2 h-2 rounded-full mr-3 shadow-sm ${idx === 0 ? 'bg-blue-600' : idx === 1 ? 'bg-emerald-600' : 'bg-amber-600'}`} />
                  <span className="text-[13px] font-medium">{team}</span>
                </Link>
              ))}
            </div>
          )}

          {/* Kill Switch */}
          {!isCollapsed && (
            <div className="px-1 mt-auto">
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

        {/* User Profile Card */}
        <div className="p-3 border-t border-black/[0.08] relative">
          <button 
            onClick={() => setShowProfileMenu(prev => !prev)}
            className={`w-full flex items-center p-2 rounded-[12px] hover:bg-zinc-200/60 active:scale-[0.98] transition-all group cursor-pointer border border-transparent hover:border-zinc-300/60 ${isCollapsed ? 'justify-center' : 'justify-between'}`}
          >
            <div className="flex items-center relative">
              <div className="w-9 h-9 rounded-full bg-gradient-to-tr from-blue-600 to-indigo-600 text-white font-bold flex items-center justify-center shrink-0 shadow-sm text-sm">
                {user?.name?.[0] || 'Z'}
              </div>
              <div className="absolute -bottom-0.5 -right-0.5 w-3.5 h-3.5 bg-emerald-500 border-2 border-[#F4F4F5] rounded-full" />
              {!isCollapsed && (
                <div className="ml-3 text-left">
                  <p className="text-[14px] font-semibold text-zinc-900 leading-none tracking-tight">
                    {user?.name || 'Zakaria'}
                  </p>
                  <p className="text-[12px] text-zinc-500 font-medium mt-1">
                    {user?.role || 'Admin'}
                  </p>
                </div>
              )}
            </div>
            {!isCollapsed && <Settings className="w-[18px] h-[18px] text-zinc-400 group-hover:text-zinc-900 transition-colors" />}
          </button>
        </div>
      </aside>

      {/* ── User Profile Popover Modal ────────────────────────────────────── */}
      {showProfileMenu && (
        <div className="fixed inset-0 z-50 bg-black/30 backdrop-blur-xs flex items-end sm:items-center justify-center p-4 animate-in fade-in duration-150">
          <div className="w-full max-w-sm bg-white rounded-[24px] shadow-2xl border border-zinc-200 p-6 z-50">
            
            {/* Header */}
            <div className="flex items-center justify-between pb-4 border-b border-zinc-100 mb-4">
              <div className="flex items-center gap-3">
                <div className="w-11 h-11 rounded-full bg-gradient-to-tr from-blue-600 to-indigo-600 text-white font-bold flex items-center justify-center text-base shadow-md">
                  {user?.name?.[0] || 'Z'}
                </div>
                <div>
                  <h3 className="text-base font-bold text-zinc-900">{user?.name || 'Zakaria'}</h3>
                  <p className="text-xs text-zinc-500">{user?.email || 'zakaria@councilos.ai'}</p>
                </div>
              </div>
              <button 
                onClick={() => setShowProfileMenu(false)}
                className="p-1.5 rounded-lg text-zinc-400 hover:text-zinc-900 hover:bg-zinc-100 transition-colors"
              >
                <X className="w-5 h-5" />
              </button>
            </div>

            {/* Profile Info List */}
            <div className="space-y-2 mb-6">
              <div className="p-3 bg-zinc-50 rounded-[12px] flex items-center justify-between">
                <span className="text-xs font-semibold text-zinc-500">Role</span>
                <span className="text-xs font-bold text-blue-700 bg-blue-50 px-2.5 py-0.5 rounded-full">{user?.role || 'Admin'}</span>
              </div>
              <div className="p-3 bg-zinc-50 rounded-[12px] flex items-center justify-between">
                <span className="text-xs font-semibold text-zinc-500">Security Session</span>
                <span className="text-xs font-semibold text-emerald-700 flex items-center gap-1">
                  <Check className="w-3.5 h-3.5 text-emerald-600" />
                  <span>Authenticated</span>
                </span>
              </div>
              <div className="p-3 bg-zinc-50 rounded-[12px] flex items-center justify-between">
                <span className="text-xs font-semibold text-zinc-500">AI Intelligence API</span>
                <span className="text-xs font-semibold text-zinc-900">OpenRouter (Active)</span>
              </div>
            </div>

            {/* Logout Action Button */}
            <button
              onClick={() => {
                setShowProfileMenu(false);
                logout();
              }}
              className="w-full h-11 bg-red-50 hover:bg-red-100 text-red-700 font-semibold text-sm rounded-[12px] border border-red-200 flex items-center justify-center gap-2 transition-colors active:scale-[0.98]"
            >
              <LogOut className="w-4 h-4 text-red-600" />
              <span>Sign Out / Log Out</span>
            </button>

          </div>
        </div>
      )}
    </>
  );
}
