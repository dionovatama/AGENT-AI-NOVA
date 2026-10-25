"use client";

import { useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import { ArrowUp } from "lucide-react";
import { ChatWindow } from "@/components/chat/ChatWindow";
import { CategoryPicker } from "@/components/chat/CategoryPicker";
import { CapabilityShortcuts } from "@/components/chat/CapabilityShortcuts";
import NovaActivity from "@/components/chat/NovaActivity";
import { novaApi, NovaApiError } from "@/lib/api";
import type { ChatMessage, TaskCategory } from "@/lib/types";
import { TOOL_CALLING_CATEGORIES } from "@/lib/types";
import { generatePuterImage } from "@/lib/puter-image";

type ProcessingStage = "understand" | "process" | "respond";

const ACTIVITY_STAGES: { id: ProcessingStage; label: string }[] = [
  { id: "understand", label: "Memahami permintaan" },
  { id: "process", label: "Memproses permintaan" },
  { id: "respond", label: "Menyiapkan respons" },
];

// NovaActivity di repo ini menerima daftar langkah + status, bukan "stage".
function toActivitySteps(stage: ProcessingStage) {
  const current = ACTIVITY_STAGES.findIndex((item) => item.id === stage);
  return ACTIVITY_STAGES.map((item, index) => ({
    label: item.label,
    status: (index < current ? "done" : index === current ? "active" : "pending") as
      | "done"
      | "active"
      | "pending",
  }));
}

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
  const isEmpty = messages.length === 0;

  function handleQuickAction(cat: TaskCategory, prompt: string, wantsTools?: boolean) {
    setCategory(cat);
    setInput(prompt);
    if (wantsTools && TOOL_CALLING_CATEGORIES.includes(cat)) setUseTools(true);
  }

  async function handleConfigurationChoice(requestText: string, choice: "file" | "direct") {
    if (sending) return;
    setMessages((prev) => [...prev, { role: "user", content: choice === "file" ? "Pilih: buatkan file konfigurasi." : "Pilih: konfigurasi langsung ke router." }]);
    setSending(true);
    setProcessingStage("process");
    const startedAt = performance.now();
    try {
      const result = await novaApi.chatCompletion(requestText, "configuration_generation", false, choice);
      setLastLatencyMs(Math.round(performance.now() - startedAt));
      setMessages((prev) => [...prev, {
        role: "assistant",
        content: result.content,
        generated_files: result.generated_files,
        meta: { model_used: result.model_used, used_fallback: result.used_fallback, tools_used: result.tools_used },
      }]);
    } catch (err) {
      setMessages((prev) => [...prev, {
        role: "assistant",
        content: "Permintaan konfigurasi gagal diproses.",
        meta: { error: err instanceof NovaApiError ? err.message : "Unknown error" },
      }]);
    } finally {
      setSending(false);
    }
  }

  async function handleImageGeneration(prompt: string) {
    if (sending) return;
    const cleanPrompt = prompt.trim();
    if (!cleanPrompt) return;
    setSending(true);
    setProcessingStage("process");
    const startedAt = performance.now();
    try {
      const imageUrl = await generatePuterImage(cleanPrompt);
      setProcessingStage("respond");
      setMessages((prev) => [...prev, {
        role: "assistant",
        content: "",
        image_url: imageUrl,
        image_prompt: cleanPrompt,
        meta: { model_used: "Puter.js Image Generation" },
      }]);
      setLastLatencyMs(Math.round(performance.now() - startedAt));
    } catch (err) {
      setMessages((prev) => [...prev, {
        role: "assistant",
        content: "Gagal membuat gambar. Periksa koneksi atau akun Puter.js, lalu coba lagi.",
        meta: { error: err instanceof Error ? err.message : "Unknown error" },
      }]);
    } finally {
      setSending(false);
    }
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
      // Match clear image-generation intent; normal chat stays on the existing AI Gateway.
      const wantsImage = /\b(generate|create|draw|make|render)\b.{0,100}\b(image|picture|illustration|artwork|poster|logo|wallpaper)\b|\b(buatkan|buat|gambar|ilustrasikan|lukiskan|hasilkan|bikin)\b.{0,100}\b(gambar|ilustrasi|poster|logo|wallpaper|foto|ilustrasi)\b|\b(gambar|ilustrasi|poster|logo|wallpaper)\b.{0,80}\b(buatkan|buat|generate|bikin|desain|gambarkan)\b/i.test(text);
      if (wantsImage) {
        const imagePrompt = text
          .replace(/^(tolong\s+)?(buatkan|buat|bikin|gambarkan|hasilkan|generate|create|draw|make|render)\s+(saya\s+)?(sebuah\s+)?(gambar|image|picture|ilustrasi|illustration|poster|logo|wallpaper|foto)\s*/i, "")
          .trim();
        const prompt = imagePrompt || text;
        const imageUrl = await generatePuterImage(prompt);
        setProcessingStage("respond");
        setMessages((prev) => [...prev, {
          role: "assistant",
          content: "",
          image_url: imageUrl,
          image_prompt: prompt,
          meta: { model_used: "Puter.js Image Generation" },
        }]);
        setLastLatencyMs(Math.round(performance.now() - startedAt));
        return;
      }

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
          generated_files: result.generated_files,
          show_configuration_choices: result.configuration_choice,
          configuration_request: result.configuration_choice ? text : undefined,
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
          content: "Permintaan gagal diproses. Periksa koneksi atau konfigurasi layanan, lalu coba lagi.",
          meta: { error: err instanceof NovaApiError ? err.message : "Unknown error" },
        },
      ]);
    } finally {
      window.clearTimeout(stageTimer);
      setSending(false);
    }
  }

  return (
    <div className="mx-auto flex h-full min-h-0 w-full max-w-[944px] flex-col px-6 pb-[18px]">
      {isEmpty ? (
        <div className="flex min-h-0 flex-1 items-center justify-center overflow-hidden">
          <ChatWindow messages={messages} onQuickAction={handleQuickAction} onConfigurationChoice={handleConfigurationChoice} onRegenerateImage={handleImageGeneration} />
        </div>
      ) : (
        <div className="nova-chat-scroll min-h-0 flex-1 overflow-y-auto pb-3 pt-1 pr-1">
          <ChatWindow messages={messages} onQuickAction={handleQuickAction} onConfigurationChoice={handleConfigurationChoice} />
          {sending && (
            <div className="mx-auto mt-5 w-full max-w-4xl px-1">
              <NovaActivity activity="NOVA Operation" steps={toActivitySteps(processingStage)} />
            </div>
          )}
        </div>
      )}

      <div className="group relative">
        <div className="pointer-events-none absolute -inset-1 rounded-2xl bg-gradient-to-r from-orb-glow/20 via-[#4C8EF7]/10 to-signal-teal/15 opacity-25 blur-xl transition-opacity duration-300 group-focus-within:opacity-70" />

        <form
          onSubmit={handleSend}
          className={`glass-composer relative flex flex-col ${isEmpty ? "p-6" : "p-4"}`}
        >
          <textarea
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                handleSend(e);
              }
            }}
            rows={isEmpty ? 3 : 2}
            placeholder="Ask NOVA anything, or ask it to check something on the lab server…"
            className={`block w-full resize-none bg-transparent text-[14px] leading-relaxed text-ink-100 placeholder:text-ink-500/80 focus:outline-none ${
              isEmpty ? "h-[82px]" : "h-[48px]"
            }`}
          />

          <div className={`flex flex-wrap items-center justify-between gap-2 ${isEmpty ? "mt-5" : "mt-3"}`}>
            <div className="flex flex-wrap items-center gap-2">
              <CategoryPicker value={category} onChange={setCategory} />

              {toolsSupported && (
                <button
                  type="button"
                  onClick={() => setUseTools((v) => !v)}
                  aria-pressed={useTools}
                  title="Aktifkan tools READ: web.search, web.read_page, diagram.create"
                  className={`flex h-9 shrink-0 items-center gap-1.5 rounded-lg border px-3.5 text-[12px] font-medium transition-colors ${
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
              className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-gradient-to-tr from-[#842BD2] to-orb-glow text-white shadow-[0_0_16px_rgba(168,85,247,0.5)] transition-all hover:brightness-110 active:scale-95 disabled:opacity-50"
            >
              <ArrowUp size={16} strokeWidth={2.5} />
            </button>
          </div>
        </form>
      </div>

      {isEmpty && (
        <div className="mt-[18px]">
          <CapabilityShortcuts />
        </div>
      )}

      <div className={`flex items-center justify-between px-1 pt-1.5 text-ink-500 ${messages.length === 0 ? "hidden" : ""}`}>
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

      <p className={`mb-2 mt-1 text-center text-[10px] text-ink-500/80 ${messages.length === 0 ? "hidden" : ""}`}>
        Chat mendukung pembuatan file konfigurasi MikroTik secara offline. File harus ditinjau sebelum diimpor; NOVA tidak menerapkannya ke router.
      </p>
    </div>
  );
}