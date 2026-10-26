'use client';

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
    <span
      role="img"
      aria-label="NOVA sedang memproses"
      className="relative inline-flex h-5 w-5 shrink-0 items-center justify-center text-[var(--nova-accent-cyan)]"
    >
      <svg viewBox="0 0 40 40" className="h-full w-full" fill="none" aria-hidden="true">
        <circle cx="20" cy="20" r="15" stroke="currentColor" strokeOpacity="0.35" strokeWidth="1" />
        <circle cx="20" cy="20" r="10.5" stroke="currentColor" strokeOpacity="0.8" strokeWidth="1.2" strokeDasharray="8 4 2 4" />
        <circle cx="20" cy="20" r="5.5" stroke="currentColor" strokeOpacity="0.8" strokeWidth="1" />
        <circle cx="20" cy="20" r="2.5" fill="currentColor" className="animate-pulse" />
        <path d="M20 1v5 M20 34v5 M1 20h5 M34 20h5" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
      </svg>
      <span className="absolute inset-0 rounded-full bg-[var(--nova-accent-cyan)]/10 blur-sm animate-pulse" aria-hidden="true" />
    </span>
  );
}

export default function NovaActivity({ activity, steps }: NovaActivityProps) {
  if (!activity && steps.length === 0) return null;

  return (
    <div className="flex items-start gap-3 py-2">
      <div className="mt-0.5 shrink-0">
        <div className="flex h-6 w-6 items-center justify-center rounded-full bg-gradient-to-br from-[var(--nova-accent-purple)] to-[var(--nova-accent-cyan)]">
          <span className="text-[10px] font-bold text-white">N</span>
        </div>
      </div>

      <div className="min-w-0 flex-1">
        <div className="mb-2 flex items-center gap-2">
          <span className="text-xs font-medium text-[var(--nova-accent-purple)]">✦ NOVA Operation</span>
          <HudRing />
        </div>

        {steps.length > 0 && (
          <div className="space-y-1">
            {steps.map((step, i) => {
              let statusClass = 'text-white/25';
              let marker = '○';

              if (step.status === 'done') {
                statusClass = 'text-white/40';
                marker = '✓';
              } else if (step.status === 'active') {
                statusClass = 'text-white/70';
                marker = '◉';
              } else if (step.status === 'error') {
                statusClass = 'text-red-400/80';
                marker = '✗';
              }

              return (
                <div key={i} className="flex items-center gap-2 text-xs">
                  <span className={statusClass}>{marker}</span>
                  <span className={statusClass}>{step.label}</span>
                </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}
