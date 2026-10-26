'use client';

import React, { useEffect, useRef, useState } from 'react';
import { Check, Copy, AlertTriangle } from 'lucide-react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { Prism as SyntaxHighlighter } from 'react-syntax-highlighter';
import { oneDark } from 'react-syntax-highlighter/dist/esm/styles/prism';
import mermaid from 'mermaid';

function CopyButton({ value, label = "Copy" }: { value: string; label?: string }) {
  const [copied, setCopied] = useState(false);

  async function handleCopy() {
    try {
      await navigator.clipboard.writeText(value);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1600);
    } catch {
      setCopied(false);
    }
  }

  return (
    <button
      type="button"
      onClick={handleCopy}
      title={copied ? "Copied" : label}
      aria-label={copied ? "Copied to clipboard" : label}
      className="inline-flex items-center gap-1.5 rounded-md border border-white/[0.08] bg-white/[0.04] px-2 py-1 text-[10px] text-ink-400 transition-colors hover:border-orb-glow/40 hover:text-ink-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-orb-glow/60"
    >
      {copied ? <Check size={12} className="text-signal-green" /> : <Copy size={12} />}
      {copied ? "Copied" : label}
    </button>
  );
}

// Initialize mermaid with NOVA theme
mermaid.initialize({
  startOnLoad: false,
  theme: 'dark',
  themeVariables: {
    darkMode: true,
    background: '#0f0f1a',
    primaryColor: '#7c3aed',
    primaryTextColor: '#e2e8f0',
    primaryBorderColor: '#7c3aed',
    lineColor: '#475569',
    secondaryColor: '#06b6d4',
    tertiaryColor: '#141425',
    fontFamily: 'Inter, system-ui, sans-serif',
  },
});

function MermaidDiagram({ code }: { code: string }) {
  const containerRef = useRef<HTMLDivElement>(null);
  const [svg, setSvg] = useState<string>('');
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const renderDiagram = async () => {
      try {
        const id = `mermaid-${Math.random().toString(36).substring(2, 11)}`;
        const { svg: renderedSvg } = await mermaid.render(id, code);
        setSvg(renderedSvg);
        setError(null);
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Failed to render diagram');
      }
    };
    renderDiagram();
  }, [code]);

  if (error) {
    return (
      <div className="my-3 flex gap-2 rounded-xl border border-signal-rose/25 bg-signal-rose/[0.07] p-3 text-xs text-signal-rose">
        <AlertTriangle size={15} className="mt-0.5 shrink-0" />
        <div className="min-w-0"><p className="mb-1 text-[11px] font-semibold uppercase tracking-wider">Diagram gagal dirender</p><p className="break-words text-ink-300">{error}</p></div>
      </div>
    );
  }

  return (
    <div
      ref={containerRef}
      className="my-3 p-4 rounded-lg bg-white/[0.02] border border-white/[0.06] overflow-x-auto"
      dangerouslySetInnerHTML={{ __html: svg }}
    />
  );
}

interface MarkdownRendererProps {
  content: string;
  className?: string;
}

/**
 * Repair compact pipe tables occasionally returned by models as a single line.
 * Standard GFM tables are left unchanged; this only runs when a table separator
 * row is present and the content has no line breaks.
 */
function normalizeMarkdownTables(content: string): string {
  if (content.includes('\n') || !/\|\s*:?-{3,}:?\s*\|/.test(content)) {
    return content;
  }

  return content
    .replace(/\\\|/g, '|')
    .replace(/\|\s+\|/g, '|\n|');
}

export default function MarkdownRenderer({ content, className = '' }: MarkdownRendererProps) {
  const markdownContent = normalizeMarkdownTables(content);

  return (
    <div className={`nova-markdown ${className}`}>
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          // Headings
          h1: ({ children }) => (
            <h1 className="text-lg font-semibold text-white mt-4 mb-2 first:mt-0">{children}</h1>
          ),
          h2: ({ children }) => (
            <h2 className="text-base font-semibold text-white mt-3 mb-1.5 first:mt-0">{children}</h2>
          ),
          h3: ({ children }) => (
            <h3 className="text-sm font-semibold text-white mt-3 mb-1 first:mt-0">{children}</h3>
          ),
          h4: ({ children }) => (
            <h4 className="text-sm font-medium text-white/90 mt-2 mb-1 first:mt-0">{children}</h4>
          ),

          // Paragraphs
          p: ({ children }) => (
            <p className="text-sm leading-relaxed text-[var(--nova-text-primary)] mb-2 last:mb-0">{children}</p>
          ),

          // Strong / Emphasis
          strong: ({ children }) => (
            <strong className="font-semibold text-white">{children}</strong>
          ),
          em: ({ children }) => (
            <em className="italic text-white/80">{children}</em>
          ),

          // Lists
          ul: ({ children }) => (
            <ul className="list-none space-y-1 mb-2 last:mb-0">{children}</ul>
          ),
          ol: ({ children }) => (
            <ol className="list-decimal list-inside space-y-1 mb-2 last:mb-0 text-sm text-[var(--nova-text-primary)]">{children}</ol>
          ),
          li: ({ children }) => (
            <li className="text-sm text-[var(--nova-text-primary)] flex items-start gap-1.5">
              <span className="text-[var(--nova-accent-cyan)] mt-1.5 shrink-0 text-[6px]">●</span>
              <span className="flex-1">{children}</span>
            </li>
          ),

          // Links
          a: ({ href, children }) => (
            <a
              href={href}
              target="_blank"
              rel="noopener noreferrer"
              className="text-[var(--nova-accent-cyan)] hover:text-[var(--nova-accent-cyan)]/80 underline underline-offset-2 decoration-[var(--nova-accent-cyan)]/30 transition-colors"
            >
              {children}
            </a>
          ),

          // Blockquote
          blockquote: ({ children }) => (
            <blockquote className="border-l-2 border-[var(--nova-accent-purple)]/50 pl-3 my-2 text-white/60 italic">
              {children}
            </blockquote>
          ),

          // Inline code
          code: ({ className, children, ...props }) => {
            const match = /language-(\w+)/.exec(className || '');
            const lang = match ? match[1] : '';
            const codeStr = String(children).replace(/\n$/, '');

            // Check for mermaid
            if (lang === 'mermaid') {
              return <MermaidDiagram code={codeStr} />;
            }

            // Block code
            if (lang || codeStr.includes('\n')) {
              return (
                <div className="my-3 overflow-hidden rounded-xl border border-white/[0.09] bg-[#0B0D13] shadow-[0_8px_24px_-18px_rgba(0,0,0,0.9)]">
                  {lang && (
                    <div className="flex items-center justify-between gap-3 border-b border-white/[0.06] bg-[#11131D] px-3 py-2">
                      <span className="truncate font-mono text-[10px] uppercase tracking-wider text-ink-400">{lang || "OUTPUT"} <span className="ml-1 normal-case tracking-normal text-ink-500">· {codeStr.split("\n").length} baris</span></span>
                      <CopyButton value={codeStr} label="Salin kode" />
                    </div>
                  )}
                  <SyntaxHighlighter
                    style={oneDark}
                    language={lang || 'text'}
                    PreTag="div"
                    customStyle={{
                      margin: 0,
                      padding: '14px 16px',
                      fontSize: '12px',
                      lineHeight: '1.7',
                      background: 'transparent',
                      borderRadius: 0,
                      overflowX: 'auto',
                    }}
                  >
                    {codeStr}
                  </SyntaxHighlighter>
                </div>
              );
            }

            // Inline code
            return (
              <code className="px-1.5 py-0.5 rounded bg-white/[0.08] text-[var(--nova-accent-cyan)] text-[13px] font-mono" {...props}>
                {children}
              </code>
            );
          },

          // Horizontal rule
          hr: () => <hr className="my-3 border-white/[0.06]" />,

          // Table
          table: ({ children }) => (
            <div className="my-3 overflow-x-auto rounded-xl border border-white/[0.09] bg-white/[0.015]">
              <table className="w-full min-w-[420px] border-collapse text-sm">{children}</table>
            </div>
          ),
          thead: ({ children }) => (
            <thead className="bg-white/[0.04] text-white/60 text-xs uppercase tracking-wider">{children}</thead>
          ),
          tbody: ({ children }) => (
            <tbody className="divide-y divide-white/[0.04]">{children}</tbody>
          ),
          tr: ({ children }) => (
            <tr className="hover:bg-white/[0.02] transition-colors">{children}</tr>
          ),
          th: ({ children }) => (
            <th className="border-b border-white/[0.07] px-3 py-2.5 text-left font-semibold text-ink-200">{children}</th>
          ),
          td: ({ children }) => (
            <td className="border-b border-white/[0.04] px-3 py-2.5 align-top text-[var(--nova-text-primary)]">{children}</td>
          ),

          // Pre - just pass through, code handles it
          pre: ({ children }) => <>{children}</>,
        }}
      >
        {markdownContent}
      </ReactMarkdown>
    </div>
  );
}
