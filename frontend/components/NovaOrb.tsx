/**
 * NovaOrb — brand identity mark. Dipakai di dua tempat: hero welcome
 * screen (size besar) dan sidebar header (size kecil, ganti nova-icon.png)
 * -- satu identitas visual, bukan dua logo berbeda.
 *
 * Sengaja TIDAK pakai animasi berputar terus-menerus (itu bahasa visual
 * HudLoader, dipakai khusus untuk momen tunggu nyata). Orb ini identitas
 * statis + glow lembut -- "hidup" secukupnya, bukan spinner.
 */
export function NovaOrb({ size = 96 }: { size?: number }) {
  return (
    <div
      className="relative flex items-center justify-center"
      style={{ width: size, height: size }}
    >
      {/* glow lembut -- blur murni, bukan gradient warna-warni */}
      <div
        className="absolute rounded-full bg-signal-blue/25 blur-xl"
        style={{ width: size * 0.75, height: size * 0.75 }}
      />
      <svg width={size} height={size} viewBox="0 0 100 100" className="relative text-signal-blue">
        <circle cx="50" cy="50" r="46" fill="none" stroke="currentColor" strokeWidth="1" opacity="0.25" />
        <circle cx="50" cy="50" r="34" fill="none" stroke="currentColor" strokeWidth="1.5" opacity="0.45" />
        <circle cx="50" cy="50" r="16" fill="currentColor" opacity="0.9" />
      </svg>
    </div>
  );
}
