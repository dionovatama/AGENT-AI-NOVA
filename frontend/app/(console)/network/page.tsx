"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { novaApi } from "@/lib/api";
import type { Device, DevicePlatform } from "@/lib/types";
import {
  Activity, Cpu, Loader2, Plus, RefreshCw, Router, Search, Server,
  Pencil, Trash2, X, Network, RadioTower,
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

function formatDate(value: string | null | undefined) {
  if (!value) return "Belum ada";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? "—" : date.toLocaleString("id-ID", { dateStyle: "medium", timeStyle: "short" });
}

export default function NetworkPage() {
  const [devices, setDevices] = useState<Device[]>([]);
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
  const [selectedDevice, setSelectedDevice] = useState<Device | null>(null);
  const [routerStatus, setRouterStatus] = useState<Record<string, unknown> | null>(null);
  const [routerStatusError, setRouterStatusError] = useState<string | null>(null);
  const [checkingRouter, setCheckingRouter] = useState(false);
  const [nodePositions, setNodePositions] = useState<Record<string, { x: number; y: number }>>({});






  const loadData = useCallback(async (quiet = false) => {
    if (quiet) setRefreshing(true);
    else setLoading(true);
    setError(null);
    try {
      const deviceRows = await novaApi.listDevices();
      setDevices(deviceRows);
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
        <div className="mt-4 grid grid-cols-2 gap-2 sm:grid-cols-3">
          <div className="rounded-lg border border-white/[0.07] bg-white/[0.025] px-3 py-2.5"><p className="text-[9px] uppercase tracking-wider text-slate-500">Registered devices</p><p className="mt-1 text-xl font-semibold">{devices.length}</p></div>
          <div className="rounded-lg border border-white/[0.07] bg-white/[0.025] px-3 py-2.5"><p className="text-[9px] uppercase tracking-wider text-slate-500">Topology links</p><p className="mt-1 text-xl font-semibold text-slate-500">—</p></div>
        </div>
      </header>

      <main className="min-h-0 flex-1 space-y-6 p-5">
        <section className="overflow-hidden rounded-xl border border-white/[0.09] bg-[#080b12]">
          <div className="flex flex-wrap items-center justify-between gap-3 border-b border-white/[0.08] bg-[#0b1019] px-4 py-3">
            <div><div className="flex items-center gap-2"><Network size={15} className="text-cyan-300"/><h2 className="text-sm font-semibold">Network topology</h2><span className="rounded bg-white/[0.06] px-2 py-0.5 text-[9px] text-slate-400">{devices.length} devices</span></div><p className="mt-1 text-[10px] text-slate-500">Drag node untuk mengatur canvas · klik node untuk membuka inspector</p></div>
            <div className="flex flex-wrap items-center gap-2">
              <button type="button" onClick={()=>setQuery("")} className="rounded border border-white/[0.1] px-2.5 py-1.5 text-[10px] text-slate-300 hover:bg-white/[.05]">Reset view</button>
              <button type="button" onClick={()=>void loadData(true)} disabled={refreshing} className="flex items-center gap-1.5 rounded border border-white/[0.1] px-2.5 py-1.5 text-[10px] text-slate-300 hover:bg-white/[.05] disabled:opacity-50"><RefreshCw size={11} className={refreshing?"animate-spin":""}/> Sync API</button>
              <button type="button" onClick={openCreate} className="flex items-center gap-1.5 rounded bg-cyan-500 px-2.5 py-1.5 text-[10px] font-semibold text-slate-950"><Plus size={12}/> Add node</button>
            </div>
          </div>
          <div className="flex min-h-[650px]">
            <div className="relative min-w-0 flex-1 overflow-auto" style={{backgroundColor:"#080b12",backgroundImage:"radial-gradient(rgba(90,115,145,.3) 1px, transparent 1px)",backgroundSize:"20px 20px"}}>
              {loading ? <div className="flex min-h-[650px] items-center justify-center gap-2 text-xs text-slate-400"><Loader2 size={16} className="animate-spin"/> Loading network nodes…</div> :
              devices.length===0 ? <div className="flex min-h-[650px] flex-col items-center justify-center text-center"><Network size={30} className="mb-3 text-slate-600"/><p className="text-sm text-slate-300">Canvas masih kosong</p><p className="mt-1 text-[10px] text-slate-500">Tambahkan perangkat untuk mulai membangun topology.</p><button type="button" onClick={openCreate} className="mt-4 rounded bg-cyan-500 px-3 py-2 text-[10px] font-semibold text-slate-950">+ Add device</button></div> :
              <div className="relative min-h-[650px] min-w-[980px]" onDragOver={(event)=>event.preventDefault()} onDrop={(event)=>{event.preventDefault();const id=event.dataTransfer.getData("text/plain");if(!id)return;const bounds=event.currentTarget.getBoundingClientRect();setNodePositions((current)=>({...current,[id]:{x:Math.max(12,event.clientX-bounds.left-125),y:Math.max(12,event.clientY-bounds.top-35)}}));}}>

                {devices.map((device,index)=>{const Icon=deviceIcon(device.platform);const x=36+(index%3)*310;const y=80+Math.floor(index/3)*190;const active=selectedDevice?.id===device.id;return <button key={`node-device-${device.id}`} type="button" draggable onDragStart={(event)=>{event.dataTransfer.setData("text/plain",device.id);event.dataTransfer.effectAllowed="move";}} onClick={()=>{setSelectedDevice(device);setRouterStatus(null);setRouterStatusError(null);}} style={{left:nodePositions[device.id]?.x ?? x,top:nodePositions[device.id]?.y ?? y}} className={`absolute w-[250px] rounded-xl border bg-[#101a28]/95 p-4 text-left shadow-[0_12px_40px_rgba(0,0,0,.35)] transition hover:border-cyan-300/60 ${active?"border-cyan-300 ring-1 ring-cyan-300/30":"border-cyan-300/25"} cursor-grab active:cursor-grabbing`}>
                  <div className="flex items-center gap-3"><div className="flex h-11 w-11 items-center justify-center rounded-lg border border-cyan-300/20 bg-cyan-300/[.08] text-cyan-200"><Icon size={21}/></div><div className="min-w-0"><p className="text-[8px] font-bold tracking-[.17em] text-cyan-300">{device.platform.toUpperCase()} · DEVICE NODE</p><p className="mt-1 truncate text-xs font-semibold text-white">{device.name}</p><p className="mt-1 truncate font-mono text-[10px] text-slate-400">{device.host}:{device.port}</p></div></div>
                  <div className="mt-3 flex items-center justify-between border-t border-white/[.08] pt-2"><span className="text-[9px] text-slate-500">{device.connection_type}</span><span className="flex items-center gap-1 text-[9px] text-cyan-300"><span className="h-1.5 w-1.5 rounded-full bg-slate-500"/> Click to inspect</span></div>
                  <span className="absolute -bottom-1.5 left-1/2 h-3 w-3 -translate-x-1/2 rounded-full border-2 border-cyan-300 bg-[#0b1119]"/>
                </button>})}

                <div className="absolute bottom-5 left-5 rounded-md border border-white/[.08] bg-[#0b1019]/90 px-3 py-2 text-[9px] text-slate-500">Drag nodes · click device to inspect</div>
              </div>}
            </div>
            <aside className="hidden w-[310px] shrink-0 border-l border-white/[.08] bg-[#0b1019] p-4 lg:block">
              {selectedDevice ? <div className="space-y-4">
                <div className="flex items-start justify-between"><div><p className="text-[9px] font-bold tracking-[.18em] text-cyan-300">NODE INSPECTOR</p><h3 className="mt-1 text-sm font-semibold text-white">{selectedDevice.name}</h3><p className="mt-1 font-mono text-[10px] text-slate-400">{selectedDevice.host}:{selectedDevice.port}</p></div><button type="button" onClick={()=>setSelectedDevice(null)} className="rounded p-1 text-slate-500 hover:bg-white/[.06]"><X size={15}/></button></div>
                <div className="rounded-lg border border-white/[.08] bg-white/[.025] p-3"><p className="text-[9px] uppercase tracking-wider text-slate-500">Inventory</p><div className="mt-2 flex items-center justify-between"><span className="text-[11px] text-slate-200">{PLATFORM_LABELS[selectedDevice.platform as DevicePlatform]||selectedDevice.platform}</span><span className="rounded border border-cyan-300/20 bg-cyan-300/[.07] px-2 py-1 text-[8px] text-cyan-200">REGISTERED</span></div><p className="mt-2 text-[9px] text-slate-500">Updated {formatDate(selectedDevice.updated_at)}</p></div>
                <div><p className="text-[10px] font-semibold text-slate-200">Live diagnostics</p><p className="mt-1 text-[9px] leading-4 text-slate-500">Ambil informasi aktual dari perangkat menggunakan tool read-only.</p></div>
                <button type="button" disabled={checkingRouter||selectedDevice.platform!=="mikrotik"} onClick={async()=>{setCheckingRouter(true);setRouterStatus(null);setRouterStatusError(null);try{const result=await novaApi.executeTool("mikrotik.system_resource",{},false,selectedDevice.id);if(!result.success)throw new Error(result.error||"Diagnostic gagal");setRouterStatus(result.output||{});}catch(err){setRouterStatusError(err instanceof Error?err.message:"Diagnostic gagal");}finally{setCheckingRouter(false);}}} className="flex w-full items-center justify-center gap-2 rounded-md bg-cyan-500 px-3 py-2.5 text-[10px] font-semibold text-slate-950 disabled:cursor-not-allowed disabled:opacity-40">{checkingRouter?<Loader2 size={13} className="animate-spin"/>:<Activity size={13}/>}Check router status</button>
                {selectedDevice.platform!=="mikrotik"&&<p className="rounded border border-amber-300/15 bg-amber-300/[.04] p-2 text-[9px] leading-4 text-amber-100/80">Diagnostic langsung saat ini tersedia untuk MikroTik. Platform lain menampilkan data inventory sampai tool diagnostiknya tersedia.</p>}
                {routerStatusError&&<p role="alert" className="rounded border border-rose-400/20 bg-rose-400/[.06] p-2 text-[9px] text-rose-200">{routerStatusError}</p>}
                {routerStatus&&<div className="space-y-2"><div className="rounded-lg border border-emerald-400/20 bg-emerald-400/[.05] p-3"><p className="text-[9px] font-semibold text-emerald-300">DEVICE RESPONDED</p><p className="mt-1 text-xs font-semibold">{String(routerStatus.identity||selectedDevice.name)}</p><p className="mt-1 text-[9px] text-slate-400">{String(routerStatus.routeros_version||routerStatus.version||"RouterOS version unavailable")}</p></div><div className="grid grid-cols-2 gap-2"><div className="rounded border border-white/[.08] p-2"><p className="text-[8px] text-slate-500">CPU</p><p className="mt-1 text-sm font-semibold">{routerStatus.cpu_load_percent!=null?`${routerStatus.cpu_load_percent}%`:"—"}</p></div><div className="rounded border border-white/[.08] p-2"><p className="text-[8px] text-slate-500">Uptime</p><p className="mt-1 text-[10px] font-semibold">{String(routerStatus.uptime||"—")}</p></div><div className="rounded border border-white/[.08] p-2"><p className="text-[8px] text-slate-500">Free RAM</p><p className="mt-1 text-[10px] font-semibold">{routerStatus.free_memory_bytes!=null?`${(Number(routerStatus.free_memory_bytes)/1048576).toFixed(0)} MB`:"—"}</p></div><div className="rounded border border-white/[.08] p-2"><p className="text-[8px] text-slate-500">Total RAM</p><p className="mt-1 text-[10px] font-semibold">{routerStatus.total_memory_bytes!=null?`${(Number(routerStatus.total_memory_bytes)/1048576).toFixed(0)} MB`:"—"}</p></div></div><details className="rounded border border-white/[.08] p-2"><summary className="cursor-pointer text-[9px] text-slate-400">Raw response</summary><pre className="mt-2 overflow-auto text-[9px] text-slate-300">{JSON.stringify(routerStatus,null,2)}</pre></details></div>}
              </div> : <div className="flex h-full min-h-[300px] flex-col items-center justify-center text-center"><Activity size={23} className="mb-3 text-slate-600"/><p className="text-xs font-medium text-slate-300">Node inspector</p><p className="mt-1 max-w-[210px] text-[9px] leading-4 text-slate-500">Pilih node perangkat di canvas untuk melihat detail dan menjalankan diagnostic.</p></div>}
            </aside>
          </div>
          <div className="flex flex-wrap items-center justify-between gap-2 border-t border-white/[.08] px-4 py-2 text-[9px] text-slate-500"><span>Device nodes only</span><span>Topology links manual menunggu endpoint relasi backend.</span></div>
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


        <div className="flex items-start gap-2 rounded-lg border border-amber-300/15 bg-amber-300/[0.035] p-3 text-[10px] leading-5 text-amber-100/80"><Activity size={13} className="mt-0.5 shrink-0 text-amber-300"/> Halaman ini hanya menampilkan perangkat dari inventory backend. Backend branch ini belum menyediakan API topology/link manual atau telemetry perangkat; karena itu koneksi antar-node, ping, dan status online Device tidak dibuat-buat.</div>
      </main>

      {selectedDevice && <div className="fixed inset-0 z-[60] flex justify-end bg-black/65 backdrop-blur-[2px]" onMouseDown={(event)=>{if(event.target===event.currentTarget)setSelectedDevice(null);}}>
        <aside className="flex h-full w-full max-w-lg flex-col overflow-y-auto border-l border-white/[0.1] bg-[#0b1119] shadow-2xl">
          <div className="flex items-start justify-between border-b border-white/[0.08] p-5"><div className="flex items-center gap-3"><div className="flex h-11 w-11 items-center justify-center rounded-lg border border-cyan-300/20 bg-cyan-300/[0.08] text-cyan-200"><Router size={21}/></div><div><p className="text-[9px] font-semibold uppercase tracking-[.18em] text-cyan-300">Device details</p><h2 className="mt-1 text-base font-semibold">{selectedDevice.name}</h2><p className="mt-1 font-mono text-[10px] text-slate-400">{selectedDevice.host}:{selectedDevice.port}</p></div></div><button type="button" onClick={()=>setSelectedDevice(null)} className="rounded-md p-2 text-slate-400 hover:bg-white/[.06]"><X size={17}/></button></div>
          <div className="space-y-4 p-5">
            <div className="rounded-lg border border-white/[.08] bg-white/[.025] p-4"><p className="text-[9px] uppercase tracking-wider text-slate-500">Inventory status</p><div className="mt-2 flex items-center justify-between"><span className="text-xs text-slate-200">Registered in NOVA</span><span className="rounded border border-cyan-300/20 bg-cyan-300/[.07] px-2 py-1 text-[9px] text-cyan-200">REGISTERED</span></div><p className="mt-2 text-[10px] text-slate-500">Status koneksi aktual hanya muncul setelah diagnostic berhasil dijalankan.</p></div>
            <div><h3 className="text-xs font-semibold">Router diagnostics</h3><p className="mt-1 text-[10px] text-slate-500">Jalankan pembacaan langsung melalui tool backend yang diizinkan.</p></div>
            <button type="button" disabled={checkingRouter || selectedDevice.platform.toLowerCase()!=="mikrotik"} onClick={async()=>{setCheckingRouter(true);setRouterStatus(null);setRouterStatusError(null);try{const result=await novaApi.executeTool("mikrotik.system_resource",{},false,selectedDevice.id);if(!result.success)throw new Error(result.error||"Router tidak merespons.");setRouterStatus(result.output||{});}catch(err){setRouterStatusError(err instanceof Error?err.message:"Diagnostic gagal.");}finally{setCheckingRouter(false);}}} className="flex w-full items-center justify-center gap-2 rounded-md bg-cyan-500 px-4 py-3 text-[11px] font-semibold text-slate-950 hover:bg-cyan-400 disabled:cursor-not-allowed disabled:opacity-50">{checkingRouter?<Loader2 size={14} className="animate-spin"/>:<Activity size={14}/>} {checkingRouter?"Memeriksa router…":"Check router status"}</button>
            {selectedDevice.platform.toLowerCase()!=="mikrotik"&&<p className="rounded-md border border-amber-300/15 bg-amber-300/[.04] p-3 text-[10px] text-amber-100/80">Diagnostic status langsung saat ini tersedia untuk MikroTik melalui RouterOS API. Perangkat platform lain tetap menampilkan data inventory.</p>}
            {routerStatusError&&<div role="alert" className="rounded-md border border-rose-400/20 bg-rose-400/[.06] p-3 text-[10px] text-rose-200">{routerStatusError}</div>}
            {routerStatus&&<div className="space-y-3"><div className="rounded-lg border border-emerald-400/20 bg-emerald-400/[.05] p-3"><p className="text-[9px] font-semibold uppercase tracking-wider text-emerald-300">Router responded</p><p className="mt-1 text-sm font-semibold text-slate-100">{String(routerStatus.identity||selectedDevice.name)}</p><p className="mt-1 text-[10px] text-slate-400">{String(routerStatus.routeros_version||"RouterOS version unavailable")} · {String(routerStatus.board_name||"Board unavailable")}</p></div><div className="grid grid-cols-2 gap-2"><div className="rounded-lg border border-white/[.08] p-3"><p className="text-[9px] text-slate-500">CPU load</p><p className="mt-1 text-xl font-semibold">{routerStatus.cpu_load_percent!=null?`${routerStatus.cpu_load_percent}%`:"—"}</p></div><div className="rounded-lg border border-white/[.08] p-3"><p className="text-[9px] text-slate-500">Uptime</p><p className="mt-1 text-sm font-semibold">{String(routerStatus.uptime||"—")}</p></div><div className="rounded-lg border border-white/[.08] p-3"><p className="text-[9px] text-slate-500">Free memory</p><p className="mt-1 text-sm font-semibold">{routerStatus.free_memory_bytes!=null?`${(Number(routerStatus.free_memory_bytes)/1024/1024).toFixed(0)} MB`:"—"}</p></div><div className="rounded-lg border border-white/[.08] p-3"><p className="text-[9px] text-slate-500">Total memory</p><p className="mt-1 text-sm font-semibold">{routerStatus.total_memory_bytes!=null?`${(Number(routerStatus.total_memory_bytes)/1024/1024).toFixed(0)} MB`:"—"}</p></div></div><details className="rounded-lg border border-white/[.08] p-3"><summary className="cursor-pointer text-[10px] text-slate-400">Raw diagnostic response</summary><pre className="mt-3 overflow-auto text-[10px] text-slate-300">{JSON.stringify(routerStatus,null,2)}</pre></details></div>}
          </div>
        </aside>
      </div>}
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
