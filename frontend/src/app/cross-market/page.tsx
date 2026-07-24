import {
  CrossMarketChart,
  type CrossMarketChartRow,
} from "@/components/cross-market-chart";
import type {
  FundamentalComponent,
  MarketObservation,
  MarketStructureSnapshot,
} from "@/lib/api";
import {
  getCrossMarketObservations,
  getDailyMarketStructure,
  getFactorCoverage,
  getLatestFundamental,
} from "@/lib/server-api";

export const dynamic = "force-dynamic";

const title = (value: string) =>
  value
    .toLowerCase()
    .split("_")
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
    .join(" ");

const signed = (value: number) => `${value >= 0 ? "+" : ""}${value.toFixed(2)}`;

const observationKeys = {
  US_TREASURY_2Y: "yield_2y",
  US_TREASURY_10Y: "yield_10y",
  US_REAL_YIELD_10Y: "real_yield_10y",
  US_BREAKEVEN_10Y: "breakeven_10y",
  USD_BROAD_NOMINAL: "usd",
  US_EQUITY_PROXY: "equity",
  US_VOLATILITY_INDEX: "vix",
} as const;

type RawRow = {
  gold: number | null;
  usd: number | null;
  equity: number | null;
  yield_2y: number | null;
  yield_10y: number | null;
  real_yield_10y: number | null;
  breakeven_10y: number | null;
  vix: number | null;
};

export default async function CrossMarketPage() {
  const fundamental = await getLatestFundamental();
  const [coverageResult, structureResult, observationsResult] =
    await Promise.allSettled([
      getFactorCoverage(),
      getDailyMarketStructure(),
      getCrossMarketObservations(fundamental.as_of),
    ]);
  const coverage =
    coverageResult.status === "fulfilled" ? coverageResult.value : null;
  const structure =
    structureResult.status === "fulfilled" ? structureResult.value : null;
  const observations =
    observationsResult.status === "fulfilled" ? observationsResult.value : [];
  const rows = buildRows(observations, structure);
  const components = fundamental.components
    .filter((component) => component.layer === 6)
    .sort(
      (left, right) =>
        Math.abs(right.contribution) - Math.abs(left.contribution),
    );
  const layerFactors = coverage?.factors.filter((factor) => factor.layer === 6) ?? [];
  const fiveMinute = structure?.timeframes.find(
    (timeframe) => timeframe.timeframe === "5m",
  );
  const macroDirection =
    fundamental.directional_score >= 5
      ? "BULLISH"
      : fundamental.directional_score <= -5
        ? "BEARISH"
        : "NEUTRAL";
  const confirmation =
    !fiveMinute || macroDirection === "NEUTRAL"
      ? "UNKNOWN"
      : fiveMinute.trend === macroDirection
        ? "CONFIRMING"
        : fiveMinute.trend === "MIXED_OR_TRANSITIONING"
          ? "CONFLICTED"
          : "CONTRADICTING";

  return (
    <div className="mx-auto max-w-[1500px]">
      <header className="flex flex-wrap items-end justify-between gap-5">
        <div>
          <p className="text-xs font-semibold uppercase tracking-[0.22em] text-[var(--gold)]">
            Cross-market confirmation
          </p>
          <h2 className="mt-2 text-3xl font-semibold tracking-tight">
            Gold must accept—or reject—the macro story.
          </h2>
          <p className="mt-3 max-w-4xl text-sm leading-6 text-[var(--muted)]">
            Point-in-time gold, yields, real yields, breakevens, the broad dollar,
            equities, and volatility share one date axis. Missing Fed-path, silver,
            and licensed flow evidence remains explicitly unknown.
          </p>
        </div>
        <div className="rounded-xl border border-[var(--border)] bg-[var(--panel)] px-4 py-3 text-right">
          <p className="text-[10px] uppercase tracking-wider text-[var(--muted)]">
            Cross-market state
          </p>
          <p className="mt-1 text-sm font-semibold">{confirmation}</p>
          <p className="mt-1 text-[11px] text-[var(--muted)]">
            Macro {macroDirection.toLowerCase()} · 5m{" "}
            {fiveMinute ? title(fiveMinute.trend) : "unknown"}
          </p>
        </div>
      </header>

      <section className="mt-7 grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        {components.map((component) => (
          <FactorCard component={component} key={component.code} />
        ))}
      </section>

      <section className="mt-6 rounded-2xl border border-[var(--border)] bg-[var(--panel)] p-4 md:p-6">
        <div className="mb-5 flex flex-wrap items-end justify-between gap-3">
          <div>
            <p className="text-xs uppercase tracking-[0.16em] text-[var(--muted)]">
              Synchronized evidence
            </p>
            <h3 className="mt-1 text-xl font-semibold">
              Price, rates, dollar, equities, and volatility
            </h3>
          </div>
          <p className="text-xs text-[var(--muted)]">
            {rows.length} common daily clocks · no future revisions
          </p>
        </div>
        <CrossMarketChart rows={rows} />
      </section>

      <section className="mt-6 overflow-hidden rounded-2xl border border-[var(--border)] bg-[var(--panel)]">
        <div className="p-6">
          <p className="text-xs uppercase tracking-[0.16em] text-[var(--muted)]">
            Layer 6 book ledger
          </p>
          <h3 className="mt-2 text-xl font-semibold">
            Connected evidence and deliberate unknowns
          </h3>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full min-w-[900px] text-left text-sm">
            <thead className="border-y border-[var(--border)] bg-black/15 text-[10px] uppercase tracking-wider text-[var(--muted)]">
              <tr>
                {[
                  "Factor",
                  "Evidence",
                  "Implementation",
                  "Phase 1",
                  "Records",
                  "Latest eligible",
                  "Missing dependency",
                ].map((heading) => (
                  <th className="px-4 py-3 font-medium" key={heading}>
                    {heading}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {layerFactors.map((factor) => (
                <tr
                  className="border-b border-[var(--border)]/70 last:border-0"
                  key={factor.code}
                >
                  <td className="px-4 py-3">
                    <p className="font-medium">{factor.name}</p>
                    <p className="mt-1 font-mono text-[10px] text-[var(--muted)]">
                      {factor.code}
                    </p>
                  </td>
                  <td className="px-4 py-3">{factor.current_epistemic_status}</td>
                  <td className="px-4 py-3">{factor.implementation_status}</td>
                  <td className="px-4 py-3">
                    {factor.phase1_required ? "Required" : "Later"}
                  </td>
                  <td className="px-4 py-3 font-mono">
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
                    {factor.missing_dependencies.map(title).join(", ") || "—"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <section className="mt-6 rounded-xl border border-amber-300/20 bg-amber-300/5 p-5 text-xs leading-6 text-amber-50/85">
        Daily public observations cannot prove one-minute event confirmation.
        Intraday post-release logic remains disabled until timestamp-compatible
        Treasury/USD data and point-in-time calendar/Fed-path evidence are available.
      </section>
    </div>
  );
}

function FactorCard({ component }: { component: FundamentalComponent }) {
  return (
    <article className="rounded-2xl border border-[var(--border)] bg-[var(--panel)] p-5">
      <div className="flex items-start justify-between gap-3">
        <div>
          <p className="text-sm font-semibold">{title(component.code)}</p>
          <p className="mt-1 text-[10px] text-[var(--muted)]">
            {component.epistemic_status}
          </p>
        </div>
        <span
          className={`font-mono text-sm ${
            component.contribution > 0
              ? "text-emerald-300"
              : component.contribution < 0
                ? "text-red-300"
                : "text-[var(--muted)]"
          }`}
        >
          {signed(component.contribution)}
        </span>
      </div>
      <p className="mt-4 text-sm leading-6 text-white/85">
        {component.explanation}
      </p>
      <p className="mt-3 text-[11px] text-[var(--muted)]">
        Strength {component.strength.toFixed(1)} · confidence{" "}
        {component.confidence.toFixed(1)} · freshness{" "}
        {component.freshness.toFixed(1)}
      </p>
    </article>
  );
}

function buildRows(
  observations: MarketObservation[],
  structure: MarketStructureSnapshot | null,
): CrossMarketChartRow[] {
  const byDate = new Map<string, Partial<RawRow>>();
  for (const observation of observations) {
    const key =
      observationKeys[
        observation.series_code as keyof typeof observationKeys
      ];
    if (!key) continue;
    const date = observation.observation_time.slice(0, 10);
    byDate.set(date, {
      ...(byDate.get(date) ?? {}),
      [key]: observation.value,
    });
  }

  const goldDates: string[] = [];
  for (const bar of structure?.chart_bars ?? []) {
    if (!bar.complete) continue;
    const date = bar.close_time.slice(0, 10);
    goldDates.push(date);
    byDate.set(date, { ...(byDate.get(date) ?? {}), gold: bar.close });
  }
  const firstGoldDate = goldDates.sort()[0];
  if (!firstGoldDate) return [];

  const state: RawRow = {
    gold: null,
    usd: null,
    equity: null,
    yield_2y: null,
    yield_10y: null,
    real_yield_10y: null,
    breakeven_10y: null,
    vix: null,
  };
  let goldBase: number | null = null;
  let usdBase: number | null = null;
  let equityBase: number | null = null;
  const rows: CrossMarketChartRow[] = [];
  for (const date of [...byDate.keys()].sort()) {
    if (date < firstGoldDate) continue;
    Object.assign(state, byDate.get(date));
    goldBase ??= state.gold;
    usdBase ??= state.usd;
    equityBase ??= state.equity;
    rows.push({
      date,
      gold_index: indexed(state.gold, goldBase),
      usd_index: indexed(state.usd, usdBase),
      equity_index: indexed(state.equity, equityBase),
      yield_2y: state.yield_2y,
      yield_10y: state.yield_10y,
      real_yield_10y: state.real_yield_10y,
      breakeven_10y: state.breakeven_10y,
      vix: state.vix,
    });
  }
  return rows;
}

function indexed(value: number | null, base: number | null) {
  return value === null || base === null || base === 0
    ? null
    : Number(((value / base) * 100).toFixed(4));
}
