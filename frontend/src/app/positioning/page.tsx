import { getLatestFundamental } from "@/lib/server-api";

export const dynamic = "force-dynamic";

const numberValue = (value: unknown) => (typeof value === "number" ? value : null);
const textValue = (value: unknown) => (typeof value === "string" ? value : "UNKNOWN");

export default async function PositioningPage() {
  const snapshot = await getLatestFundamental();
  const component = snapshot.components.find(
    (candidate) => candidate.code === "POSITIONING_FLOW",
  );
  const evidence = component?.evidence ?? {};
  const crowding = snapshot.reasoning.crowding;

  return (
    <div className="mx-auto max-w-[1200px]">
      <header>
        <p className="text-xs font-semibold uppercase tracking-[0.22em] text-[var(--gold)]">
          Positioning
        </p>
        <h2 className="mt-2 text-3xl font-semibold tracking-tight">
          Published CFTC positioning, never inferred intent as fact.
        </h2>
        <p className="mt-3 max-w-3xl text-sm leading-6 text-[var(--muted)]">
          Tuesday observations become eligible only at their scheduled publication time.
          The motive classification remains calculated or inferred.
        </p>
      </header>

      <section className="mt-7 grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        {[
          ["Managed-money long", numberValue(evidence.managed_money_long)?.toLocaleString() ?? "Unknown"],
          ["Managed-money short", numberValue(evidence.managed_money_short)?.toLocaleString() ?? "Unknown"],
          ["Net position", numberValue(evidence.managed_money_net)?.toLocaleString() ?? "Unknown"],
          [
            "Historical percentile",
            numberValue(crowding.percentile) !== null
              ? `${numberValue(crowding.percentile)?.toFixed(1)}%`
              : "Unknown",
          ],
        ].map(([name, value]) => (
          <article
            className="rounded-2xl border border-[var(--border)] bg-[var(--panel)] p-5"
            key={name}
          >
            <p className="text-xs uppercase tracking-[0.15em] text-[var(--muted)]">{name}</p>
            <p className="mt-4 text-2xl font-semibold">{value}</p>
          </article>
        ))}
      </section>

      <section className="mt-6 grid gap-6 lg:grid-cols-[1.3fr_1fr]">
        <article className="rounded-2xl border border-[var(--border)] bg-[var(--panel)] p-6">
          <p className="text-xs uppercase tracking-[0.16em] text-[var(--muted)]">
            Current published change
          </p>
          <h3 className="mt-2 text-xl font-semibold">
            {textValue(crowding.state).replaceAll("_", " ")}
          </h3>
          <p className="mt-4 text-sm leading-7 text-white/90">
            {component?.explanation ?? "No eligible COT report is available."}
          </p>
          <dl className="mt-5 grid gap-4 border-t border-[var(--border)] pt-5 sm:grid-cols-2">
            {[
              ["Observation date", textValue(evidence.observation_date)],
              ["Published at", textValue(evidence.publication_at)],
              ["Net weekly change", numberValue(evidence.net_change)?.toLocaleString() ?? "Unknown"],
              ["Open interest", numberValue(evidence.open_interest)?.toLocaleString() ?? "Unknown"],
            ].map(([name, value]) => (
              <div key={name}>
                <dt className="text-xs text-[var(--muted)]">{name}</dt>
                <dd className="mt-1 text-sm">{value}</dd>
              </div>
            ))}
          </dl>
        </article>

        <article className="rounded-2xl border border-amber-300/20 bg-amber-300/5 p-6">
          <p className="text-xs uppercase tracking-[0.16em] text-amber-200">
            Classification boundary
          </p>
          <p className="mt-4 text-sm leading-7">
            {textValue(evidence.classification_warning)}
          </p>
          <p className="mt-4 text-xs leading-5 text-[var(--muted)]">
            ETF flows, options strikes, dealer gamma, and central-bank demand remain separate
            unknown factors until licensed or point-in-time providers are connected.
          </p>
        </article>
      </section>
    </div>
  );
}
