'use client';

import { useState } from 'react';
import { Search, Command, LayoutGrid, Bell, Plus, History, CheckCircle2 } from 'lucide-react';
import { useSidebar } from '../contexts/SidebarContext';

export function TopNav() {
  const { isCollapsed, toggleSidebar } = useSidebar();
  const [isCommandFocused, setIsCommandFocused] = useState(false);

  return (
    <header 
      className={`fixed top-0 right-0 h-20 z-40 transition-all duration-200 ease-[cubic-bezier(0.2,0.8,0.2,1)] flex items-center px-8 lg:px-16 bg-white/60 backdrop-blur-2xl border-b border-black/[0.08] ${
        isCollapsed ? 'left-[72px]' : 'left-[280px]'
      }`}
    >
      <div className="flex items-center justify-between w-full max-w-[1600px] mx-auto">
        
        {/* Left Actions */}
        <div className="flex items-center space-x-6">
          <button
            onClick={toggleSidebar}
            className="p-2 -ml-2 rounded-[8px] text-zinc-500 hover:text-zinc-900 hover:bg-zinc-200/50 active:scale-[0.98] transition-all focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-offset-2 focus-visible:ring-zinc-800"
            aria-label="Toggle Sidebar"
          >
            <LayoutGrid className="w-5 h-5" />
          </button>
        </div>

        {/* Center Raycast-style Command Bar */}
        <div className="flex-1 max-w-[560px] mx-8 relative">
          <div className="relative group z-50">
            <div className="absolute inset-y-0 left-0 pl-4 flex items-center pointer-events-none">
              <Search className={`w-[18px] h-[18px] transition-colors duration-200 ${isCommandFocused ? 'text-zinc-900' : 'text-zinc-500'}`} />
            </div>
            <input
              type="text"
              placeholder="Search councils, tasks, or jump to..."
              onFocus={() => setIsCommandFocused(true)}
              onBlur={() => setIsCommandFocused(false)}
              className="w-full h-11 pl-[42px] pr-14 bg-zinc-100/80 border border-zinc-200 rounded-[12px] text-[15px] text-zinc-900 font-medium placeholder:text-zinc-500 focus:bg-white focus:border-zinc-300 focus:ring-4 focus:ring-zinc-200 focus:shadow-floating outline-none transition-all duration-200"
            />
            <div className="absolute inset-y-0 right-0 pr-3 flex items-center pointer-events-none">
              <div className="flex items-center space-x-1 text-zinc-600 px-2.5 py-1 rounded-[6px] bg-white border border-zinc-200 shadow-sm">
                <Command className="w-3 h-3" />
                <span className="text-[11px] font-semibold tracking-wider">K</span>
              </div>
            </div>
          </div>

          {/* Command Palette Dropdown (Simulated Raycast style) */}
          <div className={`absolute top-14 left-0 w-full bg-white rounded-[16px] shadow-floating border border-zinc-200 p-2 transition-all duration-200 transform origin-top ${isCommandFocused ? 'opacity-100 scale-100 pointer-events-auto' : 'opacity-0 scale-95 pointer-events-none'}`}>
            <div className="p-1 flex flex-col gap-1">
              <p className="px-3 py-2 text-[12px] font-semibold text-zinc-500 uppercase tracking-widest">Suggestions</p>
              
              <button className="w-full flex items-center justify-between p-3 rounded-[8px] bg-zinc-100 hover:bg-zinc-200 cursor-pointer transition-colors active:scale-[0.99] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-zinc-800">
                <div className="flex items-center gap-3 text-zinc-900">
                  <Plus className="w-[18px] h-[18px]" />
                  <span className="text-[14px] font-medium">Run New Council</span>
                </div>
                <div className="flex items-center gap-1">
                  <kbd className="px-2 py-1 rounded-[6px] bg-white text-[11px] font-semibold text-zinc-600 border border-zinc-200 shadow-sm">C</kbd>
                </div>
              </button>
              
              <button className="w-full flex items-center justify-between p-3 rounded-[8px] bg-transparent hover:bg-zinc-100 cursor-pointer text-zinc-600 hover:text-zinc-900 transition-colors active:scale-[0.99] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-zinc-800">
                <div className="flex items-center gap-3">
                  <CheckCircle2 className="w-[18px] h-[18px]" />
                  <span className="text-[14px] font-medium">Review Pending Approvals</span>
                </div>
                <div className="flex items-center gap-1">
                  <kbd className="px-2 py-1 rounded-[6px] bg-white text-[11px] font-semibold text-zinc-600 border border-zinc-200 shadow-sm">G</kbd>
                  <kbd className="px-2 py-1 rounded-[6px] bg-white text-[11px] font-semibold text-zinc-600 border border-zinc-200 shadow-sm">A</kbd>
                </div>
              </button>

              <button className="w-full flex items-center justify-between p-3 rounded-[8px] bg-transparent hover:bg-zinc-100 cursor-pointer text-zinc-600 hover:text-zinc-900 transition-colors active:scale-[0.99] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-zinc-800">
                <div className="flex items-center gap-3">
                  <History className="w-[18px] h-[18px]" />
                  <span className="text-[14px] font-medium">View Execution History</span>
                </div>
              </button>
            </div>
          </div>
        </div>

        {/* Right Actions */}
        <div className="flex items-center gap-4">
          <button 
            className="relative p-2 rounded-[8px] text-zinc-500 hover:text-zinc-900 hover:bg-zinc-200/50 active:scale-[0.98] transition-all focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-offset-2 focus-visible:ring-zinc-800"
            aria-label="View Notifications"
          >
            <Bell className="w-5 h-5" />
            <span className="absolute top-1.5 right-1.5 w-2 h-2 bg-blue-600 rounded-full border-2 border-white" />
          </button>
        </div>

      </div>
    </header>
  );
}
