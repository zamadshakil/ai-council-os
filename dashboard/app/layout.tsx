import type { Metadata } from 'next';
import { Inter } from 'next/font/google';
import './globals.css';
import { Suspense } from 'react';
import { Sidebar } from './components/sidebar';
import { TopNav } from './components/top-nav';
import { SidebarProvider } from './contexts/SidebarContext';

const inter = Inter({ subsets: ['latin'] });

export const metadata: Metadata = {
  title: 'Council OS Dashboard',
  description: 'AI Council OS Management Dashboard',
};

// We wrap the layout content in a separate client component if we wanted the whole layout to be client,
// but we can just use a LayoutWrapper client component to consume the SidebarContext for margin.
// Wait, Server Components can't consume Context. So the main container needs to be a Client Component or we just use CSS peer classes.
// Actually, let's create a ClientWrapper for the main layout to adjust the margin.
import { ClientLayoutWrapper } from './components/client-layout-wrapper';

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body className={`${inter.className} bg-app text-foreground antialiased selection:bg-[#111827] selection:text-white`}>
        <SidebarProvider>
          <div className="flex min-h-screen relative">
            <Sidebar />
            <Suspense fallback={<div className="h-16 fixed top-0 right-0 left-[280px] bg-white/40 backdrop-blur-xl border-b border-white/20 z-20" />}>
              <TopNav />
            </Suspense>
            <ClientLayoutWrapper>
              {children}
            </ClientLayoutWrapper>
          </div>
        </SidebarProvider>
      </body>
    </html>
  );
}
