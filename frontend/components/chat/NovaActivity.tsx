"use client";

import { Check, Circle, Loader2 } from "lucide-react";

export type ProcessingStage = "understand" | "process" | "respond";

const STAGES: Array<{ id: ProcessingStage; label: string; detail: string }> = [
  { id: "understand", label: "Memahami permintaan", detail: "NOVA sedang memahami konteks pertanyaan..." },
  { id: "process", label: "Memproses permintaan", detail: "Menghubungkan request ke AI gateway dan capability yang tersedia..." },
  { id: "respond", label: "Menyiapkan respons", detail: "Menyusun jawaban berdasarkan hasil pemrosesan..." },
];

function stageIndex(stage: ProcessingStage) {
  return STAGES.findIndex((item) => item.id === stage);
}

export function NovaActivity({
  stage,
  toolsEnabled = false,
}: {
  stage: ProcessingStage;
  toolsEnabled?: boolean;
}) {
  const activeIndex = stageIndex(stage);

  return (
    <div className="mb-1 max-w-[620px] rounded-xl border border-white/[0.07] bg-base-900/70 px-4 py-3.5 shadow-[0_10px_35px_rgba(0,0,0,0.18)]">
      <div className="mb-3 flex items-center gap-2">
        <span className="flex h-6 w-6 items-center justify-center rounded-md bg-orb-glow/10 text-orb-glow">
          ✦
        </span>
        <div>
          <p className="text-[12px] font-medium text-ink-200">NOVA Operation</p>
          <p className="font-mono text-[10px] uppercase tracking-[0.14em] text-ink-500">
            Live processing
          </p>
        </div>
      </div>

      <div className="space-y-2">
        {STAGES.map((item, index) => {
          const done = index < activeIndex;
          const active = index === activeIndex;

          return (
            <div key={item.id} className="flex items-start gap-2.5">
              <span className="mt-0.5 flex h-4 w-4 shrink-0 items-center justify-center">
                {done ? (
                  <Check size={13} className="text-signal-green" />
                ) : active ? (
                  <Loader2 size={13} className="animate-spin text-signal-teal" />
                ) : (
                  <Circle size={8} className="fill-base-600 text-base-600" />
                )}
              </span>

              <div className="min-w-0">
                <p
                  className={`text-[12px] ${
                    done
                      ? "text-ink-500"
                      : active
                        ? "text-ink-100"
                        : "text-ink-600"
                  }`}
                >
                  {item.label}
                </p>
                {active && (
                  <p className="mt-0.5 text-[11px] leading-relaxed text-ink-500">
                    {item.detail}
                  </p>
                )}
                {active && item.id === "process" && toolsEnabled && (
                  <p className="mt-1 font-mono text-[10px] text-signal-teal/80">
                    READ capabilities enabled · execution changes are not performed here
                  </p>
                )}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
