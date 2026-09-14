"use client";

import { useState } from "react";
import { HudLoader } from "@/components/HudLoader";
import { PermissionBadge } from "@/components/StatusBadge";
import { novaApi, NovaApiError } from "@/lib/api";
import type { KnownToolSpec, ToolResult } from "@/lib/types";

export function ToolRunModal({
  tool,
  onClose,
}: {
  tool: KnownToolSpec;
  onClose: () => void;
}) {
  const [values, setValues] = useState<Record<string, string>>(() => {
    const initial: Record<string, string> = {};
    for (const field of tool.fields) {
      if (field.default !== undefined) initial[field.name] = String(field.default);
    }
    return initial;
  });
  const [confirmed, setConfirmed] = useState(false);
  const [running, setRunning] = useState(false);
  const [result, setResult] = useState<ToolResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  const needsConfirmation = tool.permission_level !== "read";

  async function handleRun() {
    setRunning(true);
    setError(null);
    setResult(null);

    const args: Record<string, unknown> = {};
    for (const field of tool.fields) {
      const raw = values[field.name];
      if (raw === undefined || raw === "") continue;
      args[field.name] = field.type === "number" ? Number(raw) : raw;
    }

    try {
      const res = await novaApi.executeTool(tool.name, args, confirmed);
      setResult(res);
    } catch (err) {
      setError(err instanceof NovaApiError ? err.message : "Tool execution gagal.");
    } finally {
      setRunning(false);
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 px-4">
      <div className="panel w-full max-w-md">
        <div className="panel-header">
          <div className="flex items-center gap-2">
            <span className="font-mono text-sm text-ink-100">{tool.name}</span>
            <PermissionBadge level={tool.permission_level} />
          </div>
          <button onClick={onClose} className="text-ink-500 hover:text-ink-100">
            ✕
          </button>
        </div>

        <div className="max-h-[70vh] overflow-y-auto p-4">
          {tool.fields.length === 0 && (
            <p className="text-[13px] text-ink-500">Tool ini tidak membutuhkan argumen.</p>
          )}

          {tool.fields.map((field) => (
            <div key={field.name} className="mb-3">
              <label className="field-label">
                {field.label}
                {field.required && <span className="text-signal-rose"> *</span>}
              </label>
              <input
                type={field.type}
                required={field.required}
                min={field.min}
                max={field.max}
                placeholder={field.placeholder}
                value={values[field.name] ?? ""}
                onChange={(e) => setValues((v) => ({ ...v, [field.name]: e.target.value }))}
                className="field-input"
              />
              {field.helpText && <p className="mt-1 text-[11px] text-ink-500">{field.helpText}</p>}
            </div>
          ))}

          {needsConfirmation && (
            <label className="mb-3 flex items-start gap-2 rounded-sm border border-signal-amber/30 bg-signal-amber/10 p-3 text-[13px] text-signal-amber">
              <input
                type="checkbox"
                checked={confirmed}
                onChange={(e) => setConfirmed(e.target.checked)}
                className="mt-0.5"
              />
              Saya mengerti tool ini bersifat {tool.permission_level.toUpperCase()} dan
              menyetujui eksekusinya.
            </label>
          )}

          {running && !result && !error && (
            <div className="flex justify-center py-6">
              <HudLoader size={48} label={tool.name.toUpperCase()} />
            </div>
          )}

          {error && (
            <p className="mb-3 rounded-sm border border-signal-rose/30 bg-signal-rose/10 px-3 py-2 text-[13px] text-signal-rose">
              {error}
            </p>
          )}

          {result && (
            <div className="mt-2">
              <div className="mb-1.5 flex items-center justify-between">
                <span
                  className={`text-[13px] font-medium ${
                    result.success ? "text-signal-green" : "text-signal-rose"
                  }`}
                >
                  {result.success ? "success" : "failed"}
                </span>
                <span className="font-mono text-[11px] text-ink-500">
                  {result.duration_ms.toFixed(1)} ms
                </span>
              </div>
              <pre className="max-h-56 overflow-auto rounded-sm border border-base-600 bg-base-900 p-3 font-mono text-[12px] text-ink-300">
                {JSON.stringify(result.output ?? { error: result.error }, null, 2)}
              </pre>
            </div>
          )}
        </div>

        <div className="flex justify-end gap-2 border-t border-base-700 p-3">
          <button onClick={onClose} className="btn-secondary">
            Tutup
          </button>
          <button
            onClick={handleRun}
            disabled={running || (needsConfirmation && !confirmed)}
            className="btn-primary"
          >
            {running ? "Menjalankan…" : "Jalankan"}
          </button>
        </div>
      </div>
    </div>
  );
}
