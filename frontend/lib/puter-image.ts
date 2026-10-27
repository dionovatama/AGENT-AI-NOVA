"use client";

const PUTER_SCRIPT_URL = "https://js.puter.com/v2/";
const PUTER_LOAD_TIMEOUT_MS = 20_000;
const IMAGE_GENERATION_TIMEOUT_MS = 120_000;
const PUTER_POLL_INTERVAL_MS = 100;

type PuterImageElement = HTMLImageElement;

interface PuterAI {
  txt2img(prompt: string, testMode?: boolean): Promise<PuterImageElement>;
}

interface PuterClient {
  ai: PuterAI;
}

declare global {
  interface Window {
    puter?: PuterClient;
  }
}

let scriptPromise: Promise<void> | null = null;

function hasPuterImageAPI(): boolean {
  return Boolean(window.puter?.ai?.txt2img);
}

function loadPuter(): Promise<void> {
  if (typeof window === "undefined") {
    return Promise.reject(new Error("Puter.js hanya tersedia di browser."));
  }

  if (hasPuterImageAPI()) return Promise.resolve();
  if (scriptPromise) return scriptPromise;

  scriptPromise = new Promise<void>((resolve, reject) => {
    let settled = false;
    let pollId: number | undefined;

    const script =
      document.querySelector<HTMLScriptElement>('script[data-nova-puter="true"]') ??
      document.createElement("script");

    const cleanup = () => {
      window.clearTimeout(timeoutId);
      if (pollId !== undefined) window.clearInterval(pollId);
      script.removeEventListener("error", onError);
      scriptPromise = null;
    };

    const finish = () => {
      if (settled || !hasPuterImageAPI()) return;
      settled = true;
      cleanup();
      resolve();
    };

    const fail = (message: string) => {
      if (settled) return;
      settled = true;
      cleanup();
      reject(new Error(message));
    };

    const onError = () => {
      fail("Gagal memuat Puter.js dari CDN. Periksa koneksi atau pemblokir konten lalu coba lagi.");
    };

    const timeoutId = window.setTimeout(() => {
      fail("Puter.js tidak siap setelah 20 detik. Coba muat ulang halaman; jika masalah berlanjut, periksa login Puter dan pemblokir konten.");
    }, PUTER_LOAD_TIMEOUT_MS);

    // Poll for the API instead of relying only on the script's load event.
    // An existing script may already have fired its load event before NOVA
    // attaches listeners, while Puter is still initializing authentication.
    pollId = window.setInterval(finish, PUTER_POLL_INTERVAL_MS);
    script.addEventListener("error", onError, { once: true });

    if (!script.isConnected) {
      script.src = PUTER_SCRIPT_URL;
      script.async = true;
      script.dataset.novaPuter = "true";
      document.head.appendChild(script);
    }

    finish();
  });

  return scriptPromise;
}

/**
 * Runs only after an explicit user action or a clear image-generation request.
 * testMode=true uses Puter's test API to diagnose the integration without
 * requesting a normal image generation.
 */
export async function generatePuterImage(prompt: string): Promise<string> {
  const cleanPrompt = prompt.trim();
  if (!cleanPrompt) throw new Error("Prompt gambar tidak boleh kosong.");
  if (cleanPrompt.length > 4000) {
    throw new Error("Prompt terlalu panjang. Maksimal 4.000 karakter.");
  }

  await loadPuter();

  let timeoutId: number | undefined;
  try {
    const timeout = new Promise<never>((_, reject) => {
      timeoutId = window.setTimeout(() => {
        reject(
          new Error(
            "Puter.js belum menyelesaikan generasi gambar setelah 120 detik. Coba lagi; jika berulang, periksa status layanan atau sesi login Puter."
          )
        );
      }, IMAGE_GENERATION_TIMEOUT_MS);
    });

    const result = await Promise.race([
      window.puter!.ai.txt2img(cleanPrompt, true),
      timeout,
    ]);

    if (!result?.src) {
      throw new Error("Puter.js tidak mengembalikan gambar yang dapat ditampilkan.");
    }

    return result.src;
  } finally {
    if (timeoutId !== undefined) window.clearTimeout(timeoutId);
  }
}
