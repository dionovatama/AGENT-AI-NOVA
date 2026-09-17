import { HudRing } from "@/components/chat/HudRing";
import type { TaskCategory } from "@/lib/types";

// Quick-action pills -- SEMUA prompt di sini dipetakan ke tool yang
// BENERAN terdaftar di backend (lihat lib/types.ts KNOWN_TOOLS), bukan
// disalin dari referensi desain apa adanya. Referensi aslinya punya
// "Inspect BGP Routers" dan "/run security.audit_ssh_keys" -- keduanya
// tidak ada tool-nya di backend (MikroTik belum diimplementasi, tidak
// ada tool audit_ssh_keys) jadi diganti ke sesuatu yang beneran bisa
// dieksekusi kalau usernya lanjut ke halaman Tools atau dijawab NOVA.
const QUICK_ACTIONS: {
  label: string;
  glyph: string;
  glyphClass: string;
  category: TaskCategory;
  prompt: string;
  useTools?: boolean;
}[] = [
  {
    label: "Check Linux Health",
    glyph: "✦",
    glyphClass: "text-signal-teal",
    category: "troubleshooting",
    prompt: "Cek kesehatan sistem: uptime, pemakaian memory, dan status service ssh di server lab.",
  },
  {
    label: "Ping a Host",
    glyph: "◇",
    glyphClass: "text-orb-core",
    category: "network_diagnostic",
    prompt: "Ping 192.168.1.10 dan cek apakah host itu reachable.",
  },
  {
    label: "Check Service Status",
    glyph: "⌘",
    glyphClass: "text-signal-amber",
    category: "troubleshooting",
    prompt: "Cek apakah service ssh sedang active dan enabled saat boot.",
  },
  {
    label: "Search the Web",
    glyph: "⚡",
    glyphClass: "text-signal-teal",
    category: "general_chat",
    prompt: "Cari berita teknologi terbaru hari ini dan ringkas.",
    useTools: true,
  },
];

export function WelcomeHero({
  onQuickAction,
}: {
  onQuickAction: (category: TaskCategory, prompt: string, useTools?: boolean) => void;
}) {
  return (
    <div className="relative flex h-full flex-col items-center justify-center text-center">
      <div className="hero-glow" aria-hidden="true" />

      <HudRing size={96} />

      <h1 className="mt-5 text-[30px] font-medium leading-snug tracking-tight text-ink-100 md:text-[34px]">
        Ready to operate?
      </h1>
      <p className="mt-1.5 max-w-md text-sm text-ink-500">
        NOVA — Nexus Operation Virtual Assistant
      </p>

      <div className="mt-5 flex max-w-2xl flex-wrap items-center justify-center gap-2">
        {QUICK_ACTIONS.map((action) => (
          <button
            key={action.label}
            type="button"
            onClick={() => onQuickAction(action.category, action.prompt, action.useTools)}
            className="pill"
          >
            <span className={`font-mono text-[13px] ${action.glyphClass}`}>{action.glyph}</span>
            {action.label}
          </button>
        ))}
      </div>
    </div>
  );
}
