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
    <div className="flex min-h-screen relative w-full">
      <Sidebar />
      <Suspense fallback={<div className="h-20 fixed top-0 right-0 left-[280px] bg-white/60 backdrop-blur-2xl border-b border-black/[0.08] z-40" />}>
        <TopNav />
      </Suspense>
      <main className={`flex-1 transition-all duration-500 ease-[cubic-bezier(0.2,0.8,0.2,1)] pt-28 px-8 lg:px-16 pb-24 ${isCollapsed ? 'ml-[72px]' : 'ml-[280px]'}`}>
        <div className="max-w-[1600px] mx-auto w-full">
          {children}
        </div>
      </main>
    </div>
  );
}
