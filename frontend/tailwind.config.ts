import type { Config } from "tailwindcss";

/**
 * Token system NOVA — lihat frontend/README.md #Design Notes untuk rasional.
 *
 * Prinsip dasar tetap: ini operator console untuk infrastructure
 * automation, bukan landing page marketing. Warna status (ok/pending/
 * risk) mengikuti makna PRD section 23 (Permission System): READ=hijau,
 * MODIFY=amber, HIGH_RISK=merah — bukan dekorasi, di KEDUA sistem token
 * di bawah.
 *
 * Ada 2 sistem warna berdampingan saat ini:
  * 1. base-* / ink-* / signal-* — sistem asli, dipakai Tools/Devices/Audit/
 *    Settings/Login dan komponen lama.
 * 2. surface-panel/surface-card/border-glow/orb-core/orb-glow — sistem
 *    "Obsidian Violet Operator", desain terverifikasi (bukan referensi
 *    generik yang ditolak sebelumnya) yang diadopsi sengaja untuk area
 *    Chat. Violet di sini BUKAN "orb ungu generik" seperti yang
 *    sebelumnya ditolak -- itu template SaaS tanpa identitas; ini
 *    design system lengkap dengan rasional sendiri (lihat DESIGN.md
 *    yang diberikan Tuan), dipilih sadar, bukan default template.
 * Kedua sistem akan disatukan kalau/kalau halaman lain di-porting.
 */
const config: Config = {
  content: [
    "./app/**/*.{ts,tsx}",
    "./components/**/*.{ts,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        base: {
          950: "#0A0D12", // panel gelap paling belakang
          900: "#0F131A", // background utama console
          800: "#151B24", // panel/card
          700: "#1D2530", // border/divider
          600: "#2A3644", // border hover / input
        },
        ink: {
          100: "#EAEFF6", // teks utama
          300: "#AEB8C4", // teks sekunder
          500: "#6B7684", // teks muted / placeholder
        },
        signal: {
          teal: "#2FD9C4",   // aksi utama, tool aktif, link
          blue: "#4C8EF7",   // aksen sekunder lama (masih dipakai beberapa tempat lama)
          amber: "#F0B33D",  // MODIFY / butuh konfirmasi / pending
          rose: "#F0645F",   // HIGH_RISK / error / gagal
          green: "#3FCB7C",  // READ / sukses / online
        },
        // --- Obsidian Violet Operator (design system "Stitch") ---
        // Ditambahkan sebagai token BARU, bukan menimpa base-*/ink-*
        // di atas -- supaya halaman yang belum di-porting ke design
        // system ini (Tools/Devices/Audit/Settings/Login) tetap utuh.
        // Dipakai khusus di komponen area Chat untuk sekarang.
        // canvas-void (#0A0D12) & surface-deep (#0F131A) SENGAJA tidak
        // didaftarkan lagi di sini -- nilainya identik dengan base.950
        // dan base.900 yang sudah ada, jadi dipakai lewat nama itu saja
        // (satu sumber kebenaran per warna, bukan dua nama untuk satu hex).
        "surface-panel": "#15121C",       // panel bertekstur violet, ganti base-800 di area chat
        "surface-card": "#181424",        // card composer/shortcut, elevasi di atas surface-panel
        "surface-card-hover": "#211A34",
        "border-subtle": "#251F38",       // border tepi panel, ganti base-700 di area chat
        "border-glow": "#A855F7",         // electric violet -- border aktif/fokus
        "orb-core": "#C084FC",            // violet terang, highlight core orb
        "orb-glow": "#A855F7",            // = border-glow, dipakai utk gradient/shadow
      },
      fontFamily: {
        sans: ["var(--font-sans)", "system-ui", "sans-serif"],
        mono: ["var(--font-mono)", "ui-monospace", "monospace"],
      },
      borderRadius: {
        sm: "3px",
        md: "6px",
        lg: "10px",
      },
      boxShadow: {
        panel: "0 1px 0 0 rgba(255,255,255,0.02) inset",
      },
    },
  },
  plugins: [],
};

export default config;
