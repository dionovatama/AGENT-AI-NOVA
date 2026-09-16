"use client";

import { useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
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

  const searchParams = useSearchParams();
  const resetKey = searchParams.get("new");

  // Dipicu oleh tombol "New chat" di Sidebar (?new=<timestamp>) --
  // reset state percakapan beneran, bukan navigasi kosong yang diam
  // saja kalau sudah berada di /chat.
  useEffect(() => {
    if (resetKey) {
      setMessages([]);
      setInput("");
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [resetKey]);

  const toolsSupported = TOOL_CALLING_CATEGORIES.includes(category);

  async function handleSend(e: React.FormEvent) {
    e.preventDefault();
    const text = input.trim();
    if (!text || sending) return;

    setMessages((prev) => [...prev, { role: "user", content: text }]);
    setInput("");
    setSending(true);

    try {
      const toolsRequested = toolsSupported && useTools;
      const result = await novaApi.chatCompletion(text, category, toolsRequested);
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
    <div className="mx-auto flex h-full max-w-3xl flex-col">
      <div className="flex-1 overflow-y-auto pb-4">
        <ChatWindow messages={messages} />
      </div>

      {messages.length === 0 && (
        <div className="mb-4">
          <CapabilityShortcuts />
        </div>
      )}

      <form
        onSubmit={handleSend}
        className="rounded-md border border-base-700 bg-base-850 p-3.5 transition-colors focus-within:border-base-600"
      >
        <div className="mb-2.5 flex items-center justify-between gap-2">
          <CategoryPicker value={category} onChange={setCategory} />

          {toolsSupported && (
            <button
              type="button"
              onClick={() => setUseTools((v) => !v)}
              aria-pressed={useTools}
              className={`flex shrink-0 items-center gap-1.5 rounded-sm border px-2.5 py-1.5 text-[12px] transition-colors ${
                useTools
                  ? "border-signal-teal/50 bg-signal-teal/10 text-signal-teal"
                  : "border-base-600 text-ink-500 hover:text-ink-300"
              }`}
            >
              <span
                className={`h-1.5 w-1.5 rounded-full transition-colors ${
                  useTools ? "bg-signal-teal" : "bg-base-600"
                }`}
              />
              web.search / web.read_page
            </button>
          )}
        </div>

        <div className="flex items-end gap-2">
          <span className="mb-2 shrink-0 text-signal-blue">✦</span>
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
            placeholder="Tanya NOVA — reasoning murni, belum ada tool execution di sini."
            className="flex-1 resize-none bg-transparent text-sm text-ink-100 placeholder:text-ink-500 focus:outline-none"
          />
          <button type="submit" disabled={sending} className="btn-primary shrink-0 !rounded-full !p-2.5">
            {sending ? "…" : "↑"}
          </button>
        </div>

        <div className="mt-2 flex items-center justify-between font-mono text-[11px] text-ink-500">
          <span>NOVA · Operator Mode</span>
          <span>Enter to send · Shift+Enter baris baru</span>
        </div>
      </form>

      <p className="mt-2 text-center text-[11px] text-ink-500">
        Endpoint ini murni reasoning (Milestone 2). Untuk eksekusi command nyata,
        gunakan halaman Tools.
      </p>
    </div>
  );
}
