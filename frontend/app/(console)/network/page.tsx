"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { novaApi } from "@/lib/api";
import type { Device, DevicePlatform, RemoteAgent } from "@/lib/types";
import {
  Activity, Bot, Cpu, Loader2, Plus, RefreshCw, Router, Search, Server,
  Wifi, Pencil, Trash2, X, Network, RadioTower, Cable, Globe2,
} from "lucide-react";

type DeviceForm = {
  name: string;
  platform: DevicePlatform;
  host: string;
  port: string;
  connection_type: string;
};

const EMPTY_FORM: DeviceForm = {
  name: "",
  platform: "linux",
  host: "",
  port: "22",
  connection_type: "ssh",
};

const PLATFORM_LABELS: Record<DevicePlatform, string> = {
  linux: "Linux",
  windows: "Windows",
  mikrotik: "MikroTik",
  cisco: "Cisco",
};

function deviceIcon(platform: string) {
  if (platform === "mikrotik" || platform === "cisco") return Router;
  if (platform === "windows" || platform === "linux") return Server;
  return Cpu;
}

function agentStatus(status: string) {
  if (status === "online") return { label: "ONLINE", className: "border-emerald-400/25 bg-emerald-400/10 text-emerald-300", dot: "bg-emerald-400" };
  if (status === "connecting") return { label: "CONNECTING", className: "border-amber-400/25 bg-amber-400/10 text-amber-300", dot: "bg-amber-400" };
  if (status === "error") return { label: "ERROR", className: "border-rose-400/25 bg-rose-400/10 text-rose-300", dot: "bg-rose-400" };
  return { label: status.toUpperCase(), className: "border-slate-500/25 bg-slate-500/10 text-slate-400", dot: "bg-slate-500" };
}

function formatDate(value: string | null | undefined) {
  if (!value) return "Belum ada";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? "—" : date.toLocaleString("id-ID", { dateStyle: "medium", timeStyle: "short" });
}

export default function NetworkPage() {
  const [devices, setDevices] = useState<Device[]>([]);
  const [agents, setAgents] = useState<RemoteAgent[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [modalOpen, setModalOpen] = useState(false);
  const [editing, setEditing] = useState<Device | null>(null);
  const [form, setForm] = useState<DeviceForm>(EMPTY_FORM);
  const [saving, setSaving] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);
  const [deletingId, setDeletingId] = useState<string | null>(null);

  const loadData = useCallback(async (quiet = false) => {
    if (quiet) setRefreshing(true);
    else setLoading(true);
    setError(null);
    try {
      const [deviceRows, agentRows] = await Promise.all([
        novaApi.listDevices(),
        novaApi.listAgents(),
      ]);
      setDevices(deviceRows);
      setAgents(agentRows);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Gagal mengambil inventory dari API.");
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, []);

  useEffect(() => {
    void loadData();
  }, [loadData]);

  const filteredDevices = useMemo(() => {
    const needle = query.trim().toLocaleLowerCase();
    if (!needle) return devices;
    return devices.filter((device) =>
      [device.name, device.host, device.platform, device.connection_type]
        .some((value) => value.toLocaleLowerCase().includes(needle)),
    );
  }, [devices, query]);

  const openCreate = () => {
    setEditing(null);
    setForm(EMPTY_FORM);
    setActionError(null);
    setModalOpen(true);
  };

  const openEdit = (device: Device) => {
    setEditing(device);
    setForm({
      name: device.name,
      platform: (["linux", "windows", "mikrotik", "cisco"].includes(device.platform) ? device.platform : "linux") as DevicePlatform,
      host: device.host,
      port: String(device.port),
      connection_type: device.connection_type || "ssh",
    });
    setActionError(null);
    setModalOpen(true);
  };

  const submitDevice = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (saving) return;
    setSaving(true);
    setActionError(null);
    const payload = {
      name: form.name.trim(),
      platform: form.platform,
      host: form.host.trim(),
      port: Number(form.port),
      connection_type: form.connection_type.trim() || "ssh",
    };
    try {
      if (editing) {
        await novaApi.updateDevice(editing.id, payload);
      } else {
        await novaApi.createDevice(payload);
      }
      setModalOpen(false);
      await loadData(true);
    } catch (err) {
      setActionError(err instanceof Error ? err.message : "Perubahan device gagal disimpan.");
    } finally {
      setSaving(false);
    }
  };

  const removeDevice = async (device: Device) => {
    if (!window.confirm(`Hapus device "${device.name}" dari inventory?`)) return;
    setDeletingId(device.id);
    setError(null);
    try {
      await novaApi.deleteDevice(device.id);
      setDevices((items) => items.filter((item) => item.id !== device.id));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Device gagal dihapus.");
    } finally {
      setDeletingId(null);
    }
  };

  const onlineAgents = agents.filter((agent) => agent.status === "online").length;

  return (
    <div className="flex h-full min-h-0 flex-col overflow-y-auto bg-[#07090d] text-slate-100">
      <header className="shrink-0 border-b border-white/[0.08] bg-[#0a0d13] px-5 py-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex items-center gap-3">
            <div className="flex h-10 w-10 items-center justify-center rounded-lg border border-cyan-400/20 bg-cyan-400/[0.08] text-cyan-300"><Network size={19}/></div>
            <div>
              <p className="text-[10px] font-semibold uppercase tracking-[0.22em] text-cyan-300">NOVA / Infrastructure</p>
              <h1 className="text-lg font-semibold tracking-wide">Network Management</h1>
              <p className="mt-0.5 text-[11px] text-slate-500">Inventory perangkat dan koneksi Remote Agent dari backend.</p>
            </div>
          </div>
          <div className="flex items-center gap-2">
            <button type="button" onClick={() => void loadData(true)} disabled={refreshing || loading} className="flex items-center gap-2 rounded-md border border-white/[0.1] px-3 py-2 text-[11px] text-slate-300 hover:bg-white/[0.05] disabled:opacity-50">
              {refreshing ? <Loader2 size={13} className="animate-spin"/> : <RefreshCw size={13}/>} Refresh
            </button>
            <button type="button" onClick={openCreate} className="flex items-center gap-2 rounded-md bg-cyan-500 px-3 py-2 text-[11px] font-semibold text-slate-950 hover:bg-cyan-400">
              <Plus size={14}/> Add device
            </button>
          </div>
        </div>
        <div className="mt-4 grid grid-cols-2 gap-2 sm:grid-cols-4">
          <div className="rounded-lg border border-white/[0.07] bg-white/[0.025] px-3 py-2.5"><p className="text-[9px] uppercase tracking-wider text-slate-500">Registered devices</p><p className="mt-1 text-xl font-semibold">{devices.length}</p></div>
          <div className="rounded-lg border border-white/[0.07] bg-white/[0.025] px-3 py-2.5"><p className="text-[9px] uppercase tracking-wider text-slate-500">Remote agents</p><p className="mt-1 text-xl font-semibold">{agents.length}</p></div>
          <div className="rounded-lg border border-white/[0.07] bg-white/[0.025] px-3 py-2.5"><p className="text-[9px] uppercase tracking-wider text-slate-500">Agents online</p><p className="mt-1 text-xl font-semibold text-emerald-300">{onlineAgents}</p></div>
          <div className="rounded-lg border border-white/[0.07] bg-white/[0.025] px-3 py-2.5"><p className="text-[9px] uppercase tracking-wider text-slate-500">Topology links</p><p className="mt-1 text-xl font-semibold text-slate-500">—</p></div>
        </div>
      </header>

      <main className="min-h-0 flex-1 space-y-6 p-5">
        <section className="overflow-hidden rounded-xl border border-white/[0.09] bg-[#090e16]">
          <div className="flex flex-wrap items-center justify-between gap-3 border-b border-white/[0.07] px-4 py-3">
            <div>
              <div className="flex items-center gap-2"><Network size={15} className="text-cyan-300"/><h2 className="text-sm font-semibold">Network topology</h2><span className="rounded bg-white/[0.05] px-2 py-0.5 text-[9px] text-slate-400">{devices.length + agents.length} nodes</span></div>
              <p className="mt-1 text-[10px] text-slate-500">Live inventory · posisi otomatis · relasi menunggu data topology backend</p>
            </div>
            <span className="flex items-center gap-1.5 text-[9px] text-slate-500"><span className="h-1.5 w-1.5 rounded-full bg-emerald-400"/> Data API</span>
          </div>
          <div className="relative min-h-[310px] overflow-hidden p-4 sm:p-6" style={{backgroundImage:"radial-gradient(rgba(100,116,139,.22) 1px, transparent 1px)",backgroundSize:"22px 22px"}}>
            {loading ? <div className="flex min-h-[260px] items-center justify-center gap-2 text-[11px] text-slate-400"><Loader2 size={15} className="animate-spin"/> Memuat node topology…</div> :
              devices.length + agents.length === 0 ? <div className="flex min-h-[260px] flex-col items-center justify-center text-center"><Network size={28} className="mb-3 text-slate-600"/><p className="text-xs font-medium text-slate-300">Topology masih kosong</p><p className="mt-1 max-w-sm text-[10px] text-slate-500">Tambahkan Device atau provision Remote Agent. Node akan muncul di canvas ini setelah API mengembalikan datanya.</p><button type="button" onClick={openCreate} className="mt-4 rounded-md bg-cyan-500 px-3 py-2 text-[10px] font-semibold text-slate-950">Tambah device</button></div> :
              <div className="mx-auto grid max-w-5xl grid-cols-1 gap-5 sm:grid-cols-2 xl:grid-cols-3">
                {devices.map((device,index) => {
                  const Icon=deviceIcon(device.platform);
                  return <article key={`device-${device.id}`} className="relative rounded-xl border border-cyan-300/20 bg-[#101b29]/95 p-4 shadow-[0_8px_30px_rgba(0,0,0,.2)]">
                    <div className="flex items-center gap-3">
                      <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-lg border border-cyan-300/20 bg-cyan-300/[0.08] text-cyan-200"><Icon size={20}/></div>
                      <div className="min-w-0 flex-1"><div className="flex items-center gap-2"><span className="text-[8px] font-semibold uppercase tracking-[.16em] text-cyan-300">DEVICE / {index+1}</span><span className="rounded bg-slate-500/10 px-1.5 py-0.5 text-[8px] text-slate-400">REGISTERED</span></div><h3 className="mt-1 truncate text-xs font-semibold text-slate-100">{device.name}</h3><p className="mt-1 truncate font-mono text-[10px] text-slate-400">{device.host}:{device.port}</p></div>
                    </div>
                    <div className="mt-3 flex items-center justify-between border-t border-white/[0.07] pt-2 text-[9px] text-slate-500"><span>{PLATFORM_LABELS[device.platform as DevicePlatform] ?? device.platform}</span><span>{device.connection_type}</span></div>
                  </article>;
                })}
                {agents.map((agent,index) => {
                  const status=agentStatus(agent.status);
                  return <article key={`agent-${agent.id}`} className="relative rounded-xl border border-violet-300/20 bg-[#171329]/95 p-4 shadow-[0_8px_30px_rgba(0,0,0,.2)]">
                    <div className="flex items-center gap-3">
                      <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-lg border border-violet-300/20 bg-violet-300/[0.08] text-violet-200"><RadioTower size={20}/></div>
                      <div className="min-w-0 flex-1"><div className="flex items-center gap-2"><span className="text-[8px] font-semibold uppercase tracking-[.16em] text-violet-300">REMOTE AGENT / {index+1}</span></div><h3 className="mt-1 truncate text-xs font-semibold text-slate-100">{agent.name}</h3><p className="mt-1 truncate font-mono text-[9px] text-slate-500">{agent.id}</p></div>
                    </div>
                    <div className="mt-3 flex items-center justify-between border-t border-white/[0.07] pt-2"><span className="truncate text-[9px] text-slate-500">{agent.hostname || agent.os || "Agent node"}</span><span className={`rounded border px-2 py-1 text-[8px] font-semibold ${status.className}`}>{status.label}</span></div>
                  </article>;
                })}
              </div>
            }
          </div>
          <div className="flex flex-wrap items-center gap-4 border-t border-white/[0.07] bg-black/10 px-4 py-2.5 text-[9px] text-slate-500"><span className="flex items-center gap-1.5"><span className="h-2 w-2 rounded-sm border border-cyan-300/60 bg-cyan-300/20"/> Device</span><span className="flex items-center gap-1.5"><span className="h-2 w-2 rounded-sm border border-violet-300/60 bg-violet-300/20"/> Remote Agent</span><span className="ml-auto">Link belum ditampilkan: API relasi topology belum tersedia.</span></div>
        </section>
        {error && <div role="alert" className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-rose-400/20 bg-rose-400/[0.06] px-4 py-3 text-[11px] text-rose-200"><span>{error}</span><button type="button" onClick={() => void loadData(true)} className="underline underline-offset-2">Coba lagi</button></div>}

        <section>
          <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
            <div><div className="flex items-center gap-2"><Server size={15} className="text-cyan-300"/><h2 className="text-sm font-semibold">Device inventory</h2></div><p className="mt-1 text-[10px] text-slate-500">Data tersimpan pada backend dan dibatasi berdasarkan akun yang login.</p></div>
            <div className="relative w-full sm:w-64"><Search size={13} className="absolute left-3 top-2.5 text-slate-500"/><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Cari nama, host, platform…" className="w-full rounded-md border border-white/[0.09] bg-[#0a0d13] py-2 pl-8 pr-3 text-[11px] outline-none placeholder:text-slate-600 focus:border-cyan-400/50"/></div>
          </div>

          {loading ? <div className="flex items-center justify-center gap-2 rounded-lg border border-white/[0.07] py-16 text-[11px] text-slate-400"><Loader2 size={16} className="animate-spin"/> Memuat inventory dari API…</div> :
            filteredDevices.length === 0 ? <div className="rounded-lg border border-dashed border-white/[0.1] px-4 py-12 text-center"><RadioTower size={24} className="mx-auto mb-2 text-slate-600"/><p className="text-xs font-medium text-slate-300">{devices.length === 0 ? "Belum ada device terdaftar" : "Device tidak ditemukan"}</p><p className="mt-1 text-[10px] text-slate-500">{devices.length === 0 ? "Tambahkan perangkat untuk mengisi inventory akun ini." : "Coba kata kunci pencarian lain."}</p>{devices.length === 0 && <button type="button" onClick={openCreate} className="mt-4 rounded-md bg-cyan-500 px-3 py-2 text-[10px] font-semibold text-slate-950">Tambah device</button>}</div> :
            <div className="grid gap-3 md:grid-cols-2 2xl:grid-cols-3">
              {filteredDevices.map((device) => {
                const Icon = deviceIcon(device.platform);
                return <article key={device.id} className="rounded-lg border border-white/[0.08] bg-[#0b1119] p-4 transition hover:border-cyan-300/25">
                  <div className="flex items-start gap-3">
                    <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg border border-cyan-300/15 bg-cyan-300/[0.07] text-cyan-200"><Icon size={18}/></div>
                    <div className="min-w-0 flex-1"><h3 className="truncate text-xs font-semibold text-slate-100">{device.name}</h3><p className="mt-1 truncate font-mono text-[10px] text-slate-400">{device.host}:{device.port}</p><p className="mt-1 text-[9px] uppercase tracking-wider text-slate-500">{PLATFORM_LABELS[device.platform as DevicePlatform] ?? device.platform} · {device.connection_type}</p></div>
                    <span className="rounded border border-cyan-300/15 bg-cyan-300/[0.06] px-2 py-1 text-[8px] font-semibold uppercase tracking-wider text-cyan-200">REGISTERED</span>
                  </div>
                  <div className="mt-4 flex items-center justify-between border-t border-white/[0.06] pt-3"><span className="text-[9px] text-slate-600">Updated {formatDate(device.updated_at)}</span><div className="flex gap-1"><button type="button" onClick={() => openEdit(device)} className="flex items-center gap-1 rounded border border-white/[0.08] px-2 py-1.5 text-[9px] text-slate-300 hover:bg-white/[0.05]"><Pencil size={11}/> Edit</button><button type="button" onClick={() => void removeDevice(device)} disabled={deletingId === device.id} className="flex items-center gap-1 rounded border border-rose-400/15 px-2 py-1.5 text-[9px] text-rose-300 hover:bg-rose-400/[0.07] disabled:opacity-50"><Trash2 size={11}/>{deletingId === device.id ? "Deleting…" : "Delete"}</button></div></div>
                </article>;
              })}
            </div>
          }
        </section>

        <section>
          <div className="mb-3 flex items-center gap-2"><Bot size={15} className="text-cyan-300"/><h2 className="text-sm font-semibold">Remote Agents</h2><span className="rounded bg-white/[0.05] px-2 py-0.5 text-[9px] text-slate-500">{agents.length}</span></div>
          <p className="mb-3 text-[10px] text-slate-500">Status koneksi berasal dari heartbeat/session Agent backend; bukan hasil pemindaian jaringan.</p>
          {loading ? <div className="flex items-center gap-2 rounded-lg border border-white/[0.07] px-4 py-6 text-[11px] text-slate-400"><Loader2 size={14} className="animate-spin"/> Memuat Agent…</div> :
            agents.length === 0 ? <div className="rounded-lg border border-dashed border-white/[0.1] px-4 py-8 text-center"><Wifi size={22} className="mx-auto mb-2 text-slate-600"/><p className="text-xs text-slate-300">Belum ada Remote Agent</p><p className="mt-1 text-[10px] text-slate-500">Buat dan provision Agent melalui halaman Agents.</p></div> :
            <div className="grid gap-3 md:grid-cols-2 2xl:grid-cols-3">
              {agents.map((agent) => {
                const status = agentStatus(agent.status);
                return <article key={agent.id} className="rounded-lg border border-white/[0.08] bg-[#0b1119] p-4">
                  <div className="flex items-start justify-between gap-3"><div className="flex min-w-0 items-center gap-2.5"><div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg border border-violet-300/15 bg-violet-300/[0.07] text-violet-200"><RadioTower size={17}/></div><div className="min-w-0"><h3 className="truncate text-xs font-semibold">{agent.name}</h3><p className="mt-1 truncate font-mono text-[9px] text-slate-500">{agent.id}</p></div></div><span className={`flex shrink-0 items-center gap-1.5 rounded border px-2 py-1 text-[8px] font-semibold tracking-wider ${status.className}`}><span className={`h-1.5 w-1.5 rounded-full ${status.dot}`}/>{status.label}</span></div>
                  <div className="mt-4 grid grid-cols-2 gap-3 border-t border-white/[0.06] pt-3"><div><p className="text-[9px] text-slate-500">Hostname</p><p className="mt-1 truncate text-[10px] text-slate-300">{agent.hostname || "—"}</p></div><div><p className="text-[9px] text-slate-500">OS</p><p className="mt-1 truncate text-[10px] text-slate-300">{agent.os || "—"}</p></div><div><p className="text-[9px] text-slate-500">Last heartbeat</p><p className="mt-1 text-[10px] text-slate-300">{formatDate(agent.last_heartbeat_at)}</p></div><div><p className="text-[9px] text-slate-500">Agent version</p><p className="mt-1 text-[10px] text-slate-300">{agent.agent_version || "—"}</p></div></div>
                  {agent.last_error && <p className="mt-3 rounded bg-rose-400/[0.06] px-2 py-1.5 text-[9px] text-rose-200">{agent.last_error}</p>}
                </article>;
              })}
            </div>
          }
        </section>

        <div className="flex items-start gap-2 rounded-lg border border-amber-300/15 bg-amber-300/[0.035] p-3 text-[10px] leading-5 text-amber-100/80"><Activity size={13} className="mt-0.5 shrink-0 text-amber-300"/> Halaman ini menampilkan inventory Device dan status Remote Agent yang tersedia saat ini. Backend branch ini belum menyediakan API topology/link manual atau telemetry perangkat; karena itu koneksi antar-node, ping, dan status online Device tidak dibuat-buat.</div>
      </main>

      {modalOpen && <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/75 p-4 backdrop-blur-sm">
        <form onSubmit={submitDevice} className="w-full max-w-md rounded-xl border border-white/[0.12] bg-[#0c1119] p-5 shadow-2xl">
          <div className="mb-4 flex items-center justify-between"><div><p className="text-[9px] uppercase tracking-[0.2em] text-cyan-300">Backend inventory</p><h2 className="mt-1 text-sm font-semibold">{editing ? "Edit device" : "Register device"}</h2></div><button type="button" onClick={() => setModalOpen(false)} className="rounded p-1 text-slate-500 hover:bg-white/[0.06]"><X size={16}/></button></div>
          <label className="mb-1 block text-[10px] text-slate-400">Device name</label><input autoFocus value={form.name} onChange={(event) => setForm((value) => ({ ...value, name: event.target.value }))} required maxLength={100} placeholder="Core Router" className="mb-3 w-full rounded-md border border-white/[0.1] bg-[#07090d] px-3 py-2.5 text-xs outline-none focus:border-cyan-400/50"/>
          <label className="mb-1 block text-[10px] text-slate-400">Platform</label><select value={form.platform} onChange={(event) => setForm((value) => ({ ...value, platform: event.target.value as DevicePlatform }))} className="mb-3 w-full rounded-md border border-white/[0.1] bg-[#07090d] px-3 py-2.5 text-xs">{Object.entries(PLATFORM_LABELS).map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select>
          <label className="mb-1 block text-[10px] text-slate-400">Host / IP address</label><input value={form.host} onChange={(event) => setForm((value) => ({ ...value, host: event.target.value }))} required maxLength={255} placeholder="192.168.1.1" className="mb-3 w-full rounded-md border border-white/[0.1] bg-[#07090d] px-3 py-2.5 font-mono text-xs outline-none focus:border-cyan-400/50"/>
          <div className="mb-4 grid grid-cols-2 gap-3"><div><label className="mb-1 block text-[10px] text-slate-400">Port</label><input type="number" min="1" max="65535" required value={form.port} onChange={(event) => setForm((value) => ({ ...value, port: event.target.value }))} className="w-full rounded-md border border-white/[0.1] bg-[#07090d] px-3 py-2.5 font-mono text-xs outline-none focus:border-cyan-400/50"/></div><div><label className="mb-1 block text-[10px] text-slate-400">Connection</label><select value={form.connection_type} onChange={(event) => setForm((value) => ({ ...value, connection_type: event.target.value }))} className="w-full rounded-md border border-white/[0.1] bg-[#07090d] px-3 py-2.5 text-xs"><option value="ssh">SSH</option><option value="api">API</option><option value="winrm">WinRM</option></select></div></div>
          {actionError && <p role="alert" className="mb-3 rounded-md border border-rose-400/20 bg-rose-400/[0.06] p-2 text-[10px] text-rose-200">{actionError}</p>}
          <div className="flex justify-end gap-2"><button type="button" onClick={() => setModalOpen(false)} className="rounded-md border border-white/[0.1] px-3 py-2 text-[11px] text-slate-300">Cancel</button><button type="submit" disabled={saving} className="flex items-center gap-2 rounded-md bg-cyan-500 px-4 py-2 text-[11px] font-semibold text-slate-950 disabled:opacity-50">{saving && <Loader2 size={12} className="animate-spin"/>}{editing ? "Save changes" : "Register device"}</button></div>
        </form>
      </div>}
    </div>
  );
}
