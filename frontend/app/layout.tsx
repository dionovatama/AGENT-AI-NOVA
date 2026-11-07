import type { Metadata } from "next";
import "./globals.css";

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
    <html lang="id">
      <body className="bg-base-900 text-ink-100 font-sans antialiased">
        {children}
      </body>
    </html>
  );
}
