import Link from "next/link";

const validSections = new Set([
  "macro",
  "events",
  "positioning",
  "structure",
  "cross-market",
  "backtests",
  "data-health",
]);

export default async function PlannedSection({ params }: { params: Promise<{ section: string }> }) {
  const { section } = await params;
  const known = validSections.has(section);
  return (
    <div className="mx-auto max-w-3xl rounded-2xl border border-[var(--border)] bg-[var(--panel)] p-8">
      <p className="text-xs uppercase tracking-[0.2em] text-[var(--gold)]">{known ? "Planned Phase 1 surface" : "Not found"}</p>
      <h2 className="mt-3 text-3xl font-semibold capitalize">{section.replaceAll("-", " ")}</h2>
      <p className="mt-4 leading-7 text-[var(--muted)]">
        {known
          ? "This route is intentionally empty until its evidence pipeline is implemented. The product never renders fabricated charts or placeholder market claims."
          : "This dashboard route is not defined."}
      </p>
      <Link className="mt-7 inline-block text-sm font-semibold text-[var(--gold)]" href="/">
        Return to overview →
      </Link>
    </div>
  );
}

