/**
 * HUD ring — pengganti langsung "orb bulat glowing biru-cyan" dari
 * referensi. Alasan bentuknya begini, bukan orb solid:
 * - Orb solid dengan glow radial = motif AI-consumer-toy paling umum
 *   (lihat catatan tailwind.config.ts).
 * - Ring dengan tick mark + arc berputar = motif targeting/status HUD —
 *   lebih dekat ke "operator memonitor sistem" daripada "asisten AI
 *   ramah". Konsisten dengan identitas NOVA sebagai operator console.
 *
 * Satu-satunya elemen yang bergerak: satu arc tipis berputar pelan
 * (10s/putaran) + dot tengah yang pulse pelan. Sesuai prinsip "satu
 * momen motion yang disengaja", bukan animasi bertebaran di banyak
 * elemen. motion-safe: menghormati prefers-reduced-motion otomatis.
 */
export function HudRing({ size = 96 }: { size?: number }) {
  const cx = 60;
  const cy = 60;

  // 16 tick mark di sekeliling ring luar — motif radar/targeting,
  // bukan dekorasi acak.
  const ticks = Array.from({ length: 16 }, (_, i) => {
    const angle = (i / 16) * 360;
    return (
      <line
        key={i}
        x1={cx}
        y1={8}
        x2={cx}
        y2={i % 4 === 0 ? 14 : 11}
        stroke="currentColor"
        strokeWidth={i % 4 === 0 ? 1.5 : 1}
        className={i % 4 === 0 ? "text-ink-500" : "text-base-600"}
        transform={`rotate(${angle} ${cx} ${cy})`}
      />
    );
  });

  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 120 120"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      aria-hidden="true"
    >
      {ticks}

      {/* Ring luar, statis, redup */}
      <circle cx={cx} cy={cy} r={52} stroke="currentColor" strokeWidth={1} className="text-base-600" />

      {/* Ring tengah, statis */}
      <circle cx={cx} cy={cy} r={40} stroke="currentColor" strokeWidth={1} className="text-base-700" />

      {/* Arc aktif — satu-satunya elemen berputar */}
      <g className="origin-center motion-safe:animate-[nova-hud-spin_10s_linear_infinite]" style={{ transformBox: "fill-box", transformOrigin: "center" }}>
        <path
          d={`M ${cx} ${cy - 40} A 40 40 0 0 1 ${cx + 28.3} ${cy - 28.3}`}
          stroke="currentColor"
          strokeWidth={2}
          strokeLinecap="round"
          className="text-signal-teal"
        />
      </g>

      {/* Ring dalam, statis */}
      <circle cx={cx} cy={cy} r={26} stroke="currentColor" strokeWidth={1} className="text-base-700" />

      {/* Crosshair tipis */}
      <line x1={cx - 6} y1={cy} x2={cx + 6} y2={cy} stroke="currentColor" strokeWidth={1} className="text-ink-500" />
      <line x1={cx} y1={cy - 6} x2={cx} y2={cy + 6} stroke="currentColor" strokeWidth={1} className="text-ink-500" />

      {/* Dot pusat — pulse pelan, indikator "sistem hidup" */}
      <circle cx={cx} cy={cy} r={3} fill="currentColor" className="text-signal-teal motion-safe:animate-pulse" />
    </svg>
  );
}
