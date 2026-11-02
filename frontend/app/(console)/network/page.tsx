"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Activity, Cable, CircleHelp, Cloud, Cpu, Database, EthernetPort, Fit, Maximize2, Minus, Plus, Router, Save, Search, Server, Shield, Wifi, X } from "lucide-react";

type DeviceType = "router" | "switch" | "server" | "access-point" | "client" | "gateway";
type DeviceNode = { id: string; name: string; type: DeviceType; ip: string; vendor: string; x: number; y: number; status: "unknown" | "online" };
type LinkEdge = { id: string; source: string; target: string };
const STORAGE_KEY = "nova-network-topology-v1";
const INITIAL: DeviceNode[] = [
  { id: "gw-01", name: "Internet Gateway", type: "gateway", ip: "192.168.88.1", vendor: "Upstream", x: 470, y: 70, status: "unknown" },
  { id: "rtr-01", name: "Core Router", type: "router", ip: "192.168.88.1", vendor: "MikroTik", x: 470, y: 260, status: "unknown" },
  { id: "sw-01", name: "Core Switch", type: "switch", ip: "192.168.88.2", vendor: "Managed switch", x: 470, y: 465, status: "unknown" },
  { id: "srv-01", name: "NOVA Server", type: "server", ip: "192.168.88.10", vendor: "Linux", x: 170, y: 650, status: "unknown" },
  { id: "ap-01", name: "Access Point", type: "access-point", ip: "192.168.88.3", vendor: "Wireless", x: 470, y: 650, status: "unknown" },
  { id: "pc-01", name: "Admin Workstation", type: "client", ip: "192.168.88.20", vendor: "Endpoint", x: 770, y: 650, status: "unknown" },
];
const INITIAL_EDGES: LinkEdge[] = [
  { id: "e1", source: "gw-01", target: "rtr-01" }, { id: "e2", source: "rtr-01", target: "sw-01" },
  { id: "e3", source: "sw-01", target: "srv-01" }, { id: "e4", source: "sw-01", target: "ap-01" }, { id: "e5", source: "sw-01", target: "pc-01" },
];
const TYPES: { type: DeviceType; label: string; icon: typeof Router }[] = [
  { type: "router", label: "Router", icon: Router }, { type: "switch", label: "Switch", icon: Cable },
  { type: "server", label: "Server", icon: Server }, { type: "access-point", label: "Access Point", icon: Wifi },
  { type: "client", label: "Client", icon: Cpu }, { type: "gateway", label: "Gateway", icon: Cloud },
];
const iconFor = (type: DeviceType) => TYPES.find((item) => item.type === type)?.icon ?? CircleHelp;

export default function NetworkPage() {
  const [nodes, setNodes] = useState<DeviceNode[]>(INITIAL);
  const [edges, setEdges] = useState<LinkEdge[]>(INITIAL_EDGES);
  const [selected, setSelected] = useState<string | null>("rtr-01");
  const [saved, setSaved] = useState(true);
  const [adding, setAdding] = useState(false);
  const [name, setName] = useState("");
  const [ip, setIp] = useState("");
  const [type, setType] = useState<DeviceType>("router");
  const [zoom, setZoom] = useState(1);
  const [pan, setPan] = useState({ x: 0, y: 0 });
  const [connectMode, setConnectMode] = useState(false);
  const [connectFrom, setConnectFrom] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const canvasRef = useRef<HTMLDivElement>(null);
  const dragRef = useRef<{ id: string; dx: number; dy: number } | null>(null);
  const panRef = useRef<{ x: number; y: number; sx: number; sy: number } | null>(null);

  useEffect(() => {
    try {
      const raw = localStorage.getItem(STORAGE_KEY);
      if (raw) { const data = JSON.parse(raw); if (Array.isArray(data.nodes) && Array.isArray(data.edges)) { setNodes(data.nodes); setEdges(data.edges); } }
    } catch { /* corrupted local layout: keep safe defaults */ }
  }, []);
  const current = nodes.find((node) => node.id === selected) ?? null;
  const visibleNodes = useMemo(() => nodes.filter((node) => (node.name + node.ip + node.type).toLowerCase().includes(query.toLowerCase())), [nodes, query]);
  const save = useCallback(() => { localStorage.setItem(STORAGE_KEY, JSON.stringify({ nodes, edges })); setSaved(true); }, [nodes, edges]);
  const addNode = () => {
    if (!name.trim()) return;
    const id = `device-${Date.now()}`;
    setNodes((items) => [...items, { id, name: name.trim(), type, ip: ip.trim() || "Not assigned", vendor: "Manual", x: 470 + Math.round(Math.random() * 180 - 90), y: 180 + Math.round(Math.random() * 100), status: "unknown" }]);
    setSelected(id); setName(""); setIp(""); setAdding(false); setSaved(false);
  };
  const startDrag = (event: React.PointerEvent, node: DeviceNode) => {
    if (connectMode) {
      if (!connectFrom) setConnectFrom(node.id);
      else if (connectFrom !== node.id && !edges.some((edge) => (edge.source === connectFrom && edge.target === node.id) || (edge.source === node.id && edge.target === connectFrom))) {
        setEdges((items) => [...items, { id: `edge-${Date.now()}`, source: connectFrom, target: node.id }]); setSaved(false); setConnectFrom(null); setConnectMode(false);
      }
      return;
    }
    event.stopPropagation(); (event.currentTarget as HTMLElement).setPointerCapture(event.pointerId);
    const rect = canvasRef.current?.getBoundingClientRect(); if (!rect) return;
    dragRef.current = { id: node.id, dx: (event.clientX - rect.left - pan.x) / zoom - node.x, dy: (event.clientY - rect.top - pan.y) / zoom - node.y };
    setSelected(node.id);
  };
  const movePointer = (event: React.PointerEvent) => {
    if (dragRef.current) {
      const rect = canvasRef.current?.getBoundingClientRect(); if (!rect) return;
      const { id, dx, dy } = dragRef.current;
      setNodes((items) => items.map((node) => node.id === id ? { ...node, x: Math.max(20, (event.clientX - rect.left - pan.x) / zoom - dx), y: Math.max(20, (event.clientY - rect.top - pan.y) / zoom - dy) } : node)); setSaved(false);
    } else if (panRef.current) {
      setPan({ x: panRef.current.x + event.clientX - panRef.current.sx, y: panRef.current.y + event.clientY - panRef.current.sy });
    }
  };
  const endPointer = () => { dragRef.current = null; panRef.current = null; };
  const removeNode = (id: string) => { setNodes((items) => items.filter((node) => node.id !== id)); setEdges((items) => items.filter((edge) => edge.source !== id && edge.target !== id)); setSelected(null); setSaved(false); };
  const resetView = () => { setZoom(1); setPan({ x: 0, y: 0 }); };
  const nodeById = (id: string) => nodes.find((node) => node.id === id);
  return <div className="flex h-full min-h-0 flex-col bg-base-950 text-ink-100">
    <header className="flex flex-wrap items-center justify-between gap-3 border-b border-white/[0.07] px-5 py-4">
      <div><div className="flex items-center gap-2 text-xs uppercase tracking-[0.2em] text-signal-blue"><Activity size={14}/> Infrastructure</div><h1 className="mt-1 text-xl font-semibold">Network Management</h1><p className="mt-1 text-xs text-ink-500">Topology workspace <span className="mx-1">/</span> Local layout mode</p></div>
      <div className="flex flex-wrap items-center gap-2">
        <span className="mr-2 text-xs text-ink-500">{nodes.length} devices · {edges.length} links</span>
        <button onClick={() => setConnectMode((v) => !v)} className={`rounded-md border px-3 py-2 text-xs ${connectMode ? "border-signal-blue bg-signal-blue/15 text-signal-blue" : "border-base-600 text-ink-300 hover:bg-white/5"}`}><Cable size={14} className="mr-1 inline"/> {connectMode ? "Select two nodes…" : "Connect nodes"}</button>
        <button onClick={() => setAdding(true)} className="rounded-md bg-signal-teal px-3 py-2 text-xs font-medium text-white hover:bg-blue-500"><Plus size={14} className="mr-1 inline"/> Add device</button>
        <button onClick={save} className="rounded-md border border-base-600 px-3 py-2 text-xs text-ink-200 hover:bg-white/5"><Save size={14} className="mr-1 inline"/> Save layout</button>
      </div>
    </header>
    <div className="flex min-h-0 flex-1">
      <aside className="hidden w-60 shrink-0 flex-col border-r border-white/[0.07] bg-base-900/70 p-3 lg:flex">
        <div className="relative mb-3"><Search size={14} className="absolute left-3 top-2.5 text-ink-500"/><input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Find device…" className="w-full rounded-md border border-base-700 bg-base-950 py-2 pl-9 pr-3 text-xs outline-none focus:border-signal-blue"/></div>
        <div className="mb-2 flex items-center justify-between text-[10px] font-semibold uppercase tracking-widest text-ink-500"><span>Devices</span><span>{nodes.length}</span></div>
        <div className="min-h-0 flex-1 space-y-1 overflow-y-auto">{visibleNodes.map((node) => { const Icon = iconFor(node.type); return <button key={node.id} onClick={() => setSelected(node.id)} className={`flex w-full items-center gap-2 rounded-md px-2.5 py-2 text-left ${selected === node.id ? "bg-signal-blue/10 text-ink-100" : "text-ink-300 hover:bg-white/[0.04]"}`}><Icon size={15} className="text-signal-blue"/><span className="min-w-0 flex-1"><span className="block truncate text-xs">{node.name}</span><span className="block truncate text-[10px] text-ink-500">{node.ip}</span></span><span className="h-1.5 w-1.5 rounded-full bg-ink-500"/></button>; })}</div>
        <div className="mt-3 border-t border-white/[0.07] pt-3 text-[10px] leading-5 text-ink-500">Manual topology<br/>Discovery: not connected<br/>Monitoring: not connected</div>
      </aside>
      <section className="relative min-w-0 flex-1 overflow-hidden bg-[#080d16]" ref={canvasRef} onPointerMove={movePointer} onPointerUp={endPointer} onPointerLeave={endPointer} onPointerDown={(event) => { if (event.target === canvasRef.current) panRef.current = { ...pan, sx: event.clientX, sy: event.clientY }; }} onWheel={(event) => { if (event.ctrlKey || event.metaKey) { event.preventDefault(); setZoom((v) => Math.min(1.6, Math.max(.45, v - event.deltaY * .001))); } }} style={{ touchAction: "none" }}>
        <div className="pointer-events-none absolute inset-0 opacity-30" style={{ backgroundImage: "radial-gradient(#40536b 1px, transparent 1px)", backgroundSize: `${24 * zoom}px ${24 * zoom}px`, backgroundPosition: `${pan.x}px ${pan.y}px` }}/>
        <div className="absolute inset-0" style={{ transform: `translate(${pan.x}px,${pan.y}px) scale(${zoom})`, transformOrigin: "0 0" }}>
          <svg className="pointer-events-none absolute inset-0 h-[1200px] w-[1200px] overflow-visible">{edges.map((edge) => { const a = nodeById(edge.source), b = nodeById(edge.target); if (!a || !b) return null; return <g key={edge.id}><path d={`M ${a.x + 100} ${a.y + 43} C ${a.x + 100} ${(a.y + b.y) / 2}, ${b.x + 100} ${(a.y + b.y) / 2}, ${b.x + 100} ${b.y + 43}`} fill="none" stroke="#3b82f6" strokeOpacity=".55" strokeWidth="2"/><circle cx={b.x + 100} cy={b.y + 43} r="3" fill="#60a5fa"/></g>; })}</svg>
          {nodes.map((node) => { const Icon = iconFor(node.type); return <button key={node.id} onPointerDown={(event) => startDrag(event, node)} onClick={() => setSelected(node.id)} style={{ left: node.x, top: node.y }} className={`absolute flex h-[86px] w-[200px] flex-col justify-center rounded-lg border px-3 text-left shadow-xl transition-colors ${selected === node.id ? "border-signal-blue bg-[#14243a] shadow-[0_0_25px_rgba(59,130,246,.14)]" : "border-[#26364c] bg-[#101a2a] hover:border-[#45617e]"} ${connectMode && connectFrom === node.id ? "ring-2 ring-signal-blue" : ""}`}><span className="flex items-center gap-2"><span className="flex h-8 w-8 items-center justify-center rounded-md bg-signal-blue/10 text-signal-blue"><Icon size={17}/></span><span className="min-w-0 flex-1"><span className="block truncate text-xs font-semibold">{node.name}</span><span className="block text-[10px] text-ink-500">{node.type.replace("-", " ")}</span></span><span className="h-1.5 w-1.5 rounded-full bg-ink-500" title="Status unknown"/></span><span className="mt-2 truncate font-mono text-[10px] text-ink-500">{node.ip}</span></button>; })}
        </div>
        <div className="absolute bottom-4 left-4 flex items-center gap-1 rounded-md border border-white/10 bg-base-900/90 p-1 backdrop-blur"><button onClick={() => setZoom((v) => Math.min(1.6, v + .1))} className="rounded p-2 text-ink-300 hover:bg-white/10" title="Zoom in"><Plus size={14}/></button><span className="w-12 text-center font-mono text-[10px] text-ink-500">{Math.round(zoom * 100)}%</span><button onClick={() => setZoom((v) => Math.max(.45, v - .1))} className="rounded p-2 text-ink-300 hover:bg-white/10" title="Zoom out"><Minus size={14}/></button><button onClick={resetView} className="rounded p-2 text-ink-300 hover:bg-white/10" title="Fit view"><Maximize2 size={14}/></button></div>
        <div className="absolute bottom-4 right-4 rounded-md border border-white/10 bg-base-900/90 px-3 py-2 text-[10px] text-ink-500">Drag nodes · Ctrl + scroll to zoom · Drag empty canvas to pan</div>
        {connectMode && <div className="absolute left-1/2 top-4 -translate-x-1/2 rounded-md border border-signal-blue/30 bg-base-900 px-3 py-2 text-xs text-signal-blue">Choose source and target device to create a link</div>}
      </section>
      <aside className="hidden w-64 shrink-0 flex-col border-l border-white/[0.07] bg-base-900/70 p-4 xl:flex">
        <div className="mb-4 flex items-center justify-between"><h2 className="text-xs font-semibold uppercase tracking-widest text-ink-300">Inspector</h2>{current && <button onClick={() => setSelected(null)} className="text-ink-500 hover:text-white"><X size={14}/></button>}</div>
        {current ? <><div className="mb-4 flex items-center gap-3"><div className="flex h-10 w-10 items-center justify-center rounded-lg bg-signal-blue/10 text-signal-blue">{(() => { const Icon = iconFor(current.type); return <Icon size={20}/>; })()}</div><div className="min-w-0"><p className="truncate text-sm font-semibold">{current.name}</p><p className="text-[10px] capitalize text-ink-500">{current.type.replace("-", " ")}</p></div></div><div className="space-y-3 text-xs"><div><p className="mb-1 text-[10px] uppercase tracking-wider text-ink-500">Management IP</p><p className="font-mono text-ink-200">{current.ip}</p></div><div><p className="mb-1 text-[10px] uppercase tracking-wider text-ink-500">Vendor / Platform</p><p className="text-ink-200">{current.vendor}</p></div><div><p className="mb-1 text-[10px] uppercase tracking-wider text-ink-500">Connectivity</p><span className="rounded bg-white/[0.06] px-2 py-1 text-[10px] text-ink-500">Unknown · not monitored</span></div><div><p className="mb-1 text-[10px] uppercase tracking-wider text-ink-500">Node ID</p><p className="break-all font-mono text-[10px] text-ink-500">{current.id}</p></div></div><button onClick={() => removeNode(current.id)} className="mt-6 rounded-md border border-signal-rose/30 px-3 py-2 text-xs text-signal-rose hover:bg-signal-rose/10">Remove device</button></> : <p className="text-xs leading-5 text-ink-500">Select a device on the canvas to inspect its properties.</p>}
        <div className="mt-auto border-t border-white/[0.07] pt-3 text-[10px] text-ink-500">{saved ? "All changes saved locally" : "Unsaved layout changes"}</div>
      </aside>
    </div>
    {adding && <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4"><form onSubmit={(event) => { event.preventDefault(); addNode(); }} className="w-full max-w-md rounded-lg border border-base-600 bg-base-900 p-5 shadow-2xl"><div className="mb-4 flex items-center justify-between"><h2 className="text-sm font-semibold">Add network device</h2><button type="button" onClick={() => setAdding(false)} className="text-ink-500"><X size={16}/></button></div><label className="mb-1 block text-xs text-ink-300">Device name</label><input autoFocus value={name} onChange={(e) => setName(e.target.value)} required placeholder="e.g. Distribution Switch" className="mb-3 w-full rounded-md border border-base-600 bg-base-950 px-3 py-2 text-xs outline-none focus:border-signal-blue"/><label className="mb-1 block text-xs text-ink-300">Device type</label><select value={type} onChange={(e) => setType(e.target.value as DeviceType)} className="mb-3 w-full rounded-md border border-base-600 bg-base-950 px-3 py-2 text-xs">{TYPES.map((item) => <option key={item.type} value={item.type}>{item.label}</option>)}</select><label className="mb-1 block text-xs text-ink-300">Management IP (optional)</label><input value={ip} onChange={(e) => setIp(e.target.value)} placeholder="192.168.1.1" className="mb-5 w-full rounded-md border border-base-600 bg-base-950 px-3 py-2 font-mono text-xs outline-none focus:border-signal-blue"/><div className="flex justify-end gap-2"><button type="button" onClick={() => setAdding(false)} className="rounded-md border border-base-600 px-3 py-2 text-xs">Cancel</button><button type="submit" className="rounded-md bg-signal-teal px-3 py-2 text-xs font-medium text-white">Add device</button></div></form></div>}
  </div>;
}
