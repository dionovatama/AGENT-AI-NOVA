import { Activity, ArrowRight, Globe2, TerminalSquare } from "lucide-react";
import { PermissionBadge, RiskBadge } from "@/components/StatusBadge";
import type { KnownToolSpec } from "@/lib/types";

const TOOL_DESCRIPTIONS: Record<string, string> = {
  ping: "Check reachability and response latency for a host or IP.",
  "linux.system_info": "Inspect Linux host details and operating system information.",
  "linux.network_info": "Review network interfaces, addresses, and routing details.",
  "linux.disk_info": "Check filesystem capacity and disk usage.",
  "linux.memory_info": "Inspect memory and swap utilization.",
  "linux.service_status": "Check whether a systemd service is running.",
  "linux.process_status": "Inspect active processes with an optional name filter.",
  "linux.docker_status": "Review Docker engine and container status.",
  "linux.log_check": "Read recent journal entries for a systemd service.",
  "web.search": "Search the web for current technical references and information.",
  "web.read_page": "Fetch and read the text content of a web page.",
};

const PLATFORM_META = {
  network: { label: "Network", Icon: Activity },
  linux: { label: "Linux / SSH", Icon: TerminalSquare },
  general: { label: "Web", Icon: Globe2 },
} as const;

export function ToolCard({
  tool,
  onRun,
}: {
  tool: KnownToolSpec;
  onRun: (tool: KnownToolSpec) => void;
}) {
  const { label: platformLabel, Icon } = PLATFORM_META[tool.platform];
  const description =
    TOOL_DESCRIPTIONS[tool.name] ??
    `Run the ${tool.label.toLowerCase()} capability on the ${platformLabel} platform.`;

  return (
    <article className="group relative isolate flex min-h-[174px] flex-col justify-between overflow-hidden rounded-lg border border-white/[0.07] bg-[linear-gradient(145deg,rgba(18,24,35,0.96),rgba(12,15,24,0.98))] p-4 transition duration-200 hover:-translate-y-0.5 hover:border-signal-blue/40 hover:shadow-[0_12px_32px_-20px_rgba(76,142,247,0.55)] motion-reduce:transform-none motion-reduce:transition-none">
      <div aria-hidden="true" className="pointer-events-none absolute inset-x-0 bottom-0 -z-10 h-20 bg-[radial-gradient(ellipse_at_bottom,rgba(76,142,247,0.13),transparent_72%)] opacity-75 transition-opacity group-hover:opacity-100" />
      <div aria-hidden="true" className="pointer-events-none absolute inset-x-0 top-0 -z-10 h-px bg-gradient-to-r from-transparent via-white/[0.12] to-transparent" />

      <div>
        <div className="mb-3 flex items-start justify-between gap-3">
          <div className="flex min-w-0 items-center gap-2.5">
            <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-md border border-signal-blue/20 bg-signal-blue/[0.08] text-signal-blue transition-colors group-hover:border-signal-blue/35 group-hover:bg-signal-blue/[0.12]">
              <Icon size={15} strokeWidth={1.8} />
            </span>
            <div className="min-w-0">
              <h3 className="truncate text-[13px] font-semibold text-ink-100">{tool.label}</h3>
              <p className="mt-0.5 truncate font-mono text-[10px] text-ink-500">{tool.name}</p>
            </div>
          </div>
          <span className="shrink-0 rounded-md border border-white/[0.07] bg-white/[0.025] px-2 py-1 text-[10px] text-ink-500">
            {platformLabel}
          </span>
        </div>
        <p className="max-w-[38ch] text-[12px] leading-[1.65] text-ink-300">{description}</p>
      </div>

      <div className="mt-4 flex flex-wrap items-center justify-between gap-3 border-t border-white/[0.06] pt-3">
        <div className="flex flex-wrap items-center gap-1.5">
          <PermissionBadge level={tool.permission_level} />
          <RiskBadge level={tool.risk_level} />
        </div>
        <button
          type="button"
          onClick={() => onRun(tool)}
          aria-label={`Configure and run ${tool.label}`}
          className="inline-flex items-center gap-1 rounded-md px-2 py-1.5 text-[11px] font-medium text-ink-300 transition-colors hover:bg-white/[0.05] hover:text-ink-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-signal-blue/50"
        >
          Configure <ArrowRight size={12} className="transition-transform group-hover:translate-x-0.5" />
        </button>
      </div>
    </article>
  );
}
