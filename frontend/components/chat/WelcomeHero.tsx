import { NovaOrb } from "@/components/NovaOrb";

export function WelcomeHero() {
  return (
    <div className="flex h-full flex-col items-center justify-center text-center">
      <NovaOrb size={96} />
      <p className="mt-6 text-2xl font-medium text-ink-100">How can I help you today?</p>
      <p className="mt-1.5 text-sm text-ink-500">NOVA — Nexus Operation Virtual Assistant</p>
    </div>
  );
}
