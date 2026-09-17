import type { Config } from "tailwindcss";

/**
 * Token system NOVA — lihat frontend/README.md #Design Notes untuk rasional.
 *
 * Prinsip: ini bukan landing page marketing, ini operator console untuk
 * infrastructure automation. Palette gelap "slate-signal", bukan orb ungu
 * generik seperti referensi. Warna status (ok/pending/risk) mengikuti
 * makna PRD section 23 (Permission System): READ=hijau, MODIFY=amber,
 * HIGH_RISK=merah — bukan dekorasi.
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
          blue: "#4C8EF7",   // aksen sekunder (NovaOrb glow, ambient glow chat) — sebelumnya dipakai di 4 tempat tapi TIDAK PERNAH didefinisikan di sini, jadi selama ini render tanpa warna sama sekali
          amber: "#F0B33D",  // MODIFY / butuh konfirmasi / pending
          rose: "#F0645F",   // HIGH_RISK / error / gagal
          green: "#3FCB7C",  // READ / sukses / online
        },
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
