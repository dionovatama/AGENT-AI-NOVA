import { HudRing } from "@/components/chat/HudRing";

export function WelcomeHero() {
  return (
    <div className="panel-glass flex h-full min-h-[420px] flex-col items-center justify-center p-8 text-center">
      <HudRing size={128} />
      <p className="mt-6 text-2xl font-medium text-ink-100">How can I help you today?</p>
      <p className="mt-1.5 text-sm text-ink-500">NOVA — Nexus Operation Virtual Assistant</p>
    </div>
  );
}
