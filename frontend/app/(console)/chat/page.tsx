"use client";

import { useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import { ArrowUp } from "lucide-react";
import { ChatWindow } from "@/components/chat/ChatWindow";
import { CategoryPicker } from "@/components/chat/CategoryPicker";
import { CapabilityShortcuts } from "@/components/chat/CapabilityShortcuts";
import { novaApi, NovaApiError } from "@/lib/api";
import type { ChatMessage, TaskCategory } from "@/lib/types";
import { TOOL_CALLING_CATEGORIES } from "@/lib/types";

export default function ChatPage() {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [category, setCategory] = useState<TaskCategory>("general_chat");
  const [useTools, setUseTools] = useState(false);
  const [sending, setSending] = useState(false);
  // Latency BENERAN diukur dari waktu tempuh request terakhir -- BUKAN
  // angka statis seperti "42ms" di referensi desain. Null sebelum ada
  // request yang selesai sama sekali (tidak ada nilai untuk ditampilkan,
  // bukan 0 yang menyesatkan seolah sudah pernah diukur).
  const [lastLatencyMs, setLastLatencyMs] = useState<number | null>(null);

  const searchParams = useSearchParams();
  const resetKey = searchParams.get("new");

  useEffect(() => {
    if (resetKey) {
      setMessages([]);
      setInput("");
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [resetKey]);

  const toolsSupported = TOOL_CALLING_CATEGORIES.includes(category);

  // Dipanggil dari quick-action pill di WelcomeHero -- isi composer +
  // ganti kategori (+ nyalain tools kalau shortcut-nya butuh), TIDAK
  // auto-kirim. User tetap yang menekan Kirim.
  function handleQuickAction(cat: TaskCategory, prompt: string, wantsTools?: boolean) {
    setCategory(cat);
    setInput(prompt);
    if (wantsTools && TOOL_CALLING_CATEGORIES.includes(cat)) setUseTools(true);
  }

  async function handleSend(e: React.FormEvent) {
    e.preventDefault();
    const text = input.trim();
    if (!text || sending) return;

    setMessages((prev) => [...prev, { role: "user", content: text }]);
    setInput("");
    setSending(true);
    const startedAt = performance.now();

    try {
      const toolsRequested = toolsSupported && useTools;
      const result = await novaApi.chatCompletion(text, category, toolsRequested);
      setLastLatencyMs(Math.round(performance.now() - startedAt));
      setMessages((prev) => [
        ...prev,
        {
          role: "assistant",
          content: result.content,
          meta: {
            model_used: result.model_used,
            used_fallback: result.used_fallback,
            tools_used: result.tools_used,
            tools_offered: toolsRequested,
          },
        },
      ]);
    } catch (err) {
      setLastLatencyMs(Math.round(performance.now() - startedAt));
      setMessages((prev) => [
        ...prev,
        {
          role: "assistant",
          content: "AI Gateway gagal memproses request ini.",
          meta: { error: err instanceof NovaApiError ? err.message : "Unknown error" },
        },
      ]);
    } finally {
      setSending(false);
    }
  }

  return (
    <div className="mx-auto flex h-full min-h-0 max-w-3xl flex-col">
      {messages.length === 0 ? (
        // Empty state: TIDAK dibungkus overflow-y-auto sendiri --
        // biarkan halaman (main, sudah overflow-y-auto di layout.tsx)
        // yang scroll kalau kontennya (hero + kartu) lebih tinggi dari
        // viewport, bukan bikin "kotak" kecil dengan scrollbar sendiri
        // di tengah halaman.
        <>
          <ChatWindow messages={messages} onQuickAction={handleQuickAction} />
          <div className="mb-6 mt-8">
            <CapabilityShortcuts />
          </div>
        </>
      ) : (
        <div className="min-h-0 flex-1 overflow-y-auto pb-4">
          <ChatWindow messages={messages} onQuickAction={handleQuickAction} />
        </div>
      )}

      {/* Ambient back-glow di belakang composer, nyala lebih terang saat
          fokus -- sesuai DESIGN.md komponen #1. */}
      <div className="group relative">
        <div className="pointer-events-none absolute -inset-1 rounded-2xl bg-gradient-to-r from-orb-glow/25 via-[#4C8EF7]/15 to-signal-teal/20 opacity-30 blur-xl transition-opacity duration-300 group-focus-within:opacity-80" />

        <form onSubmit={handleSend} className="glass-composer relative flex min-h-[148px] flex-col justify-between p-4">
          <div className="flex w-full items-start gap-2.5">
            <span className="mt-0.5 select-none font-mono text-[16px] text-orb-core drop-shadow-[0_0_8px_rgba(192,132,252,0.6)]">
              ✦
            </span>
            <textarea
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey) {
                  e.preventDefault();
                  handleSend(e);
                }
              }}
              rows={2}
              placeholder="Ask NOVA anything, or ask it to check something on the lab server…"
              className="w-full resize-none bg-transparent text-[14px] leading-relaxed text-ink-100 placeholder:text-ink-500/80 focus:outline-none"
            />
          </div>

          <div className="mt-2 flex flex-wrap items-center justify-between gap-2 border-t border-white/[0.05] pt-3">
            <div className="flex flex-wrap items-center gap-1.5">
              <CategoryPicker value={category} onChange={setCategory} />

              {toolsSupported && (
                <button
                  type="button"
                  onClick={() => setUseTools((v) => !v)}
                  aria-pressed={useTools}
                  className={`flex shrink-0 items-center gap-1.5 rounded-lg border px-2.5 py-1 text-[12px] font-medium transition-colors ${
                    useTools
                      ? "border-signal-teal/40 bg-signal-teal/10 text-signal-teal"
                      : "border-transparent bg-white/[0.04] text-ink-500 hover:bg-white/[0.08] hover:text-ink-100"
                  }`}
                >
                  <span className={`h-1.5 w-1.5 rounded-full ${useTools ? "bg-signal-teal" : "bg-base-600"}`} />
                  web.search
                </button>
              )}

              {/* READ (AUTO) -- BUKAN dekorasi, ini fakta nyata: chat
                  hanya pernah bisa memanggil tool permission READ (lihat
                  _CATEGORY_TOOL_ALLOWLIST di backend/app/ai/tool_calling.py).
                  MODIFY/HIGH_RISK tidak pernah bisa lewat sini. */}
              <span className="badge-read">
                <span className="h-1.5 w-1.5 rounded-full bg-signal-green shadow-[0_0_6px_rgba(63,203,124,0.9)]" />
                READ (AUTO)
              </span>
            </div>

            <button
              type="submit"
              disabled={sending}
              className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-gradient-to-tr from-[#842BD2] to-orb-glow text-white
                shadow-[0_0_16px_rgba(168,85,247,0.5)] transition-all hover:brightness-110 active:scale-95 disabled:opacity-50"
            >
              <ArrowUp size={16} strokeWidth={2.5} />
            </button>
          </div>
        </form>
      </div>

      <div className="flex items-center justify-between px-1 pt-2 text-ink-500">
        <span className="font-sans text-[11px] text-ink-500/80">
          Press <kbd className="rounded bg-white/[0.06] px-1 py-0.5 font-mono text-[10px] text-ink-300">Enter</kbd> to send{" "}
          <kbd className="rounded bg-white/[0.06] px-1 py-0.5 font-mono text-[10px] text-ink-300">Shift+Enter</kbd> for newline
        </span>
        {lastLatencyMs !== null && (
          <span className="flex items-center gap-1.5 font-mono text-[11px] text-ink-500/80">
            <span className="h-1.5 w-1.5 rounded-full bg-signal-teal" />
            Latency: {lastLatencyMs}ms
          </span>
        )}
      </div>

      <p className="mt-2 text-center text-[11px] text-ink-500">
        Endpoint ini murni reasoning (Milestone 2). Untuk eksekusi command nyata,
        gunakan halaman Tools.
      </p>
    </div>
  );
}
