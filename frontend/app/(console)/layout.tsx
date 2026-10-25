"use client";

import { useCallback, useEffect, useState } from "react";
import { usePathname, useRouter } from "next/navigation";
import { PanelLeftOpen } from "lucide-react";
import { HudLoader } from "@/components/HudLoader";
import { Sidebar } from "@/components/Sidebar";
import { isAuthenticated } from "@/lib/auth";

const SIDEBAR_STORAGE_KEY = "nova_sidebar_open";
const MOBILE_QUERY = "(max-width: 767px)";

function isMobileViewport() {
  return window.matchMedia(MOBILE_QUERY).matches;
}

export default function ConsoleLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const router = useRouter();
  const pathname = usePathname();
  const [checked, setChecked] = useState(false);
  const [sidebarOpen, setSidebarOpen] = useState(true);

  useEffect(() => {
    if (!isAuthenticated()) {
      router.replace("/login");
      return;
    }
    // Preferensi sidebar dibaca di sini (bukan di initial state) supaya
    // tidak terjadi hydration mismatch -- layout ini baru merender isinya
    // setelah `checked` true. Di layar kecil sidebar selalu mulai tertutup
    // karena tampil sebagai overlay, bukan mendorong konten.
    let stored: string | null = null;
    try {
      stored = window.localStorage.getItem(SIDEBAR_STORAGE_KEY);
    } catch {
      /* storage tidak tersedia (mode privat) -- pakai default */
    }
    setSidebarOpen(isMobileViewport() ? false : stored !== "0");
    setChecked(true);
  }, [router]);

  // Di layar kecil, pindah halaman menutup overlay sidebar. Tidak
  // disimpan sebagai preferensi.
  useEffect(() => {
    if (checked && isMobileViewport()) setSidebarOpen(false);
  }, [pathname, checked]);

  const changeSidebar = useCallback((open: boolean) => {
    setSidebarOpen(open);
    try {
      window.localStorage.setItem(SIDEBAR_STORAGE_KEY, open ? "1" : "0");
    } catch {
      /* abaikan */
    }
  }, []);

  const closeSidebarOnMobile = useCallback(() => {
    if (isMobileViewport()) setSidebarOpen(false);
  }, []);

  if (!checked) {
    return (
      <div className="flex h-screen items-center justify-center">
        <HudLoader label="VERIFYING SESSION" />
      </div>
    );
  }

  // Halaman chat mengatur scroll-nya sendiri; halaman lain (Tools, Devices,
  // Audit, Settings) tidak, jadi area utamanya yang menggulir dan memberi
  // padding. Saat sidebar tersembunyi, tombol "buka" melayang di pojok kiri
  // atas -- ruang atas dicadangkan di layar < lg supaya tidak menimpa konten.
  const isChat = pathname?.startsWith("/chat") ?? false;
  const mainClass = isChat
    ? `min-h-0 flex-1 overflow-hidden ${sidebarOpen ? "" : "pt-12 lg:pt-0"}`
    : `nova-chat-scroll min-h-0 flex-1 overflow-y-auto p-6 ${sidebarOpen ? "" : "pt-14 lg:pt-6"}`;

  return (
    <div className="relative flex h-screen">
      {sidebarOpen && (
        <button
          type="button"
          aria-label="Close sidebar"
          onClick={() => changeSidebar(false)}
          className="fixed inset-0 z-30 bg-black/50 md:hidden"
        />
      )}

      <div
        aria-hidden={!sidebarOpen}
        className={`flex shrink-0 overflow-hidden transition-[width,visibility] duration-200 ease-out motion-reduce:transition-none max-md:fixed max-md:inset-y-0 max-md:left-0 max-md:z-40 ${
          sidebarOpen ? "visible w-[228px]" : "invisible w-0"
        }`}
      >
        <Sidebar onHide={() => changeSidebar(false)} onNavigate={closeSidebarOnMobile} />
      </div>

      <main className={mainClass}>{children}</main>

      {!sidebarOpen && (
        <button
          type="button"
          onClick={() => changeSidebar(true)}
          aria-label="Show sidebar"
          title="Show sidebar"
          className="absolute left-3 top-3 z-20 flex h-8 w-8 items-center justify-center rounded-lg border border-white/[0.08] bg-base-950/70 text-ink-300 backdrop-blur-md transition-colors hover:bg-white/[0.08] hover:text-ink-100"
        >
          <PanelLeftOpen size={16} />
        </button>
      )}
    </div>
  );
}
