"use client";

import { useEffect, useState } from "react";
import { HudLoader } from "@/components/HudLoader";
import { PlaceholderPanel } from "@/components/PlaceholderPanel";
import { ToolCard } from "@/components/tools/ToolCard";
import { ToolRunModal } from "@/components/tools/ToolRunModal";
import { novaApi, NovaApiError } from "@/lib/api";
import { KNOWN_TOOLS, type KnownToolSpec } from "@/lib/types";

export default function ToolsPage() {
  const [toolNames, setToolNames] = useState<string[] | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [activeTool, setActiveTool] = useState<KnownToolSpec | null>(null);

  useEffect(() => {
    novaApi
      .listTools()
      .then(setToolNames)
      .catch((err) => setLoadError(err instanceof NovaApiError ? err.message : "Gagal memuat allowlist tool."));
  }, []);

  const known = (toolNames ?? []).map((name) => KNOWN_TOOLS[name]).filter(Boolean) as KnownToolSpec[];
  const unrecognized = (toolNames ?? []).filter((name) => !KNOWN_TOOLS[name]);

  const networkTools = known.filter((t) => t.platform === "network");
  const linuxTools = known.filter((t) => t.platform === "linux");
  const generalTools = known.filter((t) => t.platform === "general");

  return (
    <div className="mx-auto max-w-4xl">
      <header className="mb-6">
        <h1 className="text-base font-medium text-ink-100">Tools</h1>
        <p className="mt-1 text-[13px] text-ink-500">
          Allowlist langsung dari Tool Manager backend (GET /tools/list). Tidak ada
          tool di luar daftar ini yang bisa dijalankan — sesuai prinsip PRD section 30.
        </p>
      </header>

      {loadError && (
        <p className="mb-4 rounded-sm border border-signal-rose/30 bg-signal-rose/10 px-3 py-2 text-[13px] text-signal-rose">
          {loadError}
        </p>
      )}

      {toolNames === null && !loadError && (
        <div className="flex justify-center py-10">
          <HudLoader size={56} label="LOADING ALLOWLIST" />
        </div>
      )}

      {networkTools.length > 0 && (
        <section className="mb-8">
          <h2 className="mb-2.5 text-[13px] text-ink-500">Network Diagnostics</h2>
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            {networkTools.map((tool) => (
              <ToolCard key={tool.name} tool={tool} onRun={setActiveTool} />
            ))}
          </div>
        </section>
      )}

      {linuxTools.length > 0 && (
        <section className="mb-8">
          <h2 className="mb-2.5 text-[13px] text-ink-500">Linux Executor (SSH)</h2>
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            {linuxTools.map((tool) => (
              <ToolCard key={tool.name} tool={tool} onRun={setActiveTool} />
            ))}
          </div>
        </section>
      )}

      {generalTools.length > 0 && (
        <section className="mb-8">
          <h2 className="mb-2.5 text-[13px] text-ink-500">General / Web</h2>
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            {generalTools.map((tool) => (
              <ToolCard key={tool.name} tool={tool} onRun={setActiveTool} />
            ))}
          </div>
        </section>
      )}

      {unrecognized.length > 0 && (
        <p className="mb-8 font-mono text-[11px] text-ink-500">
          Terdaftar di backend tapi belum punya form di console: {unrecognized.join(", ")}
        </p>
      )}

      <section>
        <h2 className="mb-2.5 text-[13px] text-ink-500">Belum tersedia</h2>
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          <PlaceholderPanel
            title="Windows Executor"
            milestone="Phase 4 lanjutan"
            description="PowerShell / WinRM diagnostics — system_info, service_status, event_log, dst."
            prdReference="PRD §16 Windows Executor"
          />
          <PlaceholderPanel
            title="MikroTik Engine"
            milestone="Phase 5"
            description="Diagnostic & configuration RouterOS lewat API-SSL/SSH — interfaces, DHCP, firewall, VLAN."
            prdReference="PRD §17 MikroTik Engine"
          />
          <PlaceholderPanel
            title="Cisco Engine"
            milestone="Phase 6"
            description="Diagnostic & configuration lewat SSH/NETCONF/RESTCONF — VLAN, routing, ACL."
            prdReference="PRD §18 Cisco Engine"
          />
          <PlaceholderPanel
            title="Configuration Engine"
            milestone="Phase 7–8"
            description="Plan → validate → preview → confirm → apply → verify → rollback untuk perubahan konfigurasi network."
            prdReference="PRD §19–22"
          />
        </div>
      </section>

      {activeTool && <ToolRunModal tool={activeTool} onClose={() => setActiveTool(null)} />}
    </div>
  );
}
