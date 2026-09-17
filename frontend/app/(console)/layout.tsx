"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { SlidersHorizontal } from "lucide-react";
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
      <Sidebar />
      <div className="flex flex-1 flex-col overflow-hidden">
        <header className="chrome-glass flex items-center justify-between border-b px-6 py-3">
          <SystemPulse />
          {/* "Export" dari referensi desain sengaja tidak ditiru -- belum
              ada endpoint export audit log nyata di backend. Daripada
              tombol mati/pura-pura jalan, cuma tampilkan yang beneran
              mengarah ke sesuatu: /settings. */}
          <Link
            href="/settings"
            className="pill !bg-white/[0.03] hover:!bg-white/[0.07]"
          >
            <SlidersHorizontal size={14} />
            <span>Configuration</span>
          </Link>
        </header>
        <main className="flex-1 overflow-y-auto p-6">{children}</main>
      </div>
    </div>
  );
}
