"use client";

import { useEffect, useState } from "react";
import { HudLoader } from "@/components/HudLoader";
import { PermissionBadge, RiskBadge } from "@/components/StatusBadge";
import { novaApi, NovaApiError } from "@/lib/api";
import type { AuditLogEntry, PermissionLevel, RiskLevel } from "@/lib/types";

const KNOWN_PERMISSIONS: PermissionLevel[] = ["read", "modify", "high_risk"];
const KNOWN_RISKS: RiskLevel[] = ["low", "medium", "high"];

const STATUS_STYLE: Record<string, string> = {
  success: "text-signal-green border-signal-green/30 bg-signal-green/10",
  denied: "text-signal-amber border-signal-amber/30 bg-signal-amber/10",
  failed: "text-signal-rose border-signal-rose/30 bg-signal-rose/10",
  timeout: "text-signal-rose border-signal-rose/30 bg-signal-rose/10",
};

export default function AuditPage() {
  const [logs, setLogs] = useState<AuditLogEntry[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);

  async function load() {
    try {
      const data = await novaApi.listAuditLogs();
      setLogs(data);
      setError(null);
    } catch (err) {
      setError(err instanceof NovaApiError ? err.message : "Gagal memuat audit log.");
    } finally {
      setRefreshing(false);
    }
  }

  useEffect(() => {
    load();
  }, []);

  return (
    <div className="mx-auto max-w-5xl">
      <header className="mb-6 flex items-start justify-between">
        <div>
          <h1 className="text-base font-medium text-ink-100">Audit Log</h1>
          <p className="mt-1 text-[13px] text-ink-500">
            Data asli dari <code className="font-mono text-ink-300">GET /audit-logs</code> —
            setiap eksekusi tool sekarang tersimpan permanen ke tabel{" "}
            <code className="font-mono text-ink-300">audit_logs</code>, tenant-isolated
            per user, sesuai PRD §32.
          </p>
        </div>
        <button
          className="btn-secondary shrink-0 !px-2.5 !py-1.5 text-[12px]"
          onClick={() => {
            setRefreshing(true);
            load();
          }}
        >
          {refreshing ? "…" : "Refresh"}
        </button>
      </header>

      {error && (
        <p className="mb-4 rounded-sm border border-signal-rose/30 bg-signal-rose/10 px-3 py-2 text-[13px] text-signal-rose">
          {error}
        </p>
      )}

      <div className="panel overflow-hidden">
        {logs === null && !error && (
          <div className="flex justify-center py-10">
            <HudLoader size={48} label="LOADING AUDIT LOG" />
          </div>
        )}

        {logs !== null && (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-[13px]">
              <thead>
                <tr className="text-ink-500">
                  <th className="px-4 py-2 font-normal">Waktu</th>
                  <th className="px-4 py-2 font-normal">Action</th>
                  <th className="px-4 py-2 font-normal">Tool</th>
                  <th className="px-4 py-2 font-normal">Permission</th>
                  <th className="px-4 py-2 font-normal">Risk</th>
                  <th className="px-4 py-2 font-normal">Status</th>
                  <th className="px-4 py-2 font-normal">Durasi</th>
                  <th className="px-4 py-2 font-normal">Error</th>
                </tr>
              </thead>
              <tbody>
                {logs.length === 0 && (
                  <tr>
                    <td colSpan={8} className="px-4 py-6 text-center text-ink-500">
                      Belum ada aktivitas tercatat. Jalankan sebuah tool di halaman Tools,
                      lalu refresh di sini.
                    </td>
                  </tr>
                )}
                {logs.map((log) => (
                  <tr key={log.id} className="border-t border-base-700 align-top">
                    <td className="whitespace-nowrap px-4 py-2 font-mono text-ink-500">
                      {new Date(log.created_at).toLocaleString("id-ID")}
                    </td>
                    <td className="px-4 py-2">{log.action}</td>
                    <td className="px-4 py-2 font-mono">{log.tool_name ?? "—"}</td>
                    <td className="px-4 py-2">
                      {log.permission && KNOWN_PERMISSIONS.includes(log.permission as PermissionLevel) ? (
                        <PermissionBadge level={log.permission as PermissionLevel} />
                      ) : (
                        <span className="text-ink-500">—</span>
                      )}
                    </td>
                    <td className="px-4 py-2">
                      {log.risk_level && KNOWN_RISKS.includes(log.risk_level as RiskLevel) ? (
                        <RiskBadge level={log.risk_level as RiskLevel} />
                      ) : (
                        <span className="text-ink-500">—</span>
                      )}
                    </td>
                    <td className="px-4 py-2">
                      <span
                        className={`rounded-sm border px-1.5 py-0.5 font-mono text-[11px] ${
                          STATUS_STYLE[log.result_status] ?? "text-ink-500 border-base-600"
                        }`}
                      >
                        {log.result_status}
                      </span>
                    </td>
                    <td className="px-4 py-2 font-mono text-ink-500">
                      {log.duration_ms != null ? `${log.duration_ms.toFixed(1)}ms` : "—"}
                    </td>
                    <td className="max-w-[220px] truncate px-4 py-2 font-mono text-[11px] text-signal-rose">
                      {log.error_message ?? ""}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}
