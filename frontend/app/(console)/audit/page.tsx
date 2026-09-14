import { PlaceholderPanel } from "@/components/PlaceholderPanel";

export default function AuditPage() {
  return (
    <div className="mx-auto max-w-4xl">
      <header className="mb-6">
        <h1 className="text-base font-medium text-ink-100">Audit Log</h1>
        <p className="mt-1 text-[13px] text-ink-500">
          <code className="font-mono text-ink-300">app/security/audit.py</code> saat ini
          menulis ke Python logger biasa, belum ke tabel{" "}
          <code className="font-mono text-ink-300">audit_logs</code> di PostgreSQL, dan
          belum ada endpoint untuk membacanya balik. Halaman ini menampilkan bentuk
          yang dituju, bukan data nyata.
        </p>
      </header>

      <PlaceholderPanel
        title="Queryable Audit Trail"
        milestone="Fase integrasi DB"
        description="User → Request → Intent → Tool Request → Authorization → Permission → Execution → Result → Verification → Response, per PRD §32. Perlu tabel audit_logs + GET /audit/executions."
        prdReference="PRD §32 Audit Logging, §33 Database"
      />
    </div>
  );
}
