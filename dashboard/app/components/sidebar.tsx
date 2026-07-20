'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { LayoutDashboard, CheckCircle2, Users, BarChart3, Settings, Hexagon } from 'lucide-react';

const navItems = [
  { name: 'Overview', href: '/', icon: LayoutDashboard },
  { name: 'Approvals', href: '/approvals', icon: CheckCircle2, badge: true },
  { name: 'Councils', href: '/councils', icon: Users },
  { name: 'Analytics', href: '/analytics', icon: BarChart3 },
  { name: 'Settings', href: '/settings', icon: Settings },
];

export function Sidebar() {
  const pathname = usePathname();

  return (
    <div className="w-64 bg-[#F4F4F5] h-screen fixed top-0 left-0 border-r border-zinc-200 flex flex-col">
      <div className="p-6 flex items-center space-x-2">
        <Hexagon className="w-6 h-6 text-blue-600 fill-blue-600/20" />
        <span className="font-semibold text-lg tracking-tight text-zinc-900">Council OS</span>
      </div>
      
      <nav className="flex-1 px-4 space-y-1 mt-4">
        {navItems.map((item) => {
          const isActive = pathname === item.href;
          const Icon = item.icon;
          
          return (
            <Link
              key={item.name}
              href={item.href}
              className={`flex items-center space-x-3 px-3 py-2.5 rounded-md transition-all duration-200 ${
                isActive 
                  ? 'bg-blue-50 text-blue-600 font-medium' 
                  : 'text-zinc-600 hover:bg-zinc-100 hover:text-zinc-900'
              }`}
            >
              <Icon className={`w-5 h-5 ${isActive ? 'text-blue-600' : 'text-zinc-500'}`} />
              <span className="flex-1">{item.name}</span>
              {item.badge && (
                <span className={`text-xs px-2 py-0.5 rounded-full ${
                  isActive ? 'bg-blue-100 text-blue-700' : 'bg-zinc-200 text-zinc-600'
                }`}>
                  3
                </span>
              )}
            </Link>
          );
        })}
      </nav>

      <div className="p-6 text-xs text-zinc-400">
        v0.1.0
      </div>
    </div>
  );
}
