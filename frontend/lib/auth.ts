// Penyimpanan JWT access token di sisi client.
//
// CATATAN KEAMANAN: localStorage dipakai di skeleton awal ini untuk
// kecepatan development. Untuk production, pertimbangkan httpOnly
// cookie + refresh token supaya token tidak terjangkau JavaScript
// (XSS surface). Ini konsisten dengan cara backend menandai hal-hal
// yang "cukup untuk lab, belum untuk production" (lihat known_hosts=None
// di app/tools/linux.py) — dicatat eksplisit, bukan didiamkan.

const TOKEN_KEY = "nova_access_token";

export function getToken(): string | null {
  if (typeof window === "undefined") return null;
  return window.localStorage.getItem(TOKEN_KEY);
}

export function setToken(token: string): void {
  window.localStorage.setItem(TOKEN_KEY, token);
}

export function clearToken(): void {
  window.localStorage.removeItem(TOKEN_KEY);
}

export function isAuthenticated(): boolean {
  return getToken() !== null;
}
