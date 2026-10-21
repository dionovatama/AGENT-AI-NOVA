"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { Mail, Lock, Eye, EyeOff } from "lucide-react";
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
  // UI-only: kontrol tampil/sembunyi teks password. Tidak menyentuh
  // validasi/submit — <input> tetap punya required + minLength di bawah,
  // ini cuma mengganti atribut `type` untuk kenyamanan mengetik.
  const [showPassword, setShowPassword] = useState(false);

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

  const isLogin = mode === "login";

  return (
    <BootSplash>
      <main className="relative flex min-h-screen items-center justify-center overflow-hidden bg-base-950 px-4 py-10">
        {/* Ambient glow — subtle, biru redup di sekitar tepi bawah card saja
            (bukan seluruh layar), sesuai referensi. Dekoratif murni,
            pointer-events-none supaya tidak mengganggu interaksi. */}
        <div className="pointer-events-none absolute inset-0 -z-10 overflow-hidden">
          <div className="absolute left-1/2 top-[58%] h-[420px] w-[420px] -translate-x-1/2 rounded-full bg-signal-blue/20 blur-[110px]" />
          <div className="absolute left-1/2 top-[72%] h-[300px] w-[520px] -translate-x-1/2 rounded-full bg-signal-blue/10 blur-[130px]" />
        </div>

        <div className="w-full max-w-[420px]">
          <div className="relative overflow-hidden rounded-[22px] border border-white/[0.06] bg-base-900 p-7 sm:p-8">
            {/* Sheen tipis di tepi atas card — kesan permukaan charcoal premium,
                bukan blok flat. */}
            <div
              className="pointer-events-none absolute inset-0 rounded-[22px]"
              style={{
                boxShadow:
                  "inset 0 1px 0 0 rgba(255,255,255,0.05), inset 0 0 40px 0 rgba(76,142,247,0.04)",
              }}
            />

            <div className="relative">
              <div className="text-center">
                <h1 className="text-[28px] font-semibold tracking-tight text-ink-100">
                  {isLogin ? "Log in" : "Create account"}
                </h1>
                <p className="mx-auto mt-2.5 max-w-[300px] text-[13px] leading-relaxed text-ink-500">
                  {isLogin
                    ? "Log in to your account and seamlessly continue managing your devices, diagnostics, and automations right where you left off."
                    : "Create your NOVA account to start managing your devices, diagnostics, and automations."}
                </p>
              </div>

              <form onSubmit={handleSubmit} className="mt-7">
                <div className="space-y-3.5">
                  <div className="relative">
                    <span className="pointer-events-none absolute inset-y-0 left-4 flex items-center text-ink-500">
                      <Mail size={17} strokeWidth={1.75} />
                    </span>
                    <label htmlFor="email" className="sr-only">
                      Email
                    </label>
                    <input
                      id="email"
                      type="email"
                      required
                      value={email}
                      onChange={(e) => setEmail(e.target.value)}
                      placeholder="Enter your email address"
                      className="w-full rounded-full border border-base-600 bg-base-950/60 py-3 pl-11 pr-4 text-[13px] text-ink-100
                        placeholder:text-ink-500 transition-colors focus:border-signal-blue/70 focus:outline-none
                        focus:ring-1 focus:ring-signal-blue/30"
                    />
                  </div>

                  <div className="relative">
                    <span className="pointer-events-none absolute inset-y-0 left-4 flex items-center text-ink-500">
                      <Lock size={17} strokeWidth={1.75} />
                    </span>
                    <label htmlFor="password" className="sr-only">
                      Password
                    </label>
                    <input
                      id="password"
                      type={showPassword ? "text" : "password"}
                      required
                      minLength={8}
                      value={password}
                      onChange={(e) => setPassword(e.target.value)}
                      placeholder="Enter your password"
                      className="w-full rounded-full border border-base-600 bg-base-950/60 py-3 pl-11 pr-11 text-[13px] text-ink-100
                        placeholder:text-ink-500 transition-colors focus:border-signal-blue/70 focus:outline-none
                        focus:ring-1 focus:ring-signal-blue/30"
                    />
                    <button
                      type="button"
                      onClick={() => setShowPassword((v) => !v)}
                      aria-label={showPassword ? "Hide password" : "Show password"}
                      className="absolute inset-y-0 right-4 flex items-center text-ink-500 transition-colors hover:text-signal-blue"
                    >
                      {showPassword ? (
                        <EyeOff size={17} strokeWidth={1.75} />
                      ) : (
                        <Eye size={17} strokeWidth={1.75} />
                      )}
                    </button>
                  </div>
                </div>

                {error && (
                  <p className="mt-3.5 rounded-2xl border border-signal-rose/30 bg-signal-rose/10 px-4 py-2.5 text-[13px] text-signal-rose">
                    {error}
                  </p>
                )}

                <button
                  type="submit"
                  disabled={pending}
                  className="mt-5 w-full rounded-full bg-base-700 py-3 text-[13px] font-medium text-ink-100 transition-colors
                    hover:bg-base-600 disabled:pointer-events-none disabled:opacity-40"
                >
                  {pending
                    ? isLogin
                      ? "Logging in…"
                      : "Creating account…"
                    : isLogin
                      ? "Log in"
                      : "Create account"}
                </button>
              </form>

              <button
                type="button"
                onClick={() => setMode(isLogin ? "register" : "login")}
                className="mt-5 w-full text-center text-[13px] text-ink-500"
              >
                {isLogin ? (
                  <>
                    Didn&apos;t have an account?{" "}
                    <span className="text-signal-blue hover:underline">Sign up</span>
                  </>
                ) : (
                  <>
                    Already have an account?{" "}
                    <span className="text-signal-blue hover:underline">Log in</span>
                  </>
                )}
              </button>
            </div>
          </div>
        </div>
      </main>
    </BootSplash>
  );
}
