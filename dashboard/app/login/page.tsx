'use client';

import { useState } from 'react';
import { useAuth } from '../contexts/AuthContext';
import { useRouter } from 'next/navigation';
import { Sparkles, Shield, Lock, User as UserIcon, ArrowRight, AlertCircle } from 'lucide-react';

export default function LoginPage() {
  const { login } = useAuth();
  const router = useRouter();

  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');
    setLoading(true);

    try {
      await login(username, password);
      router.push('/');
    } catch (err: any) {
      setError(err.message || 'Invalid credentials. Access denied.');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen w-full bg-[#090D16] text-white flex items-center justify-center p-6 relative overflow-hidden font-sans selection:bg-blue-600">
      {/* Ambient background glows */}
      <div className="absolute top-1/4 left-1/2 -translate-x-1/2 -translate-y-1/2 w-[600px] h-[600px] bg-blue-600/15 rounded-full blur-[140px] pointer-events-none" />
      <div className="absolute bottom-10 right-10 w-[400px] h-[400px] bg-purple-600/15 rounded-full blur-[120px] pointer-events-none" />
      <div className="absolute top-10 left-10 w-[300px] h-[300px] bg-emerald-600/10 rounded-full blur-[100px] pointer-events-none" />

      {/* Main Glass Card */}
      <div className="w-full max-w-md bg-white/[0.04] backdrop-blur-2xl border border-white/[0.08] rounded-[24px] p-8 md:p-10 shadow-2xl relative z-10">
        
        {/* Header */}
        <div className="text-center mb-8">
          <div className="inline-flex items-center justify-center w-14 h-14 rounded-[18px] bg-gradient-to-tr from-blue-600 to-indigo-600 p-0.5 shadow-lg shadow-blue-500/25 mb-4">
            <div className="w-full h-full bg-[#090D16] rounded-[16px] flex items-center justify-center">
              <Sparkles className="w-7 h-7 text-blue-400" />
            </div>
          </div>

          <h1 className="text-2xl font-bold tracking-tight text-white">AI Council OS</h1>
          <p className="text-sm text-zinc-400 mt-2">Sign in to access Multi-Agent Consensus Platform</p>
        </div>

        {/* Security Badge */}
        <div className="mb-6 p-3 rounded-[12px] bg-blue-500/10 border border-blue-500/20 flex items-center justify-center gap-2 text-blue-300 text-xs font-medium">
          <Shield className="w-4 h-4 shrink-0 text-blue-400" />
          <span>Encrypted Session • HMAC SHA-256 Auth</span>
        </div>

        {/* Error Alert */}
        {error && (
          <div className="mb-6 p-3.5 rounded-[12px] bg-red-500/10 border border-red-500/30 flex items-center gap-3 text-red-300 text-xs animate-shake">
            <AlertCircle className="w-4 h-4 shrink-0 text-red-400" />
            <span>{error}</span>
          </div>
        )}

        {/* Form */}
        <form onSubmit={handleSubmit} className="space-y-5">
          <div>
            <label className="block text-xs font-semibold text-zinc-300 uppercase tracking-wider mb-2">
              Username
            </label>
            <div className="relative">
              <div className="absolute inset-y-0 left-0 pl-3.5 flex items-center pointer-events-none text-zinc-500">
                <UserIcon className="w-4 h-4" />
              </div>
              <input
                type="text"
                required
                autoComplete="username"
                value={username}
                onChange={(e) => {
                  setError('');
                  setUsername(e.target.value);
                }}
                placeholder="Enter your username"
                className="w-full h-11 pl-10 pr-4 bg-white/[0.06] border border-white/[0.1] rounded-[12px] text-sm text-white placeholder:text-zinc-500 focus:outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-500/20 transition-all"
              />
            </div>
          </div>

          <div>
            <label className="block text-xs font-semibold text-zinc-300 uppercase tracking-wider mb-2">
              Password
            </label>
            <div className="relative">
              <div className="absolute inset-y-0 left-0 pl-3.5 flex items-center pointer-events-none text-zinc-500">
                <Lock className="w-4 h-4" />
              </div>
              <input
                type="password"
                required
                autoComplete="current-password"
                value={password}
                onChange={(e) => {
                  setError('');
                  setPassword(e.target.value);
                }}
                placeholder="Enter your password"
                className="w-full h-11 pl-10 pr-4 bg-white/[0.06] border border-white/[0.1] rounded-[12px] text-sm text-white placeholder:text-zinc-500 focus:outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-500/20 transition-all"
              />

            </div>
          </div>

          <button
            type="submit"
            disabled={loading}
            className="w-full h-11 mt-2 bg-gradient-to-r from-blue-600 to-indigo-600 hover:from-blue-500 hover:to-indigo-500 text-white font-medium text-sm rounded-[12px] shadow-lg shadow-blue-600/30 flex items-center justify-center gap-2 transition-all active:scale-[0.98] disabled:opacity-50 cursor-pointer"
          >
            {loading ? (
              <div className="w-5 h-5 border-2 border-white/30 border-t-white rounded-full animate-spin" />
            ) : (
              <>
                <span>Sign In to Dashboard</span>
                <ArrowRight className="w-4 h-4" />
              </>
            )}
          </button>
        </form>

      </div>
    </div>
  );
}
