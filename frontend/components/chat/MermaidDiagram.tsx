"use client";

import { useEffect, useState } from "react";
import type { DiagramAttachment } from "@/lib/types";

/**
 * Render diagram Mermaid dari backend (tool diagram.create).
 *
 * Keamanan — kode Mermaid berasal dari LLM (untrusted), walau sudah
 * divalidasi backend (backend/app/tools/diagram.py). Lapisan di sisi sini:
 *  1. securityLevel: "strict" — Mermaid menyaring HTML & menonaktifkan
 *     interaksi (click/callback).
 *  2. htmlLabels: false — teks digambar sebagai <text> SVG biasa, tanpa
 *     <foreignObject>/HTML.
 *  3. Hasil SVG ditampilkan lewat <img src="data:image/svg+xml,..."> — BUKAN
 *     innerHTML/dangerouslySetInnerHTML. Script di dalam SVG yang dimuat
 *     lewat <img> tidak pernah dieksekusi.
 *
 * useMaxWidth: false supaya SVG punya width/height eksplisit — SVG dengan
 * width="100%" yang dimuat via <img> tidak punya ukuran intrinsik dan bisa
 * menyusut. Responsivitas ditangani CSS (max-w-full h-auto) di <img>.
 */

const MERMAID_CONFIG = {
  startOnLoad: false,
  // Jangan biarkan Mermaid mencoba menulis error UI sendiri ke DOM.
  // NOVA menangani error melalui React state agar lifecycle DOM tetap terkendali.
  suppressErrorRendering: true,
  securityLevel: "strict",
  theme: "base",
  fontFamily: "IBM Plex Sans, system-ui, sans-serif",
  htmlLabels: false,
  flowchart: { htmlLabels: false, useMaxWidth: false },
  sequence: { useMaxWidth: false },
  state: { useMaxWidth: false },
  er: { useMaxWidth: false },
  class: { useMaxWidth: false },
  themeVariables: {
    darkMode: true,
    background: "#151B24",
    primaryColor: "#1D2530",
    primaryTextColor: "#EAEFF6",
    primaryBorderColor: "#2FD9C4",
    secondaryColor: "#151B24",
    tertiaryColor: "#0F131A",
    lineColor: "#6B7684",
    textColor: "#EAEFF6",
    actorBkg: "#1D2530",
    actorBorder: "#2FD9C4",
    actorTextColor: "#EAEFF6",
    actorLineColor: "#6B7684",
    signalColor: "#AEB8C4",
    signalTextColor: "#EAEFF6",
    noteBkgColor: "#2A3644",
    noteTextColor: "#EAEFF6",
    noteBorderColor: "#6B7684",
  },
} as const;

let initialized = false;
let idCounter = 0;

// Mermaid.render() temporarily mutates document.body. Multiple diagram
// components can mount at the same time (e.g. 2 diagrams in one response),
// so concurrent renders can race with Mermaid's temporary DOM cleanup and
// produce errors such as "Cannot read properties of null (reading 'firstChild')".
// Serialize all Mermaid renders in this browser tab while keeping React
// rendering itself fully asynchronous.
let renderQueue: Promise<unknown> = Promise.resolve();

async function renderMermaidSerialized(
  mermaid: Awaited<ReturnType<typeof getMermaid>>,
  id: string,
  code: string,
) {
  const task = renderQueue.then(async () => {
    // Parse terlebih dahulu supaya syntax error gagal sebelum render membuat
    // elemen DOM sementara. Ini juga membuat jalur error deterministik.
    await mermaid.parse(code);
    return mermaid.render(id, code);
  });
  renderQueue = task.then(
    () => undefined,
    () => undefined,
  );
  return task;
}

async function getMermaid() {
  const mod = await import("mermaid");
  const mermaid = mod.default;
  if (!initialized) {
    mermaid.initialize(MERMAID_CONFIG);
    initialized = true;
  }
  return mermaid;
}

type RenderState =
  | { status: "loading" }
  | { status: "ready"; src: string }
  | { status: "error"; message: string };

export function MermaidDiagram({ diagram }: { diagram: DiagramAttachment }) {
  const [renderId] = useState(() => `nova-diagram-${++idCounter}`);
  const [state, setState] = useState<RenderState>({ status: "loading" });
  const [showCode, setShowCode] = useState(false);

  useEffect(() => {
    let cancelled = false;
    setState({ status: "loading" });

    (async () => {
      try {
        const mermaid = await getMermaid();
        const { svg } = await renderMermaidSerialized(mermaid, renderId, diagram.code);
        if (cancelled) return;
        // <br> tanpa penutup bukan XML valid -> <img> gagal memuat SVG.
        const xmlSafe = svg.replace(/<br\s*>/gi, "<br/>");
        setState({
          status: "ready",
          src: `data:image/svg+xml;charset=utf-8,${encodeURIComponent(xmlSafe)}`,
        });
      } catch (err) {
        if (cancelled) return;
        setState({
          status: "error",
          message: err instanceof Error ? err.message : "Diagram tidak dapat dirender.",
        });
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [diagram.code, renderId]);

  return (
    <figure className="overflow-hidden rounded-md border border-base-700 bg-base-800/60">
      <figcaption className="flex items-center justify-between gap-3 border-b border-base-700/70 px-3 py-1.5">
        <span className="truncate font-mono text-[11px] text-ink-300">{diagram.title}</span>
        <button
          type="button"
          onClick={() => setShowCode((v) => !v)}
          className="shrink-0 font-mono text-[11px] text-ink-500 transition-colors hover:text-ink-100"
        >
          {showCode ? "sembunyikan kode" : "lihat kode"}
        </button>
      </figcaption>

      <div className="overflow-x-auto p-3">
        {state.status === "loading" && (
          <p className="py-6 text-center font-mono text-[11px] text-ink-500">Merender diagram…</p>
        )}

        {state.status === "ready" && (
          // eslint-disable-next-line @next/next/no-img-element
          <img
            src={state.src}
            alt={diagram.title}
            className="mx-auto h-auto max-w-full"
            onError={() =>
              setState({ status: "error", message: "Browser gagal menampilkan hasil render diagram." })
            }
          />
        )}

        {state.status === "error" && (
          <div>
            <p className="text-[12px] text-signal-rose">Diagram tidak dapat ditampilkan.</p>
            <p className="mt-1 font-mono text-[11px] text-ink-500">{state.message}</p>
          </div>
        )}
      </div>

      {(showCode || state.status === "error") && (
        <pre className="max-h-56 overflow-auto border-t border-base-700/70 bg-base-900 p-3 font-mono text-[12px] text-ink-300">
          {diagram.code}
        </pre>
      )}
    </figure>
  );
}
