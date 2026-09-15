import { HudRing } from "./HudRing";
import { CapabilityShortcuts } from "./CapabilityShortcuts";
import type { TaskCategory } from "@/lib/types";

export function WelcomeHero({
  onFill,
}: {
  onFill: (category: TaskCategory, prompt: string) => void;
}) {
  return (
    <div className="flex h-full flex-col items-center justify-center gap-6 text-center">
      <HudRing size={96} />

      <div>
        <p className="font-mono text-xs tracking-[0.3em] text-signal-green">SYSTEM READY</p>
        <p className="mt-2 text-lg text-ink-100">What&apos;s your command, sir?</p>
      </div>

      <CapabilityShortcuts onFill={onFill} />
    </div>
  );
}
