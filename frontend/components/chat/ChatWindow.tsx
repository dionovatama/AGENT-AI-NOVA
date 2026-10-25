"use client";

import { useState } from "react";
import type { ChatMessage, TaskCategory } from "@/lib/types";
import { WelcomeHero } from "@/components/chat/WelcomeHero";
import { MermaidDiagram } from "@/components/chat/MermaidDiagram";

function InlineMarkdown({ text }: { text: string }) {
  const parts = text.split(/(\*\*[^*]+\*\*|__[^_]+__|\`[^\`]+\`)/g);

  return (
    <>
      {parts.map((part, index) => {
        if ((part.startsWith("**") && part.endsWith("**")) || (part.startsWith("__") && part.endsWith("__"))) {
          return <strong key={index} className="font-semibold text-ink-100">{part.slice(2, -2)}</strong>;
        }
        if (part.startsWith("`") && part.endsWith("`")) {
          return (
            <code key={index} className="rounded-md border border-white/[0.07] bg-white/[0.05] px-1.5 py-0.5 font-mono text-[0.92em] text-orb-core">
              {part.slice(1, -1)}
            </code>
          );
        }
        return <span key={index}>{part}</span>;
      })}
    </>
  );
}

function MarkdownContent({ content }: { content: string }) {
  const lines = content.replace(/\r\n/g, "\n").split("\n");
  const blocks: React.ReactNode[] = [];
  let i = 0;

  while (i < lines.length) {
    const line = lines[i];

    if (line.trim().startsWith("```")) {
      const language = line.trim().slice(3).trim();
      const code: string[] = [];
      i += 1;
      while (i < lines.length && !lines[i].trim().startsWith("```")) {
        code.push(lines[i]);
        i += 1;
      }
      if (i < lines.length) i += 1;

      blocks.push(
        <div key={blocks.length} className="my-3 overflow-hidden rounded-xl border border-white/[0.07] bg-[#0A0B10]">
          {language && (
            <div className="border-b border-white/[0.06] px-3 py-1.5 font-mono text-[10px] uppercase tracking-wider text-ink-500">
              {language}
            </div>
          )}
          <pre className="overflow-x-auto px-4 py-3 font-mono text-[12px] leading-6 text-ink-200">
            <code>{code.join("\n")}</code>
          </pre>
        </div>
      );
      continue;
    }

    const heading = line.match(/^(#{1,3})\s+(.+)$/);
    if (heading) {
      blocks.push(
        <h3 key={blocks.length} className="mb-2 mt-4 text-[15px] font-semibold text-ink-100 first:mt-0">
          <InlineMarkdown text={heading[2]} />
        </h3>
      );
      i += 1;
      continue;
    }

    if (/^\s*[-*]\s+/.test(line)) {
      const items: string[] = [];
      while (i < lines.length && /^\s*[-*]\s+/.test(lines[i])) {
        items.push(lines[i].replace(/^\s*[-*]\s+/, ""));
        i += 1;
      }
      blocks.push(
        <ul key={blocks.length} className="my-2 ml-5 list-disc space-y-1.5 text-ink-200">
          {items.map((item, index) => <li key={index}><InlineMarkdown text={item} /></li>)}
        </ul>
      );
      continue;
    }

    if (/^\s*\d+\.\s+/.test(line)) {
      const items: string[] = [];
      while (i < lines.length && /^\s*\d+\.\s+/.test(lines[i])) {
        items.push(lines[i].replace(/^\s*\d+\.\s+/, ""));
        i += 1;
      }
      blocks.push(
        <ol key={blocks.length} className="my-2 ml-5 list-decimal space-y-1.5 text-ink-200">
          {items.map((item, index) => <li key={index}><InlineMarkdown text={item} /></li>)}
        </ol>
      );
      continue;
    }

    if (/^\s*>\s?/.test(line)) {
      blocks.push(
        <blockquote key={blocks.length} className="my-3 border-l-2 border-orb-glow/50 pl-3 text-ink-300">
          <InlineMarkdown text={line.replace(/^\s*>\s?/, "")} />
        </blockquote>
      );
      i += 1;
      continue;
    }

    if (!line.trim()) {
      i += 1;
      continue;
    }

    const paragraph: string[] = [line];
    i += 1;
    while (
      i < lines.length &&
      lines[i].trim() &&
      !lines[i].trim().startsWith("```") &&
      !/^(#{1,3})\s+/.test(lines[i]) &&
      !/^\s*[-*]\s+/.test(lines[i]) &&
      !/^\s*\d+\.\s+/.test(lines[i]) &&
      !/^\s*>\s?/.test(lines[i])
    ) {
      paragraph.push(lines[i]);
      i += 1;
    }

    blocks.push(
      <p key={blocks.length} className="my-2 leading-7 text-ink-100">
        <InlineMarkdown text={paragraph.join("\n")} />
      </p>
    );
  }

  return <div className="text-[14px]">{blocks}</div>;
}

/**
 * Evidence metadata is intentionally quiet and expandable. It provides
 * operational provenance without exposing model chain-of-thought.
 */
function MessageMeta({ meta }: { meta: NonNullable<ChatMessage["meta"]> }) {
  const [expanded, setExpanded] = useState(false);

  const hasTools = !!meta.tools_used && meta.tools_used.length > 0;
  const offeredButUnused = !hasTools && meta.tools_offered;
  const hasDetail = hasTools || offeredButUnused;

  if (!meta.model_used && !hasDetail && !meta.error) return null;

  return (
    <div className="mt-3 border-t border-white/[0.05] pt-2">
      <button
        type="button"
        onClick={() => setExpanded((v) => !v)}
        disabled={!hasDetail}
        className="flex items-center gap-1.5 font-mono text-[10px] text-ink-500 transition-colors hover:text-ink-300 disabled:pointer-events-none"
      >
        {hasDetail && (
          <span className={`inline-block transition-transform ${expanded ? "rotate-90" : ""}`}>
            ›
          </span>
        )}
        <span>{meta.model_used}</span>
        {meta.used_fallback && <span className="text-signal-amber">· fallback</span>}
        {hasTools && <span className="text-signal-teal">· {meta.tools_used!.length} tool dipanggil</span>}
        {offeredButUnused && <span className="text-signal-amber/80">· tidak memanggil tool</span>}
      </button>

      {expanded && hasDetail && (
        <div className="mt-1.5 pl-3.5 font-mono text-[10px] text-ink-500">
          {hasTools ? (
            <p className="text-signal-teal">🔍 {meta.tools_used!.join(", ")}</p>
          ) : (
            <p className="text-signal-amber/80">
              tools ditawarkan tapi model tidak memanggil tool apa pun — jawaban murni dari memori model
            </p>
          )}
        </div>
      )}

      {meta.error && <p className="mt-1.5 font-mono text-[10px] text-signal-rose">{meta.error}</p>}
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
    <div className="mx-auto flex w-full max-w-4xl flex-col gap-5 px-1">
      {messages.map((msg, i) =>
        msg.role === "user" ? (
          <div key={i} className="flex justify-end">
            <div className="max-w-[78%] rounded-2xl rounded-br-md border border-white/[0.06] bg-white/[0.065] px-4 py-2.5 text-[13px] leading-6 text-ink-100 shadow-[0_6px_20px_-12px_rgba(0,0,0,0.8)]">
              <p className="whitespace-pre-wrap break-words">{msg.content}</p>
            </div>
          </div>
        ) : (
          <div key={i} className="min-w-0 px-1 sm:px-2">
            <div className="mb-1.5 flex items-center gap-2">
              <span className="font-mono text-[13px] text-orb-core drop-shadow-[0_0_7px_rgba(192,132,252,0.45)]">✦</span>
              <span className="text-[11px] font-medium tracking-wide text-ink-400">NOVA</span>
            </div>

            <MarkdownContent content={msg.content} />

            {msg.diagrams && msg.diagrams.length > 0 && (
              <div className="mt-3 flex flex-col gap-3">
                {msg.diagrams.map((d, j) => <MermaidDiagram key={j} diagram={d} />)}
              </div>
            )}
            {msg.meta && <MessageMeta meta={msg.meta} />}
          </div>
        )
      )}
    </div>
  );
}
