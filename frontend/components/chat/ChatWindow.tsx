"use client";

import { useState } from "react";
import type { ChatMessage, TaskCategory } from "@/lib/types";
import { WelcomeHero } from "@/components/chat/WelcomeHero";

/**
 * Evidence metadata (model_used / tools_used) BUKAN dekorasi -- ini satu-
 * satunya cara verifikasi "NOVA beneran nyari atau ngarang dari memori"
 * (lihat catatan di lib/types.ts dan kasus tanggal pelantikan presiden
 * yang sempat salah). Didesain quiet (satu baris mono, expandable),
 * TIDAK pernah dihapus sepenuhnya -- itu bertentangan dengan Core
 * Principle project ini ("LLM = untrusted decision maker").
 */
function MessageMeta({ meta }: { meta: NonNullable<ChatMessage["meta"]> }) {
  const [expanded, setExpanded] = useState(false);

  const hasTools = !!meta.tools_used && meta.tools_used.length > 0;
  const offeredButUnused = !hasTools && meta.tools_offered;
  const hasDetail = hasTools || offeredButUnused;

  if (!meta.model_used && !hasDetail && !meta.error) return null;

  return (
    <div className="mt-2.5 border-t border-base-700/60 pt-1.5">
      <button
        type="button"
        onClick={() => setExpanded((v) => !v)}
        disabled={!hasDetail}
        className="flex items-center gap-1.5 font-mono text-[11px] text-ink-500 transition-colors hover:text-ink-300 disabled:pointer-events-none"
      >
        {hasDetail && (
          <span className={`inline-block transition-transform ${expanded ? "rotate-90" : ""}`}>
            ›
          </span>
        )}
        <span>{meta.model_used}</span>
        {meta.used_fallback && <span className="text-signal-amber">· fallback</span>}
        {hasTools && (
          <span className="text-signal-teal">
            · {meta.tools_used!.length} tool dipanggil
          </span>
        )}
        {offeredButUnused && <span className="text-signal-amber/80">· tidak memanggil tool</span>}
      </button>

      {expanded && hasDetail && (
        <div className="mt-1.5 pl-3.5 font-mono text-[11px] text-ink-500">
          {hasTools ? (
            <p className="text-signal-teal">🔍 {meta.tools_used!.join(", ")}</p>
          ) : (
            <p className="text-signal-amber/80">
              tools ditawarkan tapi model tidak memanggil tool apa pun — jawaban murni
              dari memori model
            </p>
          )}
        </div>
      )}

      {meta.error && <p className="mt-1.5 font-mono text-[11px] text-signal-rose">{meta.error}</p>}
    </div>
  );
}

export function ChatWindow({
  messages,
  onQuickAction,
}: {
  messages: ChatMessage[];
  onQuickAction: (category: TaskCategory, prompt: string, useTools?: boolean) => void;
}) {
  if (messages.length === 0) {
    return <WelcomeHero onQuickAction={onQuickAction} />;
  }

  return (
    <div className="mx-auto flex w-full max-w-[720px] flex-col gap-7">
      {messages.map((msg, i) =>
        msg.role === "user" ? (
          <div key={i} className="flex justify-end">
            <div className="max-w-[70%] rounded-md bg-base-800/70 px-3.5 py-2 text-[13px] leading-relaxed text-ink-100">
              <p className="whitespace-pre-wrap">{msg.content}</p>
            </div>
          </div>
        ) : (
          <div key={i}>
            <p className="whitespace-pre-wrap text-[14px] leading-[1.7] text-ink-100">
              {msg.content}
            </p>
            {msg.meta && <MessageMeta meta={msg.meta} />}
          </div>
        )
      )}
    </div>
  );
}
