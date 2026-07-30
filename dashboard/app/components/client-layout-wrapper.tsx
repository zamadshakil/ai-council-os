'use client';

import { useSidebar } from '../contexts/SidebarContext';
import { useAuth } from '../contexts/AuthContext';
import { usePathname, useRouter } from 'next/navigation';
import { useEffect, Suspense } from 'react';
import { Sidebar } from './sidebar';
import { TopNav } from './top-nav';
import { Sparkles } from 'lucide-react';

export function ClientLayoutWrapper({ children }: { children: React.ReactNode }) {
  const { isCollapsed } = useSidebar();
  const { user, isLoading } = useAuth();
  const pathname = usePathname();
  const router = useRouter();

  const isLoginPage = pathname === '/login';

  useEffect(() => {
    if (!isLoading && !user && !isLoginPage) {
      router.push('/login');
    }
  }, [user, isLoading, isLoginPage, router]);

  // If on login page, render plain container
  if (isLoginPage) {
    return <main className="min-h-screen w-full">{children}</main>;
  }

  // Show loading spinner while checking auth session
  if (isLoading) {
    return (
      <div className="min-h-screen w-full bg-[#090D16] flex flex-col items-center justify-center gap-4 text-white">
        <div className="w-12 h-12 rounded-[16px] bg-gradient-to-tr from-blue-600 to-indigo-600 flex items-center justify-center shadow-lg shadow-blue-500/25 animate-pulse">
          <Sparkles className="w-6 h-6 text-white" />
        </div>
        <p className="text-sm font-medium text-zinc-400">Authenticating Council OS Session...</p>
      </div>
    );
  }

  // Guard redirect if unauthenticated
  if (!user && !isLoginPage) {
    return null;
  }

  return (
    <div className="min-h-screen bg-[#FAFAFA]">
      <Sidebar />
      <div
        className={`transition-all duration-300 ease-in-out flex flex-col min-h-screen ${
          isCollapsed ? 'pl-20' : 'pl-64'
        }`}
      >
        <TopNav />
        <main className="pt-28 px-8 pb-8 flex-1">
          <Suspense fallback={
            <div className="flex items-center justify-center p-12 text-zinc-500 font-medium">
              Loading Page Content...
            </div>
          }>
            {children}
          </Suspense>
        </main>
      </div>
    </div>
  );
}
