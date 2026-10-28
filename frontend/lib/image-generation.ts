import { getToken } from "./auth";

const BASE_URL =
  process.env.NEXT_PUBLIC_NOVA_API_BASE_URL ?? "http://localhost:8000";

export const MAX_IMAGE_PROMPT_CHARS = 2000;

export interface GeneratedImage {
  imageDataUrl: string;
  model: string;
}

/**
 * Generate gambar lewat backend NOVA (POST /images/generate).
 * Token Cloudflare tidak pernah ada di frontend — hanya JWT user.
 * Pesan error dari backend berlabel [AUTH]/[QUOTA]/[UPSTREAM]/
 * [TIMEOUT]/[CONFIG]/[RATE_LIMIT] dan ditampilkan apa adanya.
 */
export async function generateImage(prompt: string): Promise<GeneratedImage> {
  const clean = prompt.trim();
  if (!clean) throw new Error("Prompt gambar tidak boleh kosong.");
  if (clean.length > MAX_IMAGE_PROMPT_CHARS) {
    throw new Error(`Prompt terlalu panjang. Maksimal ${MAX_IMAGE_PROMPT_CHARS} karakter.`);
  }

  const headers: Record<string, string> = { "Content-Type": "application/json" };
  const token = getToken();
  if (token) headers.Authorization = `Bearer ${token}`;

  const controller = new AbortController();
  const timer = window.setTimeout(() => controller.abort(), 90_000);

  let response: Response;
  try {
    response = await fetch(`${BASE_URL}/images/generate`, {
      method: "POST",
      headers,
      body: JSON.stringify({ prompt: clean }),
      signal: controller.signal,
    });
  } catch (err) {
    if (err instanceof DOMException && err.name === "AbortError") {
      throw new Error("[TIMEOUT] Backend tidak merespons dalam 90 detik.");
    }
    throw new Error("Tidak dapat menghubungi backend NOVA.");
  } finally {
    window.clearTimeout(timer);
  }

  if (!response.ok) {
    let detail = response.statusText;
    try {
      const body = await response.json();
      detail = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail ?? body);
    } catch {
      /* body bukan JSON */
    }
    throw new Error(detail);
  }

  const data = (await response.json()) as { image_data_url?: string; model?: string };
  if (!data.image_data_url) {
    throw new Error("Backend tidak mengembalikan gambar.");
  }
  return { imageDataUrl: data.image_data_url, model: data.model ?? "" };
}