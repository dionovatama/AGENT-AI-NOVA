"use client";

import { useEffect, useState } from "react";
import { HudLoader } from "@/components/HudLoader";
import { PlaceholderPanel } from "@/components/PlaceholderPanel";
import { novaApi, NovaApiError } from "@/lib/api";
import type { Credential, Device, DevicePlatform } from "@/lib/types";

const PLATFORMS: DevicePlatform[] = ["linux", "windows", "mikrotik", "cisco"];
const CREDENTIAL_TYPES = ["ssh_key", "password", "api_token"] as const;

export default function DevicesPage() {
  const [devices, setDevices] = useState<Device[] | null>(null);
  const [credentials, setCredentials] = useState<Credential[] | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);

  const [showDeviceForm, setShowDeviceForm] = useState(false);
  const [showCredentialForm, setShowCredentialForm] = useState(false);

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

  return (
    <div className="mx-auto max-w-4xl">
      <header className="mb-6">
        <h1 className="text-base font-medium text-ink-100">Devices</h1>
        <p className="mt-1 text-[13px] text-ink-500">
          Data asli dari <code className="font-mono text-ink-300">GET /devices</code> —
          tenant-isolated lewat JWT (owner_id), bukan preview lagi.
        </p>
      </header>

      {loadError && (
        <p className="mb-4 rounded-sm border border-signal-rose/30 bg-signal-rose/10 px-3 py-2 text-[13px] text-signal-rose">
          {loadError}
        </p>
      )}

      {/* --- Credentials --- */}
      <section className="mb-8">
        <div className="mb-2.5 flex items-center justify-between">
          <h2 className="text-[13px] text-ink-500">Credentials</h2>
          <button className="btn-secondary !px-2.5 !py-1 text-[12px]" onClick={() => setShowCredentialForm((v) => !v)}>
            {showCredentialForm ? "Batal" : "+ Credential"}
          </button>
        </div>

        {showCredentialForm && (
          <CredentialForm
            onCreated={() => {
              setShowCredentialForm(false);
              refresh();
            }}
          />
        )}

        <div className="panel overflow-hidden">
          {credentials === null && !loadError && (
            <div className="flex justify-center py-8">
              <HudLoader size={40} />
            </div>
          )}
          {credentials !== null && (
            <table className="w-full text-left text-[13px]">
              <thead>
                <tr className="text-ink-500">
                  <th className="px-4 py-2 font-normal">Name</th>
                  <th className="px-4 py-2 font-normal">Type</th>
                  <th className="px-4 py-2 font-normal">Dibuat</th>
                </tr>
              </thead>
              <tbody>
                {credentials.length === 0 && (
                  <tr>
                    <td colSpan={3} className="px-4 py-4 text-center text-ink-500">
                      Belum ada credential. Tambah dulu sebelum bikin device yang butuh auth.
                    </td>
                  </tr>
                )}
                {credentials.map((c) => (
                  <tr key={c.id} className="border-t border-base-700">
                    <td className="px-4 py-2 font-mono">{c.name}</td>
                    <td className="px-4 py-2">{c.type}</td>
                    <td className="px-4 py-2 text-ink-500">{new Date(c.created_at).toLocaleString("id-ID")}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </section>

      {/* --- Devices --- */}
      <section className="mb-8">
        <div className="mb-2.5 flex items-center justify-between">
          <h2 className="text-[13px] text-ink-500">Devices</h2>
          <button className="btn-secondary !px-2.5 !py-1 text-[12px]" onClick={() => setShowDeviceForm((v) => !v)}>
            {showDeviceForm ? "Batal" : "+ Device"}
          </button>
        </div>

        {showDeviceForm && (
          <DeviceForm
            credentials={credentials ?? []}
            onCreated={() => {
              setShowDeviceForm(false);
              refresh();
            }}
          />
        )}

        <div className="panel overflow-hidden">
          {devices === null && !loadError && (
            <div className="flex justify-center py-8">
              <HudLoader size={40} />
            </div>
          )}
          {devices !== null && (
            <table className="w-full text-left text-[13px]">
              <thead>
                <tr className="text-ink-500">
                  <th className="px-4 py-2 font-normal">Name</th>
                  <th className="px-4 py-2 font-normal">Platform</th>
                  <th className="px-4 py-2 font-normal">Host</th>
                  <th className="px-4 py-2 font-normal">Connection</th>
                  <th className="px-4 py-2 font-normal">Credential</th>
                  <th className="px-4 py-2 font-normal">Status</th>
                </tr>
              </thead>
              <tbody>
                {devices.length === 0 && (
                  <tr>
                    <td colSpan={6} className="px-4 py-4 text-center text-ink-500">
                      Belum ada device terdaftar.
                    </td>
                  </tr>
                )}
                {devices.map((d) => (
                  <tr key={d.id} className="border-t border-base-700">
                    <td className="px-4 py-2 font-mono">{d.name}</td>
                    <td className="px-4 py-2 uppercase text-ink-300">{d.platform}</td>
                    <td className="px-4 py-2 font-mono">
                      {d.host}:{d.port}
                    </td>
                    <td className="px-4 py-2">{d.connection_type}</td>
                    <td className="px-4 py-2 font-mono text-ink-500">{credentialName(d.credential_id)}</td>
                    <td className="px-4 py-2">
                      <span className="rounded-sm border border-signal-green/30 bg-signal-green/10 px-1.5 py-0.5 text-[11px] text-signal-green">
                        {d.status}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </section>

      <section>
        <h2 className="mb-2.5 text-[13px] text-ink-500">Menunggu implementasi</h2>
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          <PlaceholderPanel
            title="Protocol Execution"
            milestone="Phase 5–6"
            description="Device record di atas cuma data registry — belum ada satu pun tool yang benar-benar connect memakainya (RouterOS API-SSL untuk MikroTik, SSH/NETCONF untuk Cisco)."
            prdReference="PRD §17 MikroTik Engine, §18 Cisco Engine"
          />
        </div>
      </section>
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
            onChange={(e) => setPlatform(e.target.value as DevicePlatform)}
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
