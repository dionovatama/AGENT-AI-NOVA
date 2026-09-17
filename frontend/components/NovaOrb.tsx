/**
 * NovaOrb — brand identity mark, dipakai di sidebar header (28px).
 * Gradient ring (violet -> teal) + dot pusat, sesuai DESIGN.md/
 * code.html: "relative w-6 h-6 rounded-full bg-gradient-to-tr from-
 * [#6823c2] via-[#9B51E0] to-[#2FD9C4]". Statis (tidak berputar) --
 * animasi terus-menerus itu bahasa visual HudLoader/HudRing, dipakai
 * khusus momen tunggu nyata atau hero, bukan identitas sehari-hari
 * yang harus tetap jelas dibaca di ukuran kecil.
 */
export function NovaOrb({ size = 28 }: { size?: number }) {
  const dot = Math.max(6, Math.round(size * 0.3));

  return (
    <div
      className="relative flex shrink-0 items-center justify-center rounded-full bg-gradient-to-tr from-[#6823c2] via-[#9B51E0] to-signal-teal p-[1px] shadow-[0_0_12px_rgba(168,85,247,0.4)]"
      style={{ width: size, height: size }}
    >
      <div className="flex h-full w-full items-center justify-center rounded-full bg-[#0E0917]">
        <span
          className="rounded-full bg-gradient-to-r from-orb-core to-signal-teal shadow-[0_0_6px_rgba(47,217,196,0.8)]"
          style={{ width: dot, height: dot }}
        />
      </div>
    </div>
  );
}
