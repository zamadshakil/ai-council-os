import type { Metadata } from 'next';
import './globals.css';
import { SidebarProvider } from './contexts/SidebarContext';
import { AuthProvider } from './contexts/AuthContext';
import { ClientLayoutWrapper } from './components/client-layout-wrapper';
import { InterfaceMotionProvider } from './components/motion-provider';

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
      <body className="bg-app text-foreground antialiased">
        <InterfaceMotionProvider>
          <AuthProvider>
            <SidebarProvider>
              <Suspense fallback={<div className="min-h-screen bg-[#090D16]" />}>
                <ClientLayoutWrapper>
                  {children}
                </ClientLayoutWrapper>
              </Suspense>
            </SidebarProvider>
          </AuthProvider>
        </InterfaceMotionProvider>
      </body>
    </html>
  );
}
