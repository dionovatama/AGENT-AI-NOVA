"use client";

import { useEffect, useState } from "react";
import { novaApi } from "@/lib/api";
import type { MikrotikMonitoringHistoryPoint } from "@/lib/types";

const RANGES = [
  { label: "15m", minutes: 15 },
  { label: "1h", minutes: 60 },
  { label: "6h", minutes: 360 },
  { label: "24h", minutes: 1440 },
];

function Line({ values, stroke }: { values: Array<number | null>; stroke: string }) {
  const valid = values.filter((value): value is number => value !== null && Number.isFinite(value));
  if (valid.length < 2) return <svg viewBox="0 0 300 64" className="h-16 w-full"><text x="150" y="34" textAnchor="middle" fill="#64748b" fontSize="10">Belum cukup titik data</text></svg>;
  const min = Math.min(0, ...valid);
  const max = Math.max(1, ...valid);
  const points = values.map((value, index) => value === null ? null : {
    x: (index / Math.max(values.length - 1, 1)) * 296 + 2,
    y: 58 - ((value - min) / (max - min || 1)) * 52,
  }).filter((point): point is { x: number; y: number } => point !== null);
  return <svg viewBox="0 0 300 64" className="h-16 w-full" role="img" aria-label="Grafik metrik historis">
    <line x1="0" y1="58" x2="300" y2="58" stroke="#334155" strokeWidth="1" />
    <polyline points={points.map((point) => `${point.x},${point.y}`).join(" ")} fill="none" stroke={stroke} strokeWidth="2" strokeLinejoin="round" strokeLinecap="round" />
  </svg>;
}

function Metric({ title, suffix, values, stroke }: { title: string; suffix: string; values: Array<number | null>; stroke: string }) {
  const latest = [...values].reverse().find((value) => value !== null);
  return <div className="rounded border border-white/[.06] bg-white/[.015] p-2">
    <div className="flex items-center justify-between text-[9px]"><span className="text-slate-400">{title}</span><span className="font-mono text-slate-200">{latest === undefined ? "—" : `${latest.toLocaleString("id-ID")} ${suffix}`}</span></div>
    <Line values={values} stroke={stroke} />
  </div>;
}

export default function MikrotikHistoryChart({ deviceId, interfaces }: { deviceId: string; interfaces: string[] }) {
  const [minutes, setMinutes] = useState(60);
  const [iface, setIface] = useState("");
  const [points, setPoints] = useState<MikrotikMonitoringHistoryPoint[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setError(null);
    novaApi.getMikrotikMonitoringHistory(deviceId, minutes, iface || undefined, controller.signal)
      .then((response) => { setPoints(response.points); })
      .catch((cause) => {
        if (!controller.signal.aborted) setError(cause instanceof Error ? cause.message : "Gagal memuat riwayat.");
      })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [deviceId, minutes, iface]);

  const cpu = points.map((point) => point.cpu_load_percent);
  const memory = points.map((point) => point.memory_used_percent);
  const rx = points.map((point) => point.rx_bps);
  const tx = points.map((point) => point.tx_bps);

  return <section className="space-y-2 border-t border-white/[.07] pt-3">
    <div className="flex flex-wrap items-center justify-between gap-2"><p className="text-[9px] font-semibold uppercase tracking-wider text-cyan-300">Riwayat metrik</p>
      <div className="flex gap-1">{RANGES.map((range) => <button key={range.minutes} onClick={() => setMinutes(range.minutes)} className={`rounded border px-2 py-1 text-[9px] ${minutes === range.minutes ? "border-cyan-300/40 bg-cyan-300/10 text-cyan-100" : "border-white/[.08] text-slate-400"}`}>{range.label}</button>)}</div>
    </div>
    <label className="flex items-center gap-2 text-[9px] text-slate-400">Interface traffic
      <select value={iface} onChange={(event) => setIface(event.target.value)} className="min-w-0 flex-1 rounded border border-white/[.1] bg-[#07090d] px-2 py-1 text-slate-200">
        <option value="">Pilih interface…</option>{interfaces.map((name) => <option key={name} value={name}>{name}</option>)}
      </select>
    </label>
    {loading ? <p className="py-4 text-center text-[10px] text-slate-400">Memuat riwayat…</p> : error ? <p role="alert" className="rounded border border-rose-300/20 p-2 text-[9px] text-rose-200">{error}</p> : points.length === 0 ? <p className="py-4 text-center text-[10px] text-slate-500">Belum ada riwayat untuk rentang ini.</p> : <>
      <Metric title="CPU" suffix="%" values={cpu} stroke="#22d3ee" />
      <Metric title="Memory" suffix="%" values={memory} stroke="#a78bfa" />
      {iface && <div className="grid gap-2 sm:grid-cols-2"><Metric title={`${iface} RX`} suffix="bps" values={rx} stroke="#34d399" /><Metric title={`${iface} TX`} suffix="bps" values={tx} stroke="#fbbf24" /></div>}
      <p className="text-right text-[8px] text-slate-600">{points.length} titik · update dari histori tersimpan</p>
    </>}
  </section>;
}
