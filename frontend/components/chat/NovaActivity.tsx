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

export default function NovaActivity({ activity, steps }: NovaActivityProps) {
  if (!activity && steps.length === 0) return null;

  return (
    <div className="flex items-start gap-3 py-2">
      {/* NOVA icon */}
      <div className="shrink-0 mt-0.5">
        <div className="w-6 h-6 rounded-full bg-gradient-to-br from-[var(--nova-accent-purple)] to-[var(--nova-accent-cyan)] flex items-center justify-center">
          <span className="text-white text-[10px] font-bold">N</span>
        </div>
      </div>

      <div className="flex-1 min-w-0">
        {/* Label */}
        <div className="flex items-center gap-2 mb-2">
          <span className="text-xs font-medium text-[var(--nova-accent-purple)]">✦ NOVA Operation</span>
          <div className="w-3 h-3 rounded-full border-[1.5px] border-[var(--nova-accent-cyan)] border-t-transparent animate-spin" />
        </div>

        {/* Steps */}
        {steps.length > 0 && (
          <div className="space-y-1">
            {steps.map((step, i) => (
              <div key={i} className="flex items-center gap-2 text-xs">
                {step.status === 'done' && (
                  <span className="text-[var(--nova-accent-cyan)]">✓</span>
                )}
                {step.status === 'active' && (
                  <span className="text-[var(--nova-accent-purple)]">◉</span>
                )}
                {step.status === 'pending' && (
                  <span className="text-white/20">○</span>
                )}
                {step.status === 'error' && (
                  <span className="text-red-400">✗</span>
                )}
                <span className={`${
                  step.status === 'active' ? 'text-white/70' :
                  step.status === 'done' ? 'text-white/40' :
                  step.status === 'error' ? 'text-red-400/80' :
                  'text-white/25'
                }`}>
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
