import { Activity } from 'lucide-react';

export function StatusOrb({ active = true, size = 'md' }: { active?: boolean; size?: 'sm' | 'md' | 'lg' }) {
  const dimensions = size === 'lg' ? 'h-16 w-16' : size === 'sm' ? 'h-8 w-8' : 'h-11 w-11';
  const icon = size === 'lg' ? 'h-6 w-6' : size === 'sm' ? 'h-3.5 w-3.5' : 'h-4 w-4';
  return (
    <span className={`${active ? 'jarvis-orb' : 'border border-rose-300/20'} ${dimensions} grid place-items-center rounded-full ${active ? 'bg-cyan-400/12 text-cyan-300 shadow-[0_0_32px_rgba(34,211,238,.18)]' : 'bg-rose-400/10 text-rose-300'}`}>
      <Activity className={icon} />
    </span>
  );
}
