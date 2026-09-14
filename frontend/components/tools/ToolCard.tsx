import { PermissionBadge, RiskBadge } from "@/components/StatusBadge";
import type { KnownToolSpec } from "@/lib/types";

export function ToolCard({
  tool,
  onRun,
}: {
  tool: KnownToolSpec;
  onRun: (tool: KnownToolSpec) => void;
}) {
  return (
    <div className="panel flex flex-col justify-between p-4">
      <div>
        <div className="flex items-start justify-between gap-2">
          <h3 className="font-mono text-[13px] text-ink-100">{tool.name}</h3>
          <span className="rounded-sm border border-base-600 px-1.5 py-0.5 text-[11px] text-ink-500">
            {tool.platform}
          </span>
        </div>
        <p className="mt-1 text-[13px] text-ink-500">{tool.label}</p>
      </div>
      <div className="mt-4 flex items-center justify-between">
        <div className="flex gap-1.5">
          <PermissionBadge level={tool.permission_level} />
          <RiskBadge level={tool.risk_level} />
        </div>
        <button onClick={() => onRun(tool)} className="btn-secondary !px-3 !py-1.5 text-[13px]">
          Run
        </button>
      </div>
    </div>
  );
}
