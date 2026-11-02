"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { novaApi } from "@/lib/api";
import {
  Activity, Cable, CircleHelp, Cloud, Cpu, Gauge, Globe2, MessageSquare, Send, Bot, Loader2,
  Maximize2, Minus, Plus, RadioTower, Router, Save, Search, Server,
  ShieldCheck, Wifi, X, Pencil, Trash2, Network, RefreshCw, PanelLeftClose, PanelLeftOpen, PanelRightClose, PanelRightOpen, Minimize2,
} from "lucide-react";

type DeviceType = "router" | "switch" | "server" | "access-point" | "client" | "gateway";
type DeviceNode = {
  id: string; name: string; type: DeviceType; ip: string; vendor: string;
  x: number; y: number; status: "unknown" | "online";
};
type LinkEdge = { id: string; source: string; target: string };
const STORAGE_KEY = "nova-network-topology-v1";
const INITIAL: DeviceNode[] = [
  { id: "gw-01", name: "Internet Gateway", type: "gateway", ip: "192.168.88.254", vendor: "Upstream", x: 500, y: 40, status: "unknown" },
  { id: "rtr-01", name: "CHR", type: "router", ip: "192.168.88.1", vendor: "MikroTik", x: 500, y: 235, status: "unknown" },
  { id: "sw-01", name: "Core Switch", type: "switch", ip: "192.168.88.2", vendor: "Managed switch", x: 500, y: 455, status: "unknown" },
  { id: "srv-01", name: "NOVA Server", type: "server", ip: "192.168.88.10", vendor: "Linux", x: 140, y: 650, status: "unknown" },
  { id: "ap-01", name: "Access Point", type: "access-point", ip: "192.168.88.3", vendor: "Wireless", x: 500, y: 650, status: "unknown" },
  { id: "pc-01", name: "Admin Workstation", type: "client", ip: "192.168.88.20", vendor: "Endpoint", x: 860, y: 650, status: "unknown" },
];
const INITIAL_EDGES: LinkEdge[] = [
  { id: "e1", source: "gw-01", target: "rtr-01" }, { id: "e2", source: "rtr-01", target: "sw-01" },
  { id: "e3", source: "sw-01", target: "srv-01" }, { id: "e4", source: "sw-01", target: "ap-01" }, { id: "e5", source: "sw-01", target: "pc-01" },
];
const TYPES: { type: DeviceType; label: string; icon: typeof Router }[] = [
  { type: "router", label: "Router", icon: Router }, { type: "switch", label: "Switch", icon: Cable },
  { type: "server", label: "Server", icon: Server }, { type: "access-point", label: "Access Point", icon: Wifi },
  { type: "client", label: "Endpoint", icon: Cpu }, { type: "gateway", label: "Gateway", icon: Globe2 },
];
const iconFor = (type: DeviceType) => TYPES.find((item) => item.type === type)?.icon ?? CircleHelp;

export default function NetworkPage() {
  const [nodes, setNodes] = useState<DeviceNode[]>(INITIAL);
  const [edges, setEdges] = useState<LinkEdge[]>(INITIAL_EDGES);
  const [selected, setSelected] = useState<string | null>("rtr-01");
  const [saved, setSaved] = useState(true);
  const [adding, setAdding] = useState(false);
  const [editing, setEditing] = useState(false);
  const [name, setName] = useState("");
  const [ip, setIp] = useState("");
  const [vendor, setVendor] = useState("");
  const [type, setType] = useState<DeviceType>("router");
  const [zoom, setZoom] = useState(1);
  const [pan, setPan] = useState({ x: 0, y: 0 });
  const [connectMode, setConnectMode] = useState(false);
  const [connectFrom, setConnectFrom] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [leftPanelOpen, setLeftPanelOpen] = useState(true);
  const [rightPanelOpen, setRightPanelOpen] = useState(true);
  const [isFullscreen, setIsFullscreen] = useState(false);
  const workspaceRef = useRef<HTMLDivElement>(null);
  const [copilotOpen, setCopilotOpen] = useState(false);
  const [copilotInput, setCopilotInput] = useState("");
  const [copilotBusy, setCopilotBusy] = useState(false);
  const [copilotMessages, setCopilotMessages] = useState<{ role: "user" | "assistant"; content: string }[]>([
    { role: "assistant", content: "NMS Copilot siap. Saya dapat menganalisis inventory dan koneksi pada topology lokal ini. Status perangkat dan telemetry live belum tersedia." },
  ]);
  const canvasRef = useRef<HTMLDivElement>(null);
  const dragRef = useRef<{ id: string; dx: number; dy: number } | null>(null);
  const panRef = useRef<{ x: number; y: number; sx: number; sy: number } | null>(null);

  useEffect(() => {
    try {
      const raw = localStorage.getItem(STORAGE_KEY);
      if (!raw) return;
      const data = JSON.parse(raw);
      if (Array.isArray(data.nodes) && Array.isArray(data.edges)) {
        setNodes(data.nodes); setEdges(data.edges);
      }
    } catch { /* Keep default topology if local data is invalid. */ }
  }, []);

  const current = nodes.find((node) => node.id === selected) ?? null;
  const visibleNodes = useMemo(
    () => nodes.filter((node) => (node.name + node.ip + node.type).toLowerCase().includes(query.toLowerCase())),
    [nodes, query],
  );
  const save = useCallback(() => {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify({ nodes, edges }));
      setSaved(true);
    } catch { setSaved(false); }
  }, [nodes, edges]);

  const openAdd = () => {
    setEditing(false); setName(""); setIp(""); setVendor(""); setType("router"); setAdding(true);
  };
  const openEdit = () => {
    if (!current) return;
    setEditing(true); setName(current.name); setIp(current.ip); setVendor(current.vendor); setType(current.type); setAdding(true);
  };
  const submitDevice = (event: React.FormEvent) => {
    event.preventDefault();
    if (!name.trim()) return;
    if (editing && current) {
      setNodes((items) => items.map((node) => node.id === current.id
        ? { ...node, name: name.trim(), ip: ip.trim() || "Not assigned", vendor: vendor.trim() || "Unspecified", type }
        : node));
    } else {
      const id = `device-${Date.now()}`;
      setNodes((items) => [...items, {
        id, name: name.trim(), type, ip: ip.trim() || "Not assigned",
        vendor: vendor.trim() || "Manual", x: 500 + Math.round(Math.random() * 220 - 110),
        y: 180 + Math.round(Math.random() * 130), status: "unknown",
      }]);
      setSelected(id);
    }
    setSaved(false); setAdding(false);
  };
  const startDrag = (event: React.PointerEvent, node: DeviceNode) => {
    if (connectMode) {
      if (!connectFrom) setConnectFrom(node.id);
      else if (connectFrom !== node.id && !edges.some((edge) =>
        (edge.source === connectFrom && edge.target === node.id) ||
        (edge.source === node.id && edge.target === connectFrom))) {
        setEdges((items) => [...items, { id: `edge-${Date.now()}`, source: connectFrom, target: node.id }]);
        setSaved(false); setConnectFrom(null); setConnectMode(false);
      }
      return;
    }
    event.stopPropagation();
    (event.currentTarget as HTMLElement).setPointerCapture(event.pointerId);
    const rect = canvasRef.current?.getBoundingClientRect();
    if (!rect) return;
    dragRef.current = {
      id: node.id,
      dx: (event.clientX - rect.left - pan.x) / zoom - node.x,
      dy: (event.clientY - rect.top - pan.y) / zoom - node.y,
    };
    setSelected(node.id);
  };
  const movePointer = (event: React.PointerEvent) => {
    if (dragRef.current) {
      const rect = canvasRef.current?.getBoundingClientRect();
      if (!rect) return;
      const { id, dx, dy } = dragRef.current;
      setNodes((items) => items.map((node) => node.id === id ? {
        ...node,
        x: Math.max(12, (event.clientX - rect.left - pan.x) / zoom - dx),
        y: Math.max(12, (event.clientY - rect.top - pan.y) / zoom - dy),
      } : node));
      setSaved(false);
    } else if (panRef.current) {
      setPan({ x: panRef.current.x + event.clientX - panRef.current.sx, y: panRef.current.y + event.clientY - panRef.current.sy });
    }
  };
  const endPointer = () => { dragRef.current = null; panRef.current = null; };
  const removeNode = (id: string) => {
    setNodes((items) => items.filter((node) => node.id !== id));
    setEdges((items) => items.filter((edge) => edge.source !== id && edge.target !== id));
    setSelected(null); setSaved(false);
  };
  const resetView = () => { setZoom(1); setPan({ x: 0, y: 0 }); };
  const nodeById = (id: string) => nodes.find((node) => node.id === id);
  const connectedCount = current ? edges.filter((edge) => edge.source === current.id || edge.target === current.id).length : 0;

  useEffect(() => {
    const syncFullscreen = () => setIsFullscreen(document.fullscreenElement === workspaceRef.current);
    document.addEventListener("fullscreenchange", syncFullscreen);
    return () => document.removeEventListener("fullscreenchange", syncFullscreen);
  }, []);

  const toggleFullscreen = async () => {
    try {
      if (document.fullscreenElement === workspaceRef.current) await document.exitFullscreen();
      else await workspaceRef.current?.requestFullscreen();
    } catch (error) {
      console.error("Unable to toggle Network workspace fullscreen:", error);
    }
  };

  const sendCopilotMessage = async (event: React.FormEvent) => {
    event.preventDefault();
    const prompt = copilotInput.trim();
    if (!prompt || copilotBusy) return;
    const topologyContext = {
      source: "local-manual-topology",
      telemetry_available: false,
      devices: nodes.map(({ id, name, type, ip, vendor, status }) => ({ id, name, type, ip, vendor, status })),
      links: edges.map(({ id, source, target }) => ({ id, source, target })),
      selected_device: current ? { id: current.id, name: current.name } : null,
    };
    const contextPrompt = `Anda adalah NMS Copilot di workspace Network Management NOVA.
Gunakan hanya fakta topology dalam JSON. Status semua perangkat tidak terverifikasi dan telemetry live tidak tersedia.
Bedakan fakta, dugaan, dan rekomendasi. Jangan mengklaim ping, CPU, traffic, routing, firewall, atau status perangkat telah diperiksa.
Anda hanya boleh memberi analisis dan instruksi perubahan topology; jangan mengklaim sudah mengubah canvas atau perangkat.
Jika permintaan mengubah topology, jelaskan perubahan yang disarankan dan minta konfirmasi. Jangan mengarang hasil eksekusi.
TOPOLOGY CONTEXT:
${JSON.stringify(topologyContext)}
USER REQUEST: ${prompt}`;
    setCopilotMessages((items) => [...items, { role: "user", content: prompt }]);
    setCopilotInput("");
    setCopilotBusy(true);
    try {
      const result = await novaApi.chatCompletion(contextPrompt, "troubleshooting", false);
      setCopilotMessages((items) => [...items, { role: "assistant", content: result.content }]);
    } catch (error) {
      setCopilotMessages((items) => [...items, { role: "assistant", content: `Permintaan gagal: ${error instanceof Error ? error.message : "Unknown error"}` }]);
    } finally {
      setCopilotBusy(false);
    }
  };

  return (
    <div ref={workspaceRef} className={`relative flex h-full min-h-0 flex-col bg-[#07090d] text-slate-100 ${isFullscreen ? "h-screen w-screen" : ""}`}>
      <header className="shrink-0 border-b border-white/[0.08] bg-[#0a0d13]">
        <div className="flex flex-wrap items-center justify-between gap-3 px-5 py-3">
          <div className="flex items-center gap-3">
            <div className="flex h-9 w-9 items-center justify-center rounded-lg border border-cyan-400/20 bg-cyan-400/[0.08] text-cyan-300"><Network size={18}/></div>
            <div><p className="text-[10px] font-semibold uppercase tracking-[0.22em] text-cyan-300">NOVA / Infrastructure</p><h1 className="text-base font-semibold tracking-wide">Network Management</h1></div>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <button type="button" onClick={() => setLeftPanelOpen((value) => !value)} title={leftPanelOpen ? "Hide inventory panel" : "Show inventory panel"} className="flex items-center gap-1.5 rounded-md border border-white/[0.09] px-2.5 py-2 text-[11px] text-slate-300 hover:bg-white/[0.05]">{leftPanelOpen ? <PanelLeftClose size={14}/> : <PanelLeftOpen size={14}/>} <span className="hidden sm:inline">Inventory</span></button>
            <button type="button" onClick={() => setRightPanelOpen((value) => !value)} title={rightPanelOpen ? "Hide inspector panel" : "Show inspector panel"} className="flex items-center gap-1.5 rounded-md border border-white/[0.09] px-2.5 py-2 text-[11px] text-slate-300 hover:bg-white/[0.05]">{rightPanelOpen ? <PanelRightClose size={14}/> : <PanelRightOpen size={14}/>} <span className="hidden sm:inline">Inspector</span></button>
            <button type="button" onClick={toggleFullscreen} title={isFullscreen ? "Exit fullscreen" : "Enter fullscreen"} className="flex items-center gap-1.5 rounded-md border border-cyan-300/20 bg-cyan-300/[0.06] px-2.5 py-2 text-[11px] text-cyan-100 hover:bg-cyan-300/[0.12]">{isFullscreen ? <Minimize2 size={14}/> : <Maximize2 size={14}/>} <span className="hidden sm:inline">{isFullscreen ? "Exit Focus" : "Focus Mode"}</span></button>
            <span className="mr-1 flex items-center gap-1.5 rounded-md border border-white/[0.08] bg-white/[0.03] px-2.5 py-2 text-[11px] text-slate-400"><span className="h-1.5 w-1.5 rounded-full bg-amber-400" />Local inventory</span>
            <button type="button" title="Discovery belum terhubung ke backend" className="flex items-center gap-1.5 rounded-md border border-white/[0.09] px-3 py-2 text-[11px] text-slate-400"><RefreshCw size={13}/> Auto Discover <span className="text-[9px] text-amber-300">SOON</span></button>
            <button type="button" onClick={() => setConnectMode((value) => !value)} className={`flex items-center gap-1.5 rounded-md border px-3 py-2 text-[11px] transition ${connectMode ? "border-cyan-300/50 bg-cyan-300/10 text-cyan-200" : "border-white/[0.09] text-slate-300 hover:bg-white/[0.05]"}`}><Cable size={13}/>{connectMode ? "Select devices…" : "Wiring"}</button>
            <button type="button" onClick={openAdd} className="flex items-center gap-1.5 rounded-md bg-gradient-to-r from-cyan-500 to-blue-600 px-3 py-2 text-[11px] font-semibold text-white shadow-[0_0_18px_rgba(6,182,212,.15)]"><Plus size={14}/> Node</button>
            <button type="button" onClick={save} className="flex items-center gap-1.5 rounded-md border border-white/[0.1] px-3 py-2 text-[11px] text-slate-300 hover:bg-white/[0.05]"><Save size={13}/> Save</button>
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-x-5 gap-y-2 border-t border-white/[0.06] px-5 py-2 text-[10px]">
          <span className="text-slate-500">INVENTORY SCOPE</span>
          <span className="rounded-full bg-cyan-400/10 px-2.5 py-1 font-medium text-cyan-200">Manual topology</span>
          <span className="text-slate-400">All devices <b className="ml-1 text-slate-200">{nodes.length}</b></span>
          <span className="text-slate-400">Owned <b className="ml-1 text-emerald-300">{nodes.length}</b></span>
          <span className="text-slate-400">Links <b className="ml-1 text-slate-200">{edges.length}</b></span>
          <span className="text-slate-400">Interfaces <b className="ml-1 text-slate-200">—</b></span>
          <span className="ml-auto flex items-center gap-1.5 text-amber-300"><ShieldCheck size={12}/> Discovery & live telemetry not connected</span>
        </div>
      </header>

      <div className="flex min-h-0 flex-1">
        {leftPanelOpen && <aside className="w-[218px] shrink-0 flex-col border-r border-white/[0.07] bg-[#0a0d13] p-3 hidden lg:flex">
          <div className="relative mb-4"><Search size={13} className="absolute left-3 top-2.5 text-slate-500"/><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search inventory…" className="w-full rounded-md border border-white/[0.09] bg-[#07090d] py-2 pl-8 pr-3 text-[11px] outline-none placeholder:text-slate-600 focus:border-cyan-400/50"/></div>
          <div className="mb-2 flex items-center justify-between text-[9px] font-semibold uppercase tracking-[0.18em] text-slate-500"><span>Inventory</span><span>{visibleNodes.length}/{nodes.length}</span></div>
          <div className="min-h-0 flex-1 space-y-1 overflow-y-auto">
            {visibleNodes.map((node) => { const Icon = iconFor(node.type); return <button key={node.id} type="button" onClick={() => setSelected(node.id)} className={`flex w-full items-center gap-2 rounded-md border px-2 py-2 text-left transition ${selected === node.id ? "border-cyan-400/20 bg-cyan-400/[0.08]" : "border-transparent hover:bg-white/[0.04]"}`}><Icon size={14} className="shrink-0 text-cyan-300"/><span className="min-w-0 flex-1"><span className="block truncate text-[11px] text-slate-200">{node.name}</span><span className="block truncate font-mono text-[9px] text-slate-500">{node.ip}</span></span><span className="h-1.5 w-1.5 rounded-full bg-slate-600" title="Status unknown"/></button>; })}
            {visibleNodes.length === 0 && <p className="px-2 py-4 text-[10px] text-slate-500">No matching devices.</p>}
          </div>
          <div className="mt-3 border-t border-white/[0.07] pt-3"><p className="mb-2 text-[9px] font-semibold uppercase tracking-[0.18em] text-slate-500">Legend</p><div className="space-y-2 text-[10px] text-slate-400"><div className="flex items-center gap-2"><span className="h-1.5 w-1.5 rounded-full bg-emerald-400"/> Online (not verified)</div><div className="flex items-center gap-2"><span className="h-1.5 w-1.5 rounded-full bg-slate-500"/> Unknown status</div><div className="flex items-center gap-2"><span className="h-px w-5 bg-cyan-400"/> Manual link</div></div></div>
        </aside>}

        <main className="relative min-w-0 flex-1 overflow-hidden bg-[#070b11]" ref={canvasRef}
          onPointerMove={movePointer} onPointerUp={endPointer} onPointerLeave={endPointer}
          onPointerDown={(event) => { if (!(event.target as HTMLElement).closest("button")) panRef.current = { ...pan, sx: event.clientX, sy: event.clientY }; }}
          onWheel={(event) => { if (event.ctrlKey || event.metaKey) { event.preventDefault(); setZoom((value) => Math.min(1.65, Math.max(.4, value - event.deltaY * .001))); } }}
          style={{ touchAction: "none" }}>
          <div className="pointer-events-none absolute inset-0 opacity-35" style={{ backgroundImage: "radial-gradient(#334155 1px, transparent 1px)", backgroundSize: `${25 * zoom}px ${25 * zoom}px`, backgroundPosition: `${pan.x}px ${pan.y}px` }}/>
          <div className="absolute inset-0" style={{ transform: `translate(${pan.x}px,${pan.y}px) scale(${zoom})`, transformOrigin: "0 0" }}>
            <svg className="pointer-events-none absolute left-0 top-0 h-[1200px] w-[1400px] overflow-visible">
              {edges.map((edge) => { const a = nodeById(edge.source), b = nodeById(edge.target); if (!a || !b) return null; const x1 = a.x + 105, y1 = a.y + 48, x2 = b.x + 105, y2 = b.y + 48, mid = (y1 + y2) / 2; return <g key={edge.id}><path d={`M ${x1} ${y1} C ${x1} ${mid}, ${x2} ${mid}, ${x2} ${y2}`} fill="none" stroke="#164e63" strokeWidth="7" strokeOpacity=".18"/><path d={`M ${x1} ${y1} C ${x1} ${mid}, ${x2} ${mid}, ${x2} ${y2}`} fill="none" stroke="#22d3ee" strokeWidth="1.5" strokeOpacity=".65"/><circle cx={x2} cy={y2} r="3" fill="#67e8f9"/></g>; })}
            </svg>
            {nodes.map((node) => { const Icon = iconFor(node.type); const active = selected === node.id; return <button key={node.id} type="button" onPointerDown={(event) => startDrag(event, node)} onClick={() => setSelected(node.id)} style={{ left: node.x, top: node.y }} className={`absolute flex h-[96px] w-[210px] flex-col justify-center rounded-xl border px-3.5 text-left transition-colors ${active ? "border-cyan-300/80 bg-[#101f2b] shadow-[0_0_0_1px_rgba(34,211,238,.12),0_0_28px_rgba(34,211,238,.16)]" : "border-[#263746] bg-[#0d151e] shadow-[0_12px_28px_rgba(0,0,0,.25)] hover:border-cyan-400/40"} ${connectMode && connectFrom === node.id ? "ring-2 ring-cyan-300" : ""}`}><span className="mb-2 flex items-center justify-between"><span className="rounded-sm border border-emerald-400/20 bg-emerald-400/[0.08] px-1.5 py-0.5 text-[8px] font-semibold uppercase tracking-wider text-emerald-300">Manual</span><span className="flex items-center gap-1.5 text-[8px] text-slate-500">{node.vendor}<span className="h-1.5 w-1.5 rounded-full bg-slate-500"/></span></span><span className="flex items-center gap-2.5"><span className={`flex h-9 w-9 items-center justify-center rounded-lg border ${active ? "border-cyan-300/20 bg-cyan-300/10 text-cyan-200" : "border-white/[0.07] bg-white/[0.04] text-slate-300"}`}><Icon size={18}/></span><span className="min-w-0 flex-1"><span className="block truncate text-[12px] font-semibold text-slate-100">{node.name}</span><span className="mt-0.5 block text-[9px] capitalize text-slate-500">{node.type.replace("-", " ")}</span></span></span><span className="mt-2 truncate font-mono text-[9px] text-slate-400">{node.ip}</span></button>; })}
          </div>

          <div className="absolute left-4 top-4 flex items-center gap-2 rounded-md border border-white/[0.08] bg-[#0b1119]/90 px-3 py-2 backdrop-blur"><span className="h-1.5 w-1.5 rounded-full bg-cyan-300"/><span className="text-[10px] font-medium text-slate-300">TOPOLOGY CANVAS</span><span className="text-[9px] text-slate-600">/ LOCAL</span></div>
          <div className="absolute bottom-4 left-4 flex items-center gap-1 rounded-lg border border-white/[0.09] bg-[#0b1119]/95 p-1 backdrop-blur"><button type="button" onClick={() => setZoom((value) => Math.min(1.65, value + .1))} className="rounded p-2 text-slate-300 hover:bg-white/10" title="Zoom in"><Plus size={13}/></button><span className="w-11 text-center font-mono text-[9px] text-slate-500">{Math.round(zoom * 100)}%</span><button type="button" onClick={() => setZoom((value) => Math.max(.4, value - .1))} className="rounded p-2 text-slate-300 hover:bg-white/10" title="Zoom out"><Minus size={13}/></button><button type="button" onClick={resetView} className="rounded p-2 text-slate-300 hover:bg-white/10" title="Reset view"><Maximize2 size={13}/></button></div>
          <div className="absolute bottom-4 right-4 hidden rounded-md border border-white/[0.08] bg-[#0b1119]/90 px-3 py-2 text-[9px] text-slate-500 sm:block">Drag nodes · Ctrl + scroll to zoom · Drag canvas to pan</div>
          {connectMode && <div className="absolute left-1/2 top-4 -translate-x-1/2 rounded-md border border-cyan-300/30 bg-[#0b1119] px-3 py-2 text-[10px] text-cyan-200 shadow-lg">{connectFrom ? "Select target device" : "Select source device"} · click a node</div>}
        </main>

        {rightPanelOpen && <aside className="hidden w-[286px] shrink-0 flex-col overflow-y-auto border-l border-white/[0.07] bg-[#0a0d13] p-4 xl:flex">
          <div className="mb-4 flex items-center justify-between"><div><p className="text-[9px] font-semibold uppercase tracking-[0.2em] text-cyan-300">Selected resource</p><h2 className="mt-1 text-xs font-semibold text-slate-200">Device Inspector</h2></div><button type="button" onClick={() => setSelected(null)} className="rounded p-1 text-slate-500 hover:bg-white/[0.06] hover:text-white"><X size={14}/></button></div>
          {current ? <>
            <div className="mb-4 rounded-lg border border-white/[0.08] bg-white/[0.025] p-3"><div className="flex items-center gap-2.5"><div className="flex h-10 w-10 items-center justify-center rounded-lg border border-cyan-300/20 bg-cyan-300/[0.08] text-cyan-200">{(() => { const Icon = iconFor(current.type); return <Icon size={20}/>; })()}</div><div className="min-w-0"><h3 className="truncate text-sm font-semibold">{current.name}</h3><p className="text-[9px] capitalize text-slate-500">{current.type.replace("-", " ")} · {current.vendor}</p></div></div><div className="mt-3 flex items-center justify-between border-t border-white/[0.07] pt-2"><span className="text-[9px] text-slate-500">Inventory status</span><span className="rounded bg-slate-500/10 px-2 py-1 text-[9px] text-slate-400">UNKNOWN</span></div></div>
            <section className="mb-3"><h4 className="mb-2 flex items-center gap-2 text-[9px] font-semibold uppercase tracking-[0.16em] text-slate-500"><Gauge size={12}/> Management</h4><div className="space-y-2 rounded-lg border border-white/[0.07] p-3"><div className="flex justify-between gap-2 text-[10px]"><span className="text-slate-500">Management IP</span><span className="font-mono text-slate-200">{current.ip}</span></div><div className="flex justify-between gap-2 text-[10px]"><span className="text-slate-500">Vendor / Platform</span><span className="text-slate-200">{current.vendor}</span></div><div className="flex justify-between gap-2 text-[10px]"><span className="text-slate-500">Node ID</span><span className="max-w-[130px] truncate font-mono text-slate-400">{current.id}</span></div></div></section>
            <section className="mb-3"><h4 className="mb-2 flex items-center gap-2 text-[9px] font-semibold uppercase tracking-[0.16em] text-slate-500"><Activity size={12}/> NMS Live Telemetry & Traffic</h4><div className="rounded-lg border border-amber-400/15 bg-amber-400/[0.035] p-3"><p className="text-[10px] font-medium text-amber-200">Waiting for integration</p><p className="mt-1 text-[9px] leading-4 text-slate-500">CPU, memory, interface traffic, ICMP latency, and freshness data are not available in local topology mode.</p></div></section>
            <section className="mb-3"><h4 className="mb-2 text-[9px] font-semibold uppercase tracking-[0.16em] text-slate-500">Connectivity</h4><div className="grid grid-cols-2 gap-2"><div className="rounded-lg border border-white/[0.07] p-2.5"><p className="text-[9px] text-slate-500">Linked nodes</p><p className="mt-1 text-lg font-semibold text-slate-200">{connectedCount}</p></div><div className="rounded-lg border border-white/[0.07] p-2.5"><p className="text-[9px] text-slate-500">ICMP latency</p><p className="mt-1 text-sm font-semibold text-slate-500">— ms</p></div></div></section>
            <div className="mt-auto flex gap-2 border-t border-white/[0.07] pt-3"><button type="button" onClick={openEdit} className="flex flex-1 items-center justify-center gap-1.5 rounded-md border border-white/[0.1] py-2 text-[10px] text-slate-300 hover:bg-white/[0.05]"><Pencil size={12}/> Edit</button><button type="button" onClick={() => removeNode(current.id)} className="flex items-center justify-center gap-1.5 rounded-md border border-rose-400/20 px-3 py-2 text-[10px] text-rose-300 hover:bg-rose-400/[0.08]"><Trash2 size={12}/> Remove</button></div>
          </> : <div className="rounded-lg border border-dashed border-white/[0.1] p-4 text-center"><RadioTower size={20} className="mx-auto mb-2 text-slate-600"/><p className="text-[10px] text-slate-500">Select a node on the canvas to inspect its properties.</p></div>}
          <div className="mt-4 flex items-center justify-between border-t border-white/[0.07] pt-3 text-[9px]"><span className="text-slate-500">{saved ? "Layout saved locally" : "Unsaved changes"}</span><span className={saved ? "text-emerald-300" : "text-amber-300"}>{saved ? "SAVED" : "MODIFIED"}</span></div>
        </aside>}
      </div>


      <button type="button" onClick={() => setCopilotOpen((value) => !value)} aria-label={copilotOpen ? "Close NMS Copilot" : "Open NMS Copilot"} className="fixed bottom-6 right-6 z-[60] flex h-12 items-center gap-2 rounded-full border border-cyan-300/30 bg-[#10202c] px-4 text-xs font-semibold text-cyan-100 shadow-2xl hover:bg-[#163044]">
        {copilotOpen ? <X size={16}/> : <Bot size={17}/>} {copilotOpen ? "Close Copilot" : "NMS Copilot"}
      </button>
      {copilotOpen && <section className="fixed bottom-20 right-6 z-[60] flex h-[min(620px,calc(100vh-120px))] w-[min(420px,calc(100vw-32px))] flex-col overflow-hidden rounded-xl border border-cyan-300/20 bg-[#0a111a] shadow-2xl shadow-black/60">
        <header className="flex items-center justify-between border-b border-white/[0.08] px-4 py-3">
          <div className="flex items-center gap-2"><span className="flex h-8 w-8 items-center justify-center rounded-lg border border-cyan-300/20 bg-cyan-300/10 text-cyan-200"><Bot size={17}/></span><div><p className="text-xs font-semibold text-slate-100">NMS Copilot</p><p className="text-[9px] text-slate-500">Workspace-aware · Local topology</p></div></div>
          <button type="button" onClick={() => setCopilotMessages([{ role: "assistant", content: "Percakapan dibersihkan. Konteks topology terbaru akan digunakan." }])} className="rounded-md border border-white/10 px-2 py-1 text-[10px] text-slate-400 hover:bg-white/5">Clear chat</button>
        </header>
        <div className="flex items-center gap-2 border-b border-amber-300/10 bg-amber-300/[0.04] px-4 py-2 text-[9px] text-amber-200"><ShieldCheck size={12}/> Inventory lokal saja — live discovery & telemetry belum aktif</div>
        <div className="min-h-0 flex-1 space-y-3 overflow-y-auto p-3">
          {copilotMessages.map((message, index) => <div key={index} className={`max-w-[92%] whitespace-pre-wrap rounded-lg px-3 py-2.5 text-[11px] leading-5 ${message.role === "user" ? "ml-auto border border-cyan-300/15 bg-cyan-300/[0.08] text-cyan-50" : "border border-white/[0.07] bg-white/[0.035] text-slate-300"}`}>{message.content}</div>)}
          {copilotBusy && <div className="flex items-center gap-2 px-2 text-[10px] text-cyan-200"><Loader2 size={13} className="animate-spin"/> Menganalisis topology…</div>}
        </div>
        <div className="border-t border-white/[0.08] p-3">
          <div className="mb-2 flex flex-wrap gap-1.5">{["Ringkas topology", "Perangkat belum terhubung", "Analisis jalur server ke gateway"].map((suggestion) => <button key={suggestion} type="button" onClick={() => setCopilotInput(suggestion)} className="rounded-full border border-white/[0.09] px-2 py-1 text-[9px] text-slate-400 hover:border-cyan-300/30 hover:text-cyan-100">{suggestion}</button>)}</div>
          <form onSubmit={sendCopilotMessage} className="flex items-end gap-2"><textarea value={copilotInput} onChange={(event) => setCopilotInput(event.target.value)} onKeyDown={(event) => { if (event.key === "Enter" && !event.shiftKey) { event.preventDefault(); (event.currentTarget.form as HTMLFormElement)?.requestSubmit(); } }} rows={2} placeholder="Tanyakan kondisi topology…" className="min-h-[42px] flex-1 resize-none rounded-lg border border-white/10 bg-[#070b11] px-3 py-2 text-[11px] text-slate-100 outline-none placeholder:text-slate-600 focus:border-cyan-300/40"/>
            <button type="submit" disabled={copilotBusy || !copilotInput.trim()} className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-cyan-500 text-slate-950 disabled:opacity-40"><Send size={15}/></button></form>
        </div>
      </section>}

      {adding && <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/75 p-4 backdrop-blur-sm"><form onSubmit={submitDevice} className="w-full max-w-md rounded-xl border border-white/[0.12] bg-[#0c1119] p-5 shadow-2xl"><div className="mb-4 flex items-center justify-between"><div><p className="text-[9px] uppercase tracking-[0.2em] text-cyan-300">Inventory</p><h2 className="mt-1 text-sm font-semibold">{editing ? "Edit device" : "Add network device"}</h2></div><button type="button" onClick={() => setAdding(false)} className="rounded p-1 text-slate-500 hover:bg-white/[0.06]"><X size={16}/></button></div><label className="mb-1 block text-[10px] text-slate-400">Device name</label><input autoFocus value={name} onChange={(event) => setName(event.target.value)} required placeholder="e.g. Distribution Switch" className="mb-3 w-full rounded-md border border-white/[0.1] bg-[#07090d] px-3 py-2.5 text-xs outline-none focus:border-cyan-400/50"/><label className="mb-1 block text-[10px] text-slate-400">Device type</label><select value={type} onChange={(event) => setType(event.target.value as DeviceType)} className="mb-3 w-full rounded-md border border-white/[0.1] bg-[#07090d] px-3 py-2.5 text-xs">{TYPES.map((item) => <option key={item.type} value={item.type}>{item.label}</option>)}</select><label className="mb-1 block text-[10px] text-slate-400">Management IP</label><input value={ip} onChange={(event) => setIp(event.target.value)} placeholder="192.168.1.1" className="mb-3 w-full rounded-md border border-white/[0.1] bg-[#07090d] px-3 py-2.5 font-mono text-xs outline-none focus:border-cyan-400/50"/><label className="mb-1 block text-[10px] text-slate-400">Vendor / Platform</label><input value={vendor} onChange={(event) => setVendor(event.target.value)} placeholder="MikroTik, Linux, Cisco…" className="mb-5 w-full rounded-md border border-white/[0.1] bg-[#07090d] px-3 py-2.5 text-xs outline-none focus:border-cyan-400/50"/><div className="flex justify-end gap-2"><button type="button" onClick={() => setAdding(false)} className="rounded-md border border-white/[0.1] px-3 py-2 text-[11px] text-slate-300">Cancel</button><button type="submit" className="rounded-md bg-cyan-500 px-4 py-2 text-[11px] font-semibold text-slate-950">{editing ? "Save changes" : "Add device"}</button></div></form></div>}
    </div>
  );
}
