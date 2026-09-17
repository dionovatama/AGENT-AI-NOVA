import Image from "next/image";

/**
 * HUD ring — versi gambar (aset dari user), menggantikan versi SVG
 * hand-drawn sebelumnya. Perilaku motion tetap dipertahankan sesuai
 * prinsip "satu momen motion yang disengaja":
 * - Gambar berputar pelan (14s/putaran, arah jarum jam) — mensimulasikan
 *   arc/scan yang bergerak di HUD, sama seperti versi SVG sebelumnya.
 * - Dot pusat tetap ada, pulse pelan, sebagai indikator "sistem hidup"
 *   di atas gambar (gambar sumbernya tidak punya elemen ini).
 * motion-safe: tetap menghormati prefers-reduced-motion otomatis.
 *
 * Aset: public/hud/hud-ring.png — sudah di-resize dari 1254x1254
 * asli ke 400x400 (cukup untuk retina di ukuran render ~120-160px,
 * dari 1.7MB jadi ~228KB) dan sudah transparan (tidak perlu proses
 * background removal, PNG asli sudah alpha channel).
 */
export function HudRing({ size = 128 }: { size?: number }) {
  return (
    <div className="relative" style={{ width: size, height: size }}>
      <Image
        src="/hud/hud-ring.png"
        alt=""
        width={400}
        height={400}
        priority
        className="h-full w-full motion-safe:animate-[nova-hud-spin_14s_linear_infinite] object-contain"
      />

      {/* Dot pusat — pulse pelan, indikator "sistem hidup", diposisikan
          absolut di atas gambar supaya tidak ikut berputar bersama gambar. */}
      <span
        className="absolute left-1/2 top-1/2 h-2 w-2 -translate-x-1/2 -translate-y-1/2 rounded-full bg-signal-teal motion-safe:animate-pulse"
        aria-hidden="true"
      />
    </div>
  );
}
