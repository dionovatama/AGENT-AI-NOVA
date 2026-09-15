import type { ChatMessage } from "@/lib/types";

export function ChatWindow({ messages }: { messages: ChatMessage[] }) {
  if (messages.length === 0) {
    return (
      <div className="flex h-full flex-col items-center justify-center text-center">
        <p className="font-mono text-xs tracking-[0.2em] text-ink-500">AWAITING INPUT</p>
        <p className="mt-2 max-w-sm text-sm text-ink-500">
          Tanyakan sesuatu, Tuan. Pilih kategori task di bawah supaya Model
          Router memilih model yang paling tepat.
        </p>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-4">
      {messages.map((msg, i) => (
        <div key={i} className={msg.role === "user" ? "flex justify-end" : "flex justify-start"}>
          <div
            className={`max-w-[75%] rounded-md px-4 py-2.5 text-sm leading-relaxed ${
              msg.role === "user"
                ? "bg-signal-teal/15 text-ink-100"
                : "panel text-ink-100"
            }`}
          >
            <p className="whitespace-pre-wrap">{msg.content}</p>
            {msg.meta?.model_used && (
              <p className="mt-2 font-mono text-[11px] text-ink-500">
                {msg.meta.model_used}
                {msg.meta.used_fallback ? " · fallback" : ""}
              </p>
            )}
            {/* Indikator tool yang BENAR-BENAR dipanggil backend -- bukan
                tebakan dari isi jawaban. Kalau checkbox "gunakan web.search"
                dicentang tapi badge ini TIDAK muncul, berarti model
                menjawab dari memori sendiri tanpa benar-benar mencari
                (lihat kasus tanggal pelantikan presiden yang sempat salah). */}
            {msg.meta?.tools_used && msg.meta.tools_used.length > 0 ? (
              <p className="mt-1 font-mono text-[11px] text-signal-teal">
                🔍 tool dipanggil: {msg.meta.tools_used.join(", ")}
              </p>
            ) : (
              msg.meta?.tools_offered && (
                <p className="mt-1 font-mono text-[11px] text-signal-amber/70">
                  (tools ditawarkan tapi model tidak memanggil tool apa
                  pun -- jawaban murni dari memori model)
                </p>
              )
            )}
            {msg.meta?.error && (
              <p className="mt-2 font-mono text-[11px] text-signal-rose">{msg.meta.error}</p>
            )}
          </div>
        </div>
      ))}
    </div>
  );
}
