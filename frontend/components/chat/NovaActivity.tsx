'use client';

import React from 'react';

interface ActivityStep {
  label: string;
  status: 'pending' | 'active' | 'done' | 'error';
}

interface NovaActivityProps {
  activity: string | null;
  steps: ActivityStep[];
}

function HudRing() {
  return (
    <span role="img" aria-label="NOVA sedang memproses" className="relative inline-flex h-5 w-5 shrink-0 items-center justify-center text-[var(--nova-accent-cyan)]">
      <svg viewBox="0 0 40 40" className="h-full w-full overflow-visible" fill="none" aria-hidden="true">
        <circle cx="20" cy="20" r="15.5" stroke="currentColor" strokeOpacity=".28" strokeWidth="1" />
        <circle cx="20" cy="20" r="11.5" stroke="currentColor" strokeOpacity=".72" strokeWidth="1.2" strokeDasharray="9 4 2 4" className="origin-center animate-pulse" />
        <circle cx="20" cy="20" r="6.5" stroke="currentColor" strokeOpacity=".8" strokeWidth="1" />
        <circle cx="20" cy="20" r="2.5" fill="currentColor" className="animate-pulse" />
        <path d="M20 1.5v4 M20 34.5v4 M1.5 20h4 M34.5 20h4" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
        <path d="M8 8l2.5 2.5 M29.5 29.5L32 32 M32 8l-2.5 2.5 M10.5 29.5L8 32" stroke="currentColor" strokeOpacity=".65" strokeWidth="1" strokeLinecap="round" />
      </svg>
      <span className="absolute inset-0 rounded-full bg-[var(--nova-accent-cyan)]/10 blur-sm animate-pulse" aria-hidden="true" />
    </span>
  );
}

export default function NovaActivity({ activity, steps }: NovaActivityProps) {
  if (!activity && steps.length === 0) return null;

  return (
    <div className="flex items-start gap-3 py-2">
      <div className="shrink-0 mt-0.5">
        <div className="w-6 h-6 rounded-full bg-gradient-to-br from-[var(--nova-accent-purple)] to-[var(--nova-accent-cyan)] flex items-center justify-center">
          <span className="text-white text-[10px] font-bold">N</span>
        </div>
      </div>
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2 mb-2">
          <span className="text-xs font-medium text-[var(--nova-accent-purple)]">✦ NOVA Operation</span>
          <HudRing />
        </div>
        {steps.length > 0 && (
          <div className="space-y-1">
            {steps.map((step, i) => (
              <div key={i} className="flex items-center gap-2 text-xs">
                {step.status === 'done' && <span className="text-[var(--nova-accent-cyan)]">✓</span>}
                {step.status === 'active' && <span className="text-[var(--nova-accent-cyan)] animate-pulse">◉</span>}
                {step.status === 'pending' && <span className="text-white/20">○</span>}
                {step.status === 'error' && <span className="text-red-400">✗</span>}
                <span className={`${
                  step.status === 'active' ? 'text-white/70' :
                  step.status === 'done' ? 'text-white/40' :
                  step.status === 'error' ? 'text-red-400/80' :
                  'text-white/25'
                }\`}>
                  {step.label}
                </span>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
