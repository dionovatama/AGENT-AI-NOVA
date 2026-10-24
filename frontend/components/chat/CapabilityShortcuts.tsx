"use client";

/**
 * Kartu kemampuan NOVA -- versi jujur dari card referensi desain. Setiap kartu
 * menautkan ke /tools; ukurannya (288x112, padding 24, jarak 16) mengikuti
 * referensi layout chat. Header "Verified Automations" dan ikon dihapus agar
 * kartu sama dengan referensi; jumlah tool tetap dari GET /tools/list.
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

import { useEffect, useState } from "react";
import Link from "next/link";
import { novaApi } from "@/lib/api";
import { KNOWN_TOOLS } from "@/lib/types";

type PlatformKey = "linux" | "network" | "general";

// Deskripsi dibatasi ~2 baris (line-clamp-2) supaya tinggi kartu selalu
// sama. Isinya hanya kemampuan yang benar-benar dicakup `platform` pada
// KNOWN_TOOLS — "network" saat ini = ping saja, jadi tidak menyebut
// MikroTik/Cisco.
const GROUPS: {
  key: PlatformKey;
  title: string;
  description: string;
}[] = [
  {
    key: "linux",
    title: "System Assistant",
    description: "Read uptime, memory, disk, network, services and logs on Linux over SSH.",
  },
  {
    key: "network",
    title: "Network Operations",
    description: "Ping a host to check reachability, latency and packet loss.",
  },
  {
    key: "general",
    title: "General & Web",
    description: "Search the web and read page contents for up-to-date answers.",
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
    <div className="hidden w-full grid-cols-3 gap-4 md:grid">
      {GROUPS.map((group) => {
        const count = countFor(group.key);
        return (
          <Link
            key={group.key}
            href="/tools"
            className="glass-card block min-h-[112px] px-6 py-[23px]"
          >
            <div className="flex items-center justify-between gap-3">
              <h3 className="min-w-0 truncate text-base font-medium leading-6 text-ink-100">
                {group.title}
              </h3>
              <span className="flex shrink-0 items-center gap-1.5 font-mono text-[11px] text-ink-300">
                <span
                  className={`h-1.5 w-1.5 rounded-full ${
                    failed ? "bg-signal-rose" : count === null ? "bg-base-600" : "bg-signal-green"
                  }`}
                />
                {failed ? "verifikasi gagal" : count === null ? "checking…" : `${count} live`}
              </span>
            </div>
            <p className="mt-1 line-clamp-2 text-xs leading-[18px] text-ink-500">
              {group.description}
            </p>
          </Link>
        );
      })}
    </div>
  );
}