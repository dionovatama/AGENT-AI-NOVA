import { MilestoneBadge } from "@/components/StatusBadge";

interface PlaceholderPanelProps {
  title: string;
  milestone: string;
  description: string;
  prdReference?: string;
}

/**
 * Dipakai untuk seksi yang belum punya endpoint backend nyata
 * (MikroTik, Cisco, Windows executor, Voice, Automation, dst).
 * Sengaja TIDAK dibuat seperti kartu "coming soon" generik marketing —
 * ini progress board internal: apa yang belum ada, kapan (fase PRD),
 * dan kenapa (rujukan section PRD).
 */
export function PlaceholderPanel({
  title,
  milestone,
  description,
  prdReference,
}: PlaceholderPanelProps) {
  return (
    <div className="panel border-dashed p-5">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h3 className="text-sm font-medium text-ink-100">{title}</h3>
          <p className="mt-1.5 max-w-md text-[13px] leading-relaxed text-ink-500">
            {description}
          </p>
          {prdReference && (
            <p className="mt-2 font-mono text-[11px] text-ink-500">{prdReference}</p>
          )}
        </div>
        <MilestoneBadge label={milestone} />
      </div>
    </div>
  );
}
