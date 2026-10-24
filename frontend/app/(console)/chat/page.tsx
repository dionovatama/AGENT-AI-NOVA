"use client";

import { useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import { ArrowUp } from "lucide-react";
import { ChatWindow } from "@/components/chat/ChatWindow";
import { CategoryPicker } from "@/components/chat/CategoryPicker";
import { CapabilityShortcuts } from "@/components/chat/CapabilityShortcuts";
import { NovaActivity, type ProcessingStage } from "@/components/chat/NovaActivity";
import { novaApi, NovaApiError } from "@/lib/api";
import type { ChatMessage, TaskCategory } from "@/lib/types";
import { TOOL_CALLING_CATEGORIES } from "@/lib/types";

export default function ChatPage() {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [category, setCategory] = useState<TaskCategory>("general_chat");
  const [useTools, setUseTools] = useState(false);
  const [sending, setSending] = useState(false);
  const [processingStage, setProcessingStage] = useState<ProcessingStage>("understand");
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
    setProcessingStage("understand");
    const stageTimer = window.setTimeout(() => setProcessingStage("process"), 350);
    const startedAt = performance.now();

    try {
      const toolsRequested = toolsSupported && useTools;
      setProcessingStage("process");
      const result = await novaApi.chatCompletion(text, category, toolsRequested);
      setLastLatencyMs(Math.round(performance.now() - startedAt));
      setProcessingStage("respond");
      setMessages((prev) => [
        ...prev,
        {
          role: "assistant",
          content: result.content,
          diagrams: result.diagrams,
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
      window.clearTimeout(stageTimer);
      setSending(false);
    }
  }

  return (
    <div className="mx-auto flex h-full min-h-0 w-full max-w-[900px] flex-col px-3 sm:px-5 lg:px-7">
      {messages.length === 0 ? (
        <div className="min-h-0 flex-1">
          <ChatWindow messages={messages} onQuickAction={handleQuickAction} />
          <div className="mb-5 mt-6">
            <CapabilityShortcuts />
          </div>
        </div>
      ) : (
        <div className="nova-chat-scroll min-h-0 flex-1 overflow-y-auto pb-3 pt-1">
          <ChatWindow messages={messages} onQuickAction={handleQuickAction} />
          {sending && (
            <div className="mx-auto mt-5 w-full max-w-[820px] px-2 sm:px-4">
              <NovaActivity stage={processingStage} toolsEnabled={toolsSupported && useTools} />
            </div>
          )}
        </div>
      )}

      <div className="group relative mt-2">
        <div className="pointer-events-none absolute -inset-1 rounded-2xl bg-gradient-to-r from-orb-glow/20 via-[#4C8EF7]/10 to-signal-teal/15 opacity-25 blur-xl transition-opacity duration-300 group-focus-within:opacity-70" />

        <form onSubmit={handleSend} className="glass-composer relative flex min-h-[116px] flex-col justify-between p-3.5 sm:p-4">
          <div className="flex w-full items-start gap-2.5">
            <span className="mt-0.5 select-none font-mono text-[15px] text-orb-core drop-shadow-[0_0_8px_rgba(192,132,252,0.6)]">
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

          <div className="mt-2 flex flex-wrap items-center justify-between gap-2 border-t border-white/[0.05] pt-2.5">
            <div className="flex flex-wrap items-center gap-1.5">
              <CategoryPicker value={category} onChange={setCategory} />

              {toolsSupported && (
                <button
                  type="button"
                  onClick={() => setUseTools((v) => !v)}
                  aria-pressed={useTools}
                  title="Aktifkan tools READ: web.search, web.read_page, diagram.create"
                  className={`flex shrink-0 items-center gap-1.5 rounded-lg border px-2.5 py-1 text-[12px] font-medium transition-colors ${
                    useTools
                      ? "border-signal-teal/40 bg-signal-teal/10 text-signal-teal"
                      : "border-transparent bg-white/[0.04] text-ink-500 hover:bg-white/[0.08] hover:text-ink-100"
                  }`}
                >
                  <span className={`h-1.5 w-1.5 rounded-full ${useTools ? "bg-signal-teal" : "bg-base-600"}`} />
                  tools
                </button>
              )}

              <span className="badge-read">
                <span className="h-1.5 w-1.5 rounded-full bg-signal-green shadow-[0_0_6px_rgba(63,203,124,0.9)]" />
                READ (AUTO)
              </span>
            </div>

            <button
              type="submit"
              disabled={sending}
              className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-gradient-to-tr from-[#842BD2] to-orb-glow text-white shadow-[0_0_16px_rgba(168,85,247,0.5)] transition-all hover:brightness-110 active:scale-95 disabled:opacity-50"
            >
              <ArrowUp size={16} strokeWidth={2.5} />
            </button>
          </div>
        </form>
      </div>

      <div className="flex items-center justify-between px-1 pt-1.5 text-ink-500">
        <span className="font-sans text-[10px] text-ink-500/80">
          <kbd className="rounded bg-white/[0.06] px-1 py-0.5 font-mono text-[9px] text-ink-300">Enter</kbd> send ·{" "}
          <kbd className="rounded bg-white/[0.06] px-1 py-0.5 font-mono text-[9px] text-ink-300">Shift+Enter</kbd> newline
        </span>
        {lastLatencyMs !== null && (
          <span className="flex items-center gap-1.5 font-mono text-[10px] text-ink-500/80">
            <span className="h-1.5 w-1.5 rounded-full bg-signal-teal" />
            {lastLatencyMs}ms
          </span>
        )}
      </div>

      <p className="mb-2 mt-1 text-center text-[10px] text-ink-500/80">
        Endpoint ini murni reasoning (Milestone 2). Untuk eksekusi command nyata, gunakan halaman Tools.
      </p>
    </div>
  );
}
