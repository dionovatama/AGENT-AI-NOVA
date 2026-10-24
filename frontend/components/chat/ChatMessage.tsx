'use client';

import React from 'react';
import MarkdownRenderer from '@/components/chat/MarkdownRenderer';

interface ToolCall {
  tool_name: string;
  success: boolean;
  result?: string;
}

interface Message {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  timestamp: Date;
  toolCalls?: ToolCall[];
}

interface ChatMessageProps {
  message: Message;
}

export default function ChatMessage({ message }: ChatMessageProps) {
  const isUser = message.role === 'user';

  if (isUser) {
    return (
      <div className="flex justify-end">
        <div className="max-w-[75%] rounded-2xl rounded-br-md px-4 py-2.5 
          bg-[var(--nova-accent-purple)]/15 border border-[var(--nova-accent-purple)]/20
          text-white/90">
          <p className="text-sm leading-relaxed whitespace-pre-wrap">{message.content}</p>
        </div>
      </div>
    );
  }

  return (
    <div className="flex items-start gap-3">
      {/* NOVA avatar */}
      <div className="shrink-0 mt-0.5">
        <div className="w-6 h-6 rounded-full bg-gradient-to-br from-[var(--nova-accent-purple)] to-[var(--nova-accent-cyan)] flex items-center justify-center">
          <span className="text-white text-[10px] font-bold">N</span>
        </div>
      </div>

      <div className="flex-1 min-w-0">
        {/* NOVA label */}
        <div className="flex items-center gap-2 mb-1.5">
          <span className="text-xs font-medium text-[var(--nova-accent-purple)]">✦ NOVA</span>
        </div>

        {/* Markdown content */}
        <MarkdownRenderer content={message.content} />

        {/* Tool calls */}
        {message.toolCalls && message.toolCalls.length > 0 && (
          <div className="mt-3 flex flex-wrap gap-1.5">
            {message.toolCalls.map((tool, i) => (
              <span
                key={i}
                className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-md text-[10px] font-mono
                  ${tool.success
                    ? 'bg-[var(--nova-accent-cyan)]/10 border border-[var(--nova-accent-cyan)]/15 text-[var(--nova-accent-cyan)]'
                    : 'bg-red-400/10 border border-red-400/15 text-red-400'
                  }`}
              >
                <span>{tool.success ? '✓' : '✗'}</span>
                {tool.tool_name}
              </span>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
