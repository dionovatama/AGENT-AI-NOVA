"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { novaApi } from "@/lib/api";
import type { Device, DevicePlatform, ManualTopology, ManualTopologyNode } from "@/lib/types";
import { Activity, Cpu, Loader2, Plus, RefreshCw, Router, Server, Network, Trash2, X, Link2, Unlink } from "lucide-react";

const PLATFORM_LABELS: Record<DevicePlatform, string> = { linux: "Linux", windows: "Windows", mikrotik: "MikroTik", cisco: "Cisco" };
function DeviceIcon({ platform }: { platform: string }) {
  const Icon = platform === "mikrotik" || platform === "cisco" ? Router : platform === "linux" || platform === "windows" ? Server : Cpu;
  return <Icon size={20}/>;
}
function statusLabel(node: ManualTopologyNode) {
  if (!node.device) return "MANUAL";
  return (node.device.reachability || "unknown").toUpperCase();
}

export default function NetworkPage() {
  const [devices, setDevices] = useState<Device[]>([]);
  const [topology, setTopology] = useState<ManualTopology>({ nodes: [], links: [], available_devices: [] });
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<ManualTopologyNode | null>(null);
  const [linkMode, setLinkMode] = useState(false);
  const [linkStart, setLinkStart] = useState<string | null>(null);
  const [addingDevice, setAddingDevice] = useState("");
  const [manualName, setManualName] = useState("");
  const [manualKind, setManualKind] = useState("switch");
  const [showManual, setShowManual] = useState(false);
  const [showDeviceForm, setShowDeviceForm] = useState(false);
  const [deviceForm, setDeviceForm] = useState({ name: "", platform: "mikrotik" as DevicePlatform, host: "", port: "8729", connection_type: "api-ssl" });

  const load = useCallback(async () => {
    setError(null);
    try {
      const [rows, saved] = await Promise.all([novaApi.listDevices(), novaApi.getManualTopology()]);
      setDevices(rows);
      setTopology(saved);
      setSelected((current) => current ? saved.nodes.find((n) => n.id === current.id) ?? null : null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Gagal memuat topology.");
    } finally { setLoading(false); }
  }, []);

  useEffect(() => { void load(); }, [load]);

  const availableDevices = useMemo(() => topology.available_devices, [topology.available_devices]);

  const addDeviceNode = async () => {
    const device = devices.find((d) => d.id === addingDevice);
    if (!device) return;
    setBusy(true);
    try {
      const node = await novaApi.createManualNode({ device_id: device.id, name: device.name, kind: device.platform, x: 40 + topology.nodes.length % 3 * 280, y: 50 + Math.floor(topology.nodes.length / 3) * 170 });
      setTopology((v) => ({ ...v, nodes: [...v.nodes, node] }));
      setSelected(node); setAddingDevice("");
    } catch (e) { setError(e instanceof Error ? e.message : "Gagal menambahkan node."); }
    finally { setBusy(false); }
  };

  const addManualNode = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!manualName.trim()) return;
    setBusy(true);
    try {
      const node = await novaApi.createManualNode({ name: manualName.trim(), kind: manualKind, x: 40 + topology.nodes.length % 3 * 280, y: 50 + Math.floor(topology.nodes.length / 3) * 170 });
      setTopology((v) => ({ ...v, nodes: [...v.nodes, node] }));
      setSelected(node); setManualName(""); setShowManual(false);
    } catch (e) { setError(e instanceof Error ? e.message : "Gagal membuat node manual."); }
    finally { setBusy(false); }
  };

  const persistPosition = async (node: ManualTopologyNode, event: React.DragEvent) => {
    const canvas = event.currentTarget.parentElement;
    if (!canvas) return;
    const rect = canvas.getBoundingClientRect();
    const x = Math.max(0, event.clientX - rect.left - 100 + canvas.scrollLeft);
    const y = Math.max(0, event.clientY - rect.top - 35 + canvas.scrollTop);
    try {
      const updated = await novaApi.updateManualNode(node.id, { x, y });
      setTopology((v) => ({ ...v, nodes: v.nodes.map((n) => n.id === node.id ? updated : n) }));
      setSelected((v) => v?.id === node.id ? updated : v);
    } catch (e) { setError(e instanceof Error ? e.message : "Posisi node gagal disimpan."); }
  };

  const handleNodeClick = async (node: ManualTopologyNode) => {
    if (linkMode) {
      if (!linkStart) { setLinkStart(node.id); return; }
      if (linkStart === node.id) { setLinkStart(null); return; }
      try {
        const link = await novaApi.createManualLink({ source_node_id: linkStart, target_node_id: node.id, connection_type: "ethernet" });
        setTopology((v) => ({ ...v, links: [...v.links, link] }));
        setLinkStart(null); setLinkMode(false);
      } catch (e) { setError(e instanceof Error ? e.message : "Koneksi gagal dibuat."); }
      return;
    }
    setSelected(node);
  };

  const removeNode = async (node: ManualTopologyNode) => {
    if (!window.confirm(`Hapus node "${node.name}" dari canvas? Perangkat inventory tidak ikut dihapus.`)) return;
    try {
      await novaApi.deleteManualNode(node.id);
      setTopology((v) => ({ ...v, nodes: v.nodes.filter((n) => n.id !== node.id), links: v.links.filter((l) => l.source_node_id !== node.id && l.target_node_id !== node.id) }));
      if (selected?.id === node.id) setSelected(null);
    } catch (e) { setError(e instanceof Error ? e.message : "Node gagal dihapus."); }
  };

  const removeLink = async (id: string) => {
    try { await novaApi.deleteManualLink(id); setTopology((v) => ({ ...v, links: v.links.filter((l) => l.id !== id) })); }
    catch (e) { setError(e instanceof Error ? e.message : "Link gagal dihapus."); }
  };

  const refreshDevice = async (node: ManualTopologyNode) => {
    if (!node.device_id) return;
    setBusy(true);
    try {
      await fetchRefresh(node.device_id);
      await load();
    } catch (e) { setError(e instanceof Error ? e.message : "Refresh perangkat gagal."); }
    finally { setBusy(false); }
  };

  const fetchRefresh = async (id: string) => {
    const token = (await import("@/lib/auth")).getToken();
    const base = process.env.NEXT_PUBLIC_NOVA_API_BASE_URL ?? "http://localhost:8000";
    const response = await fetch(`${base}/network/devices/${id}/refresh`, { method: "POST", headers: token ? { Authorization: `Bearer ${token}` } : {} });
    if (!response.ok) { const body = await response.json().catch(() => ({})); throw new Error(body.detail || "Refresh gagal."); }
    return response.json();
  };

  const registerDevice = async (event: React.FormEvent) => {
    event.preventDefault(); setBusy(true);
    try {
      const device = await novaApi.createDevice({ name: deviceForm.name.trim(), platform: deviceForm.platform, host: deviceForm.host.trim(), port: Number(deviceForm.port), connection_type: deviceForm.connection_type });
      setDevices((v) => [...v, device]); setShowDeviceForm(false); setAddingDevice(device.id);
    } catch (e) { setError(e instanceof Error ? e.message : "Gagal mendaftarkan perangkat."); }
    finally { setBusy(false); }
  };

  const nodeById = new Map(topology.nodes.map((n) => [n.id, n]));

  return <div className="flex h-full min-h-0 flex-col overflow-y-auto bg-[#07090d] text-slate-100">
    <header className="shrink-0 border-b border-white/[0.08] bg-[#0a0d13] px-5 py-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-3"><div className="flex h-10 w-10 items-center justify-center rounded-lg border border-cyan-400/20 bg-cyan-400/[0.08] text-cyan-300"><Network size={19}/></div><div><p className="text-[10px] font-semibold uppercase tracking-[0.22em] text-cyan-300">NOVA / Infrastructure</p><h1 className="text-lg font-semibold">Network topology</h1><p className="mt-0.5 text-[11px] text-slate-500">Susun perangkat yang dimonitor melalui Agent. Posisi dan link disimpan di database.</p></div></div>
        <button onClick={() => void load()} disabled={loading} className="flex items-center gap-2 rounded-md border border-white/[0.1] px-3 py-2 text-[11px] text-slate-300"><RefreshCw size={13}/> Refresh</button>
      </div>
      <div className="mt-4 grid grid-cols-3 gap-2"><div className="rounded-lg border border-white/[0.07] bg-white/[0.025] px-3 py-2"><p className="text-[9px] text-slate-500">Inventory devices</p><p className="text-xl font-semibold">{devices.length}</p></div><div className="rounded-lg border border-white/[0.07] bg-white/[0.025] px-3 py-2"><p className="text-[9px] text-slate-500">Canvas nodes</p><p className="text-xl font-semibold">{topology.nodes.length}</p></div><div className="rounded-lg border border-white/[0.07] bg-white/[0.025] px-3 py-2"><p className="text-[9px] text-slate-500">Manual links</p><p className="text-xl font-semibold">{topology.links.length}</p></div></div>
    </header>

    <main className="min-h-0 flex-1 space-y-4 p-5">
      {error && <div role="alert" className="flex items-center justify-between rounded-lg border border-rose-400/20 bg-rose-400/[0.06] px-4 py-3 text-[11px] text-rose-200">{error}<button onClick={() => setError(null)}><X size={14}/></button></div>}
      <section className="overflow-hidden rounded-xl border border-white/[0.09] bg-[#080b12]">
        <div className="flex flex-wrap items-center justify-between gap-3 border-b border-white/[0.08] bg-[#0b1019] px-4 py-3">
          <div><h2 className="text-sm font-semibold">Topology canvas</h2><p className="mt-1 text-[10px] text-slate-500">Drag node untuk menyimpan posisi · aktifkan Connect lalu klik dua node untuk membuat link manual.</p></div>
          <div className="flex flex-wrap items-center gap-2">
            <select value={addingDevice} onChange={(e) => setAddingDevice(e.target.value)} className="max-w-[190px] rounded border border-white/[0.1] bg-[#080b12] px-2 py-2 text-[10px] text-slate-200"><option value="">Pilih device inventory…</option>{availableDevices.map((d) => <option key={d.id} value={d.id}>{d.name} · {d.host}</option>)}</select>
            <button disabled={!addingDevice || busy} onClick={() => void addDeviceNode()} className="flex items-center gap-1 rounded bg-cyan-500 px-3 py-2 text-[10px] font-semibold text-slate-950 disabled:opacity-40"><Plus size={12}/> Add device</button>
            <button onClick={() => setShowManual(true)} className="rounded border border-white/[0.1] px-3 py-2 text-[10px] text-slate-300">Manual node</button>
            <button onClick={() => { setLinkMode((v) => !v); setLinkStart(null); }} className={`flex items-center gap-1 rounded border px-3 py-2 text-[10px] ${linkMode ? "border-cyan-300 bg-cyan-300/10 text-cyan-200" : "border-white/[0.1] text-slate-300"}`}><Link2 size={12}/>{linkMode ? "Cancel connect" : "Connect"}</button>
          </div>
        </div>
        {linkMode && <div className="border-b border-cyan-300/20 bg-cyan-300/[0.06] px-4 py-2 text-[10px] text-cyan-100">{linkStart ? "Pilih node tujuan untuk menyelesaikan koneksi." : "Pilih node pertama."}</div>}
        <div className="relative min-h-[680px] overflow-auto" style={{ backgroundColor: "#080b12", backgroundImage: "radial-gradient(rgba(90,115,145,.3) 1px, transparent 1px)", backgroundSize: "20px 20px" }}>
          {loading ? <div className="flex min-h-[680px] items-center justify-center gap-2 text-xs text-slate-400"><Loader2 size={16} className="animate-spin"/> Loading topology…</div> : topology.nodes.length === 0 ? <div className="flex min-h-[680px] flex-col items-center justify-center text-center"><Network size={30} className="mb-3 text-slate-600"/><p className="text-sm text-slate-300">Canvas masih kosong</p><p className="mt-1 text-[10px] text-slate-500">Pilih perangkat inventory untuk menambahkannya ke topology.</p></div> :
          <div className="relative min-h-[680px] min-w-[1100px]">
            <svg className="pointer-events-none absolute inset-0 h-full w-full overflow-visible" style={{ minHeight: 680 }}>
              {topology.links.map((link) => { const a = nodeById.get(link.source_node_id), b = nodeById.get(link.target_node_id); if (!a || !b) return null; return <g key={link.id}><line x1={a.x + 110} y1={a.y + 48} x2={b.x + 110} y2={b.y + 48} stroke="#22d3ee" strokeWidth="2" opacity=".65"/><circle cx={(a.x+b.x)/2+110} cy={(a.y+b.y)/2+48} r="3" fill="#22d3ee"/></g>; })}
            </svg>
            {topology.nodes.map((node) => <div key={node.id} draggable onDragEnd={(e) => void persistPosition(node, e)} onClick={() => void handleNodeClick(node)} style={{ left: node.x, top: node.y }} className={`absolute z-10 w-[220px] cursor-grab rounded-xl border bg-[#101a28]/95 p-3 text-left shadow-xl active:cursor-grabbing ${selected?.id === node.id || linkStart === node.id ? "border-cyan-300 ring-1 ring-cyan-300/30" : "border-cyan-300/25"}`}>
              <div className="flex items-center gap-3"><div className="flex h-10 w-10 items-center justify-center rounded-lg border border-cyan-300/20 bg-cyan-300/[.08] text-cyan-200"><DeviceIcon platform={node.device?.platform || node.kind}/></div><div className="min-w-0"><p className="truncate text-xs font-semibold text-white">{node.name}</p><p className="truncate font-mono text-[9px] text-slate-400">{node.device ? `${node.device.host}:${node.device.port}` : `Manual · ${node.kind}`}</p></div></div>
              <div className="mt-3 flex items-center justify-between border-t border-white/[.08] pt-2"><span className={`text-[9px] font-semibold ${node.device?.reachability === "online" ? "text-emerald-300" : node.device?.reachability === "offline" ? "text-rose-300" : "text-amber-200"}`}>{statusLabel(node)}</span><span className="text-[8px] text-slate-500">{node.device ? "DEVICE" : "MANUAL"}</span></div>
            </div>)}
            <div className="absolute bottom-4 left-4 rounded border border-white/[.08] bg-[#0b1019]/90 px-3 py-2 text-[9px] text-slate-500">Node layout tersimpan otomatis saat selesai drag · koneksi digambar manual</div>
          </div>}
        </div>
      </section>

      <section className="grid gap-4 lg:grid-cols-[1fr_320px]">
        <div className="rounded-xl border border-white/[0.08] bg-[#0b1119] p-4"><div className="mb-3 flex items-center justify-between"><h3 className="text-xs font-semibold">Topology links</h3><span className="text-[9px] text-slate-500">{topology.links.length} connections</span></div>
          {topology.links.length === 0 ? <p className="text-[10px] text-slate-500">Belum ada koneksi manual.</p> : <div className="space-y-2">{topology.links.map((link) => <div key={link.id} className="flex items-center justify-between gap-3 rounded border border-white/[.06] px-3 py-2"><div className="flex min-w-0 items-center gap-2 text-[10px]"><span className="truncate">{nodeById.get(link.source_node_id)?.name || "Node"}</span><Link2 size={12} className="shrink-0 text-cyan-300"/><span className="truncate">{nodeById.get(link.target_node_id)?.name || "Node"}</span></div><button onClick={() => void removeLink(link.id)} className="text-rose-300"><Unlink size={13}/></button></div>)}</div>}
        </div>
        <aside className="rounded-xl border border-white/[0.08] bg-[#0b1119] p-4">
          {selected ? <><div className="flex items-start justify-between"><div><p className="text-[9px] font-bold tracking-[.18em] text-cyan-300">NODE INSPECTOR</p><h3 className="mt-1 text-sm font-semibold">{selected.name}</h3><p className="mt-1 text-[10px] text-slate-500">{selected.device ? `${selected.device.host}:${selected.device.port}` : `Manual node · ${selected.kind}`}</p></div><button onClick={() => setSelected(null)}><X size={14}/></button></div>
            {selected.device ? <><div className="mt-3 rounded border border-white/[.07] p-3"><p className="text-[9px] text-slate-500">Reachability</p><p className="mt-1 text-sm font-semibold">{selected.device.reachability.toUpperCase()}</p><p className="mt-1 text-[9px] text-slate-500">Last checked: {selected.device.last_checked_at ? new Date(selected.device.last_checked_at).toLocaleString("id-ID") : "Belum pernah"}</p></div><button disabled={busy} onClick={() => void refreshDevice(selected)} className="mt-3 flex w-full items-center justify-center gap-2 rounded bg-cyan-500 px-3 py-2 text-[10px] font-semibold text-slate-950 disabled:opacity-50"><Activity size={12}/> Refresh via Agent</button></> : <p className="mt-3 text-[10px] text-slate-500">Node manual untuk merepresentasikan perangkat/komponen tambahan.</p>}
            <button onClick={() => void removeNode(selected)} className="mt-3 flex w-full items-center justify-center gap-2 rounded border border-rose-400/20 px-3 py-2 text-[10px] text-rose-300"><Trash2 size={12}/> Remove from canvas</button>
          </> : <div className="flex min-h-[140px] flex-col items-center justify-center text-center"><Activity size={22} className="mb-2 text-slate-600"/><p className="text-xs text-slate-300">Node inspector</p><p className="mt-1 text-[9px] text-slate-500">Klik node untuk melihat status dan detail.</p></div>}
        </aside>
      </section>

      <section className="rounded-xl border border-white/[.08] bg-[#0b1119] p-4"><div className="mb-3 flex items-center gap-2"><Server size={14} className="text-cyan-300"/><h3 className="text-xs font-semibold">Device inventory</h3></div><div className="grid gap-2 md:grid-cols-2 xl:grid-cols-3">{devices.map((d) => <div key={d.id} className="flex items-center justify-between gap-2 rounded border border-white/[.06] p-3"><div className="min-w-0"><p className="truncate text-[11px] font-medium">{d.name}</p><p className="truncate font-mono text-[9px] text-slate-500">{d.host}:{d.port} · {PLATFORM_LABELS[d.platform as DevicePlatform] || d.platform}</p></div><span className={`text-[8px] ${topology.nodes.some((n) => n.device_id === d.id) ? "text-emerald-300" : "text-slate-500"}`}>{topology.nodes.some((n) => n.device_id === d.id) ? "ON CANVAS" : "NOT PLACED"}</span></div>)}</div><button onClick={() => setShowDeviceForm(true)} className="mt-3 flex items-center gap-2 rounded border border-white/[.1] px-3 py-2 text-[10px] text-slate-300"><Plus size={12}/> Register device</button></section>
    </main>

    {showManual && <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4"><form onSubmit={addManualNode} className="w-full max-w-sm rounded-xl border border-white/[.12] bg-[#0c1119] p-5"><div className="mb-4 flex justify-between"><h3 className="text-sm font-semibold">Add manual node</h3><button type="button" onClick={() => setShowManual(false)}><X size={15}/></button></div><label className="mb-1 block text-[10px] text-slate-400">Node name</label><input autoFocus value={manualName} onChange={(e) => setManualName(e.target.value)} required className="mb-3 w-full rounded border border-white/[.1] bg-[#07090d] px-3 py-2 text-xs"/><label className="mb-1 block text-[10px] text-slate-400">Type</label><select value={manualKind} onChange={(e) => setManualKind(e.target.value)} className="mb-4 w-full rounded border border-white/[.1] bg-[#07090d] px-3 py-2 text-xs"><option value="router">Router</option><option value="switch">Switch</option><option value="server">Server</option><option value="firewall">Firewall</option><option value="access-point">Access Point</option><option value="other">Other</option></select><button disabled={busy} className="w-full rounded bg-cyan-500 px-3 py-2 text-xs font-semibold text-slate-950">Create node</button></form></div>}
    {showDeviceForm && <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4"><form onSubmit={registerDevice} className="w-full max-w-sm rounded-xl border border-white/[.12] bg-[#0c1119] p-5"><div className="mb-4 flex justify-between"><h3 className="text-sm font-semibold">Register network device</h3><button type="button" onClick={() => setShowDeviceForm(false)}><X size={15}/></button></div><label className="mb-1 block text-[10px] text-slate-400">Name</label><input required value={deviceForm.name} onChange={(e) => setDeviceForm((v) => ({ ...v, name: e.target.value }))} className="mb-3 w-full rounded border border-white/[.1] bg-[#07090d] px-3 py-2 text-xs"/><label className="mb-1 block text-[10px] text-slate-400">Platform</label><select value={deviceForm.platform} onChange={(e) => setDeviceForm((v) => ({ ...v, platform: e.target.value as DevicePlatform }))} className="mb-3 w-full rounded border border-white/[.1] bg-[#07090d] px-3 py-2 text-xs">{Object.entries(PLATFORM_LABELS).map(([k,v]) => <option key={k} value={k}>{v}</option>)}</select><label className="mb-1 block text-[10px] text-slate-400">Host / IP</label><input required value={deviceForm.host} onChange={(e) => setDeviceForm((v) => ({ ...v, host: e.target.value }))} className="mb-3 w-full rounded border border-white/[.1] bg-[#07090d] px-3 py-2 font-mono text-xs"/><div className="mb-4 grid grid-cols-2 gap-2"><input type="number" min="1" max="65535" required value={deviceForm.port} onChange={(e) => setDeviceForm((v) => ({ ...v, port: e.target.value }))} className="rounded border border-white/[.1] bg-[#07090d] px-3 py-2 text-xs"/><select value={deviceForm.connection_type} onChange={(e) => setDeviceForm((v) => ({ ...v, connection_type: e.target.value }))} className="rounded border border-white/[.1] bg-[#07090d] px-3 py-2 text-xs"><option value="api-ssl">API-SSL</option><option value="ssh">SSH</option><option value="winrm">WinRM</option></select></div><button disabled={busy} className="w-full rounded bg-cyan-500 px-3 py-2 text-xs font-semibold text-slate-950">Save device</button></form></div>}
  </div>;
}
