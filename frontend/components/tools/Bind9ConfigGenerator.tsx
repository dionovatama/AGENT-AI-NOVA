"use client";

import { useState } from "react";
import { Download, FileCode2, ShieldAlert } from "lucide-react";
import { novaApi, NovaApiError, type Bind9Profile, type Bind9GeneratedFile, type Bind9Record } from "@/lib/api";

const profiles: { value: Bind9Profile; label: string; description: string }[] = [
  { value: "resolver", label: "DNS Resolver", description: "Recursive DNS, ACL, dan forwarders — LKPD 1." },
  { value: "master", label: "Authoritative Master", description: "Forward/reverse zone dan zone transfer — LKPD 2." },
  { value: "slave", label: "Authoritative Slave", description: "Secondary zone yang mengambil data dari Master." },
  { value: "master-slave", label: "Master + Slave", description: "Bundle konfigurasi untuk dua server." },
  { value: "custom", label: "Custom", description: "Bangun zone dan DNS records secara terstruktur." },
];

function download(file: Bind9GeneratedFile) {
  const url = URL.createObjectURL(new Blob([file.content], { type: file.mime_type }));
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = file.filename.replaceAll("/", "-");
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export function Bind9ConfigGenerator() {
  const [profile, setProfile] = useState<Bind9Profile>("resolver");
  const [domain, setDomain] = useState("dio-tkj.id");
  const [masterIp, setMasterIp] = useState("192.168.133.207");
  const [slaveIp, setSlaveIp] = useState("192.168.133.107");
  const [network, setNetwork] = useState("192.168.133.0/24");
  const [listen, setListen] = useState("127.0.0.1");
  const [acl, setAcl] = useState("192.168.1.0/24");
  const [forwarders, setForwarders] = useState("8.8.8.8, 8.8.4.4");
  const [primaryNs, setPrimaryNs] = useState("ns1");
  const [secondaryNs, setSecondaryNs] = useState("ns2");
  const [contact, setContact] = useState("hostmaster");
  const [zoneTarget, setZoneTarget] = useState<"named.conf.local" | "named.conf.default-zones">("named.conf.local");
  const [reverse, setReverse] = useState(true);
  const [records, setRecords] = useState<Bind9Record[]>([
    { record_type: "A", name: "@", value: "192.168.133.207" },
    { record_type: "CNAME", name: "www", value: "@" },
  ]);
  const [files, setFiles] = useState<Bind9GeneratedFile[]>([]);
  const [warnings, setWarnings] = useState<string[]>([]);
  const [selected, setSelected] = useState(0);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const resolver = profile === "resolver";
  const needsMaster = profile === "master" || profile === "slave" || profile === "master-slave" || profile === "custom";

  function updateRecord(index: number, patch: Partial<Bind9Record>) {
    setRecords(current => current.map((record, i) => i === index ? { ...record, ...patch } : record));
  }

  async function generate() {
    setBusy(true); setError(""); setFiles([]); setWarnings([]);
    try {
      const result = await novaApi.generateBind9Config({
        profile, domain, master_ip: masterIp, slave_ip: slaveIp, network_cidr: network,
        resolver_listen: listen, allow_recursion: acl.split(",").map(x => x.trim()).filter(Boolean),
        forwarders: forwarders.split(",").map(x => x.trim()).filter(Boolean),
        forward_first: true, ipv6_listen: "none", primary_ns: primaryNs, secondary_ns: secondaryNs,
        soa_contact: contact, records, include_reverse_zone: reverse, zone_config_target: zoneTarget,
      });
      setFiles(result.files); setWarnings(result.warnings); setSelected(0);
    } catch (caught) {
      setError(caught instanceof NovaApiError ? caught.message : "Gagal menghasilkan konfigurasi BIND9.");
    } finally { setBusy(false); }
  }

  const active = files[selected];

  return (
    <section className="overflow-hidden rounded-xl border border-base-700 bg-base-800/50">
      <header className="border-b border-base-700 px-4 py-4">
        <div className="flex items-center gap-2"><FileCode2 size={17} className="text-signal-blue"/><h2 className="text-sm font-semibold text-ink-100">BIND9 Configuration Generator</h2><span className="rounded border border-signal-blue/30 px-2 py-0.5 text-[10px] text-signal-blue">Preview only</span></div>
        <p className="mt-1 text-xs text-ink-500">Resolver, Authoritative Master/Slave, dan Custom DNS zone builder.</p>
      </header>
      <div className="grid gap-5 p-4 lg:grid-cols-2">
        <div className="space-y-4">
          <div><label className="mb-2 block text-xs text-ink-300">Configuration profile</label><div className="grid gap-2">
            {profiles.map(item => <button key={item.value} type="button" onClick={() => setProfile(item.value)} className={`rounded-md border p-3 text-left ${profile === item.value ? "border-signal-blue/50 bg-signal-blue/10" : "border-base-700"}`}><span className="block text-xs font-semibold text-ink-100">{item.label}</span><span className="mt-1 block text-[10px] text-ink-500">{item.description}</span></button>)}
          </div></div>
          {resolver ? <>
            <div><label className="mb-1 block text-xs text-ink-300">Listen IPv4</label><input value={listen} onChange={e=>setListen(e.target.value)} className="nova-bind-input"/></div>
            <div><label className="mb-1 block text-xs text-ink-300">Allow recursion (comma-separated IP/CIDR)</label><input value={acl} onChange={e=>setAcl(e.target.value)} className="nova-bind-input"/></div>
            <div><label className="mb-1 block text-xs text-ink-300">Forwarders (comma-separated)</label><input value={forwarders} onChange={e=>setForwarders(e.target.value)} className="nova-bind-input"/></div>
          </> : null}
          {needsMaster && <>
            <div><label className="mb-1 block text-xs text-ink-300">Domain</label><input value={domain} onChange={e=>setDomain(e.target.value)} className="nova-bind-input"/></div>
            <div className="grid grid-cols-2 gap-2"><div><label className="mb-1 block text-xs text-ink-300">Master IP</label><input value={masterIp} onChange={e=>setMasterIp(e.target.value)} className="nova-bind-input"/></div><div><label className="mb-1 block text-xs text-ink-300">Slave IP</label><input value={slaveIp} onChange={e=>setSlaveIp(e.target.value)} className="nova-bind-input"/></div></div>
            <div><label className="mb-1 block text-xs text-ink-300">Network CIDR (reverse zone)</label><input value={network} onChange={e=>setNetwork(e.target.value)} className="nova-bind-input"/></div>
            <div className="grid grid-cols-2 gap-2"><div><label className="mb-1 block text-xs text-ink-300">Primary NS label</label><input value={primaryNs} onChange={e=>setPrimaryNs(e.target.value)} className="nova-bind-input"/></div><div><label className="mb-1 block text-xs text-ink-300">Secondary NS label</label><input value={secondaryNs} onChange={e=>setSecondaryNs(e.target.value)} className="nova-bind-input"/></div></div>
            <div><label className="mb-1 block text-xs text-ink-300">SOA contact label</label><input value={contact} onChange={e=>setContact(e.target.value)} className="nova-bind-input"/></div>
            <label className="flex items-center gap-2 text-xs text-ink-300"><input type="checkbox" checked={reverse} onChange={e=>setReverse(e.target.checked)}/> Generate reverse zone</label>
            <div><label className="mb-1 block text-xs text-ink-300">Zone declarations file</label><select value={zoneTarget} onChange={e=>setZoneTarget(e.target.value as typeof zoneTarget)} className="nova-bind-input"><option value="named.conf.local">named.conf.local (Debian conventional)</option><option value="named.conf.default-zones">named.conf.default-zones (LKPD layout)</option></select></div>
          </>}
          {(profile === "master" || profile === "master-slave" || profile === "custom") && <div className="space-y-2">
            <div className="flex items-center justify-between"><label className="text-xs text-ink-300">DNS records</label><button type="button" onClick={()=>setRecords(current=>[...current,{record_type:"A",name:"host",value:masterIp}])} className="text-[11px] text-signal-blue">+ Add record</button></div>
            {records.map((record,index)=><div key={index} className="grid grid-cols-[85px_1fr_1fr_24px] gap-1">
              <select aria-label="Record type" value={record.record_type} onChange={e=>updateRecord(index,{record_type:e.target.value as Bind9Record["record_type"]})} className="nova-bind-input">{["A","AAAA","CNAME","MX","NS","PTR","TXT"].map(type=><option key={type}>{type}</option>)}</select>
              <input aria-label="Record name" value={record.name} onChange={e=>updateRecord(index,{name:e.target.value})} className="nova-bind-input" placeholder="name"/>
              <input aria-label="Record value" value={record.value} onChange={e=>updateRecord(index,{value:e.target.value})} className="nova-bind-input" placeholder="value"/>
              <button type="button" aria-label="Remove record" onClick={()=>setRecords(current=>current.filter((_,i)=>i!==index))} className="text-ink-500 hover:text-signal-rose">×</button>
            </div>)}
            <p className="text-[10px] text-ink-500">Untuk MX, isi target pada value dan priority melalui API (default 10). Record kosong akan ditolak backend.</p>
          </div>}
          {error && <p role="alert" className="rounded-md border border-signal-rose/30 p-3 text-xs text-signal-rose">{error}</p>}
          <button type="button" disabled={busy} onClick={generate} className="h-10 w-full rounded-md bg-signal-blue px-4 text-xs font-semibold text-white disabled:opacity-50">{busy ? "Generating..." : "Generate & Preview"}</button>
          <p className="text-[10px] text-ink-500">Tidak mengubah /etc/bind, tidak install paket, dan tidak me-restart layanan.</p>
        </div>
        <div className="min-w-0"><div className="mb-2 flex items-center justify-between"><h3 className="text-xs font-semibold text-ink-200">Generated files</h3>{files.length>0&&<span className="font-mono text-[10px] text-ink-500">{files.length} files</span>}</div>
          {files.length===0 ? <div className="flex min-h-52 items-center justify-center rounded-lg border border-dashed border-base-700 p-5 text-xs text-ink-400">Pilih profil dan generate untuk melihat file.</div> : <>
            <div className="mb-2 flex flex-wrap gap-1">{files.map((file,index)=><button type="button" key={file.filename} onClick={()=>setSelected(index)} className={`rounded-md border px-2 py-2 text-[10px] ${selected===index?"border-signal-blue/50 bg-signal-blue/10 text-ink-100":"border-base-700 text-ink-500"}`}>{file.filename}</button>)}</div>
            <div className="overflow-hidden rounded-lg border border-base-700"><div className="flex items-center justify-between border-b border-base-700 px-3 py-2"><span className="truncate font-mono text-[10px] text-ink-300">{active?.filename}</span>{active&&<button type="button" onClick={()=>download(active)} className="flex items-center gap-1 rounded border border-base-700 px-2 py-1 text-[10px] text-ink-200"><Download size={12}/> Download</button>}</div><pre className="max-h-[440px] overflow-auto bg-base-950 p-3 text-[11px] leading-5 text-ink-300"><code>{active?.content}</code></pre></div>
            {files.map(file=><button key={file.filename} type="button" onClick={()=>download(file)} className="mr-2 mt-2 text-[10px] text-signal-blue">Download {file.filename}</button>)}
            {warnings.map((warning,index)=><p key={index} className="mt-3 flex gap-2 text-[10px] leading-4 text-ink-400"><ShieldAlert size={13} className="shrink-0 text-signal-blue"/>{warning}</p>)}
          </>}
        </div>
      </div>
      <style jsx>{`.nova-bind-input{height:2.5rem;width:100%;min-width:0;border:1px solid rgb(55 65 81);border-radius:.375rem;background:rgb(3 7 18);padding:0 .65rem;color:rgb(229 231 235);font:11px ui-monospace,monospace}`}</style>
    </section>
  );
}
