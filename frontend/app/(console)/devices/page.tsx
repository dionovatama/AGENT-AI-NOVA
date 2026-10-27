"use client";

import { useEffect, useState } from "react";
import { HudLoader } from "@/components/HudLoader";
import { novaApi, NovaApiError } from "@/lib/api";
import type { Credential, Device, DevicePlatform, ToolResult } from "@/lib/types";
import { Activity, KeyRound, Network, Plus, Router, Server, ShieldCheck, Trash2 } from "lucide-react";

const PLATFORMS: DevicePlatform[] = ["linux", "windows", "mikrotik", "cisco"];
const CREDENTIAL_TYPES = ["ssh_key", "password", "api_token"] as const;

export default function DevicesPage() {
  const [devices, setDevices] = useState<Device[] | null>(null);
  const [credentials, setCredentials] = useState<Credential[] | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);

  const [showDeviceForm, setShowDeviceForm] = useState(false);
  const [showCredentialForm, setShowCredentialForm] = useState(false);
  const [connectionTests, setConnectionTests] = useState<Record<string, { loading: boolean; result?: ToolResult; error?: string }>>({});
  const [deleteError, setDeleteError] = useState<string | null>(null);
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const [labUpdatingId, setLabUpdatingId] = useState<string | null>(null);

  async function markDeviceAsLab(device: Device) {
    const confirmed = window.confirm(
      `Tandai "${device.name}" (${device.host}) sebagai perangkat LAB? Lakukan hanya jika ini benar-benar CHR/VM terisolasi. Tindakan ini mengizinkan perangkat melewati lab guard, tetapi kill-switch backend dan approval tetap berlaku.`
    );
    if (!confirmed) return;
    setLabUpdatingId(device.id);
    setDeleteError(null);
    try {
      await novaApi.updateDevice(device.id, {
        metadata: { ...(device.metadata ?? {}), lab: true },
      });
      await refresh();
    } catch (err) {
      setDeleteError(err instanceof NovaApiError ? err.message : "Gagal memperbarui metadata perangkat.");
    } finally {
      setLabUpdatingId(null);
    }
  }

  async function handleDeleteDevice(device: Device) {
    const confirmed = window.confirm(
      `Hapus device "${device.name}" (${device.platform} — ${device.host}:${device.port})?\n\nTindakan ini tidak dapat dibatalkan. Device akan dihapus dari daftar N.O.V.A.`
    );
    if (!confirmed) return;
    setDeletingId(device.id);
    setDeleteError(null);
    try {
      await novaApi.deleteDevice(device.id);
      await refresh();
    } catch (err) {
      setDeleteError(err instanceof NovaApiError ? err.message : "Gagal menghapus device.");
    } finally {
      setDeletingId(null);
    }
  }

  async function handleDeleteCredential(credential: Credential) {
    const linkedDevices = (devices ?? []).filter((device) => device.credential_id === credential.id);
    const linkedWarning = linkedDevices.length
      ? `\n\nCredential ini dipakai oleh ${linkedDevices.length} device: ${linkedDevices.map((device) => device.name).join(", ")}. Penghapusan bisa membuat device tersebut kehilangan referensi autentikasi.`
      : "";
    const confirmed = window.confirm(
      `Hapus credential "${credential.name}" (${credential.type})?\n\nTindakan ini tidak dapat dibatalkan.${linkedWarning}`
    );
    if (!confirmed) return;
    setDeletingId(credential.id);
    setDeleteError(null);
    try {
      await novaApi.deleteCredential(credential.id);
      await refresh();
    } catch (err) {
      setDeleteError(err instanceof NovaApiError ? err.message : "Gagal menghapus credential.");
    } finally {
      setDeletingId(null);
    }
  }

  async function testConnection(device: Device) {
    setConnectionTests((current) => ({
      ...current,
      [device.id]: { loading: true },
    }));
    try {
      // Pakai tool READ yang sudah tervalidasi di backend untuk memeriksa koneksi API RouterOS.
      const result = await novaApi.executeTool("mikrotik.system_resource", {}, false, device.id);
      setConnectionTests((current) => ({
        ...current,
        [device.id]: { loading: false, result },
      }));
    } catch (err) {
      setConnectionTests((current) => ({
        ...current,
        [device.id]: {
          loading: false,
          error: err instanceof NovaApiError ? err.message : "Tes koneksi gagal.",
        },
      }));
    }
  }

  async function refresh() {
    try {
      const [d, c] = await Promise.all([novaApi.listDevices(), novaApi.listCredentials()]);
      setDevices(d);
      setCredentials(c);
    } catch (err) {
      setLoadError(err instanceof NovaApiError ? err.message : "Gagal memuat device/credential.");
    }
  }

  useEffect(() => {
    refresh();
  }, []);

  const credentialName = (id: string | null) =>
    id ? credentials?.find((c) => c.id === id)?.name ?? id.slice(0, 8) : "—";

  const activeCount = (devices ?? []).filter((device) => device.status.toLowerCase() === "active").length;

  return (
    <div className="mx-auto w-full max-w-6xl space-y-8">
      <header className="flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <div className="mb-2 flex items-center gap-2 text-[11px] uppercase tracking-[0.22em] text-ink-500">
            <span className="h-1.5 w-1.5 rounded-full bg-signal-green shadow-[0_0_10px_rgba(52,211,153,0.55)]" />
            Operator Console / Infrastructure
          </div>
          <h1 className="text-2xl font-semibold tracking-tight text-ink-100">Devices</h1>
          <p className="mt-1 max-w-2xl text-[13px] leading-6 text-ink-500">
            Kelola perangkat dan kredensial koneksi dalam satu tempat. Data dimuat dari API dengan isolasi tenant berbasis JWT.
          </p>
        </div>
        <button
          type="button"
          onClick={() => setShowDeviceForm((value) => !value)}
          className="inline-flex items-center justify-center gap-2 rounded-lg border border-accent-violet/40 bg-accent-violet/15 px-4 py-2.5 text-[13px] font-medium text-ink-100 transition hover:border-accent-violet/70 hover:bg-accent-violet/25"
        >
          <Plus size={16} />
          {showDeviceForm ? "Batal" : "Tambah Device"}
        </button>
      </header>

      {(loadError || deleteError) && (
        <div role="alert" className="rounded-xl border border-signal-rose/30 bg-signal-rose/10 px-4 py-3 text-[13px] text-signal-rose">
          {loadError || deleteError}
        </div>
      )}

      <section className="grid grid-cols-1 gap-3 sm:grid-cols-3">
        <div className="rounded-xl border border-base-700 bg-base-800/70 p-4">
          <div className="flex items-center justify-between">
            <span className="text-[12px] text-ink-500">Total Devices</span>
            <span className="rounded-lg bg-base-700 p-2 text-ink-300"><Server size={17} /></span>
          </div>
          <div className="mt-3 flex items-end gap-2">
            <span className="text-3xl font-semibold tracking-tight text-ink-100">{devices === null ? "—" : String(devices.length).padStart(2, "0")}</span>
            <span className="pb-1 text-[11px] text-ink-500">terdaftar</span>
          </div>
        </div>
        <div className="rounded-xl border border-base-700 bg-base-800/70 p-4">
          <div className="flex items-center justify-between">
            <span className="text-[12px] text-ink-500">Active Devices</span>
            <span className="rounded-lg border border-signal-green/20 bg-signal-green/10 p-2 text-signal-green"><Activity size={17} /></span>
          </div>
          <div className="mt-3 flex items-end gap-2">
            <span className="text-3xl font-semibold tracking-tight text-ink-100">{devices === null ? "—" : String(activeCount).padStart(2, "0")}</span>
            <span className="pb-1 text-[11px] text-ink-500">status tersimpan</span>
          </div>
        </div>
        <div className="rounded-xl border border-base-700 bg-base-800/70 p-4">
          <div className="flex items-center justify-between">
            <span className="text-[12px] text-ink-500">Credentials</span>
            <span className="rounded-lg bg-base-700 p-2 text-ink-300"><KeyRound size={17} /></span>
          </div>
          <div className="mt-3 flex items-end gap-2">
            <span className="text-3xl font-semibold tracking-tight text-ink-100">{credentials === null ? "—" : String(credentials.length).padStart(2, "0")}</span>
            <span className="pb-1 text-[11px] text-ink-500">referensi autentikasi</span>
          </div>
        </div>
      </section>

      {showDeviceForm && (
        <section>
          <div className="mb-3 flex items-center gap-2">
            <Plus size={16} className="text-accent-violet" />
            <h2 className="text-sm font-medium text-ink-100">Daftarkan Device</h2>
          </div>
          <DeviceForm
            credentials={credentials ?? []}
            onCreated={() => {
              setShowDeviceForm(false);
              refresh();
            }}
          />
        </section>
      )}

      <section className="space-y-4">
        <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
          <div>
            <h2 className="text-base font-semibold text-ink-100">Registered Devices</h2>
            <p className="mt-1 text-[12px] text-ink-500">Informasi perangkat, metode koneksi, dan pemeriksaan akses.</p>
          </div>
          <span className="w-fit rounded-full border border-base-700 bg-base-800 px-3 py-1 text-[11px] text-ink-400">
            {devices === null ? "Memuat…" : `${devices.length} device`}
          </span>
        </div>

        {devices === null && !loadError && (
          <div className="panel flex justify-center py-12"><HudLoader size={40} /></div>
        )}

        {devices !== null && devices.length === 0 && (
          <div className="rounded-xl border border-dashed border-base-700 bg-base-800/40 px-5 py-12 text-center">
            <div className="mx-auto mb-3 flex h-12 w-12 items-center justify-center rounded-xl bg-base-700 text-ink-400"><Server size={22} /></div>
            <h3 className="text-sm font-medium text-ink-100">Belum ada device</h3>
            <p className="mx-auto mt-1 max-w-sm text-[12px] leading-5 text-ink-500">Tambahkan perangkat untuk mulai mengelola koneksi dari N.O.V.A.</p>
            <button type="button" onClick={() => setShowDeviceForm(true)} className="mt-4 inline-flex items-center gap-2 rounded-lg border border-base-600 px-3 py-2 text-[12px] text-ink-200 transition hover:bg-base-700"><Plus size={14} /> Tambah Device</button>
          </div>
        )}

        {devices !== null && devices.length > 0 && (
          <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
            {devices.map((device) => {
              const test = connectionTests[device.id];
              const connected = Boolean(test?.result?.success);
              const platform = device.platform.toLowerCase();
              return (
                <article key={device.id} className="group overflow-hidden rounded-xl border border-base-700 bg-base-800/65 transition hover:border-base-600 hover:bg-base-800">
                  <div className="p-4 sm:p-5">
                    <div className="flex items-start gap-3">
                      <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl border border-base-600 bg-base-900 text-ink-200">
                        {platform === "mikrotik" ? <Router size={21} /> : platform === "cisco" ? <Network size={21} /> : <Server size={21} />}
                      </div>
                      <div className="min-w-0 flex-1">
                        <div className="flex flex-wrap items-center gap-2">
                          <h3 className="break-words text-sm font-semibold text-ink-100">{device.name}</h3>
                          <span className={`inline-flex items-center gap-1.5 rounded-full border px-2 py-0.5 text-[10px] ${device.status.toLowerCase() === "active" ? "border-signal-green/25 bg-signal-green/10 text-signal-green" : "border-signal-amber/25 bg-signal-amber/10 text-signal-amber"}`}>
                            <span className={`h-1.5 w-1.5 rounded-full ${device.status.toLowerCase() === "active" ? "bg-signal-green" : "bg-signal-amber"}`} />
                            {device.status}
                          </span>
                          {test?.result && (
                            <span className={`rounded-full border px-2 py-0.5 text-[10px] ${connected ? "border-signal-green/25 bg-signal-green/10 text-signal-green" : "border-signal-rose/25 bg-signal-rose/10 text-signal-rose"}`}>
                              {connected ? "Reachable" : "Test failed"}
                            </span>
                          )}
                        </div>
                        <p className="mt-1 text-[10px] uppercase tracking-[0.16em] text-ink-500">{device.platform} <span className="px-1 text-base-500">/</span> {device.connection_type}</p>
                      </div>
                    </div>

                    <div className="mt-5 grid grid-cols-1 gap-2 sm:grid-cols-2">
                      <div className="rounded-lg border border-base-700/80 bg-base-900/60 p-3">
                        <div className="mb-1 text-[10px] uppercase tracking-[0.12em] text-ink-500">Host / Port</div>
                        <div className="break-all font-mono text-[12px] text-ink-200">{device.host}:{device.port}</div>
                      </div>
                      <div className="rounded-lg border border-base-700/80 bg-base-900/60 p-3">
                        <div className="mb-1 text-[10px] uppercase tracking-[0.12em] text-ink-500">Credential</div>
                        <div className="flex min-w-0 items-center gap-2 text-[12px] text-ink-200">
                          <KeyRound size={13} className="shrink-0 text-ink-500" />
                          <span className="break-all">{credentialName(device.credential_id)}</span>
                        </div>
                      </div>
                    </div>

                    {test?.result?.success && (
                      <div className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-1 text-[11px] text-ink-400">
                        <span className="inline-flex items-center gap-1.5"><ShieldCheck size={13} className="text-signal-green" /> {String(test.result.output?.identity ?? device.name)}</span>
                        <span>{test.result.duration_ms.toFixed(1)} ms response</span>
                      </div>
                    )}
                    {test?.result && !test.result.success && (
                      <p role="alert" className="mt-3 break-words rounded-lg border border-signal-rose/25 bg-signal-rose/10 px-3 py-2 text-[11px] text-signal-rose">
                        {test.result.error ?? "Tool gagal dijalankan."}
                      </p>
                    )}
                    {test?.error && <p role="alert" className="mt-3 break-words text-[11px] text-signal-rose">{test.error}</p>}
                  </div>

                  <div className="flex flex-wrap items-center gap-2 border-t border-base-700 bg-base-900/40 px-4 py-3 sm:px-5">
                    {platform === "mikrotik" ? (
                      <button
                        type="button"
                        disabled={test?.loading}
                        onClick={() => testConnection(device)}
                        className="inline-flex items-center gap-2 rounded-lg border border-base-600 bg-base-800 px-3 py-2 text-[11px] font-medium text-ink-200 transition hover:border-accent-violet/50 hover:text-ink-100 disabled:cursor-not-allowed disabled:opacity-50"
                      >
                        <Activity size={14} />
                        {test?.loading ? "Menguji koneksi…" : "Test Connection"}
                      </button>
                    ) : (
                      <span className="inline-flex items-center gap-1.5 px-1 text-[11px] text-ink-500"><Activity size={13} /> Test connection belum tersedia</span>
                    )}
                    <div className="flex-1" />
                    {platform === "mikrotik" && device.metadata?.lab !== true && (
                      <button
                        type="button"
                        disabled={labUpdatingId === device.id}
                        onClick={() => markDeviceAsLab(device)}
                        className="inline-flex items-center gap-1.5 rounded-lg border border-signal-amber/30 px-3 py-2 text-[11px] text-signal-amber transition hover:bg-signal-amber/10 disabled:opacity-50"
                      >
                        <ShieldCheck size={13} />
                        {labUpdatingId === device.id ? "Menyimpan…" : "Tandai sebagai Lab"}
                      </button>
                    )}
                    {platform === "mikrotik" && device.metadata?.lab === true && (
                      <span className="inline-flex items-center gap-1.5 rounded-lg border border-signal-green/25 bg-signal-green/10 px-3 py-2 text-[11px] text-signal-green">
                        <ShieldCheck size={13} /> Lab terdaftar
                      </span>
                    )}
                    <button
                      type="button"
                      disabled={deletingId === device.id}
                      onClick={() => handleDeleteDevice(device)}
                      className="inline-flex items-center gap-1.5 rounded-lg border border-signal-rose/25 px-3 py-2 text-[11px] text-signal-rose transition hover:border-signal-rose/50 hover:bg-signal-rose/10 disabled:opacity-50"
                    >
                      <Trash2 size={13} />
                      {deletingId === device.id ? "Menghapus…" : "Hapus"}
                    </button>
                  </div>
                </article>
              );
            })}
          </div>
        )}
      </section>

      <section className="space-y-4 border-t border-base-700 pt-7">
        <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
          <div>
            <h2 className="text-base font-semibold text-ink-100">Credentials</h2>
            <p className="mt-1 text-[12px] text-ink-500">Referensi autentikasi yang dapat ditautkan ke perangkat.</p>
          </div>
          <button type="button" onClick={() => setShowCredentialForm((value) => !value)} className="inline-flex w-fit items-center gap-2 rounded-lg border border-base-600 bg-base-800 px-3 py-2 text-[12px] text-ink-200 transition hover:border-accent-violet/50 hover:bg-base-700">
            <Plus size={14} /> {showCredentialForm ? "Batal" : "Tambah Credential"}
          </button>
        </div>

        {showCredentialForm && (
          <CredentialForm onCreated={() => { setShowCredentialForm(false); refresh(); }} />
        )}

        {credentials === null && !loadError && <div className="panel flex justify-center py-8"><HudLoader size={32} /></div>}

        {credentials !== null && credentials.length === 0 && (
          <div className="rounded-xl border border-dashed border-base-700 px-4 py-8 text-center text-[12px] text-ink-500">
            Belum ada credential tersimpan.
          </div>
        )}

        {credentials !== null && credentials.length > 0 && (
          <div className="grid grid-cols-1 gap-3 lg:grid-cols-2">
            {credentials.map((credential) => {
              const linkedDevices = (devices ?? []).filter((device) => device.credential_id === credential.id);
              return (
                <article key={credential.id} className="flex min-w-0 items-start gap-3 rounded-xl border border-base-700 bg-base-800/50 p-4 transition hover:border-base-600">
                  <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-base-700 text-ink-300"><KeyRound size={18} /></div>
                  <div className="min-w-0 flex-1">
                    <h3 className="break-words text-[13px] font-medium text-ink-100">{credential.name}</h3>
                    <p className="mt-1 text-[11px] text-ink-500">{credential.type.replaceAll("_", " ")}</p>
                    <p className="mt-2 text-[10px] text-ink-500">Dibuat {new Date(credential.created_at).toLocaleString("id-ID")}</p>
                    <p className="mt-1 text-[10px] text-ink-500">{linkedDevices.length} device terhubung</p>
                  </div>
                  <button
                    type="button"
                    disabled={deletingId === credential.id}
                    onClick={() => handleDeleteCredential(credential)}
                    aria-label={`Hapus credential ${credential.name}`}
                    className="inline-flex shrink-0 items-center gap-1.5 rounded-lg border border-signal-rose/25 px-2.5 py-2 text-[10px] text-signal-rose transition hover:border-signal-rose/50 hover:bg-signal-rose/10 disabled:opacity-50"
                  >
                    <Trash2 size={12} />
                    {deletingId === credential.id ? "Menghapus…" : "Hapus"}
                  </button>
                </article>
              );
            })}
          </div>
        )}
      </section>

      <p className="flex items-start gap-2 border-t border-base-700 pt-4 text-[11px] leading-5 text-ink-500">
        <ShieldCheck size={14} className="mt-0.5 shrink-0" />
        Test Connection menjalankan pemeriksaan READ-only melalui <code className="font-mono text-ink-300">mikrotik.system_resource</code>; tindakan ini tidak mengubah konfigurasi router. Status Active menunjukkan status yang tersimpan, sedangkan Reachable berasal dari tes koneksi yang berhasil.
      </p>
    </div>
  );
}

function DeviceForm({
  credentials,
  onCreated,
}: {
  credentials: Credential[];
  onCreated: () => void;
}) {
  const [name, setName] = useState("");
  const [platform, setPlatform] = useState<DevicePlatform>("linux");
  const [host, setHost] = useState("");
  const [port, setPort] = useState(22);
  const [connectionType, setConnectionType] = useState("ssh");
  const [mikrotikUsername, setMikrotikUsername] = useState("");
  const [credentialId, setCredentialId] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setSaving(true);
    setError(null);
    try {
      await novaApi.createDevice({
        name,
        platform,
        host,
        port,
        connection_type: connectionType,
        credential_id: credentialId || null,
        ...(platform === "mikrotik" ? { metadata: { username: mikrotikUsername.trim() } } : {}),
      });
      onCreated();
    } catch (err) {
      setError(err instanceof NovaApiError ? err.message : "Gagal membuat device.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <form onSubmit={handleSubmit} className="panel mb-3 p-4">
      <div className="grid grid-cols-2 gap-3">
        <div>
          <label className="field-label">Name</label>
          <input required value={name} onChange={(e) => setName(e.target.value)} className="field-input" placeholder="Core-Router" />
        </div>
        <div>
          <label className="field-label">Platform</label>
          <select
            value={platform}
            onChange={(e) => {
              const nextPlatform = e.target.value as DevicePlatform;
              setPlatform(nextPlatform);
              if (nextPlatform === "mikrotik") {
                setConnectionType("api");
                setPort(8728);
              } else if (platform === "mikrotik") {
                setConnectionType("ssh");
                setPort(22);
              }
            }}
            className="field-input"
          >
            {PLATFORMS.map((p) => (
              <option key={p} value={p}>
                {p}
              </option>
            ))}
          </select>
        </div>
        <div>
          <label className="field-label">Host</label>
          <input required value={host} onChange={(e) => setHost(e.target.value)} className="field-input" placeholder="192.168.1.10" />
        </div>
        <div>
          <label className="field-label">Port</label>
          <input
            type="number"
            value={port}
            onChange={(e) => setPort(Number(e.target.value))}
            className="field-input"
            min={1}
            max={65535}
          />
        </div>
        {platform === "mikrotik" && (
          <div>
            <label className="field-label">MikroTik API Username</label>
            <input
              required
              value={mikrotikUsername}
              onChange={(e) => setMikrotikUsername(e.target.value)}
              className="field-input"
              placeholder="nova-agent"
              autoComplete="username"
            />
            <p className="mt-1 text-[11px] text-ink-500">Disimpan di metadata device; password tetap menggunakan credential yang dipilih.</p>
          </div>
        )}
        <div>
          <label className="field-label">Connection type</label>
          <input
            value={connectionType}
            onChange={(e) => setConnectionType(e.target.value)}
            className="field-input"
            placeholder="ssh / api-ssl / netconf"
          />
        </div>
        <div>
          <label className="field-label">Credential (opsional)</label>
          <select value={credentialId} onChange={(e) => setCredentialId(e.target.value)} className="field-input">
            <option value="">— tidak ada —</option>
            {credentials.map((c) => (
              <option key={c.id} value={c.id}>
                {c.name}
              </option>
            ))}
          </select>
        </div>
      </div>

      {error && <p className="mt-3 text-[13px] text-signal-rose">{error}</p>}

      <div className="mt-3 flex justify-end">
        <button type="submit" disabled={saving} className="btn-primary">
          {saving ? "Menyimpan…" : "Simpan Device"}
        </button>
      </div>
    </form>
  );
}

function CredentialForm({ onCreated }: { onCreated: () => void }) {
  const [name, setName] = useState("");
  const [type, setType] = useState<(typeof CREDENTIAL_TYPES)[number]>("ssh_key");
  const [secretReference, setSecretReference] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setSaving(true);
    setError(null);
    try {
      await novaApi.createCredential({ name, type, secret_reference: secretReference });
      onCreated();
    } catch (err) {
      setError(err instanceof NovaApiError ? err.message : "Gagal membuat credential.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <form onSubmit={handleSubmit} className="panel mb-3 p-4">
      <div className="grid grid-cols-3 gap-3">
        <div>
          <label className="field-label">Name</label>
          <input required value={name} onChange={(e) => setName(e.target.value)} className="field-input" placeholder="nova-lab-key" />
        </div>
        <div>
          <label className="field-label">Type</label>
          <select value={type} onChange={(e) => setType(e.target.value as typeof type)} className="field-input">
            {CREDENTIAL_TYPES.map((t) => (
              <option key={t} value={t}>
                {t}
              </option>
            ))}
          </select>
        </div>
        <div>
          <label className="field-label">Secret reference</label>
          <input
            required
            value={secretReference}
            onChange={(e) => setSecretReference(e.target.value)}
            className="field-input"
            placeholder="secrets/nova_backend_key"
          />
        </div>
      </div>
      <p className="mt-2 text-[11px] text-ink-500">
        Ini REFERENSI (mis. path file/vault key), bukan isi secret mentah — sesuai PRD §29,
        secret sebenarnya tidak pernah masuk field ini.
      </p>

      {error && <p className="mt-3 text-[13px] text-signal-rose">{error}</p>}

      <div className="mt-3 flex justify-end">
        <button type="submit" disabled={saving} className="btn-primary">
          {saving ? "Menyimpan…" : "Simpan Credential"}
        </button>
      </div>
    </form>
  );
}
