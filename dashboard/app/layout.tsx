import type { Metadata } from 'next';
import { Inter } from 'next/font/google';
import './globals.css';
import { SidebarProvider } from './contexts/SidebarContext';
import { AuthProvider } from './contexts/AuthContext';
import { ClientLayoutWrapper } from './components/client-layout-wrapper';

const inter = Inter({ subsets: ['latin'] });

export const metadata: Metadata = {
  title: 'Council OS Dashboard',
  description: 'AI Council OS Management Dashboard',
};

import { Suspense } from 'react';

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body className={`${inter.className} bg-app text-foreground antialiased selection:bg-[#111827] selection:text-white`}>
        <AuthProvider>
          <SidebarProvider>
            <Suspense fallback={<div className="min-h-screen bg-[#090D16]" />}>
              <ClientLayoutWrapper>
                {children}
              </ClientLayoutWrapper>
            </Suspense>
          </SidebarProvider>
        </AuthProvider>
      </body>
    </html>
  );
}
