'use client';

import React, { useEffect, useRef, useState } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { Prism as SyntaxHighlighter } from 'react-syntax-highlighter';
import { oneDark } from 'react-syntax-highlighter/dist/esm/styles/prism';
import mermaid from 'mermaid';

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
      <div className="my-3 p-3 rounded-lg bg-red-500/10 border border-red-500/20 text-red-400 text-xs font-mono">
        <p className="mb-1 text-red-300 text-[11px] uppercase tracking-wider">Diagram Error</p>
        {error}
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

export default function MarkdownRenderer({ content, className = '' }: MarkdownRendererProps) {
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
                <div className="my-3 rounded-lg overflow-hidden border border-white/[0.06]">
                  {lang && (
                    <div className="flex items-center justify-between px-3 py-1.5 bg-white/[0.04] border-b border-white/[0.06]">
                      <span className="text-[10px] text-white/30 font-mono uppercase tracking-wider">{lang}</span>
                      <button
                        onClick={() => navigator.clipboard.writeText(codeStr)}
                        className="text-[10px] text-white/30 hover:text-white/60 transition-colors"
                      >
                        Copy
                      </button>
                    </div>
                  )}
                  <SyntaxHighlighter
                    style={oneDark}
                    language={lang || 'text'}
                    PreTag="div"
                    customStyle={{
                      margin: 0,
                      padding: '12px 16px',
                      fontSize: '12px',
                      lineHeight: '1.6',
                      background: 'rgba(0, 0, 0, 0.3)',
                      borderRadius: 0,
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
            <div className="my-3 overflow-x-auto rounded-lg border border-white/[0.06]">
              <table className="w-full text-sm">{children}</table>
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
            <th className="px-3 py-2 text-left font-medium">{children}</th>
          ),
          td: ({ children }) => (
            <td className="px-3 py-2 text-[var(--nova-text-primary)]">{children}</td>
          ),

          // Pre - just pass through, code handles it
          pre: ({ children }) => <>{children}</>,
        }}
      >
        {content}
      </ReactMarkdown>
    </div>
  );
}
