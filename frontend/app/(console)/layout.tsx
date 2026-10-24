'use client';

import React, { useState } from 'react';
import Link from 'next/link';
import { usePathname, useRouter } from 'next/navigation';

// Icons as simple components
const MenuIcon = () => (
  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
    <path d="M3 12h18M3 6h18M3 18h18" />
  </svg>
);

const ChatIcon = () => (
  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
    <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" />
  </svg>
);

const DevicesIcon = () => (
  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
    <rect x="2" y="3" width="20" height="14" rx="2" />
    <path d="M8 21h8M12 17v4" />
  </svg>
);

const LogoutIcon = () => (
  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
    <path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4M16 17l5-5-5-5M21 12H9" />
  </svg>
);

const navItems = [
  { href: '/chat', icon: ChatIcon, label: 'Chat' },
  { href: '/devices', icon: DevicesIcon, label: 'Devices' },
];

export default function ConsoleLayout({ children }: { children: React.ReactNode }) {
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const pathname = usePathname();
  const router = useRouter();

  const handleLogout = () => {
    localStorage.removeItem('nova_token');
    router.push('/login');
  };

  return (
    <div className="flex h-screen overflow-hidden bg-[var(--nova-bg-primary)]">
      {/* Sidebar */}
      <aside
        className={`${
          sidebarOpen ? 'w-52' : 'w-14'
        } bg-[var(--nova-bg-secondary)] border-r border-white/[0.06] 
        flex flex-col shrink-0 transition-all duration-300 ease-in-out`}
      >
        {/* Logo */}
        <div className="h-12 flex items-center px-3 border-b border-white/[0.06]">
          {sidebarOpen ? (
            <div className="flex items-center gap-2">
              <div className="w-7 h-7 rounded-lg bg-gradient-to-br from-[var(--nova-accent-purple)] to-[var(--nova-accent-cyan)] flex items-center justify-center">
                <span className="text-white text-[10px] font-bold">N</span>
              </div>
              <span className="text-white font-semibold text-sm">N.O.V.A</span>
            </div>
          ) : (
            <div className="w-7 h-7 rounded-lg bg-gradient-to-br from-[var(--nova-accent-purple)] to-[var(--nova-accent-cyan)] flex items-center justify-center mx-auto">
              <span className="text-white text-[10px] font-bold">N</span>
            </div>
          )}
        </div>

        {/* Navigation */}
        <nav className="flex-1 p-2">
          {navItems.map((item) => {
            const isActive = pathname === item.href || pathname?.startsWith(item.href + '/');
            return (
              <Link
                key={item.href}
                href={item.href}
                className={`flex items-center gap-2.5 px-2.5 py-2 rounded-lg mb-0.5 transition-all duration-200
                  ${isActive
                    ? 'bg-white/[0.08] text-white'
                    : 'text-white/40 hover:text-white/70 hover:bg-white/[0.04]'
                  }
                `}
              >
                <item.icon />
                {sidebarOpen && <span className="text-sm">{item.label}</span>}
              </Link>
            );
          })}
        </nav>

        {/* Logout */}
        <div className="p-2 border-t border-white/[0.06]">
          <button
            onClick={handleLogout}
            className="flex items-center gap-2.5 px-2.5 py-2 rounded-lg w-full
              text-white/40 hover:text-red-400 hover:bg-red-400/10 transition-all duration-200"
          >
            <LogoutIcon />
            {sidebarOpen && <span className="text-sm">Logout</span>}
          </button>
        </div>
      </aside>

      {/* Main Content */}
      <main className="flex-1 flex flex-col overflow-hidden min-w-0">
        {/* Header — compact */}
        <header className="h-12 flex items-center justify-between px-4 border-b border-white/[0.06] bg-[var(--nova-bg-secondary)]/50 backdrop-blur-xl shrink-0">
          <div className="flex items-center gap-3">
            <button
              onClick={() => setSidebarOpen(!sidebarOpen)}
              className="text-white/40 hover:text-white/80 transition-colors p-1"
            >
              <MenuIcon />
            </button>
            <div className="flex items-center gap-2">
              <div className="w-1.5 h-1.5 rounded-full bg-[var(--nova-accent-cyan)] animate-pulse" />
              <span className="text-white/60 text-sm font-medium">NOVA Console</span>
            </div>
          </div>
          <div className="flex items-center gap-2">
            <span className="text-[10px] text-white/20 font-mono">v0.1.0-alpha</span>
          </div>
        </header>

        {/* Page Content — takes all remaining space, no overflow on this div */}
        <div className="flex-1 overflow-hidden">
          {children}
        </div>
      </main>
    </div>
  );
}
