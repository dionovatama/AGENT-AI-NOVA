"use client";

import { useState } from "react";
import { Download, FileCode2, FileJson, FileText, ShieldAlert } from "lucide-react";
import { novaApi, NovaApiError, type MikrotikGeneratorRequest, type MikrotikGeneratedFile } from "@/lib/api";

const MODULES = [
  { id: "ip", label: "IP address", description: "Alamat IPv4 pada interface LAN" },
  { id: "dhcp", label: "DHCP Server", description: "Pool, network, DNS, dan DHCP server" },
  { id: "nat", label: "NAT masquerade", description: "NAT keluar melalui interface WAN" },
  { id: "firewall", label: "Firewall dasar", description: "Rule established/related, invalid, ICMP" },
] as const;

export function MikrotikConfigGenerator() {
  const [version, setVersion] = useState<"6" | "7">("7");
  const [modules, setModules] = useState<string[]>(["ip", "dhcp", "nat", "firewall"]);
  const [lan, setLan] = useState("bridge-lan");
  const [wan, setWan] = useState("ether1");
  const [cidr, setCidr] = useState("192.168.88.1/24");
  const [poolStart, setPoolStart] = useState("192.168.88.10");
  const [poolEnd, setPoolEnd] = useState("192.168.88.254");
  const [dns, setDns] = useState("1.1.1.1,8.8.8.8");
  const [files, setFiles] = useState<MikrotikGeneratedFile[]>([]);
  const [warnings, setWarnings] = useState<string[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [selectedFile, setSelectedFile] = useState(0);

  function toggleModule(id: string) {
    setModules((current) => current.includes(id) ? current.filter((item) => item !== id) : [...current, id]);
  }

  async function generate() {
    setBusy(true);
    setError(null);
    setFiles([]);
    try {
      const result = await novaApi.generateMikrotikConfig({
        routeros_version: version,
        modules: modules as MikrotikGeneratorRequest["modules"],
        lan_interface: lan,
        wan_interface: wan,
        ip_cidr: cidr,
        dhcp_pool_start: poolStart,
        dhcp_pool_end: poolEnd,
        dns_servers: dns,
      });
      setFiles(result.files);
      setWarnings(result.warnings);
      setSelectedFile(0);
    } catch (err) {
      setError(err instanceof NovaApiError ? err.message : "Gagal membuat file konfigurasi.");
    } finally {
      setBusy(false);
    }
  }

  function download(file: MikrotikGeneratedFile) {
    const blob = new Blob([file.content], { type: file.mime_type });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = file.filename;
    document.body.appendChild(anchor);
    anchor.click();
    anchor.remove();
    URL.revokeObjectURL(url);
  }

  const fileIcon = (name: string) => name.endsWith(".rsc") ? <FileCode2 size={14} /> : name.endsWith(".json") ? <FileJson size={14} /> : <FileText size={14} />;

  return (
    <section className="mb-6 overflow-hidden rounded-xl border border-base-700 bg-base-800/50">
      <div className="border-b border-base-700 px-4 py-4 sm:px-5">
        <div className="flex items-center gap-2">
          <FileCode2 size={17} className="text-signal-blue" />
          <h2 className="text-sm font-semibold text-ink-100">MikroTik Configuration Generator</h2>
          <span className="rounded border border-signal-blue/30 bg-signal-blue/10 px-2 py-0.5 text-[10px] uppercase tracking-wide text-signal-blue">Offline</span>
        </div>
        <p className="mt-1 text-xs leading-5 text-ink-500">Buat .rsc, .json, dan .txt untuk ditinjau, tanpa terhubung atau mengubah router.</p>
      </div>

      <div className="grid gap-5 p-4 sm:p-5 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
        <div className="space-y-4">
          <div>
            <label htmlFor="routeros-version" className="mb-1.5 block text-xs font-medium text-ink-300">Target RouterOS</label>
            <select id="routeros-version" value={version} onChange={(e) => setVersion(e.target.value as "6" | "7")} className="h-10 w-full rounded-md border border-base-700 bg-base-950 px-3 text-sm text-ink-100">
              <option value="6">RouterOS v6 template</option>
              <option value="7">RouterOS v7 template</option>
            </select>
          </div>

          <fieldset>
            <legend className="mb-2 text-xs font-medium text-ink-300">Modul konfigurasi</legend>
            <div className="grid gap-2 sm:grid-cols-2">
              {MODULES.map((item) => (
                <label key={item.id} className="flex cursor-pointer gap-2.5 rounded-md border border-base-700 bg-base-900/50 p-3">
                  <input type="checkbox" checked={modules.includes(item.id)} onChange={() => toggleModule(item.id)} className="mt-0.5 accent-blue-500" />
                  <span><span className="block text-xs font-medium text-ink-100">{item.label}</span><span className="mt-1 block text-[10px] leading-4 text-ink-500">{item.description}</span></span>
                </label>
              ))}
            </div>
          </fieldset>

          <div className="grid gap-3 sm:grid-cols-2">
            <div><label htmlFor="lan-interface" className="mb-1.5 block text-xs text-ink-300">Interface LAN</label><input id="lan-interface" value={lan} onChange={(e) => setLan(e.target.value)} maxLength={32} className="h-10 w-full rounded-md border border-base-700 bg-base-950 px-3 font-mono text-xs text-ink-100" /></div>
            <div><label htmlFor="wan-interface" className="mb-1.5 block text-xs text-ink-300">Interface WAN</label><input id="wan-interface" value={wan} onChange={(e) => setWan(e.target.value)} maxLength={32} className="h-10 w-full rounded-md border border-base-700 bg-base-950 px-3 font-mono text-xs text-ink-100" /></div>
            <div className="sm:col-span-2"><label htmlFor="ip-cidr" className="mb-1.5 block text-xs text-ink-300">IP gateway / subnet (CIDR)</label><input id="ip-cidr" value={cidr} onChange={(e) => setCidr(e.target.value)} maxLength={43} className="h-10 w-full rounded-md border border-base-700 bg-base-950 px-3 font-mono text-xs text-ink-100" /></div>
            {modules.includes("dhcp") && <>
              <div><label htmlFor="pool-start" className="mb-1.5 block text-xs text-ink-300">DHCP pool mulai</label><input id="pool-start" value={poolStart} onChange={(e) => setPoolStart(e.target.value)} className="h-10 w-full rounded-md border border-base-700 bg-base-950 px-3 font-mono text-xs text-ink-100" /></div>
              <div><label htmlFor="pool-end" className="mb-1.5 block text-xs text-ink-300">DHCP pool akhir</label><input id="pool-end" value={poolEnd} onChange={(e) => setPoolEnd(e.target.value)} className="h-10 w-full rounded-md border border-base-700 bg-base-950 px-3 font-mono text-xs text-ink-100" /></div>
              <div className="sm:col-span-2"><label htmlFor="dns-servers" className="mb-1.5 block text-xs text-ink-300">DNS IPv4 (pisahkan dengan koma)</label><input id="dns-servers" value={dns} onChange={(e) => setDns(e.target.value)} className="h-10 w-full rounded-md border border-base-700 bg-base-950 px-3 font-mono text-xs text-ink-100" /></div>
            </>}
          </div>
          {error && <p role="alert" className="rounded-md border border-signal-rose/30 bg-signal-rose/10 p-3 text-xs text-signal-rose">{error}</p>}
          <button type="button" disabled={busy || modules.length === 0} onClick={generate} className="h-10 w-full rounded-md bg-signal-blue px-4 text-xs font-semibold text-white transition hover:brightness-110 disabled:cursor-not-allowed disabled:opacity-50">{busy ? "Generating..." : "Generate & Preview"}</button>
          <p className="text-[10px] leading-4 text-ink-500">Mode: generate, preview, download saja. Tidak ada tombol apply atau eksekusi ke router.</p>
        </div>

        <div className="min-w-0">
          <div className="mb-2 flex items-center justify-between">
            <h3 className="text-xs font-semibold text-ink-200">Preview & output</h3>
            {files.length > 0 && <span className="font-mono text-[10px] text-ink-500">{files.length} files</span>}
          </div>
          {files.length === 0 ? (
            <div className="flex min-h-52 flex-col items-center justify-center rounded-lg border border-dashed border-base-700 px-5 text-center">
              <FileText size={22} className="mb-3 text-ink-500" />
              <p className="text-xs text-ink-400">Pilih modul lalu generate untuk melihat hasilnya.</p>
            </div>
          ) : (
            <>
              <div className="mb-2 flex flex-wrap gap-1.5">
                {files.map((file, index) => <button type="button" key={file.filename} onClick={() => setSelectedFile(index)} className={`flex items-center gap-1.5 rounded-md border px-2.5 py-2 text-[10px] ${selectedFile === index ? "border-signal-blue/50 bg-signal-blue/10 text-ink-100" : "border-base-700 text-ink-500"}`}>{fileIcon(file.filename)}{file.filename.split(".").pop()?.toUpperCase()}</button>)}
              </div>
              <div className="overflow-hidden rounded-lg border border-base-700 bg-base-950">
                <div className="flex items-center justify-between border-b border-base-700 px-3 py-2"><span className="truncate font-mono text-[10px] text-ink-400">{files[selectedFile]?.filename}</span><button type="button" onClick={() => download(files[selectedFile])} className="ml-2 flex shrink-0 items-center gap-1.5 rounded border border-base-700 px-2 py-1.5 text-[10px] text-ink-200 hover:bg-white/5"><Download size={12} /> Download</button></div>
                <pre className="max-h-[370px] overflow-auto p-3 text-[10px] leading-5 text-ink-300"><code>{files[selectedFile]?.content}</code></pre>
              </div>
              <div className="mt-3 space-y-2">
                {warnings.map((warning) => <p key={warning} className="flex gap-2 text-[10px] leading-4 text-ink-400"><ShieldAlert size={13} className="mt-0.5 shrink-0 text-amber-400" />{warning}</p>)}
              </div>
            </>
          )}
        </div>
      </div>
    </section>
  );
}
