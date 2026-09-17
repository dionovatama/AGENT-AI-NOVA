"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { clearToken } from "@/lib/auth";
import { novaApi } from "@/lib/api";
import { NovaOrb } from "@/components/NovaOrb";

const NAV_ITEMS = [
  { href: "/chat", label: "Chat", live: true },
  { href: "/tools", label: "Tools", live: true },
  { href: "/devices", label: "Devices", live: false },
  { href: "/audit", label: "Audit Log", live: false },
  { href: "/settings", label: "Settings", live: false },
];

export function Sidebar() {
  const pathname = usePathname();
  const router = useRouter();
  const [email, setEmail] = useState<string | null>(null);

  useEffect(() => {
    // Identitas asli lewat GET /auth/me -- kalau gagal (token expired,
    // dll), profile row cukup disembunyikan, TIDAK diisi placeholder palsu.
    novaApi
      .me()
      .then((res) => setEmail(res.email))
      .catch(() => setEmail(null));
  }, []);

  function handleNewChat() {
    // Reset percakapan beneran: chat_page.tsx membaca query param ini
    // lewat useSearchParams() dan mengosongkan state messages saat
    // nilainya berubah -- bukan tombol dekoratif yang diam saja kalau
    // sudah berada di /chat.
    router.push(`/chat?new=${Date.now()}`);
  }

  return (
    <aside className="chrome-glass flex h-screen w-60 shrink-0 flex-col border-r">
      <div className="flex items-center gap-2.5 px-4 py-5">
        <NovaOrb size={30} />
        <div>
          <p className="font-mono text-xs tracking-[0.3em] text-signal-teal">N·O·V·A</p>
          <p className="mt-0.5 text-[11px] text-ink-500">operator console</p>
        </div>
      </div>

      <div className="px-3">
        <button
          onClick={handleNewChat}
          className="flex w-full items-center gap-2 rounded-sm border border-base-600 px-3 py-2 text-[13px] text-ink-100 transition-colors hover:border-signal-blue/50 hover:bg-base-800/60"
        >
          <span className="text-base leading-none">+</span>
          New chat
        </button>
      </div>

      <nav className="flex-1 px-2 pt-4">
        {NAV_ITEMS.map((item) => {
          const active = pathname?.startsWith(item.href);
          return (
            <Link
              key={item.href}
              href={item.href}
              className={`mb-0.5 flex items-center justify-between rounded-sm px-3 py-2 text-sm transition-colors ${
                active
                  ? "bg-base-800 text-ink-100"
                  : "text-ink-500 hover:bg-base-800/60 hover:text-ink-300"
              }`}
            >
              <span>{item.label}</span>
              {!item.live && (
                <span className="h-1.5 w-1.5 rounded-full bg-base-600" title="belum tersedia penuh" />
              )}
            </Link>
          );
        })}
      </nav>

      <div className="border-t border-base-700 p-3">
        {email && (
          <div className="mb-1.5 flex items-center gap-2.5 rounded-sm px-3 py-2">
            <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-signal-blue/20 text-[11px] font-medium text-signal-blue">
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
          className="w-full rounded-sm px-3 py-2 text-left text-[13px] text-ink-500 hover:bg-base-800/60 hover:text-signal-rose"
        >
          Keluar
        </button>
      </div>
    </aside>
  );
}
