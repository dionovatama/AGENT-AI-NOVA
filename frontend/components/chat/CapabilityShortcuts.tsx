"use client";

import Link from "next/link";
import type { TaskCategory } from "@/lib/types";

interface Shortcut {
  key: string;
  label: string;
  platformTag: string; // sama posisi/style seperti tag "network"/"linux" di ToolCard
  description: string;
  // Kalau ada, klik = isi composer + ganti kategori (tetap di halaman chat).
  fill?: { category: TaskCategory; prompt: string };
  // Kalau ada, klik = navigasi (dipakai untuk shortcut yang butuh
  // Permission/Confirmation UI nyata, bukan sekadar reasoning).
  href?: string;
}

const SHORTCUTS: Shortcut[] = [
  {
    key: "diagnostics",
    label: "System Diagnostics",
    platformTag: "linux",
    description: "Cek status service, resource, dan proses di server lab.",
    fill: {
      category: "troubleshooting",
      prompt: "Cek kenapa service ssh di server lab sering restart sendiri.",
    },
  },
  {
    key: "network-ops",
    label: "Network Ops",
    platformTag: "network",
    description: "Diagnosis konektivitas — ping, DNS, routing.",
    fill: {
      category: "network_diagnostic",
      prompt: "Ping 192.168.1.10 dan cek apakah gateway-nya reachable.",
    },
  },
  {
    key: "tool-execution",
    label: "Tool Execution",
    platformTag: "general",
    description: "Jalankan tool nyata lewat Permission & Confirmation flow.",
    href: "/tools",
  },
];

export function CapabilityShortcuts({
  onFill,
}: {
  onFill: (category: TaskCategory, prompt: string) => void;
}) {
  return (
    <div className="grid w-full max-w-2xl grid-cols-1 gap-2.5 sm:grid-cols-3">
      {SHORTCUTS.map((s) => {
        const body = (
          <>
            <div className="flex items-start justify-between gap-2">
              <h3 className="font-mono text-[13px] text-ink-100">{s.label}</h3>
              <span className="rounded-sm border border-base-600 px-1.5 py-0.5 text-[11px] text-ink-500">
                {s.platformTag}
              </span>
            </div>
            <p className="mt-1 text-[13px] text-ink-500">{s.description}</p>
          </>
        );

        const className =
          "panel flex flex-col justify-between p-4 text-left transition-colors hover:border-signal-teal/50";

        if (s.href) {
          return (
            <Link key={s.key} href={s.href} className={className}>
              {body}
              <span className="mt-3 font-mono text-[11px] text-signal-teal">buka halaman tools →</span>
            </Link>
          );
        }

        return (
          <button
            key={s.key}
            type="button"
            onClick={() => onFill(s.fill!.category, s.fill!.prompt)}
            className={className}
          >
            {body}
            <span className="mt-3 font-mono text-[11px] text-ink-500">isi contoh perintah</span>
          </button>
        );
      })}
    </div>
  );
}
