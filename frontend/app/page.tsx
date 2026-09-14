"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { BootSplash } from "@/components/BootSplash";
import { novaApi, NovaApiError } from "@/lib/api";
import { setToken } from "@/lib/auth";

type Mode = "login" | "register";

export default function LoginPage() {
  const router = useRouter();
  const [mode, setMode] = useState<Mode>("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setPending(true);
    try {
      if (mode === "register") {
        await novaApi.register(email, password);
      }
      const { access_token } = await novaApi.login(email, password);
      setToken(access_token);
      router.push("/chat");
    } catch (err) {
      setError(err instanceof NovaApiError ? err.message : "Tidak dapat menghubungi backend NOVA.");
    } finally {
      setPending(false);
    }
  }

  return (
    <BootSplash>
      <main className="flex min-h-screen items-center justify-center px-4">
      <div className="w-full max-w-sm">
        <div className="mb-8 text-center">
          <img
            src="/brand/nova-lockup.png"
            alt="N.O.V.A — Nexus Operation Virtual Assistant"
            className="mx-auto w-64"
          />
          <p className="mt-3 text-sm text-ink-500">
            AI thinks. Tools collect evidence. Policies control actions.
          </p>
        </div>

        <form onSubmit={handleSubmit} className="panel p-5">
          <div className="mb-4">
            <label className="field-label" htmlFor="email">Email</label>
            <input
              id="email"
              type="email"
              required
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              className="field-input"
              placeholder="operator@nova.local"
            />
          </div>
          <div className="mb-5">
            <label className="field-label" htmlFor="password">Password</label>
            <input
              id="password"
              type="password"
              required
              minLength={8}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="field-input"
              placeholder="••••••••"
            />
          </div>

          {error && (
            <p className="mb-4 rounded-sm border border-signal-rose/30 bg-signal-rose/10 px-3 py-2 text-sm text-signal-rose">
              {error}
            </p>
          )}

          <button type="submit" disabled={pending} className="btn-primary w-full justify-center">
            {pending ? "Menghubungi backend…" : mode === "login" ? "Masuk" : "Daftar & masuk"}
          </button>

          <button
            type="button"
            onClick={() => setMode(mode === "login" ? "register" : "login")}
            className="mt-3 w-full text-center text-[13px] text-ink-500 hover:text-ink-300"
          >
            {mode === "login" ? "Belum punya akun? Daftar" : "Sudah punya akun? Masuk"}
          </button>
        </form>

        <p className="mt-6 text-center text-xs text-ink-500">
          Milestone 1–4 aktif · Voice, Multi-Tenant UI, dan Automation menyusul.
        </p>
      </div>
      </main>
    </BootSplash>
  );
}
