"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { HudLoader } from "@/components/HudLoader";
import { Sidebar } from "@/components/Sidebar";
import { SystemPulse } from "@/components/SystemPulse";
import { isAuthenticated } from "@/lib/auth";

export default function ConsoleLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const router = useRouter();
  const [checked, setChecked] = useState(false);

  useEffect(() => {
    if (!isAuthenticated()) {
      router.replace("/login");
    } else {
      setChecked(true);
    }
  }, [router]);

  if (!checked) {
    return (
      <div className="flex h-screen items-center justify-center">
        <HudLoader label="VERIFYING SESSION" />
      </div>
    );
  }

  return (
    <div className="relative flex h-screen">
      {/* Ambient glow — sekarang di root shell, bukan di dalam halaman
          chat saja. Lihat globals.css .ambient-glow untuk rasional. */}
      <div className="ambient-glow" aria-hidden="true" />

      <Sidebar />
      <div className="flex flex-1 flex-col overflow-hidden">
        <header className="chrome-glass flex items-center justify-between border-b px-6 py-3">
          <SystemPulse />
        </header>
        <main className="flex-1 overflow-y-auto p-6">{children}</main>
      </div>
    </div>
  );
}
