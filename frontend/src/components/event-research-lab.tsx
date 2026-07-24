"use client";

import { useRouter } from "next/navigation";
import { useMemo, useState } from "react";
import type { ChangeEvent, FormEvent } from "react";

import {
  eventStudyRunSchema,
  publicApiUrl,
  type BacktestDataRange,
  type EconomicEvent,
  type EconomicSurprise,
  type EventStudyRun,
  type LicensedProviderHealth,
} from "@/lib/api";

type Props = {
  initialEvents: EconomicEvent[];
  initialSurprises: EconomicSurprise[];
  initialRuns: EventStudyRun[];
  priceRange: BacktestDataRange;
  tradingEconomics: LicensedProviderHealth;
  cmeFedWatch: LicensedProviderHealth;
  atlantaFedMpt: LicensedProviderHealth;
};

type StudyForm = {
  start: string;
  end: string;
  studyAsOf: string;
  minimumImportance: string;
  componentCodes: string;
};

type ResultGroup = {
  component_code: string;
  horizon_code: string;
  observations: number;
  average_return_pct: number | null;
  median_return_pct: number | null;
  expected_direction_alignment_pct: number | null;
  first_move_hold_pct: number | null;
};

const inputTime = (value: string | null, fallback: string) =>
  value ? new Date(value).toISOString().slice(0, 16) : fallback;

const metric = (value: number | null | undefined, suffix = "") =>
  value === null || value === undefined ? "N/A" : `${value.toFixed(3)}${suffix}`;

export function EventResearchLab({
  initialEvents,
  initialSurprises,
  initialRuns,
  priceRange,
  tradingEconomics,
  cmeFedWatch,
  atlantaFedMpt,
}: Props) {
  const router = useRouter();
  const [form, setForm] = useState<StudyForm>({
    start: inputTime(priceRange.earliest, "2026-06-23T08:15"),
    end: inputTime(priceRange.latest, "2026-07-23T08:15"),
    studyAsOf: inputTime(priceRange.latest, "2026-07-23T08:15"),
    minimumImportance: "3",
    componentCodes: "",
  });
  const [run, setRun] = useState<EventStudyRun | null>(
    initialRuns[0] ?? null,
  );
  const [running, setRunning] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [policyUploading, setPolicyUploading] = useState(false);
  const [syncingProvider, setSyncingProvider] = useState<
    LicensedProviderHealth["provider"] | null
  >(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const resultGroups = useMemo(
    () => parseGroups(run?.results.groups),
    [run],
  );
  const exclusionCount =
    typeof run?.exclusions.count === "number" ? run.exclusions.count : 0;

  const update = (key: keyof StudyForm, value: string) =>
    setForm((current) => ({ ...current, [key]: value }));

  async function submitStudy(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setRunning(true);
    setError(null);
    setNotice(null);
    try {
      const componentCodes = form.componentCodes
        .split(",")
        .map((value) => value.trim().toUpperCase())
        .filter(Boolean);
      const response = await fetch(`${publicApiUrl}/event-studies/runs`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          instrument: "XAUUSD",
          provider_code: "IC_MARKETS_MT5",
          start: new Date(`${form.start}:00Z`).toISOString(),
          end: new Date(`${form.end}:00Z`).toISOString(),
          study_as_of: new Date(`${form.studyAsOf}:00Z`).toISOString(),
          data_mode: "REAL_ONLY",
          minimum_importance: Number(form.minimumImportance),
          component_codes: componentCodes,
        }),
      });
      const payload: unknown = await response.json();
      if (!response.ok) {
        throw new Error(apiError(payload, response.status));
      }
      const parsed = eventStudyRunSchema.parse(payload);
      setRun(parsed);
      setNotice(
        parsed.eligible_count
          ? `Completed with ${parsed.eligible_count} eligible release(s).`
          : "Completed correctly with no eligible real releases. Upload point-in-time consensus and release facts before interpreting this as a market result.",
      );
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Event study failed.");
    } finally {
      setRunning(false);
    }
  }

  async function uploadBundle(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    if (!file) return;
    setUploading(true);
    setError(null);
    setNotice(null);
    try {
      const payload: unknown = JSON.parse(await file.text());
      const response = await fetch(`${publicApiUrl}/events/bundles`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      const result: unknown = await response.json();
      if (!response.ok) {
        throw new Error(apiError(result, response.status));
      }
      if (!isRecord(result)) {
        throw new Error("The API returned an invalid bundle response.");
      }
      setNotice(
        `Bundle accepted: ${String(result.event_count ?? 0)} event(s), ${String(result.forecast_count ?? 0)} forecast(s), ${String(result.release_count ?? 0)} release row(s).`,
      );
      router.refresh();
    } catch (reason) {
      setError(
        reason instanceof Error ? reason.message : "Bundle upload failed.",
      );
    } finally {
      event.target.value = "";
      setUploading(false);
    }
  }

  async function uploadPolicyPath(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    if (!file) return;
    setPolicyUploading(true);
    setError(null);
    setNotice(null);
    try {
      const payload: unknown = JSON.parse(await file.text());
      const response = await fetch(
        `${publicApiUrl}/expectations/policy-paths/bundles`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload),
        },
      );
      const result: unknown = await response.json();
      if (!response.ok) {
        throw new Error(apiError(result, response.status));
      }
      if (!isRecord(result)) {
        throw new Error("The API returned an invalid policy-path response.");
      }
      setNotice(
        `Policy path accepted: ${String(result.snapshot_count ?? 0)} snapshot(s), ${String(result.point_count ?? 0)} probability point(s).`,
      );
      router.refresh();
    } catch (reason) {
      setError(
        reason instanceof Error
          ? reason.message
          : "Policy-path upload failed.",
      );
    } finally {
      event.target.value = "";
      setPolicyUploading(false);
    }
  }

  async function syncLicensedProvider(
    provider: LicensedProviderHealth["provider"],
  ) {
    const start = form.start.slice(0, 10);
    const end = form.end.slice(0, 10);
    if (provider === "trading_economics" && start >= end) {
      setError("Trading Economics sync needs at least a two-date interval.");
      return;
    }
    setSyncingProvider(provider);
    setError(null);
    setNotice(null);
    try {
      const endpoint =
        provider === "trading_economics"
          ? "trading-economics"
          : provider === "cme_fedwatch"
            ? "cme-fedwatch"
            : "atlanta-fed-mpt";
      const response = await fetch(`${publicApiUrl}/providers/${endpoint}/sync`, {
        method: "POST",
        ...(provider === "atlanta_fed_mpt"
          ? {}
          : {
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ start, end }),
            }),
      });
      const payload: unknown = await response.json();
      if (!response.ok) {
        throw new Error(apiError(payload, response.status));
      }
      if (!isRecord(payload)) {
        throw new Error("The provider returned an invalid sync response.");
      }
      setNotice(
        provider === "trading_economics"
          ? `Calendar sync complete: ${String(payload.supported_rows ?? 0)} supported row(s), ${String(payload.inserted_events ?? 0)} event version(s) inserted.`
          : provider === "cme_fedwatch"
            ? `Fed-path sync complete: ${String(payload.inserted_snapshots ?? 0)} snapshot(s), ${String(payload.inserted_points ?? 0)} probability point(s) inserted.`
            : `Atlanta Fed history synced: ${String(payload.fetched_observation_dates ?? 0)} observation date(s), ${String(payload.inserted_windows ?? 0)} new quarterly window(s).`,
      );
      router.refresh();
    } catch (reason) {
      setError(
        reason instanceof Error ? reason.message : "Licensed-provider sync failed.",
      );
    } finally {
      setSyncingProvider(null);
    }
  }

  return (
    <div className="grid gap-6">
      <section className="grid gap-4 md:grid-cols-3">
        <Stat
          label="Real calendar records"
          value={initialEvents.length.toLocaleString()}
          note="Source-versioned events available now"
        />
        <Stat
          label="Eligible surprises"
          value={initialSurprises.length.toLocaleString()}
          note="Actual vs pre-release consensus only"
        />
        <Stat
          label="Reaction studies"
          value={initialRuns.length.toLocaleString()}
          note="Saved, reproducible research runs"
        />
      </section>

      {(error || notice) && (
        <div
          className={`rounded-xl border px-4 py-3 text-sm ${
            error
              ? "border-rose-400/30 bg-rose-400/10 text-rose-100"
              : "border-emerald-400/30 bg-emerald-400/10 text-emerald-100"
          }`}
        >
          {error ?? notice}
        </div>
      )}

      <section className="grid gap-6 xl:grid-cols-[390px_1fr]">
        <div className="grid content-start gap-6">
          <form
            className="rounded-2xl border border-[var(--border)] bg-[var(--panel)]/90 p-6"
            onSubmit={submitStudy}
          >
            <p className="text-xs uppercase tracking-[0.16em] text-[var(--gold)]">
              Event-study controls
            </p>
            <h3 className="mt-2 text-xl font-semibold">
              Replay post-release gold
            </h3>
            <p className="mt-3 text-xs leading-5 text-[var(--muted)]">
              Uses the last complete pre-release minute, then measures 1m, 5m,
              15m, 1h, 4h, and New York daily-close reactions.
            </p>
            <div className="mt-6 grid gap-4">
              <Field label="Release period start (UTC)">
                <input
                  className="field"
                  type="datetime-local"
                  value={form.start}
                  onChange={(event) => update("start", event.target.value)}
                />
              </Field>
              <Field label="Release period end (UTC)">
                <input
                  className="field"
                  type="datetime-local"
                  value={form.end}
                  onChange={(event) => update("end", event.target.value)}
                />
              </Field>
              <Field label="Research cutoff (UTC)">
                <input
                  className="field"
                  type="datetime-local"
                  value={form.studyAsOf}
                  onChange={(event) => update("studyAsOf", event.target.value)}
                />
              </Field>
              <Field label="Minimum importance">
                <select
                  className="field"
                  value={form.minimumImportance}
                  onChange={(event) =>
                    update("minimumImportance", event.target.value)
                  }
                >
                  <option value="5">5 — systemic</option>
                  <option value="4">4 — major</option>
                  <option value="3">3 — material</option>
                  <option value="2">2 — moderate</option>
                  <option value="1">1 — all</option>
                </select>
              </Field>
              <Field label="Components (optional CSV)">
                <input
                  className="field"
                  placeholder="CPI_CORE_MOM,NFP_CHANGE"
                  value={form.componentCodes}
                  onChange={(event) =>
                    update("componentCodes", event.target.value)
                  }
                />
              </Field>
            </div>
            <button
              className="mt-6 w-full rounded-lg bg-[var(--gold)] px-4 py-3 text-sm font-semibold text-[#172018] disabled:opacity-50"
              disabled={running}
              type="submit"
            >
              {running ? "Running point-in-time study…" : "Run event study"}
            </button>
          </form>

          <div className="rounded-2xl border border-[var(--border)] bg-[var(--panel)]/90 p-6">
            <p className="text-xs uppercase tracking-[0.16em] text-[var(--gold)]">
              Data intake
            </p>
            <h3 className="mt-2 text-lg font-semibold">Point-in-time sources</h3>
            <p className="mt-3 text-xs leading-5 text-[var(--muted)]">
              Sync uses the event-study date interval above. Credentials stay
              server-side and are never sent to the browser.
            </p>
            <div className="mt-5 grid gap-3">
              {[
                {
                  health: atlantaFedMpt,
                  label: "Atlanta Fed MPT",
                  detail: "Real quarterly SOFR option distributions · no API key",
                },
                {
                  health: tradingEconomics,
                  label: "Trading Economics",
                  detail: "Calendar, consensus, actuals, and revisions",
                },
                {
                  health: cmeFedWatch,
                  label: "CME FedWatch EOD",
                  detail: "Full meeting-by-meeting rate distributions",
                },
              ].map(({ health, label, detail }) => (
                <div
                  className="rounded-xl border border-[var(--border)] bg-black/10 p-4"
                  key={health.provider}
                >
                  <div className="flex items-start justify-between gap-3">
                    <div>
                      <p className="text-sm font-medium">{label}</p>
                      <p className="mt-1 text-[11px] text-[var(--muted)]">
                        {detail}
                      </p>
                    </div>
                    <span
                      className={`rounded-full px-2 py-1 text-[10px] ${
                        health.configured
                          ? "bg-emerald-400/10 text-emerald-200"
                          : "bg-amber-300/10 text-amber-100"
                      }`}
                    >
                      {health.configured ? "Configured" : "Needs credentials"}
                    </span>
                  </div>
                  <button
                    className="mt-3 w-full rounded-lg border border-[var(--border)] px-3 py-2 text-xs text-[var(--gold)] transition hover:bg-white/5 disabled:cursor-not-allowed disabled:opacity-40"
                    disabled={
                      !health.configured || syncingProvider !== null
                    }
                    onClick={() => syncLicensedProvider(health.provider)}
                    type="button"
                  >
                    {syncingProvider === health.provider
                      ? "Syncing real source…"
                      : health.provider === "atlanta_fed_mpt"
                        ? "Sync official history"
                        : "Sync selected interval"}
                  </button>
                  <p className="mt-2 text-[10px] leading-4 text-[var(--muted)]">
                    {health.note}
                  </p>
                </div>
              ))}
            </div>
            <p className="mt-6 text-xs leading-5 text-[var(--muted)]">
              Manual JSON remains the provider-independent fallback. It must
              carry schedule-known time, consensus time, release time,
              availability time, vintage, and an explicit synthetic flag.
              Late forecasts are rejected.
            </p>
            <label className="mt-5 block cursor-pointer rounded-lg border border-dashed border-[var(--border)] px-4 py-4 text-center text-sm text-[var(--gold)] hover:bg-white/5">
              {uploading ? "Validating and ingesting…" : "Choose JSON bundle"}
              <input
                className="sr-only"
                type="file"
                accept="application/json,.json"
                disabled={uploading}
                onChange={uploadBundle}
              />
            </label>
            <label className="mt-3 block cursor-pointer rounded-lg border border-dashed border-[var(--border)] px-4 py-4 text-center text-sm text-[var(--gold)] hover:bg-white/5">
              {policyUploading
                ? "Validating policy path…"
                : "Choose Fed-path JSON bundle"}
              <input
                className="sr-only"
                type="file"
                accept="application/json,.json"
                disabled={policyUploading}
                onChange={uploadPolicyPath}
              />
            </label>
            <p className="mt-3 text-[11px] leading-4 text-[var(--muted)]">
              Synthetic examples remain isolated from real-data calculations.
            </p>
          </div>
        </div>

        <div className="grid content-start gap-6">
          <section className="rounded-2xl border border-[var(--border)] bg-[var(--panel)]/90 p-6">
            <div className="flex flex-wrap items-start justify-between gap-4">
              <div>
                <p className="text-xs uppercase tracking-[0.16em] text-[var(--gold)]">
                  Latest result
                </p>
                <h3 className="mt-2 text-xl font-semibold">
                  {run ? run.status.replaceAll("_", " ") : "No study yet"}
                </h3>
              </div>
              {run && (
                <div className="text-right text-xs text-[var(--muted)]">
                  <p>{run.candidate_count} candidates</p>
                  <p>{run.eligible_count} eligible</p>
                  <p>{exclusionCount} excluded</p>
                </div>
              )}
            </div>
            {!run ? (
              <Empty message="Run a study after loading real point-in-time event facts." />
            ) : resultGroups.length === 0 ? (
              <Empty message="No reaction groups were eligible. The exclusions are preserved in the run rather than silently dropped." />
            ) : (
              <div className="mt-5 overflow-x-auto">
                <table className="w-full min-w-[760px] text-left text-xs">
                  <thead className="text-[var(--muted)]">
                    <tr>
                      <th className="pb-3 font-medium">Component</th>
                      <th className="pb-3 font-medium">Horizon</th>
                      <th className="pb-3 font-medium">N</th>
                      <th className="pb-3 font-medium">Average</th>
                      <th className="pb-3 font-medium">Median</th>
                      <th className="pb-3 font-medium">Macro aligned</th>
                      <th className="pb-3 font-medium">First move held</th>
                    </tr>
                  </thead>
                  <tbody>
                    {resultGroups.map((group) => (
                      <tr
                        className="border-t border-[var(--border)]"
                        key={`${group.component_code}:${group.horizon_code}`}
                      >
                        <td className="py-3 font-medium">{group.component_code}</td>
                        <td className="py-3">{group.horizon_code}</td>
                        <td className="py-3">{group.observations}</td>
                        <td className="py-3">
                          {metric(group.average_return_pct, "%")}
                        </td>
                        <td className="py-3">
                          {metric(group.median_return_pct, "%")}
                        </td>
                        <td className="py-3">
                          {metric(group.expected_direction_alignment_pct, "%")}
                        </td>
                        <td className="py-3">
                          {metric(group.first_move_hold_pct, "%")}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </section>

          <section className="rounded-2xl border border-[var(--border)] bg-[var(--panel)]/90 p-6">
            <p className="text-xs uppercase tracking-[0.16em] text-[var(--gold)]">
              Point-in-time calendar
            </p>
            {initialEvents.length === 0 ? (
              <Empty message="No real event calendar has been ingested. This is a data gap, not a neutral signal." />
            ) : (
              <div className="mt-4 grid gap-3">
                {initialEvents.slice(0, 8).map((event) => (
                  <div
                    className="flex flex-wrap items-center justify-between gap-3 rounded-xl bg-black/15 px-4 py-3"
                    key={event.id}
                  >
                    <div>
                      <p className="text-sm font-medium">{event.name}</p>
                      <p className="mt-1 text-xs text-[var(--muted)]">
                        {new Date(event.scheduled_at).toLocaleString()} ·{" "}
                        {event.status}
                      </p>
                    </div>
                    <span className="text-xs text-[var(--gold)]">
                      Importance {event.importance}/5
                    </span>
                  </div>
                ))}
              </div>
            )}
          </section>

          <section className="rounded-2xl border border-[var(--border)] bg-[var(--panel)]/90 p-6">
            <p className="text-xs uppercase tracking-[0.16em] text-[var(--gold)]">
              Explainable surprises
            </p>
            {initialSurprises.length === 0 ? (
              <Empty message="No actual-versus-consensus surprise is currently eligible." />
            ) : (
              <div className="mt-4 grid gap-3">
                {initialSurprises.slice(0, 8).map((surprise) => (
                  <div
                    className="rounded-xl bg-black/15 px-4 py-3"
                    key={surprise.id}
                  >
                    <div className="flex flex-wrap justify-between gap-2">
                      <p className="text-sm font-medium">
                        {surprise.component_code}
                      </p>
                      <p
                        className={
                          surprise.gold_direction > 0
                            ? "text-emerald-300"
                            : surprise.gold_direction < 0
                              ? "text-rose-300"
                              : "text-[var(--muted)]"
                        }
                      >
                        {surprise.gold_direction > 0 ? "+" : ""}
                        {surprise.gold_direction.toFixed(2)} gold direction
                      </p>
                    </div>
                    <p className="mt-2 text-xs leading-5 text-[var(--muted)]">
                      {surprise.explanation}
                    </p>
                  </div>
                ))}
              </div>
            )}
          </section>
        </div>
      </section>
    </div>
  );
}

function Stat({
  label,
  value,
  note,
}: {
  label: string;
  value: string;
  note: string;
}) {
  return (
    <div className="rounded-2xl border border-[var(--border)] bg-[var(--panel)]/90 p-5">
      <p className="text-xs uppercase tracking-[0.14em] text-[var(--muted)]">
        {label}
      </p>
      <p className="mt-2 text-3xl font-semibold">{value}</p>
      <p className="mt-2 text-xs text-[var(--muted)]">{note}</p>
    </div>
  );
}

function Field({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <label className="grid gap-1.5 text-xs text-[var(--muted)]">
      {label}
      {children}
    </label>
  );
}

function Empty({ message }: { message: string }) {
  return (
    <div className="mt-5 rounded-xl border border-dashed border-[var(--border)] px-5 py-6 text-sm leading-6 text-[var(--muted)]">
      {message}
    </div>
  );
}

function parseGroups(value: unknown): ResultGroup[] {
  if (!Array.isArray(value)) return [];
  return value.flatMap((item) => {
    if (!isRecord(item)) return [];
    const observations = item.observations;
    if (
      typeof item.component_code !== "string" ||
      typeof item.horizon_code !== "string" ||
      typeof observations !== "number"
    ) {
      return [];
    }
    return [
      {
        component_code: item.component_code,
        horizon_code: item.horizon_code,
        observations,
        average_return_pct: nullableNumber(item.average_return_pct),
        median_return_pct: nullableNumber(item.median_return_pct),
        expected_direction_alignment_pct: nullableNumber(
          item.expected_direction_alignment_pct,
        ),
        first_move_hold_pct: nullableNumber(item.first_move_hold_pct),
      },
    ];
  });
}

function nullableNumber(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function apiError(payload: unknown, status: number): string {
  if (isRecord(payload)) {
    if (typeof payload.detail === "string") return payload.detail;
    if (Array.isArray(payload.detail)) {
      return payload.detail
        .map((item) =>
          isRecord(item) && typeof item.msg === "string"
            ? item.msg
            : "Validation error",
        )
        .join("; ");
    }
  }
  return `Request failed with HTTP ${status}`;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}
