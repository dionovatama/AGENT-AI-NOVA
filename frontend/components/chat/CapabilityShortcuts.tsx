"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { Boxes, Router, Globe, ArrowUpRight, ChevronRight, Share2 } from "lucide-react";
import { novaApi } from "@/lib/api";
import { KNOWN_TOOLS } from "@/lib/types";

/**
 * "Verified Automations" -- versi jujur dari card referensi desain.
 *
 * Referensi aslinya menampilkan angka REKAYASA: "12 Nodes Active
 * 99.98%", "4 Core Peers ESTABLISHED", "0 Threat Alerts GUARDED",
 * plus nama tool yang tidak ada di backend ("routeros.bgp",
 * "secops.isolate"). Itu bukan cuma "belum diimplementasi" -- itu
 * tampilan yang BERBOHONG soal state sistem ke operator yang beneran
 * pegang akses SSH ke server nyata. Bertentangan langsung sama Core
 * Principle NOVA ("tidak pernah mengklaim sukses tanpa verifikasi").
 *
 * Jadi di sini: jumlah tool per kategori diambil dari HASIL NYATA
 * GET /tools/list (novaApi.listTools()), disilangkan dengan
 * KNOWN_TOOLS (registry metadata frontend, lib/types.ts) untuk tahu
 * platform-nya. Sebelum fetch selesai -> "checking…", bukan angka
 * ngarang. Kalau fetch gagal -> pesan error jujur, bukan 0 diam-diam.
 */

type PlatformKey = "linux" | "network" | "general";

const GROUPS: {
  key: PlatformKey;
  title: string;
  description: string;
  Icon: typeof Boxes;
  colorClass: string;
  sampleTool: string;
}[] = [
  {
    key: "linux",
    title: "System Assistant",
    description: "Linux system diagnostics via SSH",
    Icon: Boxes,
    colorClass: "text-signal-teal bg-signal-teal/10 border-signal-teal/20",
    sampleTool: "linux.system_info",
  },
  {
    key: "network",
    title: "Network Operations",
    description: "Reachability & connectivity checks",
    Icon: Router,
    colorClass: "text-orb-core bg-orb-core/10 border-orb-core/20",
    sampleTool: "ping",
  },
  {
    key: "general",
    title: "General & Web",
    description: "Web search and page reading",
    Icon: Globe,
    colorClass: "text-signal-amber bg-signal-amber/10 border-signal-amber/20",
    sampleTool: "web.search",
  },
];

export function CapabilityShortcuts() {
  const [liveTools, setLiveTools] = useState<string[] | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    novaApi
      .listTools()
      .then(setLiveTools)
      .catch(() => setFailed(true));
  }, []);

  function countFor(platform: PlatformKey): number | null {
    if (!liveTools) return null;
    return liveTools.filter((name) => KNOWN_TOOLS[name]?.platform === platform).length;
  }

  return (
    <div className="w-full">
      <div className="mb-3 flex items-center justify-between px-1">
        <div className="flex items-center gap-2">
          <Share2 size={16} className="text-orb-core" />
          <span className="text-[13px] font-medium text-ink-100">Verified Automations</span>
        </div>
        <Link
          href="/tools"
          className="flex items-center gap-0.5 font-mono text-[11px] text-ink-500 transition-colors hover:text-orb-core"
        >
          <span>VIEW_ALL_TOOLS</span>
          <ChevronRight size={13} />
        </Link>
      </div>

      <div className="grid grid-cols-1 gap-3 md:grid-cols-3">
        {GROUPS.map((group) => {
          const count = countFor(group.key);
          return (
            <div key={group.key} className="glass-card flex flex-col justify-between p-3.5 shadow-md">
              <div>
                <div className="mb-2 flex items-center justify-between">
                  <div className={`flex h-7 w-7 items-center justify-center rounded-lg border ${group.colorClass}`}>
                    <group.Icon size={14} />
                  </div>
                  <Link
                    href="/tools"
                    className="flex items-center gap-1 rounded-full bg-white/[0.04] px-2 py-0.5 text-[11px] text-ink-500 transition-colors hover:bg-white/[0.08] hover:text-ink-100"
                  >
                    <span>Open</span>
                    <ArrowUpRight size={11} />
                  </Link>
                </div>
                <h3 className="text-[13px] font-semibold text-ink-100">{group.title}</h3>
                <p className="mt-0.5 text-[11px] text-ink-500">{group.description}</p>
                <p className={`mt-1 truncate font-mono text-[10px] ${group.colorClass.split(" ")[0]}/80`}>
                  {group.sampleTool}
                </p>
              </div>

              <div className="mt-3 flex items-center justify-between border-t border-white/[0.04] pt-2 text-ink-500">
                <div className="flex items-center gap-1.5">
                  <span
                    className={`h-1.5 w-1.5 rounded-full ${
                      failed ? "bg-signal-rose" : count === null ? "bg-base-600" : "bg-signal-green"
                    }`}
                  />
                  <span className="font-mono text-[11px] text-ink-300">
                    {failed ? "verifikasi gagal" : count === null ? "checking…" : `${count} tool live`}
                  </span>
                </div>
                {!failed && count !== null && (
                  <span className="font-mono text-[11px] text-signal-green">verified</span>
                )}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
