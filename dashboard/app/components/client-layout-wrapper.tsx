'use client';

import { useSidebar } from '../contexts/SidebarContext';
import { useAuth } from '../contexts/AuthContext';
import { usePathname, useRouter } from 'next/navigation';
import { useEffect, Suspense, useState } from 'react';
import { Sidebar } from './sidebar';
import { TopNav } from './top-nav';
import { Sparkles } from 'lucide-react';
import { CommandPalette } from './command-palette';
import { motion } from 'framer-motion';

export function ClientLayoutWrapper({ children }: { children: React.ReactNode }) {
  const { isCollapsed } = useSidebar();
  const { user, isLoading } = useAuth();
  const pathname = usePathname();
  const router = useRouter();
  const [commandOpen, setCommandOpen] = useState(false);

  const isLoginPage = pathname === '/login';

  useEffect(() => {
    if (!isLoading && !user && !isLoginPage) {
      router.replace('/login');
    }
  }, [user, isLoading, isLoginPage, router]);

  useEffect(() => {
    const shortcut = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'k') {
        event.preventDefault();
        setCommandOpen((current) => !current);
      }
    };
    window.addEventListener('keydown', shortcut);
    return () => window.removeEventListener('keydown', shortcut);
  }, []);

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
    <div className="app-grid min-h-screen bg-[#060d17]">
      <Sidebar />
      <div
        className={`shell-content transition-all duration-300 ease-in-out flex flex-col min-h-screen ${
          isCollapsed ? 'pl-[108px]' : 'pl-[108px] md:pl-[272px]'
        }`}
      >
        <TopNav onOpenCommand={() => setCommandOpen(true)} />
        <motion.main
          key={pathname}
          initial={{ opacity: 0, y: 6 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.22, ease: [0.22, 1, 0.36, 1] }}
          className="mx-auto w-full max-w-[1500px] flex-1 px-4 pb-14 pt-8 lg:px-8"
        >
          <Suspense fallback={
            <div className="flex items-center justify-center p-12 text-zinc-500 font-medium">
              Loading Page Content...
            </div>
          }>
            {children}
          </Suspense>
        </motion.main>
      </div>
      <CommandPalette open={commandOpen} onClose={() => setCommandOpen(false)} />
    </div>
  );
}
