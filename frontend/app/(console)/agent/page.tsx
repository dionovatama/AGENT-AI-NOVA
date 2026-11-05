"use client";

import { useState } from "react";
import {
  ArrowDownToLine, CheckCircle2, CircleHelp, Copy, ExternalLink,
  Laptop, Monitor, Package, Radio, ShieldCheck, Terminal, Wifi,
} from "lucide-react";

const WINDOWS_URL = process.env.NEXT_PUBLIC_NOVA_AGENT_WINDOWS_URL;
const LINUX_DEB_URL = process.env.NEXT_PUBLIC_NOVA_AGENT_LINUX_DEB_URL;
const LINUX_APPIMAGE_URL = process.env.NEXT_PUBLIC_NOVA_AGENT_LINUX_APPIMAGE_URL;
const RELEASES_URL = process.env.NEXT_PUBLIC_NOVA_AGENT_RELEASES_URL;

function DownloadOption({ title, detail, href, format }: {
  title: string; detail: string; href?: string; format: string;
}) {
  return (
    <div className="flex flex-col gap-3 rounded-xl border border-white/[0.08] bg-white/[0.025] p-4 sm:flex-row sm:items-center">
      <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl border border-white/[0.08] bg-white/[0.04] text-cyan-300">
        {format === "Windows" ? <Monitor size={21} /> : <Terminal size={21} />}
      </div>
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-2">
          <h3 className="text-sm font-semibold text-slate-100">{title}</h3>
          <span className="rounded-md border border-white/[0.08] px-1.5 py-0.5 text-[10px] text-slate-400">{format}</span>
        </div>
        <p className="mt-1 text-xs text-slate-500">{detail}</p>
      </div>
      {href ? (
        <a href={href} className="inline-flex h-9 shrink-0 items-center justify-center gap-2 rounded-lg bg-cyan-400 px-3 text-xs font-semibold text-slate-950 transition hover:bg-cyan-300">
          <ArrowDownToLine size={14} /> Download
        </a>
      ) : (
        <span className="inline-flex h-9 shrink-0 items-center justify-center gap-2 rounded-lg border border-white/[0.08] px-3 text-xs text-slate-500">
          <Package size={14} /> Coming soon
        </span>
      )}
    </div>
  );
}

export default function AgentPage() {
  const [copied, setCopied] = useState(false);
  const command = "nova-agent pair";
  async function copyCommand() {
    try {
      await navigator.clipboard.writeText(command);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1800);
    } catch { setCopied(false); }
  }

  return (
    <div className="mx-auto min-h-full w-full max-w-5xl space-y-7 pb-10 text-slate-100">
      <header className="space-y-2">
        <div className="flex items-center gap-2 text-xs font-medium uppercase tracking-[0.18em] text-cyan-300">
          <Radio size={14} /> Network connector
        </div>
        <h1 className="text-2xl font-semibold tracking-tight sm:text-3xl">NOVA Remote Agent</h1>
        <p className="max-w-2xl text-sm leading-6 text-slate-400">
          Connect your local network to NOVA securely. The desktop agent runs inside your network and
          provides an outbound connection to NOVA Cloud, so you do not need to expose router management ports to the internet.
        </p>
      </header>

      <section className="grid gap-3 sm:grid-cols-3">
        <div className="rounded-xl border border-white/[0.08] bg-white/[0.025] p-4">
          <Laptop className="mb-3 text-cyan-300" size={20} />
          <p className="text-sm font-medium">Desktop application</p>
          <p className="mt-1 text-xs leading-5 text-slate-500">Install on a Windows or Linux computer that can reach your network devices.</p>
        </div>
        <div className="rounded-xl border border-white/[0.08] bg-white/[0.025] p-4">
          <Wifi className="mb-3 text-cyan-300" size={20} />
          <p className="text-sm font-medium">Outbound connection</p>
          <p className="mt-1 text-xs leading-5 text-slate-500">The agent initiates its secure connection to NOVA Cloud.</p>
        </div>
        <div className="rounded-xl border border-white/[0.08] bg-white/[0.025] p-4">
          <ShieldCheck className="mb-3 text-cyan-300" size={20} />
          <p className="text-sm font-medium">Approval-based actions</p>
          <p className="mt-1 text-xs leading-5 text-slate-500">Network changes must be reviewed and approved before execution.</p>
        </div>
      </section>

      <section className="space-y-3">
        <div className="flex flex-wrap items-end justify-between gap-2">
          <div>
            <h2 className="text-base font-semibold">Download for your platform</h2>
            <p className="mt-1 text-xs text-slate-500">Installers will appear here when signed and published.</p>
          </div>
          {RELEASES_URL && <a className="inline-flex items-center gap-1 text-xs text-cyan-300 hover:text-cyan-200" href={RELEASES_URL} target="_blank" rel="noreferrer">All releases <ExternalLink size={12} /></a>}
        </div>
        <div className="space-y-2">
          <DownloadOption title="NOVA Remote Agent for Windows" detail="Windows 10 / 11 · x64 installer" format="Windows" href={WINDOWS_URL} />
          <DownloadOption title="NOVA Remote Agent for Debian / Ubuntu" detail="64-bit Debian package" format="Linux · .deb" href={LINUX_DEB_URL} />
          <DownloadOption title="NOVA Remote Agent for Linux Desktop" detail="Portable application image · x64" format="Linux · AppImage" href={LINUX_APPIMAGE_URL} />
        </div>
      </section>

      <section className="grid gap-4 lg:grid-cols-[1.1fr_0.9fr]">
        <div className="rounded-xl border border-white/[0.08] bg-white/[0.025] p-5">
          <div className="mb-3 flex items-center gap-2">
            <CheckCircle2 size={17} className="text-cyan-300" />
            <h2 className="text-sm font-semibold">Connect an installed agent</h2>
          </div>
          <p className="text-xs leading-5 text-slate-400">
            Agent pairing is not enabled yet. Once the pairing service is deployed, you will be able to
            link this computer to your NOVA account using a short-lived pairing code.
          </p>
          <div className="mt-4 flex items-center gap-2 rounded-lg border border-dashed border-white/[0.12] bg-black/20 p-3">
            <div className="min-w-0 flex-1">
              <p className="text-[10px] uppercase tracking-wider text-slate-500">Pairing status</p>
              <p className="mt-1 text-xs text-amber-300">Pairing service not configured</p>
            </div>
            <span className="rounded-md border border-amber-400/20 bg-amber-400/5 px-2 py-1 text-[10px] text-amber-300">Unavailable</span>
          </div>
        </div>
        <div className="rounded-xl border border-white/[0.08] bg-white/[0.025] p-5">
          <div className="mb-3 flex items-center gap-2">
            <CircleHelp size={17} className="text-cyan-300" />
            <h2 className="text-sm font-semibold">Before you install</h2>
          </div>
          <ul className="space-y-2 text-xs leading-5 text-slate-400">
            <li>• Install the agent on a trusted computer inside the target LAN.</li>
            <li>• Do not expose RouterOS API ports directly to the public internet.</li>
            <li>• Use a dedicated MikroTik account with minimum required permissions.</li>
            <li>• Keep agent tokens and router credentials private.</li>
          </ul>
          <button onClick={copyCommand} type="button" className="mt-4 inline-flex items-center gap-2 rounded-lg border border-white/[0.1] px-3 py-2 text-xs text-slate-300 hover:bg-white/[0.05]">
            <Copy size={13} /> {copied ? "Copied" : "Copy pairing command"}
          </button>
          <p className="mt-2 text-[10px] text-slate-600">Preview only — pairing command is not active until the agent CLI is released.</p>
        </div>
      </section>
      <p className="text-[11px] text-slate-600">NOVA Remote Agent · Download center preview. No installer or live agent connection is currently published.</p>
    </div>
  );
}
