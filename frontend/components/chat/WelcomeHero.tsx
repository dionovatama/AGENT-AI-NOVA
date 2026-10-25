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
    <div className="relative flex flex-col items-center pt-6 text-center [@media(max-height:719px)]:pt-0">
      <div className="hero-glow" aria-hidden="true" />

      {/* Orb 96px (inti) seperti referensi => HudRing 144 (inti = 2/3 dari size).
          Tinggi layar < 720px: dikecilkan lewat transform (margin negatif
          mengembalikan ruang yang dilepas). Tiga rentang sengaja TIDAK saling
          tumpang tindih supaya urutan CSS tidak menentukan hasil:
          680-719px = 70%, 620-679px = 55% (+ jarak judul/tombol dirapatkan di
          bawah), < 620px = disembunyikan agar composer + kartu tidak terpotong.
          Layar laptop 1920x1080 berskala 150% = tinggi tampilan ~640px. */}
      <div className="[@media(min-height:680px)_and_(max-height:719px)]:-my-5 [@media(min-height:680px)_and_(max-height:719px)]:scale-[0.7] [@media(min-height:620px)_and_(max-height:679px)]:-my-8 [@media(min-height:620px)_and_(max-height:679px)]:scale-[0.55] [@media(max-height:619px)]:hidden">
        <HudRing size={144} />
      </div>

      <h1 className="mt-4 text-[30px] [@media(max-height:679px)]:mt-2 font-medium leading-[41px] tracking-tight text-ink-100">
        Ready to operate?
      </h1>
      <p className="mt-1 max-w-md text-sm text-ink-500">
        NOVA — Nexus Operation Virtual Assistant
      </p>

      <div className="mt-5 flex max-w-2xl flex-wrap items-center justify-center gap-2 [@media(max-height:679px)]:mt-3">
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