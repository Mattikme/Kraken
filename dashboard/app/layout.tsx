import type { Metadata, Viewport } from "next";
import { Instrument_Serif, JetBrains_Mono } from "next/font/google";
import "./globals.css";

// Polices téléchargées au moment du build et servies par Vercel (aucun appel externe à l'affichage).
const serif = Instrument_Serif({ weight: "400", subsets: ["latin"], variable: "--font-serif" });
const mono = JetBrains_Mono({ subsets: ["latin"], variable: "--font-mono" });

export const metadata: Metadata = {
  title: "Bot BTC/EUR · simulation",
  description: "Simulation de trading BTC/EUR sur Kraken, comparée au buy & hold. Argent fictif.",
  robots: { index: false, follow: false },
};

export const viewport: Viewport = { width: "device-width", initialScale: 1, themeColor: "#f3f1ea" };

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="fr" className={`${serif.variable} ${mono.variable}`}>
      <body>{children}</body>
    </html>
  );
}
