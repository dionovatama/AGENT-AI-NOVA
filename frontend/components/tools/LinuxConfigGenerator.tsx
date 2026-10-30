"use client";

import { useState } from "react";
import { Download, FileCode2, FileText, ShieldAlert } from "lucide-react";
import { novaApi, NovaApiError } from "@/lib/api";

type OutputFile = { filename: string; mime_type: string; content: string };
type Module = "packages" | "ssh" | "firewall";

const availableModules: { id: Module; label: string }[] = [
  { id: "packages", label: "Paket dasar" },
  { id: "ssh", label: "SSH server" },
  { id: "firewall", label: "Firewall UFW" },
];

export function LinuxConfigGenerator() {
  const [distro, setDistro] = useState<"debian" | "ubuntu">("debian");
  const [modules, setModules] = useState<Module[]>(["packages", "ssh"]);
  const [hostname, setHostname] = useState("nova-server");
  const [sshPort, setSshPort] = useState("22");
  const [files, setFiles] = useState<OutputFile[]>([]);
  const [warnings, setWarnings] = useState<string[]>([]);
  const [selected, setSelected] = useState(0);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const toggle = (value: Module) => {
    setModules((current) =>
      current.includes(value)
        ? current.filter((item) => item !== value)
        : [...current, value],
    );
  };

  async function generate() {
    const parsedPort = Number(sshPort);
    if (modules.includes("ssh") && (!Number.isInteger(parsedPort) || parsedPort < 1 || parsedPort > 65535)) {
      setError("Port SSH harus berupa bilangan bulat antara 1 dan 65535.");
      return;
    }
    if (!hostname.trim()) {
      setError("Hostname wajib diisi.");
      return;
    }

    setBusy(true);
    setError("");
    setFiles([]);
    setWarnings([]);

    try {
      const result = await novaApi.generateLinuxConfig({
        distro,
        modules,
        hostname: hostname.trim(),
        ssh_port: parsedPort,
        dns_listen_address: "127.0.0.1",
        dns_forwarders: "1.1.1.1; 8.8.8.8",
        firewall_ssh: modules.includes("firewall") && modules.includes("ssh"),
      });
      setFiles(result.files);
      setWarnings(result.warnings);
      setSelected(0);
    } catch (caught) {
      setError(
        caught instanceof NovaApiError
          ? caught.message
          : "Gagal membuat konfigurasi Linux.",
      );
    } finally {
      setBusy(false);
    }
  }

  function download(file: OutputFile) {
    const url = URL.createObjectURL(
      new Blob([file.content], { type: file.mime_type }),
    );
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = file.filename;
    document.body.appendChild(anchor);
    anchor.click();
    anchor.remove();
    // Give the browser time to start the download before releasing the object URL.
    window.setTimeout(() => URL.revokeObjectURL(url), 1000);
  }

  const activeFile = files[Math.min(selected, Math.max(files.length - 1, 0))];

  return (
    <section className="overflow-hidden rounded-xl border border-base-700 bg-base-800/50">
      <div className="border-b border-base-700 px-4 py-4">
        <div className="flex items-center gap-2">
          <FileCode2 size={17} className="text-signal-blue" />
          <h2 className="text-sm font-semibold text-ink-100">Linux Configuration Generator</h2>
          <span className="rounded border border-signal-blue/30 px-2 py-0.5 text-[10px] text-signal-blue">Offline</span>
        </div>
        <p className="mt-1 text-xs text-ink-500">
          Script .sh dan file konfigurasi native Debian/Ubuntu. Tidak ada remote execution.
        </p>
      </div>

      <div className="grid gap-5 p-4 lg:grid-cols-2">
        <div className="space-y-4">
          <div>
            <label className="mb-1 block text-xs text-ink-300">Distro</label>
            <select
              value={distro}
              onChange={(event) => setDistro(event.target.value as "debian" | "ubuntu")}
              className="h-10 w-full rounded-md border border-base-700 bg-base-950 px-3 text-sm text-ink-100"
            >
              <option value="debian">Debian</option>
              <option value="ubuntu">Ubuntu</option>
            </select>
          </div>

          <fieldset>
            <legend className="mb-2 text-xs text-ink-300">Komponen</legend>
            <div className="grid gap-2 sm:grid-cols-2">
              {availableModules.map((module) => (
                <label
                  key={module.id}
                  className="flex items-center gap-2 rounded-md border border-base-700 p-3 text-xs text-ink-200"
                >
                  <input
                    type="checkbox"
                    checked={modules.includes(module.id)}
                    onChange={() => toggle(module.id)}
                    className="accent-blue-500"
                  />
                  {module.label}
                </label>
              ))}
            </div>
          </fieldset>

          <div>
            <label className="mb-1 block text-xs text-ink-300">Hostname</label>
            <input
              value={hostname}
              onChange={(event) => setHostname(event.target.value)}
              maxLength={253}
              autoComplete="off"
              className="h-10 w-full rounded-md border border-base-700 bg-base-950 px-3 font-mono text-xs text-ink-100"
            />
            <p className="mt-1 text-[10px] text-ink-500">
              Contoh: nova-server atau lab.nova-server. Validasi akhir dilakukan backend.
            </p>
          </div>

          {modules.includes("ssh") && (
            <div>
              <label className="mb-1 block text-xs text-ink-300">SSH port</label>
              <input
                type="number"
                min={1}
                max={65535}
                step={1}
                value={sshPort}
                onChange={(event) => setSshPort(event.target.value)}
                className="h-10 w-full rounded-md border border-base-700 bg-base-950 px-3 font-mono text-xs text-ink-100"
              />
            </div>
          )}

          {error && (
            <p role="alert" className="rounded-md border border-signal-rose/30 p-3 text-xs text-signal-rose">
              {error}
            </p>
          )}

          <button
            type="button"
            disabled={busy || modules.length === 0}
            onClick={generate}
            className="h-10 w-full rounded-md bg-signal-blue px-4 text-xs font-semibold text-white disabled:opacity-50"
          >
            {busy ? "Generating..." : "Generate & Preview"}
          </button>
          <p className="text-[10px] text-ink-500">
            Preview hanya membuat bundle lokal untuk ditinjau; tidak mengubah sistem.
          </p>
        </div>

        <div className="min-w-0">
          <div className="mb-2 flex items-center justify-between">
            <h3 className="text-xs font-semibold text-ink-200">Preview & output</h3>
            {files.length > 0 && (
              <span className="font-mono text-[10px] text-ink-500">{files.length} files</span>
            )}
          </div>

          {files.length === 0 ? (
            <div className="flex min-h-52 items-center justify-center rounded-lg border border-dashed border-base-700 p-5 text-xs text-ink-400">
              <FileText size={20} className="mr-2" />
              Pilih komponen lalu generate.
            </div>
          ) : (
            <>
              <div className="mb-2 flex flex-wrap gap-1">
                {files.map((file, index) => (
                  <button
                    type="button"
                    key={file.filename}
                    onClick={() => setSelected(index)}
                    className={
                      "rounded-md border px-2 py-2 text-[10px] " +
                      (selected === index
                        ? "border-signal-blue/50 bg-signal-blue/10 text-ink-100"
                        : "border-base-700 text-ink-500")
                    }
                  >
                    {file.filename}
                  </button>
                ))}
              </div>

              <div className="overflow-hidden rounded-lg border border-base-700">
                <div className="flex items-center justify-between border-b border-base-700 px-3 py-2">
                  <span className="truncate font-mono text-[10px] text-ink-300">
                    {activeFile?.filename}
                  </span>
                  {activeFile && (
                    <button
                      type="button"
                      onClick={() => download(activeFile)}
                      className="flex items-center gap-1 rounded border border-base-700 px-2 py-1 text-[10px] text-ink-200"
                    >
                      <Download size={12} />
                      Download
                    </button>
                  )}
                </div>
                <pre className="max-h-[440px] overflow-auto bg-base-950 p-3 text-[11px] leading-5 text-ink-300">
                  <code>{activeFile?.content}</code>
                </pre>
              </div>

              {warnings.map((warning, index) => (
                <p key={index} className="mt-3 flex gap-2 text-[10px] leading-4 text-ink-400">
                  <ShieldAlert size={13} className="shrink-0 text-signal-blue" />
                  {warning}
                </p>
              ))}
            </>
          )}
        </div>
      </div>
    </section>
  );
}
