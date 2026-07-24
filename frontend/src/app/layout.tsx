import type { Metadata } from "next";
import Link from "next/link";

import "./globals.css";

export const metadata: Metadata = {
  title: "Gold Market Intelligence Engine",
  description: "Explainable, point-in-time gold market intelligence",
};

const navigation = [
  ["Overview", "/"],
  ["Macro", "/macro"],
  ["Events", "/events"],
  ["Positioning", "/positioning"],
  ["Structure", "/structure"],
  ["Cross-market", "/cross-market"],
  ["Backtest Lab", "/backtests"],
  ["Coverage & Health", "/data-health"],
];

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body>
        <div className="min-h-screen lg:grid lg:grid-cols-[250px_1fr]">
          <aside className="border-b border-[var(--border)] bg-black/20 p-6 lg:min-h-screen lg:border-r lg:border-b-0">
            <div className="mb-9">
              <p className="text-xs font-semibold tracking-[0.28em] text-[var(--gold)]">GOLD</p>
              <h1 className="mt-2 text-lg font-semibold leading-tight">Market Intelligence Engine</h1>
              <p className="mt-2 text-xs text-[var(--muted)]">Research, evidence, and replay</p>
            </div>
            <nav aria-label="Primary navigation" className="grid grid-cols-2 gap-2 text-sm lg:grid-cols-1">
              {navigation.map(([label, href]) => (
                <Link
                  className="rounded-lg px-3 py-2.5 text-[var(--muted)] transition hover:bg-white/5 hover:text-white"
                  href={href}
                  key={href}
                >
                  {label}
                </Link>
              ))}
            </nav>
          </aside>
          <main className="min-w-0 p-5 md:p-8 xl:p-10">{children}</main>
        </div>
      </body>
    </html>
  );
}
