import { getFactorCoverage } from "@/lib/server-api";

export const dynamic = "force-dynamic";

const label = (value: string) =>
  value
    .toLowerCase()
    .split("_")
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
    .join(" ");

const layerNames: Record<number, string> = {
  1: "Market regime",
  2: "Expectations & pricing",
  3: "Positioning & institutions",
  4: "Catalysts & event risk",
  5: "Sessions & liquidity",
  6: "Cross-market confirmation",
  7: "Execution & risk",
};

export default async function DataHealthPage() {
  const coverage = await getFactorCoverage();
  const factors = [...coverage.factors].sort(
    (left, right) =>
      (left.layer ?? 0) - (right.layer ?? 0) ||
      Number(right.phase1_required) - Number(left.phase1_required) ||
      left.name.localeCompare(right.name),
  );

  return (
    <div className="mx-auto max-w-[1500px]">
      <header>
        <p className="text-xs font-semibold uppercase tracking-[0.22em] text-[var(--gold)]">
          Data health and factor registry
        </p>
        <h2 className="mt-2 text-3xl font-semibold tracking-tight">
          The whole reference book, with no hidden gaps.
        </h2>
        <p className="mt-3 max-w-3xl text-sm leading-6 text-[var(--muted)]">
          Coverage is computed from non-synthetic records available at the report clock.
          Contract and licensed factors remain visible until a valid provider is connected.
        </p>
      </header>

      <section className="mt-7 grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        {[
          ["Book factors", coverage.total_factors.toString(), coverage.registry_version],
          ["Known now", coverage.known_factors.toString(), "Observed or reproducibly calculated"],
          [
            "Phase 1 coverage",
            `${coverage.phase1_coverage_pct.toFixed(1)}%`,
            `${coverage.phase1_known_factors}/${coverage.phase1_required_factors} required factors`,
          ],
          [
            "Unknown Phase 1",
            (coverage.phase1_required_factors - coverage.phase1_known_factors).toString(),
            "Not converted to neutral signals",
          ],
        ].map(([name, value, note]) => (
          <article
            className="rounded-2xl border border-[var(--border)] bg-[var(--panel)] p-5"
            key={name}
          >
            <p className="text-xs uppercase tracking-[0.15em] text-[var(--muted)]">{name}</p>
            <p className="mt-4 text-2xl font-semibold">{value}</p>
            <p className="mt-2 text-xs leading-5 text-[var(--muted)]">{note}</p>
          </article>
        ))}
      </section>

      <section className="mt-6 overflow-hidden rounded-2xl border border-[var(--border)] bg-[var(--panel)]">
        <div className="p-6">
          <p className="text-xs uppercase tracking-[0.16em] text-[var(--muted)]">
            Complete reference-book evidence contracts
          </p>
          <h3 className="mt-2 text-xl font-semibold">
            All {coverage.total_factors} factors: known, partial, and unavailable
          </h3>
          <p className="mt-2 max-w-4xl text-xs leading-5 text-[var(--muted)]">
            Phase 1 scope is identified explicitly; later institutional and licensed
            factors stay visible as contracts instead of disappearing from the product.
          </p>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full min-w-[1260px] text-left text-sm">
            <thead className="border-y border-[var(--border)] bg-black/15 text-[10px] uppercase tracking-wider text-[var(--muted)]">
              <tr>
                {["Layer", "Factor", "MVP scope", "Domain", "Evidence", "Build", "Source", "Records", "Latest available", "Missing dependency"].map(
                  (heading) => (
                    <th className="px-4 py-3 font-medium" key={heading}>
                      {heading}
                    </th>
                  ),
                )}
              </tr>
            </thead>
            <tbody>
              {factors.map((factor) => {
                const known = factor.current_epistemic_status !== "UNKNOWN";
                return (
                  <tr
                    className="border-b border-[var(--border)]/70 last:border-0"
                    key={factor.code}
                  >
                    <td className="px-4 py-3">
                      <p className="text-[var(--gold)]">
                        {factor.layer ? `L${factor.layer}` : "Core"}
                      </p>
                      <p className="mt-1 max-w-28 text-[10px] leading-4 text-[var(--muted)]">
                        {factor.layer ? layerNames[factor.layer] : "Market foundation"}
                      </p>
                    </td>
                    <td className="px-4 py-3">
                      <p className="font-medium">{factor.name}</p>
                      <p className="mt-1 font-mono text-[10px] text-[var(--muted)]">
                        {factor.code}
                      </p>
                    </td>
                    <td className="px-4 py-3">
                      <span
                        className={`rounded-full px-2 py-1 text-[10px] ${
                          factor.phase1_required
                            ? "bg-sky-300/10 text-sky-200"
                            : "bg-white/5 text-[var(--muted)]"
                        }`}
                      >
                        {factor.phase1_required ? "PHASE 1" : "LATER"}
                      </span>
                    </td>
                    <td className="px-4 py-3 text-xs">{label(factor.domain)}</td>
                    <td className="px-4 py-3">
                      <span
                        className={`rounded-full px-2 py-1 text-[10px] ${
                          known
                            ? "bg-emerald-300/10 text-emerald-200"
                            : "bg-amber-300/10 text-amber-200"
                        }`}
                      >
                        {factor.current_epistemic_status}
                      </span>
                    </td>
                    <td className="px-4 py-3 text-xs">{factor.implementation_status}</td>
                    <td className="px-4 py-3 text-xs">{label(factor.source_class)}</td>
                    <td className="px-4 py-3 font-mono text-xs">
                      {factor.record_count.toLocaleString()}
                    </td>
                    <td className="px-4 py-3 text-xs text-[var(--muted)]">
                      {factor.latest_available_at
                        ? new Date(factor.latest_available_at)
                            .toISOString()
                            .replace("T", " ")
                            .slice(0, 16)
                        : "—"}
                    </td>
                    <td className="px-4 py-3 text-xs text-amber-100">
                      {factor.missing_dependencies.map(label).join(", ") || "—"}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}
