'use client';

import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react';
import { useRouter } from 'next/navigation';
import { fetchSession, loginUser, logoutUser } from '../lib/api';
import { User } from '../lib/types';

interface AuthContextType {
  user: User | null;
  isLoading: boolean;
  login: (username: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
  refreshSession: () => Promise<void>;
}

const AuthContext = createContext<AuthContextType | null>(null);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const [user, setUser] = useState<User | null>(null);
  const [isLoading, setIsLoading] = useState(true);

  const refreshSession = useCallback(async () => {
    try {
      const session = await fetchSession();
      setUser(session.user);
    } catch {
      setUser(null);
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    let active = true;
    void fetchSession()
      .then((session) => { if (active) setUser(session.user); })
      .catch(() => { if (active) setUser(null); })
      .finally(() => { if (active) setIsLoading(false); });
    return () => { active = false; };
  }, []);

  useEffect(() => {
    const handleUnauthorized = () => {
      setUser(null);
      router.replace('/login');
    };
    window.addEventListener('council:unauthorized', handleUnauthorized);
    return () => window.removeEventListener('council:unauthorized', handleUnauthorized);
  }, [router]);

  const login = useCallback(async (username: string, password: string) => {
    const session = await loginUser(username, password);
    setUser(session.user);
  }, []);

  const logout = useCallback(async () => {
    await logoutUser();
    setUser(null);
    router.replace('/login');
    router.refresh();
  }, [router]);

  const value = useMemo(
    () => ({ user, isLoading, login, logout, refreshSession }),
    [user, isLoading, login, logout, refreshSession],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextType {
  const context = useContext(AuthContext);
  if (!context) throw new Error('useAuth must be used inside AuthProvider.');
  return context;
}
