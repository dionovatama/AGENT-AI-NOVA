/**
 * HudLoader — ring loader bergaya HUD sci-fi (terinspirasi boot animation
 * Lenovo LOQ yang Tuan tunjukkan), dibangun murni SVG + CSS animation.
 * Tidak ada asset video/Lottie — ringan dan bisa diberi warna via
 * currentColor/token Tailwind.
 *
 * Dipakai HANYA pada momen tunggu nyata (auth check saat masuk console,
 * fetch allowlist tool) — bukan hiasan yang muncul di semua tempat.
 */

const OUTER_DASH = "14 10"; // busur 14px, celah 10px — ring luar
const INNER_DASH = "8 7"; // busur lebih pendek — ring dalam, lebih rapat

export function HudLoader({
  size = 72,
  label,
}: {
  size?: number;
  label?: string;
}) {
  return (
    <div className="flex flex-col items-center gap-3">
      <svg
        width={size}
        height={size}
        viewBox="0 0 100 100"
        className="text-signal-teal"
        role="status"
        aria-label={label ?? "Loading"}
      >
        <circle
          cx="50"
          cy="50"
          r="42"
          fill="none"
          stroke="currentColor"
          strokeWidth="3"
          strokeLinecap="round"
          strokeDasharray={OUTER_DASH}
          opacity="0.9"
          className="origin-center animate-[spin_4s_linear_infinite]"
        />
        <circle
          cx="50"
          cy="50"
          r="30"
          fill="none"
          stroke="currentColor"
          strokeWidth="2.5"
          strokeLinecap="round"
          strokeDasharray={INNER_DASH}
          opacity="0.55"
          className="origin-center animate-[spin_2.6s_linear_infinite] [animation-direction:reverse]"
        />
        <circle cx="50" cy="50" r="3" fill="currentColor" opacity="0.8" />
      </svg>
      {label && (
        <p className="font-mono text-[11px] tracking-[0.15em] text-ink-500">{label}</p>
      )}
    </div>
  );
}
