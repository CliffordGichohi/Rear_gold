import { getLatestFundamental } from "@/lib/server-api";

export const dynamic = "force-dynamic";

const label = (value: string) =>
  value
    .toLowerCase()
    .split("_")
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
    .join(" ");

const valueText = (value: unknown) => {
  if (typeof value === "number") return value.toFixed(4).replace(/0+$/, "").replace(/\.$/, "");
  if (typeof value === "boolean") return value ? "Yes" : "No";
  if (typeof value === "string") return value;
  return null;
};

export default async function MacroRegimePage() {
  const snapshot = await getLatestFundamental();
  const macroComponents = snapshot.components.filter((component) =>
    [1, 2, 6].includes(component.layer),
  );

  return (
    <div className="mx-auto max-w-[1400px]">
      <header>
        <p className="text-xs font-semibold uppercase tracking-[0.22em] text-[var(--gold)]">
          Macro regime
        </p>
        <h2 className="mt-2 text-3xl font-semibold tracking-tight">
          Levels, direction, and what is still unknown.
        </h2>
        <p className="mt-3 max-w-3xl text-sm leading-6 text-[var(--muted)]">
          Every row uses only evidence available by the snapshot clock. A missing release
          vintage or forecast remains outside the score.
        </p>
      </header>

      <section className="mt-7 grid gap-4 md:grid-cols-3">
        {[
          ["Regime", label(snapshot.regime)],
          ["Reaction function", label(snapshot.reaction_function)],
          ["Directional score", `${snapshot.directional_score >= 0 ? "+" : ""}${snapshot.directional_score.toFixed(2)}`],
        ].map(([name, value]) => (
          <article
            className="rounded-2xl border border-[var(--border)] bg-[var(--panel)] p-5"
            key={name}
          >
            <p className="text-xs uppercase tracking-[0.15em] text-[var(--muted)]">{name}</p>
            <p className="mt-4 text-xl font-semibold">{value}</p>
          </article>
        ))}
      </section>

      <section className="mt-6 grid gap-4 lg:grid-cols-2">
        {macroComponents.map((component) => (
          <article
            className={`rounded-2xl border p-5 ${
              component.epistemic_status === "UNKNOWN"
                ? "border-amber-300/15 bg-amber-300/5"
                : "border-[var(--border)] bg-[var(--panel)]"
            }`}
            key={component.code}
          >
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div>
                <p className="text-xs uppercase tracking-[0.15em] text-[var(--muted)]">
                  Layer {component.layer} · {component.epistemic_status}
                </p>
                <h3 className="mt-2 text-lg font-semibold">{label(component.code)}</h3>
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
                {component.contribution >= 0 ? "+" : ""}
                {component.contribution.toFixed(3)}
              </p>
            </div>
            <p className="mt-4 text-sm leading-6 text-white/90">{component.explanation}</p>
            {Object.keys(component.evidence).length ? (
              <dl className="mt-5 grid gap-3 border-t border-[var(--border)] pt-4 sm:grid-cols-2">
                {Object.entries(component.evidence).map(([key, value]) => {
                  const rendered = valueText(value);
                  return rendered ? (
                    <div key={key}>
                      <dt className="text-[10px] uppercase tracking-wider text-[var(--muted)]">
                        {label(key)}
                      </dt>
                      <dd className="mt-1 break-words text-xs">{rendered}</dd>
                    </div>
                  ) : null;
                })}
              </dl>
            ) : null}
          </article>
        ))}
      </section>
    </div>
  );
}
