"use client";

import { useState } from "react";

import {
  publicApiUrl,
  sessionEdgeStrategyRunSchema,
  type SessionEdgeStrategyRun,
  type SessionEdgeStudyRun,
} from "@/lib/api";

type Props = {
  studies: SessionEdgeStudyRun[];
  initialRuns: SessionEdgeStrategyRun[];
};

const metric = (
  value: number | null | undefined,
  suffix = "",
  digits = 3,
) => (value === null || value === undefined ? "N/A" : `${value.toFixed(digits)}${suffix}`);

export function SessionEdgeStrategyLab({ studies, initialRuns }: Props) {
  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  const [mode, setMode] = useState<
    | "DELAYED_RECLAIM_PRICE_CONTROL"
    | "DELAYED_RECLAIM_FUNDAMENTAL_ALIGNED"
  >("DELAYED_RECLAIM_FUNDAMENTAL_ALIGNED");
  const [runs, setRuns] = useState(initialRuns);
  const [run, setRun] = useState<SessionEdgeStrategyRun | null>(
    initialRuns[0] ?? null,
  );
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function execute() {
    setRunning(true);
    setError(null);
    try {
      const response = await fetch(`${publicApiUrl}/session-edge-strategies/runs`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          source_study_run_ids: selectedIds,
          strategy_mode: mode,
        }),
      });
      const payload: unknown = await response.json();
      if (!response.ok) {
        const detail =
          typeof payload === "object" &&
          payload !== null &&
          "detail" in payload &&
          typeof payload.detail === "string"
            ? payload.detail
            : `Strategy run failed with HTTP ${response.status}`;
        throw new Error(detail);
      }
      const parsed = sessionEdgeStrategyRunSchema.parse(payload);
      setRun(parsed);
      setRuns((current) => [
        parsed,
        ...current.filter((candidate) => candidate.id !== parsed.id),
      ].slice(0, 5));
    } catch (reason) {
      setError(
        reason instanceof Error ? reason.message : "The strategy run failed.",
      );
    } finally {
      setRunning(false);
    }
  }

  const gate = run?.metrics.development_gate;
  const costStress = run?.metrics.robustness.cost_stress ?? [];

  return (
    <section className="mt-8 grid gap-6">
      <div className="rounded-2xl border border-[var(--border)] bg-[var(--panel)]/90 p-6">
        <p className="text-xs uppercase tracking-[0.16em] text-[var(--gold)]">
          Candidate C1 · executable development gate
        </p>
        <div className="mt-3 grid gap-6 xl:grid-cols-[1fr_440px]">
          <div>
            <h2 className="text-2xl font-semibold">
              Delayed reclaim with real execution friction
            </h2>
            <p className="mt-3 max-w-3xl text-sm leading-6 text-[var(--muted)]">
              Replays the frozen next-bar entry, structural stop, 1R target and
              four-hour exit on one-minute bars. Observed entry/exit spread,
              slippage and commission are deducted. The price control is a
              benchmark; the fundamental-aligned variant is the book-aligned
              primary.
            </p>
            <div
              className={`mt-4 rounded-xl border p-4 text-sm leading-6 ${
                gate?.status === "PASS"
                  ? "border-emerald-300/30 bg-emerald-300/5 text-emerald-100"
                  : "border-amber-300/25 bg-amber-300/5 text-amber-100"
              }`}
            >
              {gate
                ? `Development gate: ${gate.status}. ${
                    gate.continue_to_locked_validation
                      ? "The frozen candidate may proceed to locked validation."
                      : "The 2025 holdout remains locked."
                  }`
                : "No executable Candidate C1 run is stored yet."}
            </div>
          </div>

          <div className="grid gap-3 rounded-xl bg-black/15 p-4">
            <label className="grid gap-1 text-xs text-[var(--muted)]">
              Frozen variant
              <select
                className="rounded-lg border border-[var(--border)] bg-[var(--panel)] px-3 py-2 text-sm text-white"
                value={mode}
                onChange={(event) =>
                  setMode(
                    event.target.value as
                      | "DELAYED_RECLAIM_PRICE_CONTROL"
                      | "DELAYED_RECLAIM_FUNDAMENTAL_ALIGNED",
                  )
                }
              >
                <option value="DELAYED_RECLAIM_FUNDAMENTAL_ALIGNED">
                  Fundamental-aligned primary
                </option>
                <option value="DELAYED_RECLAIM_PRICE_CONTROL">
                  Price-only control
                </option>
              </select>
            </label>
            <div className="grid max-h-44 gap-2 overflow-y-auto">
              {studies.map((study) => (
                <label
                  className="flex items-start gap-3 rounded-lg border border-[var(--border)]/70 p-2 text-xs"
                  key={study.id}
                >
                  <input
                    className="mt-0.5"
                    type="checkbox"
                    checked={selectedIds.includes(study.id)}
                    onChange={(event) =>
                      setSelectedIds((current) =>
                        event.target.checked
                          ? [...current, study.id]
                          : current.filter((id) => id !== study.id),
                      )
                    }
                  />
                  <span>
                    {study.start.slice(0, 10)} to {study.end.slice(0, 10)}
                    <span className="block text-[var(--muted)]">
                      {study.trigger_count} triggers · {study.id.slice(0, 8)}
                    </span>
                  </span>
                </label>
              ))}
            </div>
            <button
              className="rounded-lg bg-[var(--gold)] px-4 py-2 text-sm font-semibold text-black disabled:opacity-50"
              type="button"
              disabled={running || selectedIds.length === 0}
              onClick={execute}
            >
              {running ? "Replaying exact fills…" : "Run frozen executable candidate"}
            </button>
            {error ? (
              <p className="text-xs leading-5 text-red-300">{error}</p>
            ) : null}
          </div>
        </div>
      </div>

      {run ? (
        <>
          <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-6">
            <MetricCard
              label="Variant"
              value={
                run.metrics.strategy_mode.includes("FUNDAMENTAL")
                  ? "Fundamental"
                  : "Control"
              }
              detail={run.strategy_version}
            />
            <MetricCard
              label="Trades"
              value={`${run.metrics.trades}`}
              detail={`${metric(run.metrics.win_rate_pct, "%", 1)} profitable`}
            />
            <MetricCard
              label="Net expectancy"
              value={metric(run.metrics.net_expectancy_r, " R")}
              detail={`Gross ${metric(run.metrics.gross_expectancy_r, " R")}`}
            />
            <MetricCard
              label="Profit factor"
              value={metric(run.metrics.profit_factor)}
              detail={`Net ${metric(run.metrics.total_net_pnl, " USD", 2)}`}
            />
            <MetricCard
              label="Execution costs"
              value={metric(run.metrics.total_costs, " USD", 2)}
              detail={`${run.metrics.unknown_catalyst_trades} catalyst-unverified trades`}
            />
            <MetricCard
              label="Maximum drawdown"
              value={metric(run.metrics.maximum_drawdown_pct, "%", 2)}
              detail={`95% CI ${metric(run.metrics.expectancy_r_bootstrap_95ci?.[0])} to ${metric(run.metrics.expectancy_r_bootstrap_95ci?.[1])}`}
            />
          </div>

          <div className="grid gap-6 xl:grid-cols-2">
            <ResultTable
              title="Performance by development year"
              rows={Object.entries(run.metrics.performance_by_year).map(
                ([label, row]) => ({
                  label,
                  trades: row.trades,
                  winRate: row.win_rate_pct,
                  expectancy: row.average_r,
                  pnl: row.net_pnl,
                }),
              )}
            />
            <ResultTable
              title="Predeclared transaction-cost stress"
              rows={costStress.map((row) => ({
                label: row.label,
                trades: row.trades,
                winRate: row.win_rate_pct,
                expectancy: row.net_expectancy_r,
                pnl: row.total_net_pnl,
              }))}
            />
          </div>

          <article className="rounded-2xl border border-[var(--border)] bg-[var(--panel)]/90 p-5">
            <p className="text-xs uppercase tracking-wider text-[var(--muted)]">
              Development continuation criteria
            </p>
            <div className="mt-4 grid gap-2 md:grid-cols-2 xl:grid-cols-3">
              {Object.entries(gate?.criteria ?? {}).map(([name, passed]) => (
                <div
                  className="flex items-center justify-between gap-3 rounded-lg bg-black/15 px-3 py-2 text-xs"
                  key={name}
                >
                  <span>{name.replaceAll("_", " ")}</span>
                  <strong className={passed ? "text-emerald-200" : "text-red-300"}>
                    {passed ? "PASS" : "FAIL"}
                  </strong>
                </div>
              ))}
            </div>
          </article>

          {runs.length > 1 ? (
            <div className="flex flex-wrap gap-2">
              {runs.map((candidate) => (
                <button
                  className="rounded-full border border-[var(--border)] px-3 py-1 text-xs"
                  key={candidate.id}
                  onClick={() => setRun(candidate)}
                  type="button"
                >
                  {candidate.metrics.strategy_mode.includes("FUNDAMENTAL")
                    ? "Fundamental"
                    : "Control"}{" "}
                  · {candidate.metrics.trades} trades · {candidate.id.slice(0, 8)}
                </button>
              ))}
            </div>
          ) : null}
        </>
      ) : null}
    </section>
  );
}

function ResultTable({
  title,
  rows,
}: {
  title: string;
  rows: {
    label: string;
    trades: number;
    winRate: number | null | undefined;
    expectancy: number | null | undefined;
    pnl: number;
  }[];
}) {
  return (
    <article className="overflow-hidden rounded-2xl border border-[var(--border)] bg-[var(--panel)]/90">
      <p className="border-b border-[var(--border)] p-5 text-xs uppercase tracking-wider text-[var(--muted)]">
        {title}
      </p>
      <table className="w-full text-left text-xs">
        <thead className="text-[var(--muted)]">
          <tr>
            <th className="px-4 py-3">Slice</th>
            <th className="px-4 py-3">Trades</th>
            <th className="px-4 py-3">Win rate</th>
            <th className="px-4 py-3">Expectancy</th>
            <th className="px-4 py-3">Net PnL</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr className="border-t border-[var(--border)]/70" key={row.label}>
              <td className="px-4 py-3 font-medium">{row.label}</td>
              <td className="px-4 py-3">{row.trades}</td>
              <td className="px-4 py-3">{metric(row.winRate, "%", 1)}</td>
              <td className="px-4 py-3">{metric(row.expectancy, " R")}</td>
              <td className="px-4 py-3">{metric(row.pnl, " USD", 2)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </article>
  );
}

function MetricCard({
  label,
  value,
  detail,
}: {
  label: string;
  value: string;
  detail: string;
}) {
  return (
    <article className="rounded-xl border border-[var(--border)] bg-[var(--panel)]/90 p-4">
      <p className="text-xs uppercase tracking-wider text-[var(--muted)]">
        {label}
      </p>
      <p className="mt-2 text-xl font-semibold">{value}</p>
      <p className="mt-2 text-xs leading-5 text-[var(--muted)]">{detail}</p>
    </article>
  );
}
