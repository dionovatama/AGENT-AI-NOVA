"use client";

const PUTER_SCRIPT_URL = "https://js.puter.com/v2/";

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

function loadPuter(): Promise<void> {
  if (typeof window === "undefined") {
    return Promise.reject(new Error("Puter.js hanya tersedia di browser."));
  }

  if (window.puter?.ai?.txt2img) return Promise.resolve();
  if (scriptPromise) return scriptPromise;

  scriptPromise = new Promise<void>((resolve, reject) => {
    const existing = document.querySelector<HTMLScriptElement>(
      'script[data-nova-puter="true"]'
    );

    const script = existing ?? document.createElement("script");
    const timeout = window.setTimeout(() => {
      scriptPromise = null;
      reject(new Error("Puter.js terlalu lama dimuat. Periksa koneksi internet lalu coba lagi."));
    }, 20000);

    const finish = () => {
      window.clearTimeout(timeout);
      if (window.puter?.ai?.txt2img) {
        resolve();
      } else {
        scriptPromise = null;
        reject(new Error("Puter.js berhasil dimuat, tetapi API gambar tidak tersedia."));
      }
    };

    script.addEventListener("load", finish, { once: true });
    script.addEventListener("error", () => {
      window.clearTimeout(timeout);
      scriptPromise = null;
      reject(new Error("Gagal memuat Puter.js dari CDN."));
    }, { once: true });

    if (!existing) {
      script.src = PUTER_SCRIPT_URL;
      script.async = true;
      script.dataset.novaPuter = "true";
      document.head.appendChild(script);
    } else if (window.puter?.ai?.txt2img) {
      window.clearTimeout(timeout);
      resolve();
    }
  });

  return scriptPromise;
}

/**
 * Runs only after an explicit user action or a clear image-generation request.
 * testMode=false means this requests a real generation and may use the user's
 * Puter account quota/billing according to Puter's current terms.
 */
export async function generatePuterImage(prompt: string): Promise<string> {
  const cleanPrompt = prompt.trim();
  if (!cleanPrompt) throw new Error("Prompt gambar tidak boleh kosong.");
  if (cleanPrompt.length > 4000) {
    throw new Error("Prompt terlalu panjang. Maksimal 4.000 karakter.");
  }

  await loadPuter();
  const result = await window.puter!.ai.txt2img(cleanPrompt, false);
  if (!result?.src) {
    throw new Error("Puter.js tidak mengembalikan gambar yang dapat ditampilkan.");
  }
  return result.src;
}
