'use client';

import React, { useEffect } from 'react';
import { CheckCircle2, AlertCircle, Info, X } from 'lucide-react';

export interface ToastProps {
  show: boolean;
  type?: 'success' | 'error' | 'info';
  title: string;
  message?: string;
  onClose: () => void;
  duration?: number;
}

export function Toast({
  show,
  type = 'success',
  title,
  message,
  onClose,
  duration = 3000,
}: ToastProps) {
  useEffect(() => {
    if (!show) return;
    const timer = setTimeout(() => {
      onClose();
    }, duration);
    return () => clearTimeout(timer);
  }, [show, duration, onClose]);

  if (!show) return null;

  const bgStyles = {
    success: 'bg-emerald-900/90 text-white border-emerald-700/50 shadow-emerald-950/20',
    error: 'bg-red-900/90 text-white border-red-700/50 shadow-red-950/20',
    info: 'bg-zinc-900/90 text-white border-zinc-700/50 shadow-zinc-950/20',
  }[type];

  const IconComponent = {
    success: CheckCircle2,
    error: AlertCircle,
    info: Info,
  }[type];

  const iconColor = {
    success: 'text-emerald-400',
    error: 'text-red-400',
    info: 'text-blue-400',
  }[type];

  return (
    <div className="fixed bottom-6 right-6 z-50 animate-in fade-in slide-in-from-bottom-5 duration-300">
      <div
        className={`flex items-center gap-3 px-4 py-3 rounded-2xl border backdrop-blur-md shadow-xl max-w-md ${bgStyles}`}
      >
        <IconComponent className={`w-5 h-5 shrink-0 ${iconColor}`} />
        <div className="flex-1 min-w-0">
          <p className="text-xs font-bold leading-snug">{title}</p>
          {message && <p className="text-[11px] text-zinc-300 leading-snug mt-0.5">{message}</p>}
        </div>
        <button
          onClick={onClose}
          className="p-1 text-zinc-400 hover:text-white rounded-lg transition-colors"
        >
          <X className="w-3.5 h-3.5" />
        </button>
      </div>
    </div>
  );
}
