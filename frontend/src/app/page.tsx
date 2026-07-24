import { FundamentalOverview } from "@/components/fundamental-overview";
import { HealthBadge } from "@/components/health-badge";
import {
  getLatestDecision,
  getMarketStructure,
} from "@/lib/server-api";

export const dynamic = "force-dynamic";

export default async function ExecutiveOverview() {
  const [decisionResult, structureResult] = await Promise.allSettled([
    getLatestDecision(),
    getMarketStructure(),
  ]);
  const decision =
    decisionResult.status === "fulfilled" ? decisionResult.value : null;
  const structure =
    structureResult.status === "fulfilled" ? structureResult.value : null;

  return (
    <div className="mx-auto max-w-[1500px]">
      <header className="flex flex-col justify-between gap-4 md:flex-row md:items-end">
        <div>
          <p className="text-xs font-semibold uppercase tracking-[0.22em] text-[var(--gold)]">
            Executive overview
          </p>
          <h2 className="mt-2 text-3xl font-semibold tracking-tight md:text-4xl">
            Fundamentals guide. Price triggers.
          </h2>
          <p className="mt-3 max-w-3xl text-sm leading-6 text-[var(--muted)]">
            Point-in-time macro permission, positioning context, and mechanical execution
            remain separate, explainable decisions.
          </p>
        </div>
        <HealthBadge />
      </header>

      {decision ? (
        <FundamentalOverview
          decision={decision}
          structure={structure}
        />
      ) : (
        <section className="mt-8 rounded-2xl border border-amber-300/20 bg-amber-300/5 p-6">
          <p className="text-xs font-semibold uppercase tracking-[0.18em] text-amber-200">
            Fundamental snapshot unavailable
          </p>
          <p className="mt-3 text-sm leading-6 text-[var(--muted)]">
            The dashboard will not invent a view. Sync official public data and calculate a
            unified seven-layer decision snapshot first.
          </p>
        </section>
      )}
    </div>
  );
}
