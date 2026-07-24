import { MarketStructureChart } from "@/components/market-structure-chart";
import { getMarketStructure } from "@/lib/server-api";

export const dynamic = "force-dynamic";

const title = (value: string) =>
  value
    .toLowerCase()
    .split("_")
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
    .join(" ");

const price = (value: number | null) =>
  value === null ? "Unknown" : value.toLocaleString(undefined, { maximumFractionDigits: 2 });

const utc = (value: string) =>
  new Intl.DateTimeFormat("en", {
    dateStyle: "medium",
    timeStyle: "short",
    timeZone: "UTC",
  }).format(new Date(value));

const age = (seconds: number) => {
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m`;
  if (seconds < 86400) return `${(seconds / 3600).toFixed(1)}h`;
  return `${(seconds / 86400).toFixed(1)}d`;
};

export default async function StructurePage() {
  const snapshot = await getMarketStructure();
  const liquidity = snapshot.liquidity;
  const liquidityTone =
    liquidity.status === "NORMAL"
      ? "border-emerald-300/25 bg-emerald-300/5 text-emerald-100"
      : liquidity.status === "ELEVATED"
        ? "border-amber-300/25 bg-amber-300/5 text-amber-100"
        : liquidity.status === "ABNORMAL"
          ? "border-red-300/25 bg-red-300/5 text-red-100"
          : "border-[var(--border)] bg-white/[0.03] text-[var(--muted)]";
  const detections = snapshot.timeframes
    .flatMap((timeframe) => timeframe.detections)
    .sort(
      (left, right) =>
        new Date(right.detected_at).getTime() - new Date(left.detected_at).getTime(),
    )
    .slice(0, 28);

  return (
    <div className="mx-auto max-w-[1500px]">
      <header className="flex flex-wrap items-end justify-between gap-5">
        <div>
          <p className="text-xs font-semibold uppercase tracking-[0.22em] text-[var(--gold)]">
            Sessions &amp; structure
          </p>
          <h2 className="mt-2 text-3xl font-semibold tracking-tight">
            Price acceptance is evidence—not permission by itself.
          </h2>
          <p className="mt-3 max-w-3xl text-sm leading-6 text-[var(--muted)]">
            All pivots wait for their right-side confirmation bars. Every marker exposes
            its method, detection clock, confidence, evidence, and invalidation.
          </p>
        </div>
        <div className="rounded-xl border border-[var(--border)] bg-[var(--panel)] px-4 py-3 text-right">
          <p className="text-[10px] uppercase tracking-wider text-[var(--muted)]">Replay clock</p>
          <p className="mt-1 text-sm font-semibold">{utc(snapshot.as_of)} UTC</p>
          <p className="mt-1 text-[11px] text-[var(--muted)]">
            {snapshot.provider_code} · {snapshot.data_mode}
          </p>
          <p className="mt-1 text-[10px] text-[var(--muted)]">
            {snapshot.provider_session_template}
          </p>
        </div>
      </header>

      {snapshot.is_synthetic ? (
        <div className="mt-6 rounded-xl border border-amber-300/25 bg-amber-300/7 px-4 py-3 text-sm text-amber-100">
          This view is isolated synthetic demo data. It is never mixed with real research.
        </div>
      ) : null}

      <section className="mt-7 grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        {[
          ["Current session", title(snapshot.session.primary), snapshot.session.active.join(" · ") || "No primary session"],
          ["Latest complete bar", utc(snapshot.latest_bar_at), `${age(snapshot.source_staleness_seconds)} old at wall clock`],
          ["Source evidence", snapshot.source_bar_count.toLocaleString(), "Canonical complete 1-minute bars"],
          ["Ruleset", snapshot.ruleset_version, `${snapshot.data_hash.slice(0, 14)}…`],
        ].map(([label, value, note]) => (
          <article className="rounded-2xl border border-[var(--border)] bg-[var(--panel)] p-5" key={label}>
            <p className="text-xs uppercase tracking-[0.14em] text-[var(--muted)]">{label}</p>
            <p className="mt-3 text-lg font-semibold">{value}</p>
            <p className="mt-2 text-xs text-[var(--muted)]">{note}</p>
          </article>
        ))}
      </section>

      <section className={`mt-6 rounded-2xl border p-5 ${liquidityTone}`}>
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div className="max-w-3xl">
            <p className="text-xs uppercase tracking-[0.16em] opacity-70">
              Execution-liquidity gate
            </p>
            <h3 className="mt-2 text-xl font-semibold">
              {title(liquidity.status)} broker conditions
            </h3>
            <p className="mt-3 text-sm leading-6 opacity-80">{liquidity.explanation}</p>
          </div>
          <div className="rounded-xl border border-current/15 bg-black/10 px-4 py-3 text-right">
            <p className="text-[10px] uppercase tracking-wider opacity-65">
              Execution-confidence multiplier
            </p>
            <p className="mt-1 font-mono text-xl font-semibold">
              {liquidity.execution_confidence_multiplier.toFixed(2)}×
            </p>
            <p className="mt-1 text-[10px] opacity-65">
              Quality {liquidity.data_quality_score.toFixed(0)}%
            </p>
          </div>
        </div>
        <dl className="mt-5 grid gap-3 text-sm sm:grid-cols-2 xl:grid-cols-5">
          <div className="rounded-xl bg-black/10 p-4">
            <dt className="text-xs opacity-65">Median spread</dt>
            <dd className="mt-2 font-mono">
              {liquidity.current_spread_points?.toFixed(1) ?? "Unknown"} points
            </dd>
            <dd className="mt-1 text-xs opacity-65">
              {liquidity.current_spread_price?.toFixed(3) ?? "—"} price units
            </dd>
          </div>
          <div className="rounded-xl bg-black/10 p-4">
            <dt className="text-xs opacity-65">Spread percentile</dt>
            <dd className="mt-2 font-mono">
              {liquidity.spread_percentile?.toFixed(1) ?? "Unknown"}%
            </dd>
            <dd className="mt-1 text-xs opacity-65">
              baseline {liquidity.baseline_spread_points?.toFixed(1) ?? "—"} · p95{" "}
              {liquidity.p95_spread_points?.toFixed(1) ?? "—"}
            </dd>
          </div>
          <div className="rounded-xl bg-black/10 p-4">
            <dt className="text-xs opacity-65">Range percentile</dt>
            <dd className="mt-2 font-mono">
              {liquidity.range_percentile?.toFixed(1) ?? "Unknown"}%
            </dd>
            <dd className="mt-1 text-xs opacity-65">
              {liquidity.current_range_bps?.toFixed(2) ?? "—"} bps per 1m bar
            </dd>
          </div>
          <div className="rounded-xl bg-black/10 p-4">
            <dt className="text-xs opacity-65">Tick-activity percentile</dt>
            <dd className="mt-2 font-mono">
              {liquidity.tick_volume_percentile?.toFixed(1) ?? "Unknown"}%
            </dd>
            <dd className="mt-1 text-xs opacity-65">
              median {liquidity.current_tick_volume?.toFixed(0) ?? "—"} ticks
            </dd>
          </div>
          <div className="rounded-xl bg-black/10 p-4">
            <dt className="text-xs opacity-65">Matched baseline</dt>
            <dd className="mt-2 font-mono">
              {liquidity.spread_observation_count.toLocaleString()} observations
            </dd>
            <dd className="mt-1 text-xs opacity-65">
              {title(liquidity.primary_session)} · {liquidity.current_window_minutes}m window
            </dd>
          </div>
        </dl>
        {liquidity.warnings.length ? (
          <ul className="mt-4 grid gap-1 text-xs opacity-75">
            {liquidity.warnings.map((warning) => (
              <li key={warning}>• {warning}</li>
            ))}
          </ul>
        ) : null}
        <p className="mt-4 border-t border-current/10 pt-3 text-[11px] opacity-60">
          The spread is the observed IC Markets quote and tick activity is broker-local.
          Neither is labeled as centralized COMEX liquidity or used as directional macro evidence.
        </p>
      </section>

      <section className="mt-6 rounded-2xl border border-[var(--border)] bg-[var(--panel)] p-4 md:p-6">
        <div className="mb-4 flex flex-wrap items-end justify-between gap-3">
          <div>
            <p className="text-xs uppercase tracking-[0.16em] text-[var(--muted)]">
              Five-minute market map
            </p>
            <h3 className="mt-1 text-xl font-semibold">Candles, sessions, support and resistance</h3>
          </div>
          <p className="text-xs text-[var(--muted)]">
            {snapshot.chart_bars.length} complete bars · UTC axis
          </p>
        </div>
        <MarketStructureChart snapshot={snapshot} />
      </section>

      <section className="mt-6">
        <div>
          <p className="text-xs uppercase tracking-[0.16em] text-[var(--muted)]">Session ledger</p>
          <h3 className="mt-1 text-xl font-semibold">Latest DST-adjusted ranges</h3>
        </div>
        <div className="mt-4 grid gap-4 lg:grid-cols-3">
          {snapshot.session.ranges.map((range) => (
            <article className="rounded-2xl border border-[var(--border)] bg-[var(--panel)] p-5" key={range.name}>
              <div className="flex items-start justify-between gap-3">
                <div>
                  <p className="text-xs uppercase tracking-wider text-[var(--gold)]">{range.name}</p>
                  <p className="mt-2 text-sm text-[var(--muted)]">{range.timezone}</p>
                </div>
                <span className="rounded-full border border-[var(--border)] px-2.5 py-1 text-[10px]">
                  {range.status}
                </span>
              </div>
              <dl className="mt-5 grid grid-cols-2 gap-4 text-sm">
                <div><dt className="text-[var(--muted)]">High</dt><dd className="mt-1 font-mono">{price(range.high)}</dd></div>
                <div><dt className="text-[var(--muted)]">Low</dt><dd className="mt-1 font-mono">{price(range.low)}</dd></div>
                <div><dt className="text-[var(--muted)]">Range</dt><dd className="mt-1 font-mono">{price(range.range_size)}</dd></div>
                <div><dt className="text-[var(--muted)]">Coverage</dt><dd className="mt-1">{range.completeness_pct.toFixed(1)}%</dd></div>
              </dl>
              <p className="mt-4 border-t border-[var(--border)] pt-4 text-xs text-[var(--muted)]">
                {title(range.breakout_state)} · {utc(range.start_at)}–{utc(range.end_at)} UTC
              </p>
            </article>
          ))}
        </div>
      </section>

      <section className="mt-7">
        <p className="text-xs uppercase tracking-[0.16em] text-[var(--muted)]">Timeframe state</p>
        <h3 className="mt-1 text-xl font-semibold">One algorithm, six horizons</h3>
        <div className="mt-4 grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
          {snapshot.timeframes.map((timeframe) => (
            <article className="rounded-2xl border border-[var(--border)] bg-[var(--panel)] p-5" key={timeframe.timeframe}>
              <div className="flex items-center justify-between gap-3">
                <p className="text-lg font-semibold">{timeframe.timeframe}</p>
                <span className="text-xs text-[var(--gold)]">{title(timeframe.trend)}</span>
              </div>
              <dl className="mt-4 grid grid-cols-2 gap-3 text-xs">
                <div><dt className="text-[var(--muted)]">Support</dt><dd className="mt-1 font-mono">{price(timeframe.support)}</dd></div>
                <div><dt className="text-[var(--muted)]">Resistance</dt><dd className="mt-1 font-mono">{price(timeframe.resistance)}</dd></div>
                <div><dt className="text-[var(--muted)]">ATR(14)</dt><dd className="mt-1 font-mono">{price(timeframe.atr14)}</dd></div>
                <div><dt className="text-[var(--muted)]">Momentum</dt><dd className="mt-1 font-mono">{timeframe.momentum_atr?.toFixed(2) ?? "Unknown"} ATR</dd></div>
              </dl>
              <p className="mt-4 border-t border-[var(--border)] pt-3 text-[11px] text-[var(--muted)]">
                {timeframe.complete_bar_count.toLocaleString()} complete bars · {timeframe.detections.length} retained detections
              </p>
            </article>
          ))}
        </div>
      </section>

      <section className="mt-7 overflow-hidden rounded-2xl border border-[var(--border)] bg-[var(--panel)]">
        <div className="border-b border-[var(--border)] p-5">
          <p className="text-xs uppercase tracking-[0.16em] text-[var(--muted)]">Evidence ledger</p>
          <h3 className="mt-1 text-xl font-semibold">Most recent detected structures</h3>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full min-w-[960px] text-left text-xs">
            <thead className="text-[10px] uppercase tracking-wider text-[var(--muted)]">
              <tr>
                {["Detected", "TF", "Structure", "Class", "Level", "Confidence", "Invalidation"].map((heading) => (
                  <th className="px-5 py-3 font-medium" key={heading}>{heading}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {detections.map((item, index) => (
                <tr className="border-t border-[var(--border)]/70" key={`${item.timeframe}-${item.kind}-${item.detected_at}-${index}`}>
                  <td className="px-5 py-3 text-[var(--muted)]">{utc(item.detected_at)}</td>
                  <td className="px-5 py-3 font-semibold">{item.timeframe}</td>
                  <td className="px-5 py-3">{title(item.kind)}</td>
                  <td className="px-5 py-3">
                    <span className={item.epistemic_status === "INFERRED" ? "text-amber-200" : "text-sky-200"}>
                      {item.epistemic_status}
                    </span>
                  </td>
                  <td className="px-5 py-3 font-mono">{item.price_level.toFixed(2)}</td>
                  <td className="px-5 py-3">{item.confidence.toFixed(0)}%</td>
                  <td className="max-w-sm px-5 py-3 text-[var(--muted)]">{item.invalidation_condition}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <section className="mt-6 rounded-2xl border border-[var(--border)] bg-black/15 p-5 text-xs leading-6 text-[var(--muted)]">
        <p>
          Method: {Number(snapshot.config.pivot_left_bars)} left and {Number(snapshot.config.pivot_right_bars)} right
          confirmation bars; pivot prominence ≥ {Number(snapshot.config.minimum_pivot_prominence_atr).toFixed(2)} ATR;
          breakout buffer {Number(snapshot.config.breakout_buffer_atr).toFixed(2)} ATR; acceptance requires{" "}
          {Number(snapshot.config.acceptance_bars)} complete closes. Missing source minutes make an aggregate incomplete;
          they are not interpolated.
        </p>
      </section>
    </div>
  );
}
