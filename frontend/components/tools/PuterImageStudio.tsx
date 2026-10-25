"use client";

import { useState } from "react";
import { Download, ImagePlus, LoaderCircle, Sparkles } from "lucide-react";
import { generatePuterImage } from "@/lib/puter-image";

export function PuterImageStudio() {
  const [prompt, setPrompt] = useState("");
  const [imageUrl, setImageUrl] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function generate() {
    if (!prompt.trim() || busy) return;
    setBusy(true);
    setError("");
    setImageUrl("");

    try {
      setImageUrl(await generatePuterImage(prompt));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Gagal menghasilkan gambar.");
    } finally {
      setBusy(false);
    }
  }

  function downloadImage() {
    if (!imageUrl) return;
    const link = document.createElement("a");
    link.href = imageUrl;
    link.target = "_blank";
    link.rel = "noreferrer";
    link.download = "nova-generated-image";
    link.click();
  }

  return (
    <section className="overflow-hidden rounded-xl border border-base-700 bg-base-800/50">
      <div className="border-b border-base-700 px-4 py-4 sm:px-5">
        <div className="flex items-center gap-2">
          <ImagePlus size={17} className="text-orb-core" />
          <h2 className="text-sm font-semibold text-ink-100">NOVA Image Studio</h2>
          <span className="rounded border border-orb-glow/30 bg-orb-glow/10 px-2 py-0.5 text-[10px] uppercase tracking-wide text-orb-core">Puter.js</span>
        </div>
        <p className="mt-1 text-xs leading-5 text-ink-500">Buat gambar dari deskripsi teks. Permintaan dikirim melalui Puter.js di browser.</p>
      </div>

      <div className="grid gap-5 p-4 sm:p-5 lg:grid-cols-[minmax(0,0.9fr)_minmax(0,1.1fr)]">
        <div className="space-y-3">
          <label htmlFor="nova-image-prompt" className="block text-xs font-medium text-ink-300">Deskripsi gambar</label>
          <textarea
            id="nova-image-prompt"
            value={prompt}
            onChange={(event) => setPrompt(event.target.value)}
            maxLength={4000}
            rows={7}
            placeholder="Contoh: ilustrasi topologi jaringan sekolah, router MikroTik terhubung ke switch dan tiga PC, diagram teknis bersih dengan latar gelap..."
            className="w-full resize-y rounded-md border border-base-700 bg-base-950 px-3 py-3 text-sm leading-6 text-ink-100 outline-none placeholder:text-ink-500 focus:border-orb-glow/60 focus:ring-2 focus:ring-orb-glow/10"
          />
          <div className="flex items-center justify-between text-[10px] text-ink-500">
            <span>Prompt maksimal 4.000 karakter</span>
            <span>{prompt.length}/4000</span>
          </div>
          {error && <p role="alert" className="rounded-md border border-signal-rose/30 bg-signal-rose/10 p-3 text-xs text-signal-rose">{error}</p>}
          <button
            type="button"
            disabled={busy || !prompt.trim()}
            onClick={generate}
            className="flex h-10 w-full items-center justify-center gap-2 rounded-md bg-gradient-to-r from-[#842BD2] to-orb-glow px-4 text-xs font-semibold text-white transition hover:brightness-110 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {busy ? <><LoaderCircle size={14} className="animate-spin" /> Membuat gambar...</> : <><Sparkles size={14} /> Generate image</>}
          </button>
          <p className="text-[10px] leading-4 text-ink-500">Puter dapat meminta login. Penggunaan mengikuti kuota dan ketentuan biaya akun Puter; periksa ketentuan sebelum menghasilkan gambar.</p>
        </div>

        <div className="min-w-0">
          <h3 className="mb-2 text-xs font-semibold text-ink-200">Preview</h3>
          {busy ? (
            <div className="flex min-h-64 flex-col items-center justify-center gap-3 rounded-lg border border-dashed border-base-700 text-center">
              <LoaderCircle size={24} className="animate-spin text-orb-core" />
              <p className="text-xs text-ink-400">Puter.js sedang memproses permintaan...</p>
            </div>
          ) : imageUrl ? (
            <div className="space-y-3">
              <div className="overflow-hidden rounded-lg border border-base-700 bg-base-950">
                <img src={imageUrl} alt="Hasil generasi gambar NOVA" className="h-auto max-h-[560px] w-full object-contain" />
              </div>
              <div className="flex flex-wrap gap-2">
                <button type="button" onClick={downloadImage} className="flex items-center gap-2 rounded-md border border-base-700 px-3 py-2 text-xs text-ink-200 hover:bg-white/[0.05]"><Download size={13} /> Buka / simpan gambar</button>
                <button type="button" onClick={() => { setImageUrl(""); }} className="rounded-md border border-base-700 px-3 py-2 text-xs text-ink-400 hover:bg-white/[0.05]">Hapus preview</button>
              </div>
            </div>
          ) : (
            <div className="flex min-h-64 flex-col items-center justify-center rounded-lg border border-dashed border-base-700 px-5 text-center">
              <ImagePlus size={24} className="mb-3 text-ink-500" />
              <p className="text-xs text-ink-400">Hasil gambar akan muncul di sini.</p>
            </div>
          )}
        </div>
      </div>
    </section>
  );
}
