"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { clearToken } from "@/lib/auth";

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

  return (
    <aside className="flex h-screen w-56 shrink-0 flex-col border-r border-base-700 bg-base-950">
      <div className="flex items-center gap-2.5 px-4 py-5">
        <img src="/brand/nova-icon.png" alt="" className="h-7 w-7 rounded-sm" />
        <div>
          <p className="font-mono text-xs tracking-[0.3em] text-signal-teal">N·O·V·A</p>
          <p className="mt-0.5 text-[11px] text-ink-500">operator console</p>
        </div>
      </div>

      <nav className="flex-1 px-2">
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
