import type { PermissionLevel, RiskLevel } from "@/lib/types";

const PERMISSION_STYLE: Record<PermissionLevel, string> = {
  read: "text-signal-green border-signal-green/30 bg-signal-green/10",
  modify: "text-signal-amber border-signal-amber/30 bg-signal-amber/10",
  high_risk: "text-signal-rose border-signal-rose/30 bg-signal-rose/10",
};

const PERMISSION_LABEL: Record<PermissionLevel, string> = {
  read: "READ",
  modify: "MODIFY",
  high_risk: "HIGH RISK",
};

export function PermissionBadge({ level }: { level: PermissionLevel }) {
  return (
    <span
      className={`rounded-sm border px-1.5 py-0.5 font-mono text-[11px] ${PERMISSION_STYLE[level]}`}
    >
      {PERMISSION_LABEL[level]}
    </span>
  );
}

const RISK_STYLE: Record<RiskLevel, string> = {
  low: "text-ink-500 border-base-600",
  medium: "text-signal-amber border-signal-amber/30",
  high: "text-signal-rose border-signal-rose/30",
};

export function RiskBadge({ level }: { level: RiskLevel }) {
  return (
    <span className={`rounded-sm border px-1.5 py-0.5 font-mono text-[11px] ${RISK_STYLE[level]}`}>
      risk:{level}
    </span>
  );
}

export function MilestoneBadge({ label }: { label: string }) {
  return (
    <span className="rounded-sm border border-base-600 px-1.5 py-0.5 font-mono text-[11px] text-ink-500">
      {label}
    </span>
  );
}
