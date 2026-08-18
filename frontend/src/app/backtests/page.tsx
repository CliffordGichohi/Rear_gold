import { BacktestLab } from "@/components/backtest-lab";
import { SessionEdgeLab } from "@/components/session-edge-lab";
import { SessionEdgeStrategyLab } from "@/components/session-edge-strategy-lab";
import type { BacktestDataRange } from "@/lib/api";
import {
  getBacktestDataRange,
  getRecentBacktests,
  getRecentSessionEdgeStrategies,
  getRecentSessionEdgeStudies,
} from "@/lib/server-api";

export const dynamic = "force-dynamic";

const unavailableRange: BacktestDataRange = {
  instrument: "XAUUSD",
  provider_code: "IC_MARKETS_MT5",
  earliest: null,
  latest: null,
  bar_count: 0,
  ready: false,
};

export default async function BacktestsPage() {
  const [rangeResult, runsResult, sessionRunsResult, strategyRunsResult] =
    await Promise.allSettled([
      getBacktestDataRange(),
      getRecentBacktests(),
      getRecentSessionEdgeStudies(),
      getRecentSessionEdgeStrategies(),
    ]);
  const range =
    rangeResult.status === "fulfilled" ? rangeResult.value : unavailableRange;
  const latestRun =
    runsResult.status === "fulfilled" ? (runsResult.value[0] ?? null) : null;

  return (
    <div className="mx-auto max-w-[1500px]">
      <header>
        <p className="text-xs font-semibold uppercase tracking-[0.22em] text-[var(--gold)]">
          Backtest laboratory
        </p>
        <h2 className="mt-2 text-3xl font-semibold tracking-tight md:text-4xl">
          Test the rule, including its friction.
        </h2>
        <p className="mt-3 max-w-3xl text-sm leading-6 text-[var(--muted)]">
          Replays immutable IC Markets MT5 bars with point-in-time availability,
          DST-aware sessions, next-bar execution, spread, slippage and commission.
          Results are research evidence—not a promise of future performance.
        </p>
        <div className="mt-5 flex flex-wrap gap-3 text-xs">
          <span className="rounded-full bg-emerald-300/10 px-3 py-1.5 text-emerald-200">
            {range.bar_count.toLocaleString()} observed 1m bars
          </span>
          <span className="rounded-full bg-white/5 px-3 py-1.5 text-[var(--muted)]">
            {range.earliest && range.latest
              ? `${new Date(range.earliest).toISOString().slice(0, 10)} → ${new Date(range.latest).toISOString().slice(0, 10)}`
              : "MT5 history unavailable"}
          </span>
        </div>
      </header>
      <div className="mt-8">
        <SessionEdgeLab
          initialRange={range}
          initialRuns={
            sessionRunsResult.status === "fulfilled"
              ? sessionRunsResult.value
              : []
          }
        />
        <SessionEdgeStrategyLab
          studies={
            sessionRunsResult.status === "fulfilled"
              ? sessionRunsResult.value
              : []
          }
          initialRuns={
            strategyRunsResult.status === "fulfilled"
              ? strategyRunsResult.value
              : []
          }
        />
      </div>
      <div className="mt-12 border-t border-[var(--border)] pt-12">
        <p className="mb-5 text-xs font-semibold uppercase tracking-[0.18em] text-[var(--muted)]">
          Rejected breakout control · retained for audit
        </p>
        <BacktestLab
          initialRange={range}
          initialRun={latestRun}
          initialRuns={runsResult.status === "fulfilled" ? runsResult.value : []}
        />
      </div>
    </div>
  );
}
