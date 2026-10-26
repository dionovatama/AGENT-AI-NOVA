import { AudioLines } from "lucide-react";

/**
 * HUD Ring — replaces the central glossy orb with a non-rotating,
 * voice-reactive-style HUD mark. The existing hero footprint stays unchanged.
 * Motion is pulse-only; no spinning loaders or rotating rings.
 */
export function HudRing({ size = 96 }: { size?: number }) {
  const center = size * 0.36;
  const tickWidth = Math.max(1, size * 0.012);
  const glyphSize = Math.round(size * 0.2);

  return (
    <div
      className="relative flex shrink-0 items-center justify-center"
      style={{ width: size, height: size }}
      role="img"
      aria-label="NOVA HUD ring"
    >
      {/* Soft ambient glow */}
      <div
        className="absolute rounded-full bg-orb-glow/20 blur-xl motion-safe:animate-pulse"
        style={{ inset: "5%" }}
        aria-hidden="true"
      />

      {/* Outer HUD boundary */}
      <div
        className="absolute rounded-full border border-orb-core/35"
        style={{ inset: "8%" }}
        aria-hidden="true"
      />

      {/* Segmented technical ring */}
      <div
        className="absolute rounded-full border-2 border-dashed border-signal-teal/55"
        style={{ inset: "17%" }}
        aria-hidden="true"
      />

      {/* Inner stable ring */}
      <div
        className="absolute rounded-full border border-[#B66BFF]/70 shadow-[0_0_12px_rgba(168,85,247,0.3)]"
        style={{ inset: "27%" }}
        aria-hidden="true"
      />

      {/* Four small calibration ticks */}
      <div className="absolute inset-0" aria-hidden="true">
        <span className="absolute left-1/2 top-[5%] -translate-x-1/2 rounded-full bg-signal-teal shadow-[0_0_7px_#2FD9C4]" style={{ width: tickWidth, height: size * 0.075 }} />
        <span className="absolute bottom-[5%] left-1/2 -translate-x-1/2 rounded-full bg-orb-core shadow-[0_0_7px_rgba(168,85,247,0.9)]" style={{ width: tickWidth, height: size * 0.075 }} />
        <span className="absolute left-[5%] top-1/2 -translate-y-1/2 rounded-full bg-orb-core" style={{ width: size * 0.075, height: tickWidth }} />
        <span className="absolute right-[5%] top-1/2 -translate-y-1/2 rounded-full bg-signal-teal" style={{ width: size * 0.075, height: tickWidth }} />
      </div>

      {/* Minimal center — no glossy sphere */}
      <div
        className="relative flex items-center justify-center rounded-full border border-signal-teal/35 bg-[#11131D]/90 text-signal-teal shadow-[0_0_18px_rgba(47,217,196,0.18)] motion-safe:animate-pulse"
        style={{ width: center, height: center }}
      >
        <AudioLines
          size={glyphSize}
          strokeWidth={1.7}
          className="drop-shadow-[0_0_6px_rgba(47,217,196,0.8)]"
        />
      </div>
    </div>
  );
}
