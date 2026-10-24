'use client';

import React, { useState, useRef, useEffect } from 'react';
import { TASK_CATEGORIES, TOOL_CALLING_CATEGORIES, type TaskCategory } from '@/lib/types';

interface ChatComposerProps {
  onSend: (message: string, category?: string, enableTools?: boolean) => void;
  disabled?: boolean;
  initialMessage?: string;
}

export default function ChatComposer({ onSend, disabled, initialMessage }: ChatComposerProps) {
  const [message, setMessage] = useState(initialMessage || '');
  const [category, setCategory] = useState<TaskCategory>('general_chat');
  const [enableTools, setEnableTools] = useState(true);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  // Set initial message if provided
  useEffect(() => {
    if (initialMessage) {
      setMessage(initialMessage);
      textareaRef.current?.focus();
    }
  }, [initialMessage]);

  // Auto-resize textarea
  useEffect(() => {
    if (textareaRef.current) {
      textareaRef.current.style.height = 'auto';
      textareaRef.current.style.height = `${Math.min(textareaRef.current.scrollHeight, 150)}px`;
    }
  }, [message]);

  const handleSend = () => {
    if (message.trim() && !disabled) {
      onSend(message, category, enableTools);
      setMessage('');
      if (textareaRef.current) {
        textareaRef.current.style.height = 'auto';
      }
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  const showToolToggle = TOOL_CALLING_CATEGORIES.includes(category);

  return (
    <div className="relative bg-white/[0.03] border border-white/[0.08] rounded-2xl p-3
      shadow-[0_0_30px_rgba(124,58,237,0.04)] hover:border-white/[0.12] 
      focus-within:border-[var(--nova-accent-purple)]/30 focus-within:shadow-[0_0_40px_rgba(124,58,237,0.08)]
      transition-all duration-300">
      {/* Textarea */}
      <div className="flex items-start gap-2.5 min-h-[52px]">
        <div className="text-[var(--nova-accent-purple)] mt-1 text-sm">✦</div>
        <textarea
          ref={textareaRef}
          value={message}
          onChange={(e) => setMessage(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder="Ask NOVA anything..."
          disabled={disabled}
          rows={2}
          className="flex-1 bg-transparent text-white/90 text-sm placeholder:text-white/25 
            resize-none focus:outline-none min-h-[42px] max-h-[150px] py-1 leading-relaxed"
        />
        <button
          onClick={handleSend}
          disabled={!message.trim() || disabled}
          className="p-2 rounded-lg bg-[var(--nova-accent-purple)] text-white shrink-0
            disabled:opacity-20 disabled:cursor-not-allowed
            hover:bg-[var(--nova-accent-purple)]/80 transition-all duration-200
            shadow-[0_0_12px_rgba(124,58,237,0.3)]"
        >
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
            <path d="M22 2L11 13M22 2L15 22L11 13M22 2L2 9L11 13" />
          </svg>
        </button>
      </div>

      {/* Bottom Bar */}
      <div className="flex items-center justify-between mt-2 pt-2 border-t border-white/[0.05]">
        <div className="flex items-center gap-0.5 overflow-x-auto">
          {TASK_CATEGORIES.map((cat) => (
            <button
              key={cat.value}
              onClick={() => setCategory(cat.value)}
              className={`px-2 py-1 rounded-md text-[11px] whitespace-nowrap transition-all duration-200 ${
                category === cat.value
                  ? 'bg-white/[0.08] text-white/90'
                  : 'text-white/30 hover:text-white/50 hover:bg-white/[0.03]'
              }`}
            >
              {cat.label}
            </button>
          ))}
        </div>
        <div className="flex items-center gap-2 shrink-0 ml-2">
          {showToolToggle && (
            <button
              onClick={() => setEnableTools(!enableTools)}
              className={`flex items-center gap-1 px-2 py-1 rounded-md text-[11px] transition-all duration-200 ${
                enableTools
                  ? 'text-[var(--nova-accent-cyan)] bg-[var(--nova-accent-cyan)]/10'
                  : 'text-white/25 hover:text-white/40'
              }`}
            >
              <span>🔧</span>
              <span>{enableTools ? 'tools' : 'no tools'}</span>
            </button>
          )}
          <span className="text-[10px] text-white/15 font-mono">
            READ (AUTO)
          </span>
        </div>
      </div>
    </div>
  );
}
