'use client';

import { useState, useEffect, useRef } from 'react';
import { useRouter } from 'next/navigation';
import { 
  Search, Command, LayoutGrid, Bell, Plus, CheckCircle2, 
  BarChart3, Zap, Users, X, ArrowRight, ShieldAlert, Sparkles 
} from 'lucide-react';
import { useSidebar } from '../contexts/SidebarContext';
import { fetchTasks, fetchKillSwitch } from '../lib/api';
import { Task } from '../lib/types';

export function TopNav() {
  const { isCollapsed } = useSidebar();
  const router = useRouter();

  // Search / Command Palette state
  const [isOpenCmd, setIsOpenCmd] = useState(false);
  const [searchQuery, setSearchQuery] = useState('');
  const [tasks, setTasks] = useState<Task[]>([]);
  const [killActive, setKillActive] = useState(false);

  // Modals state
  const [isOpenGridModal, setIsOpenGridModal] = useState(false);
  const [isOpenNotifications, setIsOpenNotifications] = useState(false);

  const cmdInputRef = useRef<HTMLInputElement>(null);

  // Fetch data for search and notifications
  useEffect(() => {
    fetchTasks().then(setTasks).catch(() => {});
    fetchKillSwitch().then(k => setKillActive(k.is_active)).catch(() => {});
  }, []);

  // Global shortcut (Cmd+K or Ctrl+K) listener
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key === 'k') {
        e.preventDefault();
        setIsOpenCmd(prev => !prev);
      }
      if (e.key === 'Escape') {
        setIsOpenCmd(false);
        setIsOpenGridModal(false);
        setIsOpenNotifications(false);
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, []);

  useEffect(() => {
    if (isOpenCmd && cmdInputRef.current) {
      cmdInputRef.current.focus();
    }
  }, [isOpenCmd]);

  // Filtered search results
  const filteredTasks = tasks.filter(t => 
    t.task_description.toLowerCase().includes(searchQuery.toLowerCase()) ||
    t.council.toLowerCase().includes(searchQuery.toLowerCase()) ||
    t.task_id.toLowerCase().includes(searchQuery.toLowerCase())
  );

  const pendingTasks = tasks.filter(t => t.status === 'awaiting_approval' || t.status === 'pending');

  const navigationPages = [
    { title: 'Overview Dashboard', path: '/', icon: LayoutGrid },
    { title: 'Approval Queue', path: '/approvals', icon: CheckCircle2 },
    { title: 'Run AI Council', path: '/councils', icon: Users },
    { title: 'Workflows & Automation', path: '/workflows', icon: Zap },
    { title: 'Analytics & Performance', path: '/analytics', icon: BarChart3 },
  ];

  const filteredPages = navigationPages.filter(p => 
    p.title.toLowerCase().includes(searchQuery.toLowerCase())
  );

  return (
    <>
      <header 
        className={`fixed top-0 right-0 h-20 z-40 transition-all duration-200 ease-[cubic-bezier(0.2,0.8,0.2,1)] flex items-center px-8 lg:px-16 bg-white/60 backdrop-blur-2xl border-b border-black/[0.08] ${
          isCollapsed ? 'left-[72px]' : 'left-[280px]'
        }`}
      >
        <div className="flex items-center justify-between w-full max-w-[1600px] mx-auto">
          
          {/* Left Grid Switcher Button */}
          <div className="flex items-center space-x-6">
            <button
              onClick={() => setIsOpenGridModal(true)}
              className="p-2.5 -ml-2 rounded-[10px] text-zinc-600 hover:text-zinc-900 hover:bg-zinc-200/60 active:scale-[0.98] transition-all focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-offset-2 focus-visible:ring-zinc-800"
              title="Quick Council & App Launcher"
              aria-label="App Launcher Grid"
            >
              <LayoutGrid className="w-5 h-5 text-zinc-700" />
            </button>
          </div>

          {/* Center Raycast-style Command Bar */}
          <div className="flex-1 max-w-[560px] mx-8 relative">
            <div 
              onClick={() => setIsOpenCmd(true)}
              className="relative group cursor-pointer"
            >
              <div className="absolute inset-y-0 left-0 pl-4 flex items-center pointer-events-none">
                <Search className="w-[18px] h-[18px] text-zinc-500 group-hover:text-zinc-900 transition-colors" />
              </div>
              <input
                type="text"
                readOnly
                placeholder="Search councils, tasks, or jump to... (Press ⌘K)"
                className="w-full h-11 pl-[42px] pr-14 bg-zinc-100/80 border border-zinc-200/80 rounded-[12px] text-[14px] text-zinc-900 font-medium placeholder:text-zinc-500 cursor-pointer hover:bg-white hover:border-zinc-300 transition-all duration-200 shadow-sm"
              />
              <div className="absolute inset-y-0 right-0 pr-3 flex items-center pointer-events-none">
                <div className="flex items-center space-x-1 text-zinc-600 px-2 py-0.5 rounded-[6px] bg-white border border-zinc-200 shadow-sm">
                  <Command className="w-3 h-3" />
                  <span className="text-[11px] font-semibold tracking-wider">K</span>
                </div>
              </div>
            </div>
          </div>

          {/* Right Actions */}
          <div className="flex items-center gap-4 relative">
            <button 
              onClick={() => setIsOpenNotifications(prev => !prev)}
              className="relative p-2.5 rounded-[10px] text-zinc-600 hover:text-zinc-900 hover:bg-zinc-200/60 active:scale-[0.98] transition-all focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-offset-2 focus-visible:ring-zinc-800"
              aria-label="View Notifications"
            >
              <Bell className="w-5 h-5 text-zinc-700" />
              {pendingTasks.length > 0 && (
                <span className="absolute top-2 right-2 w-2.5 h-2.5 bg-blue-600 rounded-full border-2 border-white animate-pulse" />
              )}
            </button>

            {/* Notifications Dropdown Drawer */}
            {isOpenNotifications && (
              <div className="absolute top-12 right-0 w-80 sm:w-96 bg-white rounded-[20px] shadow-2xl border border-zinc-200 p-4 z-50 animate-in fade-in zoom-in-95 duration-150">
                <div className="flex items-center justify-between pb-3 border-b border-zinc-100 mb-3">
                  <div className="flex items-center gap-2">
                    <Bell className="w-4 h-4 text-blue-600" />
                    <h3 className="text-sm font-semibold text-zinc-900">Notifications</h3>
                    <span className="px-2 py-0.5 text-[11px] font-bold bg-blue-50 text-blue-700 rounded-full">
                      {pendingTasks.length} new
                    </span>
                  </div>
                </div>

                <div className="space-y-2 max-h-[320px] overflow-y-auto pr-1">
                  {killActive && (
                    <div className="p-3 bg-red-50 border border-red-200 rounded-[12px] flex items-start gap-3">
                      <ShieldAlert className="w-4 h-4 text-red-600 shrink-0 mt-0.5" />
                      <div>
                        <p className="text-xs font-semibold text-red-900">Kill Switch Active</p>
                        <p className="text-[11px] text-red-700 mt-0.5">Automated council runs are currently paused.</p>
                      </div>
                    </div>
                  )}

                  {pendingTasks.map((t, idx) => (
                    <div 
                      key={t.task_id || idx}
                      onClick={() => { router.push('/approvals'); setIsOpenNotifications(false); }}
                      className="p-3 bg-zinc-50 hover:bg-blue-50/50 border border-zinc-200/60 rounded-[12px] cursor-pointer transition-colors"
                    >
                      <div className="flex items-center justify-between">
                        <span className="text-xs font-semibold text-zinc-900 capitalize">{t.council} Council Task</span>
                        <span className="text-[10px] text-zinc-600 capitalize">{t.status.replace('_', ' ')}</span>
                      </div>
                      <p className="text-[11px] text-zinc-600 mt-1 line-clamp-1">{t.task_description}</p>
                    </div>
                  ))}
                  {pendingTasks.length === 0 && !killActive && (
                    <div className="p-4 text-center text-zinc-500 text-sm">
                      No new notifications.
                    </div>
                  )}
                </div>

                <div className="pt-3 border-t border-zinc-100 mt-3 text-center">
                  <button 
                    onClick={() => { router.push('/approvals'); setIsOpenNotifications(false); }}
                    className="text-xs font-semibold text-blue-600 hover:text-blue-700 transition-colors inline-flex items-center gap-1"
                  >
                    <span>View all pending tasks</span>
                    <ArrowRight className="w-3 h-3" />
                  </button>
                </div>
              </div>
            )}
          </div>

        </div>
      </header>

      {/* ── Command Palette Overlay & Modal ──────────────────────────────── */}
      {isOpenCmd && (
        <div className="fixed inset-0 z-50 bg-black/40 backdrop-blur-sm flex items-start justify-center pt-24 px-4 animate-in fade-in duration-150">
          <div className="w-full max-w-2xl bg-white rounded-[24px] shadow-2xl border border-zinc-200 overflow-hidden flex flex-col max-h-[70vh]">
            
            {/* Search Input Bar */}
            <div className="p-4 border-b border-zinc-100 flex items-center gap-3">
              <Search className="w-5 h-5 text-zinc-400 shrink-0" />
              <input
                ref={cmdInputRef}
                type="text"
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                placeholder="Search tasks, councils, pages, or actions..."
                className="w-full text-base font-medium text-zinc-900 placeholder:text-zinc-400 bg-transparent outline-none"
              />
              <button 
                onClick={() => setIsOpenCmd(false)}
                className="p-1.5 rounded-lg text-zinc-400 hover:text-zinc-900 hover:bg-zinc-100 transition-colors"
              >
                <X className="w-5 h-5" />
              </button>
            </div>

            {/* Results Container */}
            <div className="p-3 overflow-y-auto space-y-4">
              
              {/* Pages Section */}
              {filteredPages.length > 0 && (
                <div>
                  <p className="px-3 py-1.5 text-[11px] font-bold text-zinc-600 uppercase tracking-widest">Navigation Pages</p>
                  <div className="space-y-1">
                    {filteredPages.map((page, idx) => {
                      const Icon = page.icon;
                      return (
                        <button
                          key={idx}
                          onClick={() => {
                            router.push(page.path);
                            setIsOpenCmd(false);
                          }}
                          className="w-full flex items-center justify-between p-3 rounded-[12px] hover:bg-zinc-100 text-zinc-800 transition-colors text-left group"
                        >
                          <div className="flex items-center gap-3">
                            <div className="p-2 rounded-lg bg-zinc-100 group-hover:bg-white transition-colors">
                              <Icon className="w-4 h-4 text-zinc-700" />
                            </div>
                            <span className="text-sm font-semibold">{page.title}</span>
                          </div>
                          <ArrowRight className="w-4 h-4 text-zinc-400 group-hover:text-zinc-900 transition-colors" />
                        </button>
                      );
                    })}
                  </div>
                </div>
              )}

              {/* Tasks Section */}
              {filteredTasks.length > 0 && (
                <div>
                  <p className="px-3 py-1.5 text-[11px] font-bold text-zinc-600 uppercase tracking-widest">Tasks & Council Output</p>
                  <div className="space-y-1">
                    {filteredTasks.slice(0, 4).map((t) => (
                      <button
                        key={t.task_id}
                        onClick={() => {
                          router.push(`/approvals/${t.task_id}`);
                          setIsOpenCmd(false);
                        }}
                        className="w-full flex items-center justify-between p-3 rounded-[12px] hover:bg-blue-50/60 text-zinc-800 transition-colors text-left group border border-transparent hover:border-blue-100"
                      >
                        <div className="flex flex-col gap-0.5 pr-4">
                          <div className="flex items-center gap-2">
                            <span className="text-[11px] font-bold uppercase tracking-wider text-blue-700 bg-blue-50 px-2 py-0.5 rounded-md">
                              {t.council}
                            </span>
                            <span className="text-xs text-zinc-600 font-mono">#{t.task_id.slice(0, 8)}</span>
                          </div>
                          <p className="text-xs text-zinc-700 font-medium line-clamp-1 mt-1">{t.task_description}</p>
                        </div>
                        <ArrowRight className="w-4 h-4 text-zinc-400 group-hover:text-blue-600 transition-colors shrink-0" />
                      </button>
                    ))}
                  </div>
                </div>
              )}

            </div>

            {/* Modal Footer */}
            <div className="p-3 bg-zinc-50 border-t border-zinc-100 flex items-center justify-between text-xs text-zinc-500">
              <span>Use arrow keys to navigate</span>
              <span>Press <kbd className="px-1.5 py-0.5 rounded bg-white border text-[10px]">ESC</kbd> to close</span>
            </div>

          </div>
        </div>
      )}

      {/* ── App Launcher Grid Modal ────────────────────────────────────── */}
      {isOpenGridModal && (
        <div className="fixed inset-0 z-50 bg-black/40 backdrop-blur-sm flex items-center justify-center p-4 animate-in fade-in duration-150">
          <div className="w-full max-w-xl bg-white rounded-[24px] shadow-2xl border border-zinc-200 p-6">
            
            <div className="flex items-center justify-between pb-4 border-b border-zinc-100 mb-6">
              <div className="flex items-center gap-3">
                <div className="p-2.5 rounded-[14px] bg-blue-50 text-blue-600">
                  <LayoutGrid className="w-6 h-6" />
                </div>
                <div>
                  <h2 className="text-lg font-bold text-zinc-900">AI Council Launcher</h2>
                  <p className="text-xs text-zinc-500">Jump directly to specialized agent council suites</p>
                </div>
              </div>
              <button 
                onClick={() => setIsOpenGridModal(false)}
                className="p-2 rounded-xl text-zinc-400 hover:text-zinc-900 hover:bg-zinc-100 transition-colors"
              >
                <X className="w-5 h-5" />
              </button>
            </div>

            {/* Council Grid */}
            <div className="grid grid-cols-2 gap-4 mb-6">
              {[
                { title: 'Sales Council', desc: 'Outbound emails & pitch decks', path: '/councils?select=sales', color: 'blue' },
                { title: 'Content Council', desc: 'SEO blogs & social copy', path: '/councils?select=content', color: 'emerald' },
                { title: 'Grant Council', desc: 'Proposals & applications', path: '/councils?select=grant', color: 'amber' },
                { title: 'Strategy Council', desc: 'Market analysis & planning', path: '/councils?select=strategy', color: 'purple' },
              ].map((c, i) => (
                <button
                  key={i}
                  onClick={() => {
                    router.push(c.path);
                    setIsOpenGridModal(false);
                  }}
                  className="p-4 rounded-[16px] border border-zinc-200 hover:border-blue-400 hover:shadow-md transition-all text-left bg-zinc-50/50 hover:bg-white group"
                >
                  <div className="flex items-center justify-between mb-2">
                    <span className="text-sm font-bold text-zinc-900 group-hover:text-blue-600 transition-colors">{c.title}</span>
                    <Sparkles className="w-4 h-4 text-zinc-400 group-hover:text-blue-600 transition-colors" />
                  </div>
                  <p className="text-xs text-zinc-500">{c.desc}</p>
                </button>
              ))}
            </div>

            {/* Quick Actions */}
            <div className="pt-4 border-t border-zinc-100 flex items-center justify-between">
              <button
                onClick={() => { router.push('/workflows'); setIsOpenGridModal(false); }}
                className="text-xs font-semibold text-zinc-600 hover:text-zinc-900 flex items-center gap-1.5"
              >
                <Zap className="w-4 h-4 text-amber-500" />
                <span>Open Workflows</span>
              </button>
              <button
                onClick={() => { router.push('/analytics'); setIsOpenGridModal(false); }}
                className="text-xs font-semibold text-zinc-600 hover:text-zinc-900 flex items-center gap-1.5"
              >
                <BarChart3 className="w-4 h-4 text-blue-500" />
                <span>View Analytics</span>
              </button>
            </div>

          </div>
        </div>
      )}
    </>
  );
}
