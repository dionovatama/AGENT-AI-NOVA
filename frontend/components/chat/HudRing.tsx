import { Boxes } from "lucide-react";

/**
 * "Luminous Quantum Sphere" — hero orb dari DESIGN.md/code.html
 * (design system "Obsidian Violet Operator" yang diberikan Tuan).
 *
 * INI MENGGANTIKAN versi gambar PNG (public/hud/hud-ring.png) yang
 * dipakai sebelumnya -- spec baru ini lebih detail (3 layer motion
 * independen) DAN theme-integrated (semua warna dari token Tailwind,
 * bukan file gambar statis yang tidak ikut berubah kalau palet
 * berubah lagi nanti). File gambar lama dibiarkan ada di public/hud/
 * (tidak dipakai lagi, tidak menghapus proaktif -- lihat kalau Tuan
 * masih mau pakai di tempat lain).
 *
 * 3 layer motion, arah independen (sesuai spec asli):
 * - Ambient outer halo: pulse lembut (skala 1 -> 1.03), TIDAK berputar
 * - Ring dashed terluar: rotasi searah jarum jam, 26s/putaran
 * - Ring dalam + micro-dot: rotasi BERLAWANAN arah jarum jam, 18s/putaran
 * - Core: statis, hover scale 1.05 sebagai satu-satunya respons ke
 *   interaksi user (bukan animasi ambient)
 * motion-safe: semua animasi loop menghormati prefers-reduced-motion.
 */
export function HudRing({ size = 96 }: { size?: number }) {
  const coreSize = size * (64 / 96);
  const haloInset = size * (14 / 96);
  const glyphSize = Math.round(size * (20 / 96));

  return (
    <div className="relative flex items-center justify-center" style={{ width: size, height: size }}>
      {/* Ambient Outer Halo */}
      <div
        className="absolute rounded-full bg-gradient-to-tr from-[#842bd2]/35 via-orb-glow/25 to-signal-teal/20 blur-xl motion-safe:animate-[nova-orb-pulse_4s_ease-in-out_infinite]"
        style={{ inset: -haloInset }}
        aria-hidden="true"
      />

      {/* Outer Concentric HUD Dashed Ring — searah jarum jam, 26s */}
      <div
        className="absolute inset-0 rounded-full border border-dashed border-orb-core/30 motion-safe:animate-[nova-orb-slow-spin_26s_linear_infinite]"
        aria-hidden="true"
      />

      {/* Inner Concentric Orbit Ring — berlawanan arah, 18s, ada micro-dot */}
      <div
        className="absolute inset-1.5 rounded-full border border-signal-teal/30 motion-safe:animate-[nova-orb-reverse-spin_18s_linear_infinite]"
        aria-hidden="true"
      >
        <span
          className="absolute left-3 top-1 h-1 w-1 rounded-full bg-signal-teal shadow-[0_0_6px_#2FD9C4]"
          aria-hidden="true"
        />
      </div>

      {/* Luminous Quantum Sphere Core — statis, hover scale saja */}
      <div
        className="relative flex items-center justify-center rounded-full bg-gradient-to-br from-[#E2B6FF] via-[#7924CD] to-[#120726]
          shadow-[0_0_32px_rgba(168,85,247,0.65),inset_0_2px_4px_rgba(255,255,255,0.7),inset_0_-4px_10px_rgba(2,0,8,0.9)]
          transition-transform duration-300 hover:scale-105"
        style={{ width: coreSize, height: coreSize }}
      >
        {/* Glass specular glints */}
        <div className="absolute left-2.5 top-2 h-2 w-4 -rotate-[30deg] rounded-full bg-white/75 blur-[0.8px]" aria-hidden="true" />
        <div className="absolute bottom-2 right-3 h-1.5 w-2.5 rounded-full bg-signal-teal/60 blur-[1px]" aria-hidden="true" />

        {/* Core glyph — "deployed_code" versi lucide-react */}
        <Boxes
          size={glyphSize}
          strokeWidth={2}
          className="text-white drop-shadow-[0_0_8px_rgba(255,255,255,0.9)]"
        />
      </div>
    </div>
  );
}
