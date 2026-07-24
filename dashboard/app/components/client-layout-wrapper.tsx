'use client';

import { useSidebar } from '../contexts/SidebarContext';

export function ClientLayoutWrapper({ children }: { children: React.ReactNode }) {
  const { isCollapsed } = useSidebar();
  
  return (
    <main className={`flex-1 transition-all duration-500 ease-[cubic-bezier(0.2,0.8,0.2,1)] pt-28 px-10 lg:px-20 pb-24 ${isCollapsed ? 'ml-[72px]' : 'ml-[280px]'}`}>
      <div className="max-w-[1600px] mx-auto w-full">
        {children}
      </div>
    </main>
  );
}
