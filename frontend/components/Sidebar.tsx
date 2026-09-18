"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import {
  Plus,
  MessageSquare,
  Wrench,
  Server,
  ScrollText,
  Settings as SettingsIcon,
  LogOut,
} from "lucide-react";
import { clearToken } from "@/lib/auth";
import { novaApi } from "@/lib/api";
import { NovaOrb } from "@/components/NovaOrb";

// Nav item nyata -- setiap href beneran punya route. TIDAK ada item
// dekoratif seperti "Archived"/"Library" dari referensi desain, karena
// itu bukan konsep yang ada di backend NOVA sekarang. Kalau nanti
// beneran dibangun, baru ditambah di sini -- bukan sebaliknya.
const NAV_ITEMS = [
  { href: "/chat", label: "Chat", icon: MessageSquare, live: true },
  { href: "/tools", label: "Tools", icon: Wrench, live: true },
  { href: "/devices", label: "Devices", icon: Server, live: true },
  { href: "/audit", label: "Audit Log", icon: ScrollText, live: true },
  { href: "/settings", label: "Settings", icon: SettingsIcon, live: false },
];

export function Sidebar() {
  const pathname = usePathname();
  const router = useRouter();
  const [email, setEmail] = useState<string | null>(null);

  useEffect(() => {
    // Identitas asli lewat GET /auth/me -- kalau gagal (token expired,
    // dll), profile row cukup disembunyikan, TIDAK diisi placeholder palsu
    // (referensi desain pakai avatar+username fiktif "secops_lead" --
    // kita tidak meniru itu, selalu data user yang beneran login).
    novaApi
      .me()
      .then((res) => setEmail(res.email))
      .catch(() => setEmail(null));
  }, []);

  function handleNewChat() {
    router.push(`/chat?new=${Date.now()}`);
  }

  return (
    <aside className="chrome-glass flex h-screen w-60 shrink-0 flex-col border-r">
      {/* Brand — gradient ring dari DESIGN.md (violet -> teal), ukuran
          kecil supaya identitas tetap jelas walau ring-nya detail. */}
      <div className="flex items-center gap-2.5 px-4 py-5">
        <NovaOrb size={28} />
        <div>
          <p className="font-mono text-xs tracking-[0.3em] text-ink-100">N·O·V·A</p>
          <p className="mt-0.5 text-[10px] uppercase tracking-widest text-ink-500">
            operator console
          </p>
        </div>
      </div>

      {/* New Chat — pill capsule sesuai DESIGN.md #Shapes (action
          pills = rounded-full), fungsinya sama seperti sebelumnya. */}
      <div className="px-3">
        <button
          onClick={handleNewChat}
          className="group flex w-full items-center justify-center gap-2 rounded-full border border-white/[0.06]
            bg-white/[0.04] py-2 px-3 text-[13px] font-medium text-ink-100 shadow-[0_2px_12px_rgba(0,0,0,0.3)]
            transition-all duration-200 hover:border-border-glow/40 hover:bg-white/[0.08]
            hover:shadow-[0_0_16px_rgba(168,85,247,0.2)]"
        >
          <Plus size={16} className="text-orb-core transition-transform duration-300 group-hover:rotate-90" />
          New chat
        </button>
      </div>

      <nav className="flex-1 px-2 pt-4">
        <p className="px-2.5 pb-1.5 font-mono text-[10px] uppercase tracking-wider text-ink-500">
          Features
        </p>
        {NAV_ITEMS.map((item) => {
          const active = pathname?.startsWith(item.href);
          const Icon = item.icon;
          return (
            <Link
              key={item.href}
              href={item.href}
              className={`relative mb-0.5 flex items-center gap-2.5 rounded-lg px-2.5 py-1.5 text-[13px] transition-all ${
                active
                  ? "border border-border-glow/25 bg-border-glow/[0.15] font-medium text-ink-100 shadow-[inset_0_0_12px_rgba(168,85,247,0.12)]"
                  : "text-ink-500 hover:bg-white/[0.04] hover:text-ink-300"
              }`}
            >
              {active && (
                <span className="h-1.5 w-1.5 shrink-0 rounded-full bg-orb-core shadow-[0_0_8px_rgba(192,132,252,0.9)]" />
              )}
              <Icon size={16} className={active ? "text-orb-core" : "text-ink-500"} />
              <span className="flex-1">{item.label}</span>
              {!item.live && (
                <span
                  className="h-1.5 w-1.5 rounded-full bg-base-600"
                  title="belum tersedia penuh"
                />
              )}
            </Link>
          );
        })}
      </nav>

      <div className="border-t border-white/[0.06] bg-black/20 p-3">
        {email && (
          <div className="mb-1.5 flex items-center gap-2.5 rounded-xl border border-white/[0.05] bg-white/[0.03] px-2.5 py-2">
            <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-gradient-to-tr from-orb-glow to-orb-core text-[12px] font-bold text-white">
              {email.slice(0, 2).toUpperCase()}
            </div>
            <p className="truncate text-[12px] text-ink-300">{email}</p>
          </div>
        )}
        <button
          onClick={() => {
            clearToken();
            router.push("/login");
          }}
          className="flex w-full items-center gap-2 rounded-sm px-3 py-2 text-left text-[13px] text-ink-500 transition-colors hover:bg-white/[0.04] hover:text-signal-rose"
        >
          <LogOut size={14} />
          Keluar
        </button>
      </div>
    </aside>
  );
}
