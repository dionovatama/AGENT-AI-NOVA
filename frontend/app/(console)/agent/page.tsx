"use client";

import { useCallback, useEffect, useMemo, useState, type FormEvent, type ReactNode } from "react";
import {
  Activity, AlertTriangle, Check, Copy, Laptop, Loader2,
  Plus, Radio, RefreshCw, RotateCw, Server, ShieldCheck, Terminal,
  Trash2, Wifi, WifiOff, X,
} from "lucide-react";
import { novaApi, type RemoteAgent, type RemoteAgentProvisioned } from "@/lib/api";
import type { Device, RelayTarget } from "@/lib/types";

const API_BASE = process.env.NEXT_PUBLIC_NOVA_API_BASE_URL ?? "http://localhost:8000";

function formatDate(value: string | null) {
  if (!value) return "Never";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "Unknown";
  return new Intl.DateTimeFormat(undefined, {
    dateStyle: "medium", timeStyle: "short",
  }).format(date);
}

function statusStyle(status: string) {
  switch (status) {
    case "online": return "border-emerald-400/20 bg-emerald-400/10 text-emerald-300";
    case "connecting": return "border-cyan-400/20 bg-cyan-400/10 text-cyan-300";
    case "error": return "border-rose-400/20 bg-rose-400/10 text-rose-300";
    default: return "border-amber-400/20 bg-amber-400/10 text-amber-300";
  }
}

function platformLabel(os: string | null) {
  if (!os) return "Not connected yet";
  const value = os.toLowerCase();
  if (value.includes("win")) return "Windows";
  if (value.includes("linux")) return "Linux";
  if (value.includes("darwin") || value.includes("mac")) return "macOS";
  return os;
}

function Modal({ title, onClose, children }: {
  title: string; onClose: () => void; children: ReactNode;
}) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4 backdrop-blur-sm" role="presentation" onMouseDown={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <section role="dialog" aria-modal="true" aria-label={title} className="w-full max-w-xl rounded-2xl border border-white/10 bg-[#10131b] p-5 shadow-2xl">
        <div className="mb-4 flex items-center justify-between gap-3">
          <h2 className="text-base font-semibold text-slate-100">{title}</h2>
          <button type="button" onClick={onClose} aria-label="Close" className="rounded-lg p-2 text-slate-500 hover:bg-white/5 hover:text-white"><X size={16} /></button>
        </div>
        {children}
      </section>
    </div>
  );
}

function CopyButton({ value, label = "Copy" }: { value: string; label?: string }) {
  const [copied, setCopied] = useState(false);
  async function copy() {
    try {
      await navigator.clipboard.writeText(value);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1600);
    } catch {
      setCopied(false);
    }
  }
  return (
    <button type="button" onClick={copy} className="inline-flex shrink-0 items-center gap-1.5 rounded-lg border border-white/10 px-2.5 py-2 text-xs text-slate-300 transition hover:bg-white/5">
      {copied ? <Check size={13} /> : <Copy size={13} />}{copied ? "Copied" : label}
    </button>
  );
}

function ProvisioningPanel({ agent, onClose }: { agent: RemoteAgentProvisioned; onClose: () => void }) {
  const [platform, setPlatform] = useState<"windows" | "linux">("windows");
  const base = API_BASE.replace(/\/+$/, "");
  const command = platform === "windows"
    ? `nova-agent init --server-url ${base} --agent-id ${agent.id}`
    : `read -rsp 'Agent token: ' NOVA_TOKEN; echo\nprintf '%s' "$NOVA_TOKEN" | nova-agent init --server-url ${base} --agent-id ${agent.id} --token-stdin\nunset NOVA_TOKEN`;
  return (
    <Modal title="Agent created — save this token" onClose={onClose}>
      <div className="space-y-4">
        <div className="flex items-start gap-3 rounded-xl border border-amber-400/20 bg-amber-400/[0.06] p-3">
          <ShieldCheck className="mt-0.5 shrink-0 text-amber-300" size={18} />
          <p className="text-xs leading-5 text-amber-100/80">This token is shown only once. Copy it now and keep it in a secure place. NOVA stores only its hash; it cannot be retrieved later.</p>
        </div>
        <div>
          <label className="mb-1.5 block text-[11px] uppercase tracking-wider text-slate-500">Agent ID</label>
          <div className="flex gap-2 rounded-lg border border-white/10 bg-black/30 p-2">
            <code className="min-w-0 flex-1 break-all text-xs text-cyan-200">{agent.id}</code>
            <CopyButton value={agent.id} />
          </div>
        </div>
        <div>
          <label className="mb-1.5 block text-[11px] uppercase tracking-wider text-slate-500">One-time agent token</label>
          <div className="flex gap-2 rounded-lg border border-white/10 bg-black/30 p-2">
            <code className="min-w-0 flex-1 break-all text-xs text-emerald-200">{agent.token}</code>
            <CopyButton value={agent.token} />
          </div>
        </div>
        <div>
          <div className="mb-2 flex items-center justify-between">
            <label className="text-[11px] uppercase tracking-wider text-slate-500">Installation instructions</label>
            <div className="flex rounded-lg border border-white/10 p-0.5">
              <button onClick={() => setPlatform("windows")} className={`rounded-md px-2.5 py-1 text-[11px] ${platform === "windows" ? "bg-cyan-400/15 text-cyan-200" : "text-slate-500"}`}>Windows</button>
              <button onClick={() => setPlatform("linux")} className={`rounded-md px-2.5 py-1 text-[11px] ${platform === "linux" ? "bg-cyan-400/15 text-cyan-200" : "text-slate-500"}`}>Linux</button>
            </div>
          </div>
          {platform === "windows" ? (
            <ol className="mb-3 list-decimal space-y-1 pl-5 text-xs leading-5 text-slate-400">
              <li>Install the NOVA Remote Agent package on the trusted Windows host.</li>
              <li>Run the command below in PowerShell. The token is requested through a hidden prompt.</li>
              <li>Run <code className="text-cyan-200">nova-agent install-service</code>, then <code className="text-cyan-200">nova-agent start</code>.</li>
            </ol>
          ) : (
            <ol className="mb-3 list-decimal space-y-1 pl-5 text-xs leading-5 text-slate-400">
              <li>Install the NOVA Remote Agent package in a Python 3.11+ virtual environment.</li>
              <li>Export the token in the current shell, then run the command below.</li>
              <li>Start the agent with <code className="text-cyan-200">nova-agent run</code>.</li>
            </ol>
          )}
          <div className="flex items-start gap-2 rounded-lg border border-white/10 bg-black/30 p-3">
            <code className="min-w-0 flex-1 whitespace-pre-wrap break-all text-[11px] leading-5 text-slate-300">{command}</code>
            <CopyButton value={command} />
          </div>
          {platform === "linux" && <p className="mt-2 text-[11px] text-slate-500">The command prompts for the token without echoing it, then clears the shell variable.</p>}
        </div>
        <div className="flex justify-end">
          <button onClick={onClose} className="rounded-lg bg-cyan-400 px-4 py-2 text-xs font-semibold text-slate-950 hover:bg-cyan-300">I saved the token</button>
        </div>
      </div>
    </Modal>
  );
}

function RelayTargetsPanel({ agentId }: { agentId: string }) {
  const [targets, setTargets] = useState<RelayTarget[]>([]);
  const [devices, setDevices] = useState<Device[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [name, setName] = useState("");
  const [host, setHost] = useState("");
  const [ports, setPorts] = useState("8729");
  const [deviceId, setDeviceId] = useState("");
  const [fingerprint, setFingerprint] = useState("");
  const [pinDrafts, setPinDrafts] = useState<Record<string, string>>({});
  const [busyTarget, setBusyTarget] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [targetRows, deviceRows] = await Promise.all([novaApi.listRelayTargets(agentId), novaApi.listDevices()]);
      setTargets(targetRows);
      setDevices(deviceRows);
      setError("");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to load relay targets.");
    } finally { setLoading(false); }
  }, [agentId]);

  useEffect(() => { void load(); }, [load]);

  async function createTarget(e: FormEvent) {
    e.preventDefault();
    const parsedPorts = ports.split(",").map((part) => Number(part.trim()));
    if (!name.trim() || !host.trim() || !parsedPorts.length || parsedPorts.some((port) => !Number.isInteger(port) || port < 1 || port > 65535)) {
      setError("Isi nama, host, dan port valid (1–65535; pisahkan port dengan koma)."); return;
    }
    setSaving(true); setError(""); setNotice("");
    try {
      await novaApi.createRelayTarget(agentId, {
        name: name.trim(), host: host.trim(), ports: Array.from(new Set(parsedPorts)),
        ...(deviceId ? { device_id: deviceId } : {}),
        ...(fingerprint.trim() ? { tls_fingerprint: fingerprint.trim() } : {}),
      });
      setName(""); setHost(""); setPorts("8729"); setDeviceId(""); setFingerprint("");
      setNotice("Relay target berhasil ditambahkan.");
      await load();
    } catch (err) { setError(err instanceof Error ? err.message : "Unable to create relay target."); }
    finally { setSaving(false); }
  }

  async function updatePin(target: RelayTarget) {
    const pin = (pinDrafts[target.id] || "").trim();
    if (!pin) { setError("Masukkan fingerprint SHA-256 baru (64 karakter hex)."); return; }
    setBusyTarget(target.id); setError(""); setNotice("");
    try {
      await novaApi.updateRelayTargetPin(agentId, target.id, pin);
      setPinDrafts((current) => ({ ...current, [target.id]: "" }));
      setNotice("Fingerprint pin berhasil diganti.");
      await load();
    } catch (err) { setError(err instanceof Error ? err.message : "Unable to update fingerprint."); }
    finally { setBusyTarget(null); }
  }

  async function clearPin(target: RelayTarget) {
    if (!window.confirm("Hapus TLS pin untuk target " + target.name + "?")) return;
    setBusyTarget(target.id); setError(""); setNotice("");
    try {
      await novaApi.updateRelayTargetPin(agentId, target.id, null);
      setNotice("TLS pin dihapus.");
      await load();
    } catch (err) { setError(err instanceof Error ? err.message : "Unable to clear fingerprint."); }
    finally { setBusyTarget(null); }
  }

  async function removeTarget(target: RelayTarget) {
    if (!window.confirm("Hapus relay target " + target.name + "?")) return;
    setBusyTarget(target.id); setError(""); setNotice("");
    try {
      await novaApi.deleteRelayTarget(agentId, target.id);
      setTargets((current) => current.filter((item) => item.id !== target.id));
      setNotice("Relay target dihapus.");
    } catch (err) { setError(err instanceof Error ? err.message : "Unable to delete relay target."); }
    finally { setBusyTarget(null); }
  }

  return (
    <section className="border-t border-white/[0.06] bg-black/10 px-4 py-4">
      <div className="mb-3 flex items-center justify-between gap-3">
        <div><h4 className="text-xs font-semibold text-slate-200">Relay targets</h4><p className="mt-1 text-[10px] text-slate-500">Allow-listed destinations reachable through this Agent.</p></div>
        <span className="rounded-md border border-cyan-400/15 bg-cyan-400/[0.06] px-2 py-1 text-[10px] text-cyan-200">{targets.length} targets</span>
      </div>
      {error && <p role="alert" className="mb-2 rounded-lg border border-rose-400/20 bg-rose-400/[0.06] p-2 text-[11px] text-rose-200">{error}</p>}
      {notice && <p role="status" className="mb-2 rounded-lg border border-emerald-400/20 bg-emerald-400/[0.06] p-2 text-[11px] text-emerald-200">{notice}</p>}
      {loading ? <p className="py-3 text-xs text-slate-500">Loading relay targets…</p> : targets.length === 0 ? (
        <p className="mb-3 rounded-lg border border-dashed border-white/10 px-3 py-4 text-center text-xs text-slate-500">Belum ada relay target untuk Agent ini.</p>
      ) : (
        <div className="mb-4 space-y-2">
          {targets.map((target) => (
            <div key={target.id} className="rounded-xl border border-white/[0.08] bg-white/[0.02] p-3">
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div className="min-w-0 flex-1">
                  <p className="text-xs font-semibold text-slate-200">{target.name}</p>
                  <p className="mt-1 break-all font-mono text-[11px] text-slate-400">{target.host} · {target.ports.join(", ")}</p>
                  <div className="mt-2 flex flex-wrap items-center gap-2">
                    <span className="text-[10px] uppercase tracking-wider text-slate-600">target_id</span>
                    <code className="break-all text-[10px] text-cyan-200">{target.id}</code>
                    <CopyButton value={target.id} label="Copy target_id" />
                  </div>
                  <div className="mt-2">
                    <p className="text-[10px] uppercase tracking-wider text-slate-600">TLS SHA-256 fingerprint</p>
                    <code className="mt-1 block break-all text-[10px] text-slate-300">{target.tls_fingerprint || "Not pinned"}</code>
                  </div>
                  {target.device_id && <p className="mt-1 text-[10px] text-slate-500">Linked device: {devices.find((device) => device.id === target.device_id)?.name || target.device_id}</p>}
                </div>
                <button disabled={busyTarget === target.id} onClick={() => void removeTarget(target)} className="rounded-lg border border-rose-400/20 px-2.5 py-1.5 text-[10px] text-rose-200 hover:bg-rose-400/10 disabled:opacity-50"><Trash2 size={12} className="mr-1 inline" />Delete</button>
              </div>
              <div className="mt-3 flex flex-wrap gap-2">
                <input value={pinDrafts[target.id] || ""} onChange={(e) => setPinDrafts((current) => ({ ...current, [target.id]: e.target.value }))} placeholder="New SHA-256 fingerprint (64 hex)" className="h-8 min-w-[220px] flex-1 rounded-lg border border-white/10 bg-black/30 px-2.5 font-mono text-[10px] text-slate-200 outline-none focus:border-cyan-400/40" />
                <button disabled={busyTarget === target.id} onClick={() => void updatePin(target)} className="rounded-lg border border-cyan-400/20 px-3 py-1.5 text-[10px] text-cyan-200 hover:bg-cyan-400/10 disabled:opacity-50">Replace PIN</button>
                {target.tls_fingerprint && <button disabled={busyTarget === target.id} onClick={() => void clearPin(target)} className="rounded-lg border border-amber-400/20 px-3 py-1.5 text-[10px] text-amber-200 hover:bg-amber-400/10 disabled:opacity-50">Clear PIN</button>}
              </div>
            </div>
          ))}
        </div>
      )}
      <form onSubmit={createTarget} className="grid gap-2 rounded-xl border border-white/[0.08] bg-white/[0.02] p-3 sm:grid-cols-2">
        <div className="sm:col-span-2"><p className="mb-2 text-[11px] font-semibold text-slate-300">Add relay target</p></div>
        <input value={name} onChange={(e) => setName(e.target.value)} maxLength={100} placeholder="Target name, e.g. Core Router" className="h-9 rounded-lg border border-white/10 bg-black/30 px-3 text-xs outline-none focus:border-cyan-400/40" required />
        <input value={host} onChange={(e) => setHost(e.target.value)} maxLength={255} placeholder="Router IP / hostname" className="h-9 rounded-lg border border-white/10 bg-black/30 px-3 text-xs outline-none focus:border-cyan-400/40" required />
        <input value={ports} onChange={(e) => setPorts(e.target.value)} placeholder="Ports, e.g. 8729, 22" className="h-9 rounded-lg border border-white/10 bg-black/30 px-3 font-mono text-xs outline-none focus:border-cyan-400/40" required />
        <select value={deviceId} onChange={(e) => setDeviceId(e.target.value)} className="h-9 rounded-lg border border-white/10 bg-[#11151e] px-3 text-xs text-slate-300">
          <option value="">No linked device (optional)</option>
          {devices.map((device) => <option key={device.id} value={device.id}>{device.name} · {device.host}</option>)}
        </select>
        <input value={fingerprint} onChange={(e) => setFingerprint(e.target.value)} placeholder="Optional TLS SHA-256 fingerprint" className="h-9 rounded-lg border border-white/10 bg-black/30 px-3 font-mono text-[10px] outline-none focus:border-cyan-400/40 sm:col-span-2" />
        <div className="flex items-center justify-between gap-3 sm:col-span-2">
          <p className="text-[10px] leading-4 text-slate-500">Fingerprint dapat berupa 64 hex atau format dipisah titik dua. Host divalidasi backend.</p>
          <button type="submit" disabled={saving || !name.trim() || !host.trim()} className="inline-flex shrink-0 items-center gap-1.5 rounded-lg bg-cyan-400 px-3 py-2 text-[10px] font-semibold text-slate-950 hover:bg-cyan-300 disabled:opacity-50">{saving ? <Loader2 size={12} className="animate-spin" /> : <Plus size={12} />} Add target</button>
        </div>
      </form>
    </section>
  );
}

export default function AgentPage() {
  const [agents, setAgents] = useState<RemoteAgent[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState("");
  const [newName, setNewName] = useState("");
  const [creating, setCreating] = useState(false);
  const [showAdd, setShowAdd] = useState(false);
  const [provisioned, setProvisioned] = useState<RemoteAgentProvisioned | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);

  const loadAgents = useCallback(async (quiet = false) => {
    if (!quiet) setLoading(true);
    else setRefreshing(true);
    try {
      const result = await novaApi.listAgents();
      setAgents(result);
      setError("");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to load Remote Agents.");
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, []);

  useEffect(() => {
    void loadAgents();
    const timer = window.setInterval(() => void loadAgents(true), 10000);
    return () => window.clearInterval(timer);
  }, [loadAgents]);

  const onlineCount = useMemo(() => agents.filter((agent) => agent.status === "online").length, [agents]);

  async function createAgent(e: FormEvent) {
    e.preventDefault();
    const name = newName.trim();
    if (!name) return;
    setCreating(true);
    setError("");
    try {
      const created = await novaApi.createAgent(name);
      const { token: _token, connect_path: _connectPath, ...safeAgent } = created;
      setAgents((current) => [...current, safeAgent]);
      setProvisioned(created);
      setShowAdd(false);
      setNewName("");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to create agent.");
    } finally {
      setCreating(false);
    }
  }

  async function rotateToken(agent: RemoteAgent) {
    if (!window.confirm(`Rotate token for "${agent.name}"? The current agent session will be disconnected and must be configured with the new token.`)) return;
    setBusyId(agent.id);
    try {
      const result = await novaApi.rotateAgentToken(agent.id);
      const { token: _token, connect_path: _connectPath, ...safeAgent } = result;
      setAgents((current) => current.map((item) => item.id === agent.id ? safeAgent : item));
      setProvisioned(result);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to rotate agent token.");
    } finally {
      setBusyId(null);
    }
  }

  async function disconnectAgent(agent: RemoteAgent) {
    if (!window.confirm(`Disconnect the current session for "${agent.name}"? The installed agent may reconnect automatically.`)) return;
    setBusyId(agent.id);
    try {
      await novaApi.disconnectAgent(agent.id);
      await loadAgents(true);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to disconnect agent.");
    } finally {
      setBusyId(null);
    }
  }

  async function deleteAgent(agent: RemoteAgent) {
    if (!window.confirm(`Delete "${agent.name}"? This revokes its identity and cannot be undone.`)) return;
    setBusyId(agent.id);
    try {
      await novaApi.deleteAgent(agent.id);
      setAgents((current) => current.filter((item) => item.id !== agent.id));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to delete agent.");
    } finally {
      setBusyId(null);
    }
  }

  return (
    <div className="mx-auto min-h-full w-full max-w-6xl space-y-7 pb-10 text-slate-100">
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div className="space-y-2">
          <div className="flex items-center gap-2 text-xs font-medium uppercase tracking-[0.18em] text-cyan-300">
            <Radio size={14} /> Remote connectivity
          </div>
          <h1 className="text-2xl font-semibold tracking-tight sm:text-3xl">Remote Agents</h1>
          <p className="max-w-2xl text-sm leading-6 text-slate-400">
            Provision and manage NOVA agents installed inside trusted networks. Agents initiate outbound WSS connections; router management ports do not need to be exposed to the internet.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <button onClick={() => void loadAgents(true)} disabled={refreshing} className="inline-flex h-10 items-center gap-2 rounded-lg border border-white/10 px-3 text-xs text-slate-300 hover:bg-white/5 disabled:opacity-50">
            <RefreshCw size={14} className={refreshing ? "animate-spin" : ""} /> Refresh
          </button>
          <button onClick={() => setShowAdd(true)} className="inline-flex h-10 items-center gap-2 rounded-lg bg-cyan-400 px-3.5 text-xs font-semibold text-slate-950 hover:bg-cyan-300">
            <Plus size={15} /> Add Agent
          </button>
        </div>
      </header>

      {error && (
        <div role="alert" className="flex items-start gap-2 rounded-xl border border-rose-400/20 bg-rose-400/[0.06] p-3 text-xs text-rose-200">
          <AlertTriangle size={15} className="mt-0.5 shrink-0" /> <span className="flex-1">{error}</span>
          <button onClick={() => setError("")} aria-label="Dismiss error"><X size={14} /></button>
        </div>
      )}

      <section className="grid gap-3 sm:grid-cols-3">
        <div className="rounded-xl border border-white/[0.08] bg-white/[0.025] p-4">
          <div className="mb-3 flex items-center justify-between"><Server size={18} className="text-cyan-300" /><span className="text-[10px] uppercase tracking-wider text-slate-500">Registered</span></div>
          <p className="text-2xl font-semibold tabular-nums">{agents.length}</p><p className="mt-1 text-xs text-slate-500">Total Remote Agents</p>
        </div>
        <div className="rounded-xl border border-white/[0.08] bg-white/[0.025] p-4">
          <div className="mb-3 flex items-center justify-between"><Wifi size={18} className="text-emerald-300" /><span className="text-[10px] uppercase tracking-wider text-slate-500">Connected</span></div>
          <p className="text-2xl font-semibold tabular-nums">{onlineCount}</p><p className="mt-1 text-xs text-slate-500">Agents with fresh heartbeat</p>
        </div>
        <div className="rounded-xl border border-white/[0.08] bg-white/[0.025] p-4">
          <div className="mb-3 flex items-center justify-between"><Activity size={18} className="text-violet-300" /><span className="text-[10px] uppercase tracking-wider text-slate-500">Heartbeat</span></div>
          <p className="text-2xl font-semibold">10s</p><p className="mt-1 text-xs text-slate-500">Dashboard refresh interval</p>
        </div>
      </section>

      <section className="overflow-hidden rounded-2xl border border-white/[0.08] bg-white/[0.02]">
        <div className="flex items-center justify-between border-b border-white/[0.07] px-4 py-3.5">
          <div><h2 className="text-sm font-semibold">Agent inventory</h2><p className="mt-1 text-[11px] text-slate-500">Status is derived from backend heartbeat data.</p></div>
          <span className="text-[10px] text-slate-500">AUTO REFRESH · 10 SEC</span>
        </div>
        {loading ? (
          <div className="flex items-center justify-center gap-2 py-16 text-xs text-slate-500"><Loader2 size={16} className="animate-spin" /> Loading agents…</div>
        ) : agents.length === 0 ? (
          <div className="flex flex-col items-center px-5 py-14 text-center">
            <div className="mb-3 flex h-12 w-12 items-center justify-center rounded-2xl border border-white/10 bg-white/[0.03] text-cyan-300"><Laptop size={22} /></div>
            <h3 className="text-sm font-semibold">No Remote Agents registered</h3>
            <p className="mt-1 max-w-sm text-xs leading-5 text-slate-500">Create an Agent to generate its unique identity and one-time pairing token.</p>
            <button onClick={() => setShowAdd(true)} className="mt-4 inline-flex items-center gap-2 rounded-lg bg-cyan-400 px-3 py-2 text-xs font-semibold text-slate-950 hover:bg-cyan-300"><Plus size={14} /> Add first Agent</button>
          </div>
        ) : (
          <div className="divide-y divide-white/[0.06]">
            {agents.map((agent) => (
              <article key={agent.id} className="flex flex-col gap-4 px-4 py-4 lg:flex-row lg:items-center">
                <div className="flex min-w-0 flex-1 items-center gap-3">
                  <div className={`flex h-10 w-10 shrink-0 items-center justify-center rounded-xl border ${agent.status === "online" ? "border-emerald-400/20 bg-emerald-400/10 text-emerald-300" : "border-white/10 bg-white/[0.04] text-slate-400"}`}>
                    {agent.status === "online" ? <Wifi size={18} /> : <WifiOff size={18} />}
                  </div>
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-2">
                      <h3 className="truncate text-sm font-semibold">{agent.name}</h3>
                      <span className={`rounded-md border px-2 py-0.5 text-[10px] capitalize ${statusStyle(agent.status)}`}>{agent.status}</span>
                    </div>
                    <p className="mt-1 truncate font-mono text-[10px] text-slate-600">{agent.id}</p>
                  </div>
                </div>
                <div className="grid grid-cols-2 gap-x-5 gap-y-2 text-xs sm:grid-cols-5 lg:w-[650px]">
                  <div><p className="text-[10px] uppercase tracking-wider text-slate-600">Hostname</p><p className="mt-1 truncate text-slate-300">{agent.hostname ?? "Not reported"}</p></div>
                  <div><p className="text-[10px] uppercase tracking-wider text-slate-600">Platform</p><p className="mt-1 text-slate-300">{platformLabel(agent.os)}</p></div>
                  <div><p className="text-[10px] uppercase tracking-wider text-slate-600">Agent version</p><p className="mt-1 text-slate-300">{agent.agent_version ?? "—"}</p></div>
                  <div><p className="text-[10px] uppercase tracking-wider text-slate-600">Last connected</p><p className="mt-1 text-slate-300">{formatDate(agent.last_connected_at)}</p></div>
                  <div><p className="text-[10px] uppercase tracking-wider text-slate-600">Last heartbeat</p><p className="mt-1 text-slate-300">{formatDate(agent.last_heartbeat_at)}</p></div>
                </div>
                <div className="flex flex-wrap items-center gap-1.5 lg:justify-end">
                  <button disabled={busyId === agent.id} onClick={() => void disconnectAgent(agent)} title="Disconnect current session" className="inline-flex h-8 items-center gap-1.5 rounded-lg border border-white/10 px-2.5 text-[11px] text-slate-300 hover:bg-white/5 disabled:opacity-50"><WifiOff size={13} /> Disconnect</button>
                  <button disabled={busyId === agent.id} onClick={() => void rotateToken(agent)} title="Rotate agent token" className="inline-flex h-8 items-center gap-1.5 rounded-lg border border-amber-400/20 px-2.5 text-[11px] text-amber-200 hover:bg-amber-400/10 disabled:opacity-50"><RotateCw size={13} /> Rotate</button>
                  <button disabled={busyId === agent.id} onClick={() => void deleteAgent(agent)} title="Delete agent" className="inline-flex h-8 items-center gap-1.5 rounded-lg border border-rose-400/20 px-2.5 text-[11px] text-rose-200 hover:bg-rose-400/10 disabled:opacity-50"><Trash2 size={13} /> Delete</button>
                </div>
              </article>
              <RelayTargetsPanel agentId={agent.id} />
            ))}
          </div>
        )}
      </section>

      <section className="grid gap-3 lg:grid-cols-2">
        <div className="rounded-xl border border-white/[0.08] bg-white/[0.025] p-4">
          <div className="mb-2 flex items-center gap-2"><ShieldCheck size={17} className="text-cyan-300" /><h2 className="text-sm font-semibold">Security model</h2></div>
          <ul className="space-y-1.5 text-xs leading-5 text-slate-500">
            <li>• Unique token per Agent; only its hash is stored by NOVA.</li>
            <li>• Token is shown only during create or rotate operations.</li>
            <li>• Agent establishes an outbound TLS connection to NOVA.</li>
            <li>• Agent ownership is enforced by the authenticated backend.</li>
          </ul>
        </div>
        <div className="rounded-xl border border-white/[0.08] bg-white/[0.025] p-4">
          <div className="mb-2 flex items-center gap-2"><Terminal size={17} className="text-cyan-300" /><h2 className="text-sm font-semibold">Connection behavior</h2></div>
          <p className="text-xs leading-5 text-slate-500">Disconnect closes the current WebSocket session. The installed Agent uses automatic reconnect, so stop its service on the host to keep it offline. Rotate its token to revoke the current credential.</p>
        </div>
      </section>

      {showAdd && (
        <Modal title="Register a Remote Agent" onClose={() => { if (!creating) setShowAdd(false); }}>
          <form onSubmit={createAgent} className="space-y-4">
            <div>
              <label htmlFor="agent-name" className="mb-1.5 block text-xs font-medium text-slate-300">Agent name</label>
              <input id="agent-name" autoFocus maxLength={100} value={newName} onChange={(e) => setNewName(e.target.value)} placeholder="e.g. Office Gateway Agent" className="h-10 w-full rounded-lg border border-white/10 bg-black/30 px-3 text-sm text-white outline-none placeholder:text-slate-600 focus:border-cyan-400/50" />
              <p className="mt-1.5 text-[11px] text-slate-500">Use a descriptive name for the host or site where the Agent will run.</p>
            </div>
            <div className="flex items-start gap-2 rounded-lg border border-white/10 bg-white/[0.025] p-3 text-xs leading-5 text-slate-400">
              <ShieldCheck size={15} className="mt-0.5 shrink-0 text-cyan-300" /> NOVA generates a unique Agent ID and one-time token. No network connection is started until the Agent is installed and configured on its host.
            </div>
            <div className="flex justify-end gap-2">
              <button type="button" onClick={() => setShowAdd(false)} disabled={creating} className="rounded-lg border border-white/10 px-3 py-2 text-xs text-slate-300 hover:bg-white/5">Cancel</button>
              <button type="submit" disabled={creating || !newName.trim()} className="inline-flex items-center gap-2 rounded-lg bg-cyan-400 px-4 py-2 text-xs font-semibold text-slate-950 hover:bg-cyan-300 disabled:opacity-50">{creating ? <Loader2 size={14} className="animate-spin" /> : <Plus size={14} />} Create Agent</button>
            </div>
          </form>
        </Modal>
      )}
      {provisioned && <ProvisioningPanel agent={provisioned} onClose={() => setProvisioned(null)} />}
    </div>
  );
}
