"use client";

import { useEffect, useMemo, useState } from "react";
import { ArrowRight, FileCode2, ImagePlus, Search, SlidersHorizontal, Wrench, X } from "lucide-react";
import { HudLoader } from "@/components/HudLoader";
import { PlaceholderPanel } from "@/components/PlaceholderPanel";
import { ToolCard } from "@/components/tools/ToolCard";
import { ToolRunModal } from "@/components/tools/ToolRunModal";
import { ImageStudio } from "@/components/tools/ImageStudio";
import { MikrotikConfigGenerator } from "@/components/tools/MikrotikConfigGenerator";
import { LinuxConfigGenerator } from "@/components/tools/LinuxConfigGenerator";
import { Bind9ConfigGenerator } from "@/components/tools/Bind9ConfigGenerator";
import { novaApi, NovaApiError } from "@/lib/api";
import { KNOWN_TOOLS, type KnownToolSpec, type PermissionLevel } from "@/lib/types";

type PlatformFilter = "all" | KnownToolSpec["platform"];
type PermissionFilter = "all" | PermissionLevel;

const PLATFORM_FILTERS: { value: PlatformFilter; label: string }[] = [
  { value: "all", label: "All tools" },
  { value: "network", label: "Network" },
  { value: "linux", label: "Linux / SSH" },
  { value: "general", label: "Web & general" },
];

const PERMISSION_FILTERS: { value: PermissionFilter; label: string }[] = [
  { value: "all", label: "All access" },
  { value: "read", label: "READ" },
  { value: "modify", label: "MODIFY" },
  { value: "high_risk", label: "HIGH RISK" },
];

export default function ToolsPage() {
  const [toolNames, setToolNames] = useState<string[] | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [activeTool, setActiveTool] = useState<KnownToolSpec | null>(null);
  const [query, setQuery] = useState("");
  const [platformFilter, setPlatformFilter] = useState<PlatformFilter>("all");
  const [permissionFilter, setPermissionFilter] = useState<PermissionFilter>("all");
  const [generatorOpen, setGeneratorOpen] = useState(false);
  const [linuxGeneratorOpen, setLinuxGeneratorOpen] = useState(false);
  const [bind9GeneratorOpen, setBind9GeneratorOpen] = useState(false);
  const [imageStudioOpen, setImageStudioOpen] = useState(false);

  useEffect(() => {
    let mounted = true;
    novaApi
      .listTools()
      .then((names) => {
        if (mounted) setToolNames(names);
      })
      .catch((err) => {
        if (mounted) {
          setLoadError(err instanceof NovaApiError ? err.message : "Gagal memuat allowlist tool.");
        }
      });
    return () => {
      mounted = false;
    };
  }, []);

  const known = (toolNames ?? []).map((name) => KNOWN_TOOLS[name]).filter(Boolean) as KnownToolSpec[];
  const unrecognized = (toolNames ?? []).filter((name) => !KNOWN_TOOLS[name]);

  const filteredTools = useMemo(() => {
    const normalizedQuery = query.trim().toLowerCase();
    return known.filter((tool) => {
      const matchesQuery =
        !normalizedQuery ||
        [tool.name, tool.label, tool.platform, tool.permission_level, tool.risk_level]
          .some((value) => value.toLowerCase().includes(normalizedQuery));
      const matchesPlatform = platformFilter === "all" || tool.platform === platformFilter;
      const matchesPermission =
        permissionFilter === "all" || tool.permission_level === permissionFilter;
      return matchesQuery && matchesPlatform && matchesPermission;
    });
  }, [known, query, platformFilter, permissionFilter]);

  const isFiltering = query.trim().length > 0 || platformFilter !== "all" || permissionFilter !== "all";
  const normalizedQuery = query.trim().toLowerCase();
  const showGeneratorCard =
    (platformFilter === "all" || platformFilter === "network") &&
    permissionFilter === "all" &&
    (!normalizedQuery || "mikrotik configuration generator configuration routeros".includes(normalizedQuery));

  return (
    <div className="mx-auto w-full max-w-6xl">
      <header className="mb-5 flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <div className="mb-2 flex items-center gap-2 text-[10px] font-medium uppercase tracking-[0.18em] text-signal-blue">
            <span className="h-1.5 w-1.5 rounded-full bg-signal-blue shadow-[0_0_8px_rgba(76,142,247,0.55)]" />
            NOVA capability center
          </div>
          <h1 className="text-xl font-semibold tracking-tight text-ink-100">Tools</h1>
          <p className="mt-1 max-w-2xl text-[13px] leading-5 text-ink-500">
            Available capabilities from the backend allowlist. Access level and risk are shown before execution.
          </p>
        </div>
        <div className="flex items-center gap-2 self-start rounded-md border border-base-700 bg-base-800/70 px-3 py-2 text-[11px] text-ink-300 sm:self-auto">
          <Wrench size={13} className="text-signal-blue" />
          <span className="font-mono tabular-nums">{known.length.toString().padStart(2, "0")}</span>
          <span>available</span>
        </div>
      </header>

      {loadError && (
        <div role="alert" className="mb-4 rounded-md border border-signal-rose/30 bg-signal-rose/10 px-3 py-2.5 text-[13px] text-signal-rose">
          {loadError}
        </div>
      )}

      <section aria-label="Search and filter tools" className="mb-5 rounded-lg border border-base-700/80 bg-base-800/45 p-3 sm:p-3.5">
        <div className="flex flex-col gap-3 lg:flex-row lg:items-center">
          <label className="relative block min-w-0 flex-1">
            <Search size={15} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-ink-500" />
            <input
              type="search"
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="Search tools, platform, or access level…"
              aria-label="Search tools"
              className="h-10 w-full rounded-md border border-base-700 bg-base-950/80 pl-9 pr-3 text-[13px] text-ink-100 outline-none transition placeholder:text-ink-500 focus:border-signal-blue/60 focus:ring-2 focus:ring-signal-blue/10"
            />
          </label>
          <div className="flex items-center gap-2 text-[11px] text-ink-500">
            <SlidersHorizontal size={14} />
            <span>FILTER BY</span>
          </div>
          <div className="flex flex-wrap gap-1.5" role="group" aria-label="Filter by access level">
            {PERMISSION_FILTERS.map((filter) => (
              <button
                key={filter.value}
                type="button"
                aria-pressed={permissionFilter === filter.value}
                onClick={() => setPermissionFilter(filter.value)}
                className={`rounded-md border px-2.5 py-1.5 text-[11px] transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-signal-blue/40 ${
                  permissionFilter === filter.value
                    ? "border-signal-blue/40 bg-signal-blue/10 text-ink-100"
                    : "border-base-700 text-ink-500 hover:border-base-600 hover:text-ink-300"
                }`}
              >
                {filter.label}
              </button>
            ))}
          </div>
        </div>
        <div className="mt-3 flex flex-wrap items-center gap-1.5 border-t border-base-700/70 pt-3" role="group" aria-label="Filter by platform">
          {PLATFORM_FILTERS.map((filter) => (
            <button
              key={filter.value}
              type="button"
              aria-pressed={platformFilter === filter.value}
              onClick={() => setPlatformFilter(filter.value)}
              className={`rounded-full px-3 py-1.5 text-[12px] transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-signal-blue/40 ${
                platformFilter === filter.value
                  ? "bg-white/[0.09] text-ink-100"
                  : "text-ink-500 hover:bg-white/[0.04] hover:text-ink-300"
              }`}
            >
              {filter.label}
            </button>
          ))}
          <span className="ml-auto pl-2 font-mono text-[11px] text-ink-500" aria-live="polite">
            {filteredTools.length} / {known.length}
          </span>
          {isFiltering && (
            <button
              type="button"
              onClick={() => {
                setQuery("");
                setPlatformFilter("all");
                setPermissionFilter("all");
              }}
              className="text-[11px] text-signal-blue transition hover:text-ink-100"
            >
              Reset
            </button>
          )}
        </div>
      </section>

      {toolNames === null && !loadError && (
        <div className="flex justify-center rounded-lg border border-base-700/70 py-12">
          <HudLoader size={48} label="LOADING ALLOWLIST" />
        </div>
      )}

      {toolNames !== null && !loadError && (filteredTools.length > 0 || showGeneratorCard) && (
        <section aria-label="Available tools">
          <div className="mb-2.5 flex items-center justify-between">
            <h2 className="text-[12px] font-medium text-ink-300">Available capabilities</h2>
            <span className="font-mono text-[10px] uppercase tracking-wider text-ink-500">Select a tool to configure</span>
          </div>
          <div className="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-3">
            <button
              type="button"
              onClick={() => setImageStudioOpen(true)}
              className="group relative flex min-h-[174px] flex-col justify-between overflow-hidden rounded-lg border border-white/[0.07] bg-[linear-gradient(145deg,rgba(27,18,40,0.96),rgba(12,15,24,0.98))] p-4 text-left transition duration-200 hover:-translate-y-0.5 hover:border-orb-glow/40 hover:shadow-[0_12px_32px_-20px_rgba(168,85,247,0.5)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-orb-glow/50 motion-reduce:transform-none motion-reduce:transition-none"
            >
              <div>
                <div className="mb-3 flex items-start justify-between gap-3">
                  <div className="flex min-w-0 items-center gap-2.5">
                    <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-md border border-orb-glow/20 bg-orb-glow/[0.08] text-orb-core"><ImagePlus size={15} strokeWidth={1.8} /></span>
                    <div className="min-w-0"><h3 className="text-[13px] font-semibold text-ink-100">NOVA Image Studio</h3><p className="mt-0.5 font-mono text-[10px] text-ink-500">Puter.js · Text to image</p></div>
                  </div>
                  <span className="shrink-0 rounded-md border border-orb-glow/20 bg-orb-glow/[0.06] px-2 py-1 text-[10px] text-orb-core">Image AI</span>
                </div>
                <p className="text-[12px] leading-[1.65] text-ink-300">Buat gambar dari prompt, lihat pratinjau, lalu buka atau simpan hasilnya. Memerlukan koneksi internet.</p>
              </div>
              <div className="mt-4 flex items-center justify-between border-t border-white/[0.06] pt-3"><span className="text-[10px] text-ink-500">User account / quota</span><span className="inline-flex items-center gap-1 rounded-md px-2 py-1.5 text-[11px] font-medium text-ink-300 transition-colors group-hover:text-ink-100">Open studio <ArrowRight size={12} className="transition-transform group-hover:translate-x-0.5" /></span></div>
            </button>
            {showGeneratorCard && (
              <button
                type="button"
                onClick={() => setGeneratorOpen(true)}
                className="group relative flex min-h-[174px] flex-col justify-between overflow-hidden rounded-lg border border-white/[0.07] bg-[linear-gradient(145deg,rgba(18,24,35,0.96),rgba(12,15,24,0.98))] p-4 text-left transition duration-200 hover:-translate-y-0.5 hover:border-signal-blue/40 hover:shadow-[0_12px_32px_-20px_rgba(76,142,247,0.55)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-signal-blue/50 motion-reduce:transform-none motion-reduce:transition-none"
              >
                <div>
                  <div className="mb-3 flex items-start justify-between gap-3">
                    <div className="flex min-w-0 items-center gap-2.5">
                      <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-md border border-signal-blue/20 bg-signal-blue/[0.08] text-signal-blue group-hover:bg-signal-blue/[0.12]">
                        <FileCode2 size={15} strokeWidth={1.8} />
                      </span>
                      <div className="min-w-0">
                        <h3 className="text-[13px] font-semibold text-ink-100">MikroTik Configuration Generator</h3>
                        <p className="mt-0.5 font-mono text-[10px] text-ink-500">RouterOS v6 / v7</p>
                      </div>
                    </div>
                    <span className="shrink-0 rounded-md border border-signal-blue/20 bg-signal-blue/[0.06] px-2 py-1 text-[10px] text-signal-blue">Offline</span>
                  </div>
                  <p className="text-[12px] leading-[1.65] text-ink-300">Generate dan preview konfigurasi IP, DHCP, NAT, serta firewall. Tidak menerapkan konfigurasi ke router.</p>
                </div>
                <div className="mt-4 flex items-center justify-between border-t border-white/[0.06] pt-3">
                  <span className="text-[10px] text-ink-500">.rsc · .json · .txt</span>
                  <span className="inline-flex items-center gap-1 rounded-md px-2 py-1.5 text-[11px] font-medium text-ink-300 transition-colors group-hover:text-ink-100">Open tool <ArrowRight size={12} className="transition-transform group-hover:translate-x-0.5" /></span>
                </div>
              </button>
            )}
            {(platformFilter === "all" || platformFilter === "linux") && permissionFilter === "all" && (!normalizedQuery || "linux configuration generator debian ubuntu ssh bind9 firewall".includes(normalizedQuery)) && (
              <button type="button" onClick={() => setLinuxGeneratorOpen(true)} className="group flex min-h-[174px] flex-col justify-between rounded-lg border border-white/[0.07] bg-[linear-gradient(145deg,rgba(18,24,35,0.96),rgba(12,15,24,0.98))] p-4 text-left transition hover:-translate-y-0.5 hover:border-signal-blue/40 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-signal-blue/50">
                <div><div className="mb-3 flex items-start justify-between gap-3"><div className="flex items-center gap-2.5"><span className="flex h-8 w-8 items-center justify-center rounded-md border border-signal-blue/20 bg-signal-blue/[0.08] text-signal-blue"><FileCode2 size={15}/></span><div><h3 className="text-[13px] font-semibold text-ink-100">Linux Configuration Generator</h3><p className="mt-0.5 font-mono text-[10px] text-ink-500">Debian / Ubuntu</p></div></div><span className="rounded-md border border-signal-blue/20 px-2 py-1 text-[10px] text-signal-blue">Offline</span></div><p className="text-[12px] leading-[1.65] text-ink-300">Generate script .sh dan konfigurasi SSH, BIND9, paket, serta aturan UFW untuk ditinjau.</p></div>
                <div className="mt-4 flex items-center justify-between border-t border-white/[0.06] pt-3"><span className="text-[10px] text-ink-500">.sh · native config · JSON</span><span className="text-[11px] text-ink-300 group-hover:text-ink-100">Open tool <ArrowRight size={12} className="inline"/></span></div>
              </button>
            )}
            {(platformFilter === "all" || platformFilter === "linux") && permissionFilter === "all" && (!normalizedQuery || "bind9 dns resolver authoritative master slave generator".includes(normalizedQuery)) && (
              <button type="button" onClick={() => setBind9GeneratorOpen(true)} className="group flex min-h-[174px] flex-col justify-between rounded-lg border border-white/[0.07] bg-[linear-gradient(145deg,rgba(18,24,35,0.96),rgba(12,15,24,0.98))] p-4 text-left transition hover:-translate-y-0.5 hover:border-signal-blue/40 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-signal-blue/50">
                <div><div className="mb-3 flex items-start justify-between gap-3"><div className="flex items-center gap-2.5"><span className="flex h-8 w-8 items-center justify-center rounded-md border border-signal-blue/20 bg-signal-blue/[0.08] text-signal-blue"><FileCode2 size={15}/></span><div><h3 className="text-[13px] font-semibold text-ink-100">BIND9 Configuration Generator</h3><p className="mt-0.5 font-mono text-[10px] text-ink-500">DNS Resolver · Authoritative</p></div></div><span className="rounded-md border border-signal-blue/20 px-2 py-1 text-[10px] text-signal-blue">Offline</span></div><p className="text-[12px] leading-[1.65] text-ink-300">Generate Resolver, Master, Slave, Master + Slave, dan custom DNS zone files.</p></div>
                <div className="mt-4 flex items-center justify-between border-t border-white/[0.06] pt-3"><span className="text-[10px] text-ink-500">BIND9 · Debian</span><span className="text-[11px] text-ink-300 group-hover:text-ink-100">Open tool <ArrowRight size={12} className="inline"/></span></div>
              </button>
            )}
            {filteredTools.map((tool) => (
              <ToolCard key={tool.name} tool={tool} onRun={setActiveTool} />
            ))}
          </div>
        </section>
      )}

      {toolNames !== null && !loadError && filteredTools.length === 0 && !showGeneratorCard && (
        <div className="flex flex-col items-center rounded-lg border border-dashed border-base-700 px-5 py-12 text-center">
          <Search size={19} className="mb-3 text-ink-500" />
          <p className="text-sm font-medium text-ink-300">No matching tools</p>
          <p className="mt-1 text-[12px] text-ink-500">Try another keyword or clear the current filters.</p>
          <button
            type="button"
            onClick={() => {
              setQuery("");
              setPlatformFilter("all");
              setPermissionFilter("all");
            }}
            className="mt-3 text-[12px] text-signal-blue hover:text-ink-100"
          >
            Clear filters
          </button>
        </div>
      )}

      {unrecognized.length > 0 && (
        <p className="mt-5 rounded-md border border-base-700/70 px-3 py-2 font-mono text-[11px] text-ink-500">
          Backend tools without a console form: {unrecognized.join(", ")}
        </p>
      )}

      <section className="mt-8 border-t border-base-700/70 pt-5">
        <div className="mb-3 flex items-center justify-between">
          <div>
            <h2 className="text-[12px] font-medium text-ink-300">Coming next</h2>
            <p className="mt-1 text-[11px] text-ink-500">Planned capabilities — not executable yet.</p>
          </div>
          <span className="font-mono text-[10px] uppercase tracking-wider text-ink-500">Roadmap</span>
        </div>
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          <PlaceholderPanel
            title="Windows Executor"
            milestone="Phase 4 lanjutan"
            description="PowerShell / WinRM diagnostics — system_info, service_status, event_log, dst."
            prdReference="PRD §16 Windows Executor"
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

      {imageStudioOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/75 p-3 backdrop-blur-sm sm:p-6" onMouseDown={(event) => { if (event.target === event.currentTarget) setImageStudioOpen(false); }}>
          <section role="dialog" aria-modal="true" aria-labelledby="puter-image-studio-title" className="max-h-[92vh] w-full max-w-6xl overflow-y-auto rounded-xl border border-base-700 bg-base-900 shadow-2xl">
            <div className="sticky top-0 z-10 flex items-center justify-between border-b border-base-700 bg-base-900/95 px-4 py-3 backdrop-blur sm:px-5"><div className="flex items-center gap-2 text-sm font-semibold text-ink-100"><ImagePlus size={16} className="text-orb-core" /><h2 id="puter-image-studio-title">NOVA Image Studio</h2></div><button type="button" onClick={() => setImageStudioOpen(false)} aria-label="Close Image Studio" className="rounded-md border border-base-700 p-2 text-ink-400 transition hover:bg-white/[0.05] hover:text-ink-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-orb-glow/50"><X size={15} /></button></div>
            <div className="p-2 sm:p-3"><ImageStudio/></div>
          </section>
        </div>
      )}

      {bind9GeneratorOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/75 p-3 backdrop-blur-sm sm:p-6" onMouseDown={(event) => { if (event.target === event.currentTarget) setBind9GeneratorOpen(false); }}>
          <section role="dialog" aria-modal="true" aria-labelledby="bind9-generator-title" className="max-h-[92vh] w-full max-w-6xl overflow-y-auto rounded-xl border border-base-700 bg-base-900 shadow-2xl">
            <div className="sticky top-0 z-10 flex items-center justify-between border-b border-base-700 bg-base-900/95 px-4 py-3"><div className="flex items-center gap-2 text-sm font-semibold text-ink-100"><FileCode2 size={16} className="text-signal-blue"/><h2 id="bind9-generator-title">BIND9 Configuration Generator</h2></div><button type="button" onClick={() => setBind9GeneratorOpen(false)} aria-label="Close BIND9 generator" className="rounded-md border border-base-700 p-2 text-ink-400 hover:text-ink-100"><X size={15}/></button></div>
            <div className="p-2 sm:p-3"><Bind9ConfigGenerator/></div>
          </section>
        </div>
      )}
      {linuxGeneratorOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/75 p-3 backdrop-blur-sm sm:p-6" onMouseDown={(event) => { if (event.target === event.currentTarget) setLinuxGeneratorOpen(false); }}>
          <section role="dialog" aria-modal="true" aria-labelledby="linux-generator-title" className="max-h-[92vh] w-full max-w-6xl overflow-y-auto rounded-xl border border-base-700 bg-base-900 shadow-2xl">
            <div className="sticky top-0 z-10 flex items-center justify-between border-b border-base-700 bg-base-900/95 px-4 py-3"><div className="flex items-center gap-2 text-sm font-semibold text-ink-100"><FileCode2 size={16} className="text-signal-blue"/><h2 id="linux-generator-title">Linux Configuration Generator</h2></div><button type="button" onClick={() => setLinuxGeneratorOpen(false)} aria-label="Close Linux generator" className="rounded-md border border-base-700 p-2 text-ink-400 hover:text-ink-100"><X size={15}/></button></div>
            <div className="p-2 sm:p-3"><LinuxConfigGenerator/></div>
          </section>
        </div>
      )}
      {generatorOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/75 p-3 backdrop-blur-sm sm:p-6" onMouseDown={(event) => { if (event.target === event.currentTarget) setGeneratorOpen(false); }}>
          <section role="dialog" aria-modal="true" aria-labelledby="mikrotik-generator-title" className="max-h-[92vh] w-full max-w-6xl overflow-y-auto rounded-xl border border-base-700 bg-base-900 shadow-2xl">
            <div className="sticky top-0 z-10 flex items-center justify-between border-b border-base-700 bg-base-900/95 px-4 py-3 backdrop-blur sm:px-5">
              <div className="flex items-center gap-2 text-sm font-semibold text-ink-100"><FileCode2 size={16} className="text-signal-blue" /><h2 id="mikrotik-generator-title">MikroTik Configuration Generator</h2></div>
              <button type="button" onClick={() => setGeneratorOpen(false)} aria-label="Close configuration generator" className="rounded-md border border-base-700 p-2 text-ink-400 transition hover:bg-white/[0.05] hover:text-ink-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-signal-blue/50"><X size={15} /></button>
            </div>
            <div className="p-2 sm:p-3"><MikrotikConfigGenerator /></div>
          </section>
        </div>
      )}
    </div>
  );
}
