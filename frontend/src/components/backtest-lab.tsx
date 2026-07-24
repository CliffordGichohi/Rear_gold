"use client";

import { useMemo, useState } from "react";
import type { FormEvent, ReactNode } from "react";
import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import {
  backtestRunSchema,
  publicApiUrl,
  type BacktestDataRange,
  type BacktestRun,
} from "@/lib/api";

type Props = {
  initialRange: BacktestDataRange;
  initialRun: BacktestRun | null;
  initialRuns: BacktestRun[];
};

type FormState = {
  strategyMode: "PRICE_ONLY_CONTROL" | "FUNDAMENTAL_ALIGNED";
  start: string;
  end: string;
  risk: string;
  confirmationBars: string;
  bufferAtr: string;
  stopAtr: string;
  targetR: string;
  spread: string;
  slippage: string;
  commission: string;
  fundamentalScore: string;
  fundamentalCoverage: string;
  fundamentalConfidence: string;
  blockHighImpactEvents: boolean;
  blockLiquidityRisk: boolean;
  allowUnknownLiquidity: boolean;
};

const utcInput = (value: string | null, fallback: string) =>
  value ? new Date(value).toISOString().slice(0, 16) : fallback;

const numberOrNull = (value: unknown) =>
  typeof value === "number" && Number.isFinite(value) ? value : null;

const metric = (value: unknown, suffix = "", digits = 2) => {
  const numeric = numberOrNull(value);
  return numeric === null ? "N/A" : `${numeric.toFixed(digits)}${suffix}`;
};

const parameterNumber = (
  run: BacktestRun | null,
  key: string,
  fallback: number,
) => {
  const value = run?.parameters[key];
  return typeof value === "number" && Number.isFinite(value) ? value : fallback;
};

export function BacktestLab({ initialRange, initialRun, initialRuns }: Props) {
  const earliestStart = initialRange.earliest
    ? new Date(new Date(initialRange.earliest).getTime() + 5 * 86_400_000)
        .toISOString()
        .slice(0, 16)
    : "2026-06-29T00:00";
  const [form, setForm] = useState<FormState>({
    strategyMode:
      initialRun?.parameters.strategy_mode === "PRICE_ONLY_CONTROL"
        ? "PRICE_ONLY_CONTROL"
        : "FUNDAMENTAL_ALIGNED",
    start: earliestStart,
    end: utcInput(initialRange.latest, "2026-07-23T08:15"),
    risk: String(parameterNumber(initialRun, "risk_per_trade_pct", 1)),
    confirmationBars: String(parameterNumber(initialRun, "confirmation_bars", 2)),
    bufferAtr: String(parameterNumber(initialRun, "breakout_buffer_atr", 0.1)),
    stopAtr: String(parameterNumber(initialRun, "stop_atr_multiple", 1.5)),
    targetR: String(parameterNumber(initialRun, "target_r", 2)),
    spread: String(parameterNumber(initialRun, "spread_price", 0.3)),
    slippage: String(parameterNumber(initialRun, "slippage_price", 0.05)),
    commission: String(
      parameterNumber(initialRun, "commission_per_lot_round_turn", 7),
    ),
    fundamentalScore: String(
      parameterNumber(initialRun, "fundamental_min_score", 5),
    ),
    fundamentalCoverage: String(
      parameterNumber(initialRun, "fundamental_min_coverage", 35),
    ),
    fundamentalConfidence: String(
      parameterNumber(initialRun, "fundamental_min_confidence", 25),
    ),
    blockHighImpactEvents:
      initialRun?.parameters.block_high_impact_events !== false,
    blockLiquidityRisk:
      initialRun?.parameters.block_elevated_or_abnormal_liquidity !== false,
    allowUnknownLiquidity:
      initialRun?.parameters.allow_unknown_liquidity === true,
  });
  const [run, setRun] = useState<BacktestRun | null>(initialRun);
  const [runs, setRuns] = useState<BacktestRun[]>(initialRuns);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const cards = useMemo(
    () =>
      run
        ? [
            ["Trades", `${run.metrics.trades}`, `${run.metrics.wins} wins / ${run.metrics.losses} losses`],
            ["Win rate", metric(run.metrics.win_rate_pct, "%", 1), "Outcome after modeled costs"],
            ["Expectancy", metric(run.metrics.expectancy_r, " R", 3), `Median ${metric(run.metrics.median_r, " R", 3)}`],
            ["Net P&L", metric(run.metrics.total_net_pnl, " USD"), `${metric(run.metrics.return_pct, "%")} return`],
            ["Profit factor", metric(run.metrics.profit_factor, "", 3), `Costs ${metric(run.metrics.total_costs, " USD")}`],
            ["Max drawdown", metric(run.metrics.maximum_drawdown, " USD"), metric(run.metrics.maximum_drawdown_pct, "%")],
            [
              "Sequence-risk drawdown",
              metric(run.metrics.monte_carlo_trade_order?.drawdown_pct_p95, "%"),
              "95th percentile from deterministic trade-order reshuffling",
            ],
            [
              "Trigger candidates",
              metric(run.metrics.mechanical_candidates, "", 0),
              `${metric(run.metrics.fundamental_gate_permitted, "", 0)} permitted / ${metric(run.metrics.fundamental_gate_rejected, "", 0)} filtered`,
            ],
          ]
        : [],
    [run],
  );

  const update = (key: keyof FormState, value: string) =>
    setForm((current) => ({ ...current, [key]: value }));

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setRunning(true);
    setError(null);
    try {
      const response = await fetch(`${publicApiUrl}/backtests/runs`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          instrument: "XAUUSD",
          provider_code: "IC_MARKETS_MT5",
          strategy_mode: form.strategyMode,
          start: new Date(`${form.start}:00Z`).toISOString(),
          end: new Date(`${form.end}:00Z`).toISOString(),
          initial_equity: 10_000,
          risk_per_trade_pct: Number(form.risk),
          confirmation_bars: Number(form.confirmationBars),
          breakout_buffer_atr: Number(form.bufferAtr),
          stop_atr_multiple: Number(form.stopAtr),
          target_r: Number(form.targetR),
          spread_price: Number(form.spread),
          slippage_price: Number(form.slippage),
          commission_per_lot_round_turn: Number(form.commission),
          contract_size: 100,
          min_lot: 0.01,
          lot_step: 0.01,
          max_lots: 10,
          fundamental_min_score: Number(form.fundamentalScore),
          fundamental_min_coverage: Number(form.fundamentalCoverage),
          fundamental_min_confidence: Number(form.fundamentalConfidence),
          block_high_impact_events: form.blockHighImpactEvents,
          block_elevated_or_abnormal_liquidity: form.blockLiquidityRisk,
          allow_unknown_liquidity: form.allowUnknownLiquidity,
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
            : `Backtest failed with HTTP ${response.status}`;
        throw new Error(detail);
      }
      const parsed = backtestRunSchema.parse(payload);
      setRun(parsed);
      setRuns((current) => [
        parsed,
        ...current.filter((candidate) => candidate.id !== parsed.id),
      ].slice(0, 8));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "The backtest failed.");
    } finally {
      setRunning(false);
    }
  }

  const ci = run?.metrics.expectancy_r_95ci ?? [null, null];
  const bootstrapCi = run?.metrics.expectancy_r_bootstrap_95ci ?? [null, null];
  const evidenceCi = bootstrapCi[0] === null ? ci : bootstrapCi;
  const monteCarlo = run?.metrics.monte_carlo_trade_order;
  const sideCount = Object.keys(run?.metrics.performance_by_side ?? {}).length;
  const insufficientSample =
    !run ||
    run.metrics.trades < 30 ||
    evidenceCi[0] === null ||
    evidenceCi[0] <= 0;
  const edgeFailures = run
    ? [
        ...(run.metrics.trades < 30
          ? [`Only ${run.metrics.trades} trades; fewer than the 30-trade minimum screen.`]
          : []),
        ...(evidenceCi[0] === null || evidenceCi[0] <= 0
          ? ["The 95% expectancy interval includes zero."]
          : []),
        ...(sideCount < 2
          ? ["The permitted sample contains only one trade direction."]
          : []),
        "This run is not a locked out-of-sample or walk-forward holdout.",
      ]
    : [];

  return (
    <div className="grid gap-6">
      <section className="rounded-2xl border border-[var(--border)] bg-[var(--panel)]/90 p-6">
        <p className="text-xs uppercase tracking-[0.16em] text-[var(--gold)]">
          Exact strategy contract
        </p>
        <h3 className="mt-2 text-xl font-semibold">
          The book’s four decisions are evaluated separately
        </h3>
        <div className="mt-5 grid gap-4 md:grid-cols-2 xl:grid-cols-4">
          <article className="rounded-xl bg-black/15 p-4">
            <p className="text-xs uppercase tracking-wider text-[var(--muted)]">
              1 · Bias
            </p>
            <p className="mt-3 text-sm leading-6">
              Long requires score ≥ +{form.fundamentalScore}; short requires ≤ -
              {form.fundamentalScore}. Coverage must be ≥ {form.fundamentalCoverage}%
              and confidence ≥ {form.fundamentalConfidence}%.
            </p>
          </article>
          <article className="rounded-xl bg-black/15 p-4">
            <p className="text-xs uppercase tracking-wider text-[var(--muted)]">
              2 · Trigger
            </p>
            <p className="mt-3 text-sm leading-6">
              A complete 10:05–16:00 Tokyo range, followed during 08:00–12:00
              London by {form.confirmationBars} closed 5m bars beyond the range plus{" "}
              {form.bufferAtr} ATR.
            </p>
          </article>
          <article className="rounded-xl bg-black/15 p-4">
            <p className="text-xs uppercase tracking-wider text-[var(--muted)]">
              3 · Invalidation
            </p>
            <p className="mt-3 text-sm leading-6">
              Entry is at the next 5m open. The implemented hard invalidation is{" "}
              {form.stopAtr} ATR; profit target is {form.targetR}R, otherwise exit
              at 16:00 New York.
            </p>
          </article>
          <article className="rounded-xl bg-black/15 p-4">
            <p className="text-xs uppercase tracking-wider text-[var(--muted)]">
              4 · Risk
            </p>
            <p className="mt-3 text-sm leading-6">
              Risk {form.risk}% of current equity, enforce broker lot rules, model
              spread/slippage/commission, and block high/extreme known catalysts.
            </p>
          </article>
        </div>
        <p className="mt-4 text-xs leading-5 text-amber-100/85">
          Unknown catalyst risk is disclosed but the historical research control
          currently permits it. Therefore these runs do not prove the complete
          catalyst-aware book strategy until timestamped event schedules are loaded.
        </p>
      </section>

      <section className="grid gap-6 xl:grid-cols-[360px_1fr]">
        <form
          className="rounded-2xl border border-[var(--border)] bg-[var(--panel)]/90 p-6"
          onSubmit={submit}
        >
          <p className="text-xs uppercase tracking-[0.16em] text-[var(--gold)]">Experiment controls</p>
          <h3 className="mt-2 text-xl font-semibold">
            {form.strategyMode === "FUNDAMENTAL_ALIGNED"
              ? "Fundamental-guided acceptance"
              : "Price-only control"}
          </h3>
          <p className="mt-3 text-xs leading-5 text-[var(--muted)]">
            Two closed London bars must accept beyond the complete 10:05–16:00 Tokyo range. Entry occurs at the next five-minute open.
          </p>
          <div className="mt-6 grid grid-cols-2 gap-4">
            <Field label="Research mode" span>
              <select
                className="field"
                value={form.strategyMode}
                onChange={(event) =>
                  update(
                    "strategyMode",
                    event.target.value as FormState["strategyMode"],
                  )
                }
              >
                <option value="FUNDAMENTAL_ALIGNED">Fundamental aligned</option>
                <option value="PRICE_ONLY_CONTROL">Price-only control</option>
              </select>
            </Field>
            <Field label="Start UTC" span>
              <input className="field" type="datetime-local" value={form.start} onChange={(event) => update("start", event.target.value)} />
            </Field>
            <Field label="End UTC" span>
              <input className="field" type="datetime-local" value={form.end} onChange={(event) => update("end", event.target.value)} />
            </Field>
            <Field label="Risk %">
              <input className="field" min="0.1" max="5" step="0.1" type="number" value={form.risk} onChange={(event) => update("risk", event.target.value)} />
            </Field>
            <Field label="Confirm bars">
              <input className="field" min="1" max="3" step="1" type="number" value={form.confirmationBars} onChange={(event) => update("confirmationBars", event.target.value)} />
            </Field>
            <Field label="Buffer × ATR">
              <input className="field" min="0" max="2" step="0.05" type="number" value={form.bufferAtr} onChange={(event) => update("bufferAtr", event.target.value)} />
            </Field>
            <Field label="Stop × ATR">
              <input className="field" min="0.1" max="10" step="0.1" type="number" value={form.stopAtr} onChange={(event) => update("stopAtr", event.target.value)} />
            </Field>
            <Field label="Target R">
              <input className="field" min="0.1" max="20" step="0.1" type="number" value={form.targetR} onChange={(event) => update("targetR", event.target.value)} />
            </Field>
            <Field label="Spread USD">
              <input className="field" min="0" max="20" step="0.01" type="number" value={form.spread} onChange={(event) => update("spread", event.target.value)} />
            </Field>
            <Field label="Slippage USD">
              <input className="field" min="0" max="20" step="0.01" type="number" value={form.slippage} onChange={(event) => update("slippage", event.target.value)} />
            </Field>
            <Field label="Commission/lot">
              <input className="field" min="0" max="1000" step="0.1" type="number" value={form.commission} onChange={(event) => update("commission", event.target.value)} />
            </Field>
            {form.strategyMode === "FUNDAMENTAL_ALIGNED" ? (
              <>
                <Field label="Min macro score">
                  <input className="field" min="0" max="100" step="0.5" type="number" value={form.fundamentalScore} onChange={(event) => update("fundamentalScore", event.target.value)} />
                </Field>
                <Field label="Min coverage %">
                  <input className="field" min="0" max="100" step="1" type="number" value={form.fundamentalCoverage} onChange={(event) => update("fundamentalCoverage", event.target.value)} />
                </Field>
                <Field label="Min confidence %" span>
                  <input className="field" min="0" max="100" step="1" type="number" value={form.fundamentalConfidence} onChange={(event) => update("fundamentalConfidence", event.target.value)} />
                </Field>
                <label className="col-span-2 flex items-start gap-3 rounded-xl border border-[var(--border)] bg-black/10 p-4 text-xs leading-5 text-[var(--muted)]">
                  <input
                    checked={form.blockHighImpactEvents}
                    className="mt-1 accent-[var(--gold)]"
                    type="checkbox"
                    onChange={(event) =>
                      setForm((current) => ({
                        ...current,
                        blockHighImpactEvents: event.target.checked,
                      }))
                    }
                  />
                  <span>
                    Block new entries during high/extreme event risk. Keep this
                    enabled for the book-aligned strategy; disable only as a
                    named research control.
                  </span>
                </label>
                <label className="col-span-2 flex items-start gap-3 rounded-xl border border-[var(--border)] bg-black/10 p-4 text-xs leading-5 text-[var(--muted)]">
                  <input
                    checked={form.blockLiquidityRisk}
                    className="mt-1 accent-[var(--gold)]"
                    type="checkbox"
                    onChange={(event) =>
                      setForm((current) => ({
                        ...current,
                        blockLiquidityRisk: event.target.checked,
                      }))
                    }
                  />
                  <span>
                    Block entries when the point-in-time broker spread/range
                    classification is elevated or abnormal.
                  </span>
                </label>
                <label className="col-span-2 flex items-start gap-3 rounded-xl border border-[var(--border)] bg-black/10 p-4 text-xs leading-5 text-[var(--muted)]">
                  <input
                    checked={form.allowUnknownLiquidity}
                    className="mt-1 accent-[var(--gold)]"
                    type="checkbox"
                    onChange={(event) =>
                      setForm((current) => ({
                        ...current,
                        allowUnknownLiquidity: event.target.checked,
                      }))
                    }
                  />
                  <span>
                    Allow unknown historical liquidity only as an explicit
                    research override. The book-aligned default is to block it.
                  </span>
                </label>
              </>
            ) : null}
          </div>
          <button
            className="mt-6 w-full rounded-xl bg-[var(--gold)] px-4 py-3 text-sm font-semibold text-[#171208] transition hover:brightness-110 disabled:cursor-wait disabled:opacity-60"
            disabled={running || !initialRange.ready}
            type="submit"
          >
            {running ? "Running point-in-time replay…" : "Run backtest"}
          </button>
          {error ? <p className="mt-4 rounded-lg bg-red-400/10 p-3 text-xs leading-5 text-red-200">{error}</p> : null}
        </form>

        <div className="grid content-start gap-6">
          <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
            {cards.map(([label, value, note]) => (
              <article className="rounded-2xl border border-[var(--border)] bg-[var(--panel)]/90 p-5" key={label}>
                <p className="text-xs uppercase tracking-[0.14em] text-[var(--muted)]">{label}</p>
                <p className="mt-4 text-2xl font-semibold">{value}</p>
                <p className="mt-2 text-xs text-[var(--muted)]">{note}</p>
              </article>
            ))}
          </div>

          {run ? (
            <div className="grid gap-6">
              <article className="rounded-2xl border border-red-300/20 bg-red-300/5 p-6">
                <p className="text-xs uppercase tracking-[0.16em] text-red-200">
                  Edge verdict
                </p>
                <h3 className="mt-2 text-xl font-semibold">No confirmed edge yet</h3>
                <ul className="mt-4 grid gap-2 text-sm leading-6 text-white/85">
                  {edgeFailures.map((failure) => (
                    <li key={failure}>• {failure}</li>
                  ))}
                </ul>
                <p className="mt-4 text-xs leading-5 text-[var(--muted)]">
                  Positive in-sample P&amp;L is a research lead. An edge requires
                  positive locked out-of-sample expectancy across regimes and both
                  directions after costs.
                </p>
              </article>
              <article className="rounded-2xl border border-[var(--border)] bg-[var(--panel)]/90 p-6">
              <div className="flex flex-wrap items-start justify-between gap-4">
                <div>
                  <p className="text-xs uppercase tracking-[0.16em] text-[var(--muted)]">Equity curve</p>
                  <h3 className="mt-2 text-xl font-semibold">10,000 USD research account</h3>
                </div>
                <span className={`rounded-full px-3 py-1 text-xs ${insufficientSample ? "bg-amber-300/10 text-amber-200" : "bg-emerald-300/10 text-emerald-200"}`}>
                  {insufficientSample ? "Insufficient evidence" : "Minimum statistical screen passed"}
                </span>
              </div>
              <div className="mt-5 h-72">
                <ResponsiveContainer height="100%" width="100%">
                  <LineChart data={run.equity_curve}>
                    <CartesianGrid stroke="rgba(255,255,255,0.06)" vertical={false} />
                    <XAxis dataKey="timestamp" hide />
                    <YAxis domain={["dataMin - 50", "dataMax + 50"]} stroke="#91a59d" tick={{ fontSize: 11 }} width={70} />
                    <Tooltip contentStyle={{ background: "#0d1916", border: "1px solid #203c33", borderRadius: 10 }} />
                    <Line dataKey="equity" dot={{ r: 3 }} stroke="#e8bf64" strokeWidth={2} type="monotone" />
                  </LineChart>
                </ResponsiveContainer>
              </div>
              <p className="mt-4 text-xs leading-5 text-[var(--muted)]">
                Parametric 95% expectancy interval: {metric(ci[0], " R", 3)} to{" "}
                {metric(ci[1], " R", 3)}. Bootstrap interval:{" "}
                {metric(bootstrapCi[0], " R", 3)} to{" "}
                {metric(bootstrapCi[1], " R", 3)}.
              </p>
              <p className="mt-2 text-xs leading-5 text-[var(--muted)]">
                Trade-order Monte Carlo 95th-percentile drawdown:{" "}
                {metric(monteCarlo?.drawdown_pct_p95, "%")}. This measures sequence
                risk from realized trades; it does not preserve regime clustering
                or prove an edge. A positive result with a small sample remains a
                research lead.
              </p>
              </article>
            </div>
          ) : null}
        </div>
      </section>

      {run ? (
        <>
          <section className="rounded-2xl border border-[var(--border)] bg-[var(--panel)]/90 p-6">
            <div className="flex flex-wrap justify-between gap-3">
              <div>
                <p className="text-xs uppercase tracking-[0.16em] text-[var(--muted)]">Audit manifest</p>
                <h3 className="mt-2 text-xl font-semibold">Point-in-time controls</h3>
              </div>
              <p className="font-mono text-xs text-[var(--muted)]">{run.data_hash.slice(0, 16)}…</p>
            </div>
            <div className="mt-5 grid gap-4 text-sm md:grid-cols-4">
              <Audit label="Provider" value={run.provider_code} />
              <Audit
                label="Research mode"
                value={String(run.parameters.strategy_mode ?? "PRICE_ONLY_CONTROL")}
              />
              <Audit label="Source bars" value={run.source_bar_count.toLocaleString()} />
              <Audit label="Complete sessions" value={`${String(run.provenance.complete_asia_sessions ?? "N/A")}`} />
              <Audit label="Fill policy" value="Next 5m open" />
            </div>
            <p className="mt-5 border-t border-[var(--border)] pt-5 text-xs leading-5 text-[var(--muted)]">
              {String(run.provenance.lookahead_policy ?? "")}
            </p>
          </section>

          <section className="overflow-hidden rounded-2xl border border-[var(--border)] bg-[var(--panel)]/90">
            <div className="p-6">
              <p className="text-xs uppercase tracking-[0.16em] text-[var(--muted)]">Trade ledger</p>
              <h3 className="mt-2 text-xl font-semibold">Every simulated fill</h3>
            </div>
            <div className="overflow-x-auto">
              <table className="w-full min-w-[900px] text-left text-sm">
                <thead className="border-y border-[var(--border)] bg-black/15 text-xs uppercase tracking-wider text-[var(--muted)]">
                  <tr>
                    {["#", "Side", "Entry UTC", "Exit", "Lots", "Net P&L", "R", "MFE", "MAE", "Hold"].map((heading) => (
                      <th className="px-4 py-3 font-medium" key={heading}>{heading}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {run.trades.map((trade) => (
                    <tr className="border-b border-[var(--border)]/70 last:border-0" key={trade.sequence}>
                      <td className="px-4 py-3 text-[var(--muted)]">{trade.sequence}</td>
                      <td className={`px-4 py-3 font-semibold ${trade.side === "LONG" ? "text-emerald-300" : "text-red-300"}`}>{trade.side}</td>
                      <td className="px-4 py-3">{new Date(trade.entry_time).toISOString().replace("T", " ").slice(0, 16)}</td>
                      <td className="px-4 py-3">{trade.exit_reason}</td>
                      <td className="px-4 py-3">{trade.quantity_lots.toFixed(2)}</td>
                      <td className={`px-4 py-3 ${trade.net_pnl >= 0 ? "text-emerald-300" : "text-red-300"}`}>{trade.net_pnl.toFixed(2)}</td>
                      <td className="px-4 py-3">{trade.r_multiple.toFixed(3)}</td>
                      <td className="px-4 py-3">{trade.mfe_r.toFixed(2)}R</td>
                      <td className="px-4 py-3">{trade.mae_r.toFixed(2)}R</td>
                      <td className="px-4 py-3">{trade.holding_minutes}m</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>
        </>
      ) : null}

      {runs.length ? (
        <section className="overflow-hidden rounded-2xl border border-[var(--border)] bg-[var(--panel)]/90">
          <div className="p-6">
            <p className="text-xs uppercase tracking-[0.16em] text-[var(--muted)]">
              Experiment comparison
            </p>
            <h3 className="mt-2 text-xl font-semibold">Control versus macro permission</h3>
            <p className="mt-2 text-xs leading-5 text-[var(--muted)]">
              A filter earns its place only if out-of-sample evidence improves—not because
              the narrative sounds plausible.
            </p>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full min-w-[900px] text-left text-sm">
              <thead className="border-y border-[var(--border)] bg-black/15 text-[10px] uppercase tracking-wider text-[var(--muted)]">
                <tr>
                  {["Mode", "Period", "Candidates", "Trades", "Wins", "Net P&L", "Expectancy", "Profit factor", "Max drawdown"].map(
                    (heading) => (
                      <th className="px-4 py-3 font-medium" key={heading}>
                        {heading}
                      </th>
                    ),
                  )}
                </tr>
              </thead>
              <tbody>
                {runs.map((candidate) => (
                  <tr
                    className="border-b border-[var(--border)]/70 last:border-0"
                    key={candidate.id}
                  >
                    <td className="px-4 py-3">
                      <p className="font-medium">
                        {String(candidate.parameters.strategy_mode ?? "PRICE_ONLY_CONTROL")
                          .replaceAll("_", " ")
                          .toLowerCase()}
                      </p>
                      <p className="mt-1 font-mono text-[10px] text-[var(--muted)]">
                        {candidate.id.slice(0, 8)}
                      </p>
                    </td>
                    <td className="px-4 py-3 text-xs">
                      {candidate.start.slice(0, 10)} → {candidate.end.slice(0, 10)}
                    </td>
                    <td className="px-4 py-3">
                      {metric(candidate.metrics.mechanical_candidates, "", 0)}
                    </td>
                    <td className="px-4 py-3">{candidate.metrics.trades}</td>
                    <td className="px-4 py-3">{candidate.metrics.wins}</td>
                    <td
                      className={`px-4 py-3 ${
                        candidate.metrics.total_net_pnl >= 0
                          ? "text-emerald-300"
                          : "text-red-300"
                      }`}
                    >
                      {metric(candidate.metrics.total_net_pnl, " USD")}
                    </td>
                    <td className="px-4 py-3">
                      {metric(candidate.metrics.expectancy_r, " R", 3)}
                    </td>
                    <td className="px-4 py-3">
                      {metric(candidate.metrics.profit_factor, "", 3)}
                    </td>
                    <td className="px-4 py-3">
                      {metric(candidate.metrics.maximum_drawdown, " USD")}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      ) : null}
    </div>
  );
}

function Field({ label, span = false, children }: { label: string; span?: boolean; children: ReactNode }) {
  return (
    <label className={span ? "col-span-2" : ""}>
      <span className="mb-2 block text-xs text-[var(--muted)]">{label}</span>
      {children}
    </label>
  );
}

function Audit({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <p className="text-xs text-[var(--muted)]">{label}</p>
      <p className="mt-1 break-words">{value}</p>
    </div>
  );
}
