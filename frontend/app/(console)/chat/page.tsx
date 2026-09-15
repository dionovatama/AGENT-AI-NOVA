"use client";

import { useState } from "react";
import { ChatWindow } from "@/components/chat/ChatWindow";
import { CategoryPicker } from "@/components/chat/CategoryPicker";
import { novaApi, NovaApiError } from "@/lib/api";
import type { ChatMessage, TaskCategory } from "@/lib/types";
import { TOOL_CALLING_CATEGORIES } from "@/lib/types";

export default function ChatPage() {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [category, setCategory] = useState<TaskCategory>("general_chat");
  const [useTools, setUseTools] = useState(false);
  const [sending, setSending] = useState(false);

  const toolsSupported = TOOL_CALLING_CATEGORIES.includes(category);

  async function handleSend(e: React.FormEvent) {
    e.preventDefault();
    const text = input.trim();
    if (!text || sending) return;

    setMessages((prev) => [...prev, { role: "user", content: text }]);
    setInput("");
    setSending(true);

    try {
      const result = await novaApi.chatCompletion(text, category, toolsSupported && useTools);
      setMessages((prev) => [
        ...prev,
        {
          role: "assistant",
          content: result.content,
          meta: { model_used: result.model_used, used_fallback: result.used_fallback },
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

      <form onSubmit={handleSend} className="panel p-3">
        <div className="mb-2.5 flex items-center justify-between">
          <CategoryPicker value={category} onChange={setCategory} />
          {toolsSupported && (
            <label className="flex shrink-0 items-center gap-1.5 pl-2 text-[12px] text-ink-500">
              <input
                type="checkbox"
                checked={useTools}
                onChange={(e) => setUseTools(e.target.checked)}
              />
              gunakan web.search / web.read_page
            </label>
          )}
        </div>
        <div className="flex items-end gap-2">
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
            className="field-input resize-none"
          />
          <button type="submit" disabled={sending} className="btn-primary shrink-0">
            {sending ? "Mengirim…" : "Kirim"}
          </button>
        </div>
      </form>
      <p className="mt-2 text-center text-[11px] text-ink-500">
        Endpoint ini murni reasoning (Milestone 2). Untuk eksekusi command
        nyata, gunakan halaman Tools.
      </p>
    </div>
  );
}
