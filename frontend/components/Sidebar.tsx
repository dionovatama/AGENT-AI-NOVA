"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import {
  Plus,
  MessageSquare,
  Wrench,
  Server,
  Network,
  Radio,
  ScrollText,
  Settings as SettingsIcon,
  LogOut,
  PanelLeftClose,
  Trash2,
} from "lucide-react";
import { clearToken } from "@/lib/auth";
import { novaApi } from "@/lib/api";
import { NovaOrb } from "@/components/NovaOrb";
import { SystemPulse } from "@/components/SystemPulse";
import type { ConversationSummary } from "@/lib/types";

// Nav item nyata -- setiap href beneran punya route. TIDAK ada item
// dekoratif seperti "Archived"/"Library" dari referensi desain, karena
// itu bukan konsep yang ada di backend NOVA sekarang. Kalau nanti
// beneran dibangun, baru ditambah di sini -- bukan sebaliknya.
const NAV_ITEMS = [
  { href: "/chat", label: "Chat", icon: MessageSquare, live: true },
  { href: "/tools", label: "Tools", icon: Wrench, live: true },
  { href: "/devices", label: "Devices", icon: Server, live: true },
  { href: "/network", label: "Network Management", icon: Network, live: true },
  { href: "/agent", label: "Remote Agents", icon: Radio, live: true },
  { href: "/audit", label: "Audit Log", icon: ScrollText, live: true },
  { href: "/settings", label: "Settings", icon: SettingsIcon, live: false },
];

export function Sidebar({
  onHide,
  onNavigate,
}: {
  onHide: () => void;
  onNavigate?: () => void;
}) {
  const pathname = usePathname();
  const router = useRouter();
  const searchParams = useSearchParams();
  const searchKey = searchParams.toString();
  const selectedConversationId = searchParams.get("conversation");
  const [email, setEmail] = useState<string | null>(null);
  const [conversations, setConversations] = useState<ConversationSummary[]>([]);
  const [deletingConversationId, setDeletingConversationId] = useState<string | null>(null);
  const [conversationError, setConversationError] = useState<string | null>(null);

  useEffect(() => {
    // Identitas asli lewat GET /auth/me -- kalau gagal (token expired,
    // dll), profile row cukup disembunyikan, TIDAK diisi placeholder palsu
    // (referensi desain pakai avatar+username fiktif "secops_lead" --
    // kita tidak meniru itu, selalu data user yang beneran login).
    novaApi
      .me()
      .then((res) => setEmail(res.email))
      .catch(() => setEmail(null));
    novaApi.listConversations().then((items) => setConversations(items.slice(0, 8))).catch(() => setConversations([]));
  }, [pathname, searchKey]);

  function handleNewChat() {
    router.push(`/chat?new=${Date.now()}`);
    onNavigate?.();
  }

  async function handleDeleteConversation(conversation: ConversationSummary) {
    if (deletingConversationId) return;
    const confirmed = window.confirm(`Hapus percakapan "${conversation.title}"? Semua pesan di dalamnya akan ikut dihapus dan tindakan ini tidak dapat dibatalkan.`);
    if (!confirmed) return;

    setDeletingConversationId(conversation.id);
    setConversationError(null);
    try {
      await novaApi.deleteConversation(conversation.id);
      setConversations((current) => current.filter((item) => item.id !== conversation.id));
      if (selectedConversationId === conversation.id) {
        router.push(`/chat?new=${Date.now()}`);
      }
    } catch (error) {
      setConversationError(error instanceof Error ? error.message : "Gagal menghapus percakapan.");
    } finally {
      setDeletingConversationId(null);
    }
  }

  return (
    <aside className="chrome-glass flex w-[228px] shrink-0 flex-col border-r">
      {/* Brand — gradient ring dari DESIGN.md (violet -> teal), ukuran
          kecil supaya identitas tetap jelas walau ring-nya detail. */}
      <div className="flex items-center gap-2.5 px-[18px] pt-2.5">
        <NovaOrb size={28} />
        <div>
          <p className="font-mono text-xs tracking-[0.3em] text-ink-100">N·O·V·A</p>
          <p className="mt-0.5 text-[10px] uppercase tracking-widest text-ink-500">
            operator console
          </p>
        </div>
        <button
          type="button"
          onClick={onHide}
          aria-label="Hide sidebar"
          title="Hide sidebar"
          className="-mr-1 ml-auto flex h-7 w-7 shrink-0 items-center justify-center rounded-md text-ink-500 transition-colors hover:bg-white/[0.06] hover:text-ink-100"
        >
          <PanelLeftClose size={16} />
        </button>
      </div>

      {/* New Chat — pill capsule sesuai DESIGN.md #Shapes (action
          pills = rounded-full), fungsinya sama seperti sebelumnya. */}
      <div className="mt-5 px-2.5">
        <button
          onClick={handleNewChat}
          className="group flex h-9 w-full items-center justify-center gap-2 rounded-full border border-white/[0.06]
            bg-white/[0.04] px-3 text-[13px] font-medium text-ink-100 shadow-[0_2px_12px_rgba(0,0,0,0.3)]
            transition-all duration-200 hover:border-border-glow/40 hover:bg-white/[0.08]
            hover:shadow-[0_0_16px_rgba(168,85,247,0.2)]"
        >
          <Plus size={16} className="text-orb-core transition-transform duration-300 group-hover:rotate-90" />
          New chat
        </button>
      </div>

      <nav className="flex-1 space-y-px px-2.5 pt-3.5">
        {NAV_ITEMS.map((item) => {
          const active = pathname?.startsWith(item.href);
          const Icon = item.icon;
          return (
            <Link
              key={item.href}
              href={item.href}
              onClick={onNavigate}
              className={`relative flex h-9 items-center gap-2 rounded-lg px-3 text-[13px] transition-all ${
                active
                  ? "border border-border-glow/25 bg-border-glow/[0.15] font-medium text-ink-100 shadow-[inset_0_0_12px_rgba(168,85,247,0.12)]"
                  : "text-ink-500 hover:bg-white/[0.04] hover:text-ink-300"
              }`}
            >
              <Icon size={14} className={active ? "text-orb-core" : "text-ink-500"} />
              <span className="flex-1">{item.label}</span>
              {!item.live && (
                <span
                  className="h-1.5 w-1.5 rounded-full bg-base-600"
                  title="belum tersedia penuh"
                />
              )}
            </Link>
          );
        })}
      </nav>

      <div className="px-3 pb-3">
        <p className="mb-2 px-2 text-[10px] font-semibold uppercase tracking-[0.16em] text-ink-500">Recent chats</p>
        <div className="max-h-48 space-y-1 overflow-y-auto">
          {conversations.map((conversation) => (
            <div key={conversation.id} className="group flex min-w-0 items-center gap-1 rounded-md hover:bg-white/[0.06]">
              <button type="button" onClick={() => { router.push("/chat?conversation=" + conversation.id); onNavigate?.(); }} title={conversation.title} className="min-w-0 flex-1 truncate rounded-md px-2 py-1.5 text-left text-[11px] text-ink-400 transition-colors hover:text-ink-100">
                <span className="mr-2 inline-block align-middle"><MessageSquare size={11} /></span>
                {conversation.title}
              </button>
              <button
                type="button"
                onClick={() => void handleDeleteConversation(conversation)}
                disabled={deletingConversationId !== null}
                aria-label={`Hapus percakapan ${conversation.title}`}
                title="Hapus percakapan"
                className="mr-1 flex h-7 w-7 shrink-0 items-center justify-center rounded text-ink-600 opacity-0 transition-all hover:bg-signal-rose/10 hover:text-signal-rose focus:opacity-100 group-hover:opacity-100 disabled:cursor-not-allowed disabled:opacity-40"
              >
                <Trash2 size={12} />
              </button>
            </div>
          ))}
          {conversationError && <p role="alert" className="px-2 py-1 text-[10px] text-signal-rose">{conversationError}</p>}
          {conversations.length === 0 && <p className="px-2 text-[11px] text-ink-600">Belum ada riwayat chat</p>}
        </div>
      </div>

      <div className="border-t border-white/[0.06] bg-black/20 p-3">
        {/* Status backend dipindah ke sini dari header atas yang dihapus. */}
        <div className="mb-2.5 px-1">
          <SystemPulse compact />
        </div>
        {email && (
          <div className="mb-1.5 flex items-center gap-2.5 rounded-xl border border-white/[0.05] bg-white/[0.03] px-2.5 py-2">
            <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-gradient-to-tr from-orb-glow to-orb-core text-[12px] font-bold text-white">
              {email.slice(0, 2).toUpperCase()}
            </div>
            <p className="truncate text-[12px] text-ink-300">{email}</p>
          </div>
        )}
        <button
          onClick={() => {
            clearToken();
            router.push("/login");
          }}
          className="flex w-full items-center gap-2 rounded-sm px-3 py-2 text-left text-[13px] text-ink-500 transition-colors hover:bg-white/[0.04] hover:text-signal-rose"
        >
          <LogOut size={14} />
          Keluar
        </button>
      </div>
    </aside>
  );
}