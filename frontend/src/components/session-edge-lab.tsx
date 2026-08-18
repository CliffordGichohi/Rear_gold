"use client";

import { useMemo, useState } from "react";
import type { FormEvent } from "react";

import {
  publicApiUrl,
  sessionEdgeStudyRunSchema,
  type BacktestDataRange,
  type SessionEdgeStudyRun,
} from "@/lib/api";

type Props = {
  initialRange: BacktestDataRange;
  initialRuns: SessionEdgeStudyRun[];
};

const metric = (
  value: number | null | undefined,
  suffix = "",
  digits = 3,
) => (value === null || value === undefined ? "N/A" : `${value.toFixed(digits)}${suffix}`);

const inputTimestamp = (value: Date) => value.toISOString().slice(0, 16);

export function SessionEdgeLab({ initialRange, initialRuns }: Props) {
  const latest = initialRange.latest
    ? new Date(initialRange.latest)
    : new Date("2026-07-27T00:00:00Z");
  const earliest = initialRange.earliest
    ? new Date(initialRange.earliest)
    : new Date(latest.getTime() - 90 * 86_400_000);
  const defaultStart = new Date(
    Math.max(earliest.getTime(), latest.getTime() - 120 * 86_400_000),
  );
  const [start, setStart] = useState(inputTimestamp(defaultStart));
  const [end, setEnd] = useState(inputTimestamp(latest));
  const [includeFundamentals, setIncludeFundamentals] = useState(true);
  const [runs, setRuns] = useState(initialRuns);
  const [run, setRun] = useState<SessionEdgeStudyRun | null>(
    initialRuns[0] ?? null,
  );
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setRunning(true);
    setError(null);
    try {
      const response = await fetch(
        `${publicApiUrl}/session-edge-studies/runs?detail_limit=20`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            instrument: "XAUUSD",
            provider_code: "IC_MARKETS_MT5",
            start: new Date(`${start}:00Z`).toISOString(),
            end: new Date(`${end}:00Z`).toISOString(),
            include_fundamentals: includeFundamentals,
            config: {},
          }),
        },
      );
      const payload: unknown = await response.json();
      if (!response.ok) {
        const detail =
          typeof payload === "object" &&
          payload !== null &&
          "detail" in payload &&
          typeof payload.detail === "string"
            ? payload.detail
            : `Session study failed with HTTP ${response.status}`;
        throw new Error(detail);
      }
      const parsed = sessionEdgeStudyRunSchema.parse(payload);
      setRun(parsed);
      setRuns((current) => [
        parsed,
        ...current.filter((candidate) => candidate.id !== parsed.id),
      ].slice(0, 5));
    } catch (reason) {
      setError(
        reason instanceof Error ? reason.message : "The session study failed.",
      );
    } finally {
      setRunning(false);
    }
  }

  const cohortRows = useMemo(() => {
    if (!run) return [];
    const preferred = [
      "ALL_TRIGGERED",
      "FUNDAMENTAL_ALIGNED",
      "FUNDAMENTAL_OPPOSED",
      "FUNDAMENTAL_NEUTRAL_OR_INSUFFICIENT",
      "CATALYST_KNOWN_LOW",
      "CATALYST_UNKNOWN",
      "COMPRESSED_ASIA",
      "NON_COMPRESSED_ASIA",
      "VOLUME_EXPANSION",
      "VOLUME_NOT_EXPANDED",
      "REFERENCE_LEVEL_CONFLUENCE",
      "QUALITY_PRICE_LIQUIDITY",
      "FUNDAMENTAL_ALIGNED_QUALITY_PRICE_LIQUIDITY",
      "SAME_BAR_RECLAIM",
      "DELAYED_RECLAIM",
      "LONG",
      "SHORT",
    ];
    return preferred
      .filter((name) => name in run.results.cohorts)
      .map((name) => [name, run.results.cohorts[name]] as const);
  }, [run]);

  const aligned = run?.results.cohorts.FUNDAMENTAL_ALIGNED;
  const all = run?.results.cohorts.ALL_TRIGGERED;

  return (
    <section className="grid gap-6">
      <div className="rounded-2xl border border-[var(--border)] bg-[var(--panel)]/90 p-6">
        <p className="text-xs uppercase tracking-[0.16em] text-[var(--gold)]">
          Candidate C1 · session opportunity research
        </p>
        <div className="mt-2 grid gap-5 xl:grid-cols-[1fr_420px]">
          <div>
            <h2 className="text-2xl font-semibold">
              Fundamental-biased London sweep and reclaim
            </h2>
            <p className="mt-3 max-w-3xl text-sm leading-6 text-[var(--muted)]">
              Every London session stays in the denominator. The detector records
              a bounded Asian-range sweep, rapid reclaim, and displacement through
              micro structure. Fundamentals classify the result as aligned,
              opposed, neutral, or unknown; they do not manufacture a trigger.
            </p>
            <div className="mt-4 rounded-xl border border-amber-300/25 bg-amber-300/5 p-4 text-sm leading-6 text-amber-100">
              {run?.results.research_status ??
                "RESEARCH / EDGE NOT YET ESTABLISHED"}
              . MFE/MAE and target-before-stop paths are observations, not executed
              trades or a profitability claim.
            </div>
          </div>

          <form
            className="grid gap-3 rounded-xl bg-black/15 p-4"
            onSubmit={submit}
          >
            <label className="grid gap-1 text-xs text-[var(--muted)]">
              Start UTC
              <input
                className="rounded-lg border border-[var(--border)] bg-black/20 px-3 py-2 text-sm text-white"
                type="datetime-local"
                value={start}
                onChange={(event) => setStart(event.target.value)}
              />
            </label>
            <label className="grid gap-1 text-xs text-[var(--muted)]">
              End UTC
              <input
                className="rounded-lg border border-[var(--border)] bg-black/20 px-3 py-2 text-sm text-white"
                type="datetime-local"
                value={end}
                onChange={(event) => setEnd(event.target.value)}
              />
            </label>
            <label className="flex items-center gap-3 text-sm">
              <input
                type="checkbox"
                checked={includeFundamentals}
                onChange={(event) =>
                  setIncludeFundamentals(event.target.checked)
                }
              />
              Freeze point-in-time fundamentals before London
            </label>
            <button
              className="rounded-lg bg-[var(--gold)] px-4 py-2 text-sm font-semibold text-black disabled:opacity-50"
              type="submit"
              disabled={running || !initialRange.ready}
            >
              {running ? "Building opportunity ledger…" : "Run frozen C1 study"}
            </button>
            {error ? (
              <p className="text-xs leading-5 text-red-300">{error}</p>
            ) : null}
          </form>
        </div>
      </div>

      {run ? (
        <>
          <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-5">
            <MetricCard
              label="Requested sessions"
              value={`${run.session_count}`}
              detail={`${run.results.complete_session_count} complete`}
            />
            <MetricCard
              label="Price triggers"
              value={`${run.trigger_count}`}
              detail={`${metric(run.results.trigger_rate_pct, "%", 1)} of all sessions`}
            />
            <MetricCard
              label="Aligned setups"
              value={`${aligned?.setup_count ?? 0}`}
              detail={`${aligned?.complete_outcome_count ?? 0} complete paths`}
            />
            <MetricCard
              label="All-trigger gross path"
              value={metric(all?.mean_gross_path_outcome_r_1r, " R")}
              detail="1R target / 1R stop observational proxy"
            />
            <MetricCard
              label="Aligned gross path"
              value={metric(aligned?.mean_gross_path_outcome_r_1r, " R")}
              detail={`95% CI ${metric(aligned?.gross_path_outcome_r_bootstrap_95ci[0], "")} to ${metric(aligned?.gross_path_outcome_r_bootstrap_95ci[1], "")}`}
            />
          </div>

          <div className="grid gap-6 xl:grid-cols-[320px_1fr]">
            <article className="rounded-2xl border border-[var(--border)] bg-[var(--panel)]/90 p-5">
              <p className="text-xs uppercase tracking-wider text-[var(--muted)]">
                Session funnel
              </p>
              <div className="mt-4 grid gap-3">
                {Object.entries(run.results.status_funnel).map(
                  ([status, count]) => (
                    <div
                      className="flex items-center justify-between gap-4 rounded-lg bg-black/15 px-3 py-2"
                      key={status}
                    >
                      <span className="text-xs">{status.replaceAll("_", " ")}</span>
                      <strong>{count}</strong>
                    </div>
                  ),
                )}
              </div>
            </article>

            <article className="overflow-hidden rounded-2xl border border-[var(--border)] bg-[var(--panel)]/90">
              <div className="border-b border-[var(--border)] p-5">
                <p className="text-xs uppercase tracking-wider text-[var(--muted)]">
                  Matched cohort comparison · longest complete horizon
                </p>
              </div>
              <div className="overflow-x-auto">
                <table className="w-full min-w-[780px] text-left text-xs">
                  <thead className="text-[var(--muted)]">
                    <tr>
                      <th className="px-4 py-3">Cohort</th>
                      <th className="px-4 py-3">Setups</th>
                      <th className="px-4 py-3">Complete</th>
                      <th className="px-4 py-3">Gross path</th>
                      <th className="px-4 py-3">Mean MFE</th>
                      <th className="px-4 py-3">Mean MAE</th>
                      <th className="px-4 py-3">+0.75R before -1R</th>
                    </tr>
                  </thead>
                  <tbody>
                    {cohortRows.map(([name, cohort]) => (
                      <tr
                        className="border-t border-[var(--border)]/70"
                        key={name}
                      >
                        <td className="px-4 py-3 font-medium">
                          {name.replaceAll("_", " ")}
                        </td>
                        <td className="px-4 py-3">{cohort.setup_count}</td>
                        <td className="px-4 py-3">
                          {cohort.complete_outcome_count}
                        </td>
                        <td className="px-4 py-3">
                          {metric(cohort.mean_gross_path_outcome_r_1r, " R")}
                        </td>
                        <td className="px-4 py-3">
                          {metric(cohort.mean_mfe_r, " R")}
                        </td>
                        <td className="px-4 py-3">
                          {metric(cohort.mean_mae_r, " R")}
                        </td>
                        <td className="px-4 py-3">
                          {metric(
                            cohort.target_before_stop_pct["0.75R"],
                            "%",
                            1,
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </article>
          </div>

          <article className="overflow-hidden rounded-2xl border border-[var(--border)] bg-[var(--panel)]/90">
            <div className="border-b border-[var(--border)] p-5">
              <p className="text-xs uppercase tracking-wider text-[var(--muted)]">
                Recent session ledger rows
              </p>
            </div>
            <div className="overflow-x-auto">
              <table className="w-full min-w-[900px] text-left text-xs">
                <thead className="text-[var(--muted)]">
                  <tr>
                    <th className="px-4 py-3">Date</th>
                    <th className="px-4 py-3">Status</th>
                    <th className="px-4 py-3">Side</th>
                    <th className="px-4 py-3">Alignment</th>
                    <th className="px-4 py-3">Fundamental score</th>
                    <th className="px-4 py-3">Regime / driver</th>
                    <th className="px-4 py-3">Catalyst</th>
                    <th className="px-4 py-3">Asia range</th>
                  </tr>
                </thead>
                <tbody>
                  {run.opportunities.map((opportunity) => (
                    <tr
                      className="border-t border-[var(--border)]/70"
                      key={opportunity.id}
                    >
                      <td className="px-4 py-3">{opportunity.session_date}</td>
                      <td className="px-4 py-3">
                        {opportunity.status.replaceAll("_", " ")}
                      </td>
                      <td className="px-4 py-3">
                        {opportunity.setup_side ?? "—"}
                      </td>
                      <td className="px-4 py-3">
                        {opportunity.bias_alignment.replaceAll("_", " ")}
                      </td>
                      <td className="px-4 py-3">
                        {metric(opportunity.directional_score, "", 1)}
                      </td>
                      <td className="px-4 py-3">
                        {opportunity.regime_label} /{" "}
                        {opportunity.dominant_driver ?? "UNKNOWN"}
                      </td>
                      <td className="px-4 py-3">{opportunity.event_risk}</td>
                      <td className="px-4 py-3">
                        {metric(opportunity.asia_range_size, "", 2)} ·{" "}
                        {opportunity.asia_compression_state}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
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
                  {new Date(candidate.created_at).toLocaleString()} ·{" "}
                  {candidate.trigger_count} triggers
                </button>
              ))}
            </div>
          ) : null}
        </>
      ) : (
        <div className="rounded-2xl border border-dashed border-[var(--border)] p-8 text-sm text-[var(--muted)]">
          No session-edge study is stored yet. Run the frozen detector after the
          migration and observed price data are available.
        </div>
      )}
    </section>
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
      <p className="mt-2 text-2xl font-semibold">{value}</p>
      <p className="mt-2 text-xs leading-5 text-[var(--muted)]">{detail}</p>
    </article>
  );
}
