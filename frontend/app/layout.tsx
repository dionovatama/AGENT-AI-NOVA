import type { Metadata } from "next";
import { IBM_Plex_Sans, IBM_Plex_Mono } from "next/font/google";
import "./globals.css";

// IBM Plex Sans/Mono: dipilih karena punya nuansa "engineering
// documentation" — bukan geometric sans default (Inter/Helvetica) yang
// dipakai hampir semua AI console generik. Mono dipakai fungsional untuk
// hostname, command, JSON — bukan hiasan label.
const plexSans = IBM_Plex_Sans({
  subsets: ["latin"],
  weight: ["400", "500", "600"],
  variable: "--font-sans",
  display: "swap",
});

const plexMono = IBM_Plex_Mono({
  subsets: ["latin"],
  weight: ["400", "500"],
  variable: "--font-mono",
  display: "swap",
});

export const metadata: Metadata = {
  title: "N.O.V.A — Operator Console",
  description:
    "Nexus Operation Virtual Assistant — console operasi untuk Linux, Windows, MikroTik, dan Cisco.",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="id" className={`${plexSans.variable} ${plexMono.variable}`}>
      <body className="bg-base-900 text-ink-100 font-sans antialiased">
        {children}
      </body>
    </html>
  );
}
