"use client";

import { useEffect, useState } from "react";
import { novaApi } from "@/lib/api";

type Status = "checking" | "online" | "offline";

export function SystemPulse() {
  const [status, setStatus] = useState<Status>("checking");
  const [env, setEnv] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;

    async function check() {
      try {
        const res = await novaApi.health();
        if (!cancelled) {
          setStatus("online");
          setEnv(res.environment);
        }
      } catch {
        if (!cancelled) setStatus("offline");
      }
    }

    check();
    const interval = setInterval(check, 15000);
    return () => {
      cancelled = true;
      clearInterval(interval);
    };
  }, []);

  const dotColor =
    status === "online"
      ? "bg-signal-green"
      : status === "offline"
      ? "bg-signal-rose"
      : "bg-ink-500";

  const label =
    status === "online"
      ? `backend online${env ? ` · ${env}` : ""}`
      : status === "offline"
      ? "backend tidak terjangkau"
      : "menghubungi backend…";

  return (
    <div className="flex items-center gap-2 font-mono text-[11px] text-ink-500">
      <span className="relative flex h-2 w-2">
        {status === "online" && (
          <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-signal-green opacity-60" />
        )}
        <span className={`relative inline-flex h-2 w-2 rounded-full ${dotColor}`} />
      </span>
      {label}
    </div>
  );
}
