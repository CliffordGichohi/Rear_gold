import Link from "next/link";

import type {
  DecisionSnapshot,
  MarketStructureSnapshot,
} from "@/lib/api";

const label = (value: string) =>
  value
    .toLowerCase()
    .split("_")
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
    .join(" ");

const signed = (value: number) => `${value >= 0 ? "+" : ""}${value.toFixed(2)}`;

const statusTone: Record<string, string> = {
  COMPLETE: "bg-emerald-300/10 text-emerald-200",
  ACTIVE: "bg-emerald-300/10 text-emerald-200",
  PARTIAL: "bg-amber-300/10 text-amber-200",
  GATED: "bg-amber-300/10 text-amber-200",
  STALE: "bg-red-300/10 text-red-200",
  UNKNOWN: "bg-white/5 text-[var(--muted)]",
};

const layerNames: Record<number, string> = {
  1: "Market regime",
  2: "Expectations",
  3: "Positioning",
  4: "Catalysts",
  5: "Sessions & liquidity",
  6: "Cross-market",
  7: "Execution & risk",
};

function record(value: unknown): Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {};
}

function strings(value: unknown): string[] {
  return Array.isArray(value)
    ? value.filter((item): item is string => typeof item === "string")
    : [];
}

export function FundamentalOverview({
  decision,
  structure,
}: {
  decision: DecisionSnapshot;
  structure: MarketStructureSnapshot | null;
}) {
  const connected = decision.components
    .filter((component) => component.epistemic_status !== "UNKNOWN")
    .sort((left, right) => Math.abs(right.contribution) - Math.abs(left.contribution));
  const unknownComponents = decision.components.filter(
    (component) => component.epistemic_status === "UNKNOWN",
  );
  const dominantComponent = connected.find(
    (component) => component.code === decision.dominant_driver,
  );
  const trigger = record(decision.execution_plan.trigger);
  const risk = record(decision.execution_plan.risk);
  const confirmationRequirements = strings(
    decision.execution_plan.confirmation_requirements,
  );
  const invalidationRequirements = strings(
    decision.execution_plan.invalidation_requirements,
  );
  const warnings = strings(decision.execution_plan.warnings);
  const upcomingCatalyst =
    decision.upcoming_catalyst &&
    typeof decision.upcoming_catalyst.name === "string"
      ? decision.upcoming_catalyst.name
      : "No verified upcoming catalyst";
  const latestPrice =
    structure?.timeframes.find((timeframe) => timeframe.timeframe === "5m")
      ?.last_close ?? null;

  return (
    <>
      <section className="mt-7 rounded-2xl border border-emerald-300/20 bg-emerald-300/5 p-5">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <p className="text-xs font-semibold uppercase tracking-[0.18em] text-emerald-200">
              Unified seven-layer decision
            </p>
            <p className="mt-2 max-w-4xl text-sm leading-6 text-white/90">
              Direction comes only from Layers 1-4 and 6. Sessions, liquidity,
              structure, catalyst safety, and account risk can reduce confidence or
              force WAIT, but never manufacture a trade.
            </p>
          </div>
          <p className="font-mono text-xs text-[var(--muted)]">
            {new Date(decision.as_of).toISOString().replace("T", " ").slice(0, 16)} UTC
          </p>
        </div>
      </section>

      <section className="mt-5 grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        {[
          ["Directional bias", label(decision.bias), "Macro permission, never an entry"],
          [
            "Gold intelligence score",
            signed(decision.directional_score),
            `Bull ${decision.bullish_score.toFixed(1)} / bear ${decision.bearish_score.toFixed(1)}`,
          ],
          [
            "Directional confidence",
            `${decision.directional_confidence.toFixed(1)}%`,
            "Evidence certainty, not probability of profit",
          ],
          [
            "Execution confidence",
            `${decision.execution_confidence.toFixed(1)}%`,
            `${label(decision.liquidity_state)} liquidity; ${label(decision.price_macro_alignment)}`,
          ],
        ].map(([name, value, note]) => (
          <article
            className="rounded-2xl border border-[var(--border)] bg-[var(--panel)]/90 p-5"
            key={name}
          >
            <p className="text-xs uppercase tracking-[0.15em] text-[var(--muted)]">
              {name}
            </p>
            <p className="mt-4 text-xl font-semibold text-white">{value}</p>
            <p className="mt-2 text-xs leading-5 text-[var(--muted)]">{note}</p>
          </article>
        ))}
      </section>

      <section className="mt-6 rounded-2xl border border-[var(--gold)]/25 bg-[var(--gold)]/5 p-6">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <p className="text-xs uppercase tracking-[0.16em] text-[var(--gold)]">
              Book decision brief
            </p>
            <h3 className="mt-2 text-xl font-semibold">
              Bias, trigger, invalidation, and risk are separate contracts
            </h3>
          </div>
          <span className="rounded-full border border-amber-200/20 bg-amber-200/10 px-3 py-1 text-xs text-amber-100">
            {label(decision.execution_state)}
          </span>
        </div>

        <dl className="mt-6 grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
          <div className="rounded-xl bg-black/15 p-4">
            <dt className="text-xs text-[var(--muted)]">Regime / reaction function</dt>
            <dd className="mt-2 text-sm">
              {label(decision.regime)} / {label(decision.reaction_function)}
            </dd>
          </div>
          <div className="rounded-xl bg-black/15 p-4">
            <dt className="text-xs text-[var(--muted)]">Dominant driver</dt>
            <dd className="mt-2 text-sm">
              {label(decision.dominant_driver ?? "unknown")}
            </dd>
          </div>
          <div className="rounded-xl bg-black/15 p-4">
            <dt className="text-xs text-[var(--muted)]">Catalyst / event risk</dt>
            <dd className="mt-2 text-sm">
              {upcomingCatalyst} / {label(decision.event_risk)}
            </dd>
          </div>
          <div className="rounded-xl bg-black/15 p-4">
            <dt className="text-xs text-[var(--muted)]">Session / live price</dt>
            <dd className="mt-2 text-sm">
              {label(decision.current_session)}
              {latestPrice !== null ? ` / ${latestPrice.toFixed(2)}` : ""}
            </dd>
          </div>
        </dl>

        <div className="mt-4 grid gap-4 lg:grid-cols-4">
          <article className="rounded-xl border border-[var(--border)] bg-black/10 p-4">
            <p className="text-xs uppercase tracking-wider text-[var(--muted)]">
              What changed?
            </p>
            <p className="mt-3 text-sm leading-6">
              {dominantComponent?.explanation ??
                "No eligible change can be attributed from connected evidence."}
            </p>
          </article>
          <article className="rounded-xl border border-sky-300/15 bg-sky-300/5 p-4">
            <p className="text-xs uppercase tracking-wider text-sky-200">
              Trigger state
            </p>
            <p className="mt-3 text-sm leading-6">
              {typeof trigger.explanation === "string"
                ? trigger.explanation
                : "Trigger evidence is unknown."}
            </p>
          </article>
          <article className="rounded-xl border border-emerald-300/15 bg-emerald-300/5 p-4">
            <p className="text-xs uppercase tracking-wider text-emerald-200">
              What confirms the view?
            </p>
            <ul className="mt-3 grid gap-2 text-sm leading-6">
              {confirmationRequirements.map((item) => (
                <li key={item}>- {item}</li>
              ))}
            </ul>
          </article>
          <article className="rounded-xl border border-red-300/15 bg-red-300/5 p-4">
            <p className="text-xs uppercase tracking-wider text-red-200">
              What invalidates it?
            </p>
            <ul className="mt-3 grid gap-2 text-sm leading-6">
              {invalidationRequirements.map((item) => (
                <li key={item}>- {item}</li>
              ))}
            </ul>
          </article>
        </div>

        <div className="mt-4 grid gap-4 lg:grid-cols-[1.2fr_1fr]">
          <article className="rounded-xl border border-amber-300/20 bg-amber-300/5 p-4">
            <p className="text-xs uppercase tracking-wider text-amber-200">
              Highest-risk assumption
            </p>
            <p className="mt-3 text-sm leading-6">{decision.highest_risk_assumption}</p>
            {warnings.length ? (
              <ul className="mt-3 grid gap-2 text-xs leading-5 text-amber-50/80">
                {warnings.slice(1).map((warning) => (
                  <li key={warning}>- {warning}</li>
                ))}
              </ul>
            ) : null}
          </article>
          <article className="rounded-xl border border-[var(--border)] bg-black/10 p-4">
            <p className="text-xs uppercase tracking-wider text-[var(--muted)]">
              Risk contract
            </p>
            <dl className="mt-3 grid grid-cols-2 gap-3 text-sm">
              <div>
                <dt className="text-[var(--muted)]">Stop distance</dt>
                <dd>
                  {typeof risk.suggested_stop_distance_price === "number"
                    ? risk.suggested_stop_distance_price.toFixed(2)
                    : "Unknown"}
                </dd>
              </div>
              <div>
                <dt className="text-[var(--muted)]">Target zone</dt>
                <dd>
                  {typeof risk.target_zone === "number"
                    ? risk.target_zone.toFixed(2)
                    : "Unknown"}
                </dd>
              </div>
              <div>
                <dt className="text-[var(--muted)]">Reward / risk</dt>
                <dd>
                  {typeof risk.reward_to_risk === "number"
                    ? `${risk.reward_to_risk.toFixed(2)}R`
                    : "Unknown"}
                </dd>
              </div>
              <div>
                <dt className="text-[var(--muted)]">Position size</dt>
                <dd>{label(String(risk.total_open_risk ?? "unknown"))}</dd>
              </div>
            </dl>
          </article>
        </div>
      </section>

      <section className="mt-6 grid gap-6 xl:grid-cols-[1.45fr_1fr]">
        <article className="rounded-2xl border border-[var(--border)] bg-[var(--panel)]/90 p-6">
          <div className="flex flex-wrap items-end justify-between gap-3">
            <div>
              <p className="text-xs uppercase tracking-[0.16em] text-[var(--muted)]">
                Weighted evidence ledger
              </p>
              <h3 className="mt-2 text-xl font-semibold">What drives the score</h3>
            </div>
            <p className="text-xs text-[var(--muted)]">{decision.ruleset_version}</p>
          </div>
          <div className="mt-6 grid gap-4">
            {connected.map((component) => {
              const width = Math.max(
                2,
                Math.min(100, Math.abs(component.direction) * 100),
              );
              return (
                <div
                  className="rounded-xl border border-[var(--border)] bg-black/15 p-4"
                  key={component.code}
                >
                  <div className="flex flex-wrap items-start justify-between gap-3">
                    <div>
                      <p className="text-sm font-semibold">{label(component.code)}</p>
                      <p className="mt-1 text-xs text-[var(--muted)]">
                        Layer {component.layer} / {component.epistemic_status} / effective
                        weight {component.weight.toFixed(0)}
                      </p>
                    </div>
                    <p
                      className={`font-mono text-sm ${
                        component.contribution > 0
                          ? "text-emerald-300"
                          : component.contribution < 0
                            ? "text-red-300"
                            : "text-[var(--muted)]"
                      }`}
                    >
                      {signed(component.contribution)}
                    </p>
                  </div>
                  <div className="mt-3 h-1.5 overflow-hidden rounded-full bg-white/5">
                    <div
                      className={`h-full rounded-full ${
                        component.direction >= 0 ? "bg-emerald-300" : "bg-red-300"
                      }`}
                      style={{ width: `${width}%` }}
                    />
                  </div>
                  <p className="mt-3 text-sm leading-6 text-white/85">
                    {component.explanation}
                  </p>
                  <p className="mt-2 text-xs text-[var(--muted)]">
                    Strength {component.strength.toFixed(1)} / confidence{" "}
                    {component.confidence.toFixed(1)} / freshness{" "}
                    {component.freshness.toFixed(1)} / quality{" "}
                    {component.data_quality.toFixed(1)}
                  </p>
                </div>
              );
            })}
          </div>
        </article>

        <div className="grid content-start gap-6">
          <article className="rounded-2xl border border-[var(--border)] bg-[var(--panel-raised)]/90 p-6">
            <p className="text-xs uppercase tracking-[0.16em] text-[var(--muted)]">
              Explainable conclusion
            </p>
            <p className="mt-4 text-sm leading-7 text-white/90">
              {typeof decision.reasoning.summary === "string"
                ? decision.reasoning.summary
                : "No explanation is available."}
            </p>
            <dl className="mt-5 grid gap-4 border-t border-[var(--border)] pt-5 text-sm">
              <div>
                <dt className="text-xs text-[var(--muted)]">Main contradiction</dt>
                <dd className="mt-1">
                  {decision.main_contradiction ??
                    "No material contradiction in connected evidence."}
                </dd>
              </div>
              <div>
                <dt className="text-xs text-[var(--muted)]">Conflict within evidence</dt>
                <dd className="mt-1">
                  {decision.neutral_conflict_score.toFixed(1)}%
                </dd>
              </div>
              <div>
                <dt className="text-xs text-[var(--muted)]">Position size status</dt>
                <dd className="mt-1">
                  {label(String(risk.position_size_status ?? "unknown"))}
                </dd>
              </div>
            </dl>
          </article>

          <article className="rounded-2xl border border-amber-300/20 bg-amber-300/5 p-6">
            <p className="text-xs uppercase tracking-[0.16em] text-amber-200">
              Unknown is not neutral
            </p>
            <p className="mt-3 text-sm leading-6 text-white/90">
              {unknownComponents.length} directional component(s) are withheld from the
              score. Across the complete book, missing and stale factors reduce coverage
              instead of contributing zero.
            </p>
            <div className="mt-4 flex flex-wrap gap-2">
              {unknownComponents.map((component) => (
                <span
                  className="rounded-full border border-amber-300/15 px-2.5 py-1 text-[11px] text-amber-100"
                  key={component.code}
                >
                  {label(component.code)}
                </span>
              ))}
            </div>
          </article>
        </div>
      </section>

      <section className="mt-6 rounded-2xl border border-[var(--border)] bg-[var(--panel)]/90 p-6">
        <div className="flex flex-wrap items-end justify-between gap-3">
          <div>
            <p className="text-xs uppercase tracking-[0.16em] text-[var(--muted)]">
              Reference-book coverage
            </p>
            <h3 className="mt-2 text-xl font-semibold">
              All seven layers, measured against the full book
            </h3>
          </div>
          <div className="grid gap-1 text-right text-xs">
            <span className="text-[var(--gold)]">
              {decision.book_factor_coverage_pct.toFixed(1)}% connected full-book factors
            </span>
            <span className="text-[var(--muted)]">
              {decision.book_usable_coverage_pct.toFixed(1)}% usable now /{" "}
              {decision.phase1_factor_coverage_pct.toFixed(1)}% Phase 1 connected /{" "}
              {decision.directional_evidence_coverage_pct.toFixed(1)}% directional budget
            </span>
          </div>
        </div>
        <div className="mt-6 grid gap-3 sm:grid-cols-2 xl:grid-cols-7">
          {decision.layers.map((layer) => (
            <div
              className="rounded-xl border border-[var(--border)] bg-black/15 p-4"
              key={layer.number}
            >
              <div className="flex items-center justify-between gap-2">
                <span className="text-xs text-[var(--gold)]">L{layer.number}</span>
                <span
                  className={`rounded-full px-2 py-1 text-[9px] tracking-wider ${
                    statusTone[layer.operational_status] ??
                    statusTone[layer.status] ??
                    statusTone.UNKNOWN
                  }`}
                >
                  {layer.operational_status}
                </span>
              </div>
              <p className="mt-4 text-lg font-semibold">
                {layer.book_coverage_pct.toFixed(0)}%
              </p>
              <p className="mt-1 text-[11px] text-white/80">
                {layerNames[layer.number]}
              </p>
              <p className="mt-1 text-[11px] leading-4 text-[var(--muted)]">
                {layer.known_factor_count}/{layer.book_factor_count} book factors;{" "}
                {layer.usable_factor_count} usable
              </p>
              <p className="mt-3 text-[10px] leading-4 text-white/60">
                {layer.summary}
              </p>
            </div>
          ))}
        </div>
        <p className="mt-5 border-t border-[var(--border)] pt-4 font-mono text-[10px] text-[var(--muted)]">
          Registry {decision.registry_hash.slice(0, 16)}... / decision{" "}
          {decision.data_hash.slice(0, 16)}...
        </p>
        <Link
          className="mt-4 inline-block text-sm font-semibold text-[var(--gold)]"
          href="/data-health"
        >
          Open the complete factor and data-health ledger -&gt;
        </Link>
      </section>
    </>
  );
}
