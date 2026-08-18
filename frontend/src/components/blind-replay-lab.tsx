"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { FormEvent } from "react";

import {
  blindReplayCaseSchema,
  blindReplayDecisionResponseSchema,
  blindReplayStatusSchema,
  publicApiUrl,
  type BlindReplayCase,
  type BlindReplayDecisionResponse,
  type BlindReplayStatus,
} from "@/lib/api";
import {
  ReplayChartWorkspace,
  type PositionPlan,
  type ReplayChartEvent,
} from "@/components/replay-chart-workspace";


const timeframes = ["1w", "1d", "4h", "1h", "15m", "5m", "1m"] as const;
const evidenceOptions = [
  "FUNDAMENTAL_ALIGNMENT",
  "HTF_TREND",
  "SUPPORT_RESISTANCE",
  "LIQUIDITY_SWEEP",
  "ACCEPTANCE_REJECTION",
  "BREAK_RETEST",
  "SESSION_RANGE",
  "CROSS_MARKET_CONFIRMATION",
  "POSITIONING",
  "OTHER",
] as const;
type Action = "LONG" | "SHORT" | "NO_TRADE";
type Trigger = "MARKET" | "PULLBACK_LIMIT" | "BREAKOUT_STOP";

export type PositionExecution = {
  action: "LONG" | "SHORT";
  trigger: Trigger;
  entryOffsetAtr: number;
  stopDistanceAtr: number;
  targetR: number;
};


export function positionPlanToExecution(
  plan: PositionPlan,
  m15AtrIndex: number,
): { execution: PositionExecution; error: null } | { execution: null; error: string } {
  if (!(m15AtrIndex > 0)) {
    return { execution: null, error: "The displayed M15 ATR is unavailable; position geometry cannot be converted." };
  }
  const entryOffsetAtr = (plan.entryIndex - 100) / m15AtrIndex;
  const stopDistanceAtr = Math.abs(plan.entryIndex - plan.stopIndex) / m15AtrIndex;
  const riskDistance = Math.abs(plan.entryIndex - plan.stopIndex);
  const targetR = Math.abs(plan.targetIndex - plan.entryIndex) / riskDistance;
  if (Math.abs(entryOffsetAtr) > 2) {
    return { execution: null, error: `Entry is ${entryOffsetAtr.toFixed(2)} ATR from index 100; the frozen maximum is 2.00 ATR.` };
  }
  if (stopDistanceAtr < 0.25 || stopDistanceAtr > 3) {
    return { execution: null, error: `Stop is ${stopDistanceAtr.toFixed(2)} ATR from entry; the frozen range is 0.25–3.00 ATR.` };
  }
  if (targetR < 0.5 || targetR > 5) {
    return { execution: null, error: `Target is ${targetR.toFixed(2)}R; the frozen range is 0.50–5.00R.` };
  }
  let trigger: Trigger;
  let normalizedOffset = entryOffsetAtr;
  if (Math.abs(entryOffsetAtr) < 1e-9) {
    trigger = "MARKET";
    normalizedOffset = 0;
  } else if (
    (plan.direction === "LONG" && entryOffsetAtr < 0) ||
    (plan.direction === "SHORT" && entryOffsetAtr > 0)
  ) {
    trigger = "PULLBACK_LIMIT";
  } else {
    trigger = "BREAKOUT_STOP";
  }
  return {
    error: null,
    execution: {
      action: plan.direction,
      trigger,
      entryOffsetAtr: Number(normalizedOffset.toFixed(6)),
      stopDistanceAtr: Number(stopDistanceAtr.toFixed(6)),
      targetR: Number(targetR.toFixed(6)),
    },
  };
}

function offsetRule(action: Action | null, trigger: Trigger) {
  if (!action || action === "NO_TRADE" || trigger === "MARKET") {
    return {
      minimum: 0,
      maximum: 0,
      initial: 0,
      hint: "Market uses the first eligible M1 open after the frozen one-minute latency.",
    };
  }
  if (trigger === "PULLBACK_LIMIT") {
    return action === "LONG"
      ? {
          minimum: -2,
          maximum: 0,
          initial: -0.25,
          hint: "Long pullback: use a negative offset below index 100.",
        }
      : {
          minimum: 0,
          maximum: 2,
          initial: 0.25,
          hint: "Short pullback: use a positive offset above index 100.",
        };
  }
  return action === "LONG"
    ? {
        minimum: 0,
        maximum: 2,
        initial: 0.25,
        hint: "Long breakout: use a positive offset above index 100.",
      }
    : {
        minimum: -2,
        maximum: 0,
        initial: -0.25,
        hint: "Short breakout: use a negative offset below index 100.",
      };
}


function record(value: unknown): Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {};
}


function text(value: unknown, fallback = "UNKNOWN") {
  if (value === null || value === undefined || value === "") return fallback;
  return typeof value === "number" ? value.toFixed(2) : String(value);
}


function compactMacroState(explanationValue: unknown) {
  const explanation = text(explanationValue).toLowerCase();
  const states: Array<[RegExp, string]> = [
    [/unavailable|unknown/, "UNKNOWN"],
    [/positive surprise/, "POSITIVE SURPRISE"],
    [/negative surprise/, "NEGATIVE SURPRISE"],
    [/gold-negative/, "GOLD-NEGATIVE SURPRISE"],
    [/gold-positive/, "GOLD-POSITIVE SURPRISE"],
    [/reflation|accelerat/, "ACCELERATING"],
    [/disinflation|decelerat/, "DISINFLATING"],
    [/falling|decreased|declin|lowering/, "FALLING"],
    [/rising|increased|higher/, "RISING"],
    [/weakening|weaker/, "WEAKENING"],
    [/strengthening|stronger/, "STRENGTHENING"],
    [/tightening|tighter/, "TIGHTENING"],
    [/easing|easier/, "EASING"],
    [/defensive/, "DEFENSIVE"],
    [/normal or mixed/, "MIXED"],
  ];
  return states.find(([pattern]) => pattern.test(explanation))?.[1] ?? "MIXED";
}


function chartEvent(value: unknown): ReplayChartEvent | null {
  const event = record(value);
  if (typeof event.event_code !== "string" || typeof event.minutes_before_checkpoint !== "number") return null;
  const surprises = Array.isArray(event.surprises) ? event.surprises.map(record) : [];
  const first = surprises[0];
  const raw = typeof first?.raw_surprise === "number" ? first.raw_surprise : null;
  const direction = typeof first?.gold_direction === "number" ? first.gold_direction : null;
  const surpriseLabel = raw === null ? null : raw > 0 ? "POSITIVE SURPRISE" : raw < 0 ? "NEGATIVE SURPRISE" : "ON FORECAST";
  return {
    eventCode: event.event_code,
    name: text(event.name, event.event_code),
    minutesBeforeCheckpoint: Math.max(0, Math.round(event.minutes_before_checkpoint)),
    importance: typeof event.importance === "number" ? event.importance : null,
    surpriseLabel,
    goldImpact: direction === null ? null : direction > 0.05 ? "SUPPORTIVE" : direction < -0.05 ? "PRESSURE" : "NEUTRAL",
  };
}


function apiError(payload: unknown, status: number) {
  const candidate = record(payload).detail;
  if (typeof candidate === "string") return candidate;
  if (Array.isArray(candidate)) {
    return candidate.map((item) => text(record(item).msg, "Invalid decision")).join("; ");
  }
  return `Replay request failed with HTTP ${status}`;
}


function ReplayInstructions() {
  return (
    <details className="rounded-2xl border border-[#D1D4DC] bg-white p-5 shadow-sm" open>
      <summary className="cursor-pointer text-sm font-semibold text-[#131722]">
        How to label each case — use the same top-down process every time
      </summary>
      <div className="mt-5 grid gap-4 text-sm leading-6 text-[#5D606B] md:grid-cols-2 xl:grid-cols-5">
        <div><strong className="text-[#131722]">1 · Direction</strong><p>Read fundamentals first. Decide whether they support gold, oppose gold, or conflict. This is context, not an automatic entry.</p></div>
        <div><strong className="text-[#131722]">2 · Location</strong><p>Read W1, D1, H4 and H1. Identify trend, range, support, resistance and known liquidity relative to index 100.</p></div>
        <div><strong className="text-[#131722]">3 · Trigger</strong><p>Use M15, M5 and M1 to decide whether price has accepted, rejected, swept, reclaimed, broken or retested a level.</p></div>
        <div><strong className="text-[#131722]">4 · Plan</strong><p>Long/Short takes three marks: ENTRY, SL, then TP. Select a drawing to edit or delete it; add your remark, arm the plan, then use Place &amp; Play.</p></div>
        <div><strong className="text-[#131722]">5 · Lock</strong><p>Record confidence and evidence, then lock once. Practice reveals its path afterward; scored cases reveal nothing until all 240 are complete.</p></div>
      </div>
      <div className="mt-4 rounded-xl border border-[#B7C7FF] bg-[#EEF3FF] p-4 text-sm leading-6 text-[#174EA6]">
        Your task is not to describe what eventually happened. Your task is to record exactly what you would trade now. Use <strong>NO TRADE</strong> whenever direction, location or trigger is not sufficiently clear.
      </div>
    </details>
  );
}


function FundamentalSummary({
  fundamental,
  crossMarket,
  positioning,
  liquidity,
}: {
  fundamental: Record<string, unknown>;
  crossMarket: Record<string, unknown>;
  positioning: Record<string, unknown>;
  liquidity: Record<string, unknown>;
}) {
  const bias = text(fundamental.bias_label);
  const tone = bias.includes("BULL")
    ? "border-[#A5DCCF] bg-[#EAF8F4] text-[#087363]"
    : bias.includes("BEAR")
      ? "border-[#F3B3B8] bg-[#FFF0F1] text-[#B4232F]"
      : bias.includes("CONFLICT")
        ? "border-[#E8D28A] bg-[#FFF9E6] text-[#785D00]"
        : "border-[#D1D4DC] bg-[#F4F5F7] text-[#434651]";
  const componentRows = Array.isArray(fundamental.components)
    ? fundamental.components.map(record)
    : [];
  const macroPulseCodes = [
    "REAL_YIELD",
    "TWO_YEAR_YIELD",
    "INFLATION_REGIME",
    "GROWTH_REGIME",
    "LABOUR_REGIME",
    "USD",
    "CATALYST_SURPRISE",
  ];
  const macroPulse = macroPulseCodes.flatMap((code) => {
    const row = componentRows.find((component) => component.code === code);
    return row ? [row] : [];
  });
  const componentLabels: Record<string, string> = {
    REAL_YIELD: "Real yields",
    TWO_YEAR_YIELD: "2-year yield",
    INFLATION_REGIME: "Inflation",
    GROWTH_REGIME: "Growth",
    LABOUR_REGIME: "Labour",
    USD: "US dollar",
    CATALYST_SURPRISE: "Latest catalyst",
  };
  return (
    <section className="rounded-2xl border border-[#D1D4DC] bg-white p-4 shadow-sm">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <p className="text-[10px] font-semibold uppercase tracking-[0.18em] text-[#787B86]">Point-in-time macro pulse</p>
          <div className="mt-1 flex flex-wrap items-baseline gap-x-4 gap-y-1">
            <p className="text-sm font-semibold text-[#131722]">Score {text(fundamental.directional_score)} · confidence {text(fundamental.confidence)}%</p>
            <p className="text-xs text-[#5D606B]">{text(fundamental.regime_label)} · event risk {text(fundamental.event_risk)}</p>
          </div>
        </div>
        <span className={`rounded-full border px-4 py-2 text-xs font-bold ${tone}`}>{bias.replaceAll("_", " ")}</span>
      </div>
      <div className="mt-3 grid gap-2 sm:grid-cols-2 lg:grid-cols-4 xl:grid-cols-7">
        {macroPulse.length ? macroPulse.map((component) => {
          const direction = typeof component.direction === "number" ? component.direction : 0;
          const impact = direction > 0.05 ? "GOLD +" : direction < -0.05 ? "GOLD −" : "NEUTRAL";
          const impactStyle = direction > 0.05
            ? "text-[#087363]"
            : direction < -0.05
              ? "text-[#B4232F]"
              : "text-[#5D606B]";
          return (
            <div className="rounded-lg border border-[#E6E8EC] bg-[#F8F9FB] px-3 py-2" key={text(component.code)}>
              <p className="truncate text-[9px] font-semibold uppercase tracking-wide text-[#787B86]">{componentLabels[text(component.code)] ?? text(component.code).replaceAll("_", " ")}</p>
              <p className="mt-1 truncate text-xs font-bold text-[#131722]" title={text(component.explanation)}>{compactMacroState(component.explanation)}</p>
              <p className={`mt-1 text-[9px] font-bold ${impactStyle}`}>{impact}</p>
            </div>
          );
        }) : <p className="text-xs text-[#787B86]">Macro-component states are unavailable.</p>}
      </div>
      <div className="mt-3 flex flex-wrap gap-2 text-[10px]">
        <span className="rounded-full bg-[#F4F5F7] px-3 py-1.5"><strong>Cross-market:</strong> {text(crossMarket.status)}</span>
        <span className="rounded-full bg-[#F4F5F7] px-3 py-1.5"><strong>Positioning:</strong> {text(positioning.crowding_state)}</span>
        <span className="rounded-full bg-[#F4F5F7] px-3 py-1.5"><strong>Liquidity:</strong> {text(liquidity.status)}</span>
        <span className="rounded-full bg-[#EEF3FF] px-3 py-1.5 text-[#174EA6]"><strong>Driver:</strong> {text(fundamental.dominant_driver)}</span>
        <span className="rounded-full bg-[#FFF8E1] px-3 py-1.5 text-[#6B5200]"><strong>Conflict:</strong> {text(fundamental.main_contradiction)}</span>
      </div>
      <details className="mt-3 rounded-lg border border-[#E6E8EC] bg-white px-3 py-2">
        <summary className="cursor-pointer text-xs font-semibold text-[#434651]">Expand source explanations</summary>
        <div className="mt-3 grid gap-2 lg:grid-cols-2">
          {macroPulse.map((component) => (
            <p className="rounded-md bg-[#F8F9FB] p-2 text-xs leading-5 text-[#434651]" key={`explain-${text(component.code)}`}>
              <strong className="text-[#131722]">{componentLabels[text(component.code)] ?? text(component.code)}:</strong> {text(component.explanation)}
              <span className="block text-[9px] uppercase tracking-wide text-[#8A8D96]">{text(component.epistemic_status)} · quality {text(component.data_quality)} · freshness {text(component.freshness)}</span>
            </p>
          ))}
          <p className="rounded-md bg-[#F8F9FB] p-2 text-xs leading-5 text-[#434651]"><strong className="text-[#131722]">Engine summary:</strong> {text(fundamental.summary)}</p>
        </div>
      </details>
    </section>
  );
}


function RetracementChecklist() {
  const checks = [
    ["Trend", "Is W1/D1/H4/H1 structure aligned or is this a range?"],
    ["Impulse", "Can you mark a completed displacement leg with clear origin and extreme?"],
    ["Retrace", "Does price return into a Fib/structural zone without invalidating the impulse?"],
    ["Confluence", "Is the zone supported by pre-existing level, session range or liquidity?"],
    ["Trigger", "Is there completed-candle rejection, reclaim, break or retest?"],
    ["Asymmetry", "Is a structural stop valid and a known target reachable at acceptable R?"],
  ];
  return (
    <details className="rounded-2xl border border-[#D1D4DC] bg-white p-5 shadow-sm">
      <summary className="cursor-pointer text-sm font-semibold text-[#131722]">Retracement setup checklist</summary>
      <div className="mt-4 grid gap-3 md:grid-cols-2 xl:grid-cols-3">
        {checks.map(([label, explanation], index) => (
          <div className="flex gap-3 rounded-xl border border-[#E6E8EC] bg-[#F8F9FB] p-3" key={label}>
            <span className="grid h-6 w-6 shrink-0 place-items-center rounded-full bg-white text-xs font-bold text-[#2962FF] shadow-sm">{index + 1}</span>
            <p className="text-xs leading-5 text-[#5D606B]"><strong className="block text-[#131722]">{label}</strong>{explanation}</p>
          </div>
        ))}
      </div>
      <p className="mt-3 text-xs text-[#787B86]">This is a consistency checklist, not an automated signal. If a required element is absent, NO TRADE remains valid.</p>
    </details>
  );
}


function ContextCard({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <article className="rounded-xl border border-[#D1D4DC] bg-white p-4 shadow-sm">
      <p className="text-[10px] font-semibold uppercase tracking-[0.16em] text-[#8A6200]">{title}</p>
      <div className="mt-3 text-sm leading-6 text-[#5D606B]">{children}</div>
    </article>
  );
}


export function BlindReplayLab() {
  const idempotencyKey = useRef<string | null>(null);
  const decisionForm = useRef<HTMLFormElement | null>(null);
  const [replay, setReplay] = useState<BlindReplayCase | null>(null);
  const [status, setStatus] = useState<BlindReplayStatus | null>(null);
  const [timeframe, setTimeframe] = useState<(typeof timeframes)[number]>("15m");
  const [action, setAction] = useState<Action | null>(null);
  const [confidence, setConfidence] = useState(60);
  const [trigger, setTrigger] = useState<Trigger>("MARKET");
  const [entryOffset, setEntryOffset] = useState(0);
  const [stopDistance, setStopDistance] = useState(1);
  const [targetR, setTargetR] = useState(2);
  const [evidence, setEvidence] = useState<string[]>([]);
  const [thesis, setThesis] = useState("");
  const [triggerCondition, setTriggerCondition] = useState("");
  const [invalidation, setInvalidation] = useState("");
  const [targetExplanation, setTargetExplanation] = useState("");
  const [feedback, setFeedback] = useState<BlindReplayDecisionResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [chartAtCheckpoint, setChartAtCheckpoint] = useState(true);

  const resetForm = useCallback(() => {
    setTimeframe("15m");
    setAction(null);
    setConfidence(60);
    setTrigger("MARKET");
    setEntryOffset(0);
    setStopDistance(1);
    setTargetR(2);
    setEvidence([]);
    setThesis("");
    setTriggerCondition("");
    setInvalidation("");
    setTargetExplanation("");
    setFeedback(null);
    setChartAtCheckpoint(true);
    idempotencyKey.current = null;
  }, []);

  const loadNext = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const response = await fetch(`${publicApiUrl}/blind-replay/next`, { cache: "no-store" });
      const payload: unknown = await response.json();
      if (response.status === 404) {
        const statusResponse = await fetch(`${publicApiUrl}/blind-replay/status`, { cache: "no-store" });
        const finalStatus = blindReplayStatusSchema.parse(await statusResponse.json());
        setStatus(finalStatus);
        setReplay(null);
        return;
      }
      if (!response.ok) throw new Error(apiError(payload, response.status));
      const parsed = blindReplayCaseSchema.parse(payload);
      setReplay(parsed);
      setStatus(parsed.progress);
      resetForm();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Unable to load the certified replay.");
    } finally {
      setLoading(false);
    }
  }, [resetForm]);

  useEffect(() => {
    const task = window.setTimeout(() => void loadNext(), 0);
    return () => window.clearTimeout(task);
  }, [loadNext]);

  const levels = useMemo(() => {
    const raw = record(replay?.case.session).known_levels;
    if (!Array.isArray(raw)) return [];
    return raw.flatMap((item) => {
      const row = record(item);
      return typeof row.code === "string" && typeof row.level === "number"
        ? [{ code: row.code, level: row.level }]
        : [];
    });
  }, [replay]);

  const chartEvents = useMemo(() => (
    replay?.case.released_events.flatMap((event) => {
      const parsed = chartEvent(event);
      return parsed ? [parsed] : [];
    }) ?? []
  ), [replay]);

  const fundamental = record(replay?.case.fundamental);
  const positioning = record(replay?.case.positioning);
  const liquidity = record(replay?.case.liquidity);
  const crossMarket = record(replay?.case.cross_market);
  const gcOrderFlow = record(replay?.case.gc_order_flow);
  const structureRows = Array.isArray(record(replay?.case.structure).timeframes)
    ? (record(replay?.case.structure).timeframes as unknown[])
    : [];

  const applyPositionPlan = useCallback((plan: PositionPlan): string | null => {
    if (!replay) return "The certified case is unavailable.";
    const mapped = positionPlanToExecution(plan, replay.case.m15_atr_index);
    if (!mapped.execution) return mapped.error;
    const execution = mapped.execution;
    setAction(execution.action);
    setTrigger(execution.trigger);
    setEntryOffset(execution.entryOffsetAtr);
    setStopDistance(execution.stopDistanceAtr);
    setTargetR(execution.targetR);
    setTriggerCondition(`${execution.action} ${execution.trigger.replaceAll("_", " ").toLowerCase()} at normalized index ${plan.entryIndex.toFixed(4)}.`);
    setInvalidation(`Structural invalidation and stop-loss at normalized index ${plan.stopIndex.toFixed(4)}.`);
    setTargetExplanation(`Take-profit at the selected known-liquidity objective, normalized index ${plan.targetIndex.toFixed(4)} (${execution.targetR.toFixed(2)}R).`);
    return null;
  }, [replay]);

  const clearPositionPlan = useCallback(() => {
    setAction(null);
    setTrigger("MARKET");
    setEntryOffset(0);
    setStopDistance(1);
    setTargetR(2);
    setTriggerCondition("");
    setInvalidation("");
    setTargetExplanation("");
  }, []);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!replay || !action) return;
    if (!chartAtCheckpoint) {
      setError("Return the chart replay to the frozen decision checkpoint before locking a decision.");
      return;
    }
    setSubmitting(true);
    setError(null);
    const noTrade = action === "NO_TRADE";
    idempotencyKey.current ??= crypto.randomUUID();
    try {
      const response = await fetch(`${publicApiUrl}/blind-replay/decisions`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "Idempotency-Key": idempotencyKey.current,
        },
        body: JSON.stringify({
          case_alias: replay.case.case_alias,
          action,
          confidence,
          entry_trigger: noTrade ? null : trigger,
          entry_offset_atr: noTrade ? null : entryOffset,
          stop_distance_atr: noTrade ? null : stopDistance,
          target_r: noTrade ? null : targetR,
          evidence_codes: evidence,
          thesis,
          trigger_condition: triggerCondition,
          invalidation,
          target_explanation: targetExplanation,
        }),
      });
      const payload: unknown = await response.json();
      if (!response.ok) throw new Error(apiError(payload, response.status));
      const parsed = blindReplayDecisionResponseSchema.parse(payload);
      setFeedback(parsed);
      setStatus(parsed.progress);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "The decision was not locked.");
    } finally {
      setSubmitting(false);
    }
  }

  if (loading) {
    return <div className="mt-8 rounded-2xl border border-[#D1D4DC] bg-white p-8 text-sm text-[#5D606B] shadow-sm">Verifying the sealed replay and loading the next case…</div>;
  }

  if (!replay) {
    return (
      <div className="mt-8 rounded-2xl border border-[#A5DCCF] bg-[#EAF8F4] p-8 text-[#131722]">
        <h3 className="text-xl font-semibold">Labeling is complete</h3>
        <p className="mt-2 text-sm text-[#5D606B]">{status?.total_locked ?? 0} immutable decisions are locked. No results are exposed by this interface.</p>
      </div>
    );
  }

  const bars = replay.case.charts[timeframe] ?? [];
  const progressValue = replay.case.mode === "PRACTICE" ? status?.practice_completed ?? 0 : status?.scored_completed ?? 0;
  const progressTotal = replay.case.mode === "PRACTICE" ? 20 : 240;
  const currentOffsetRule = offsetRule(action, trigger);
  const requestedEntryIndex = 100 + entryOffset * replay.case.m15_atr_index;
  const stopDistanceIndex = stopDistance * replay.case.m15_atr_index;
  const targetDistanceIndex = stopDistanceIndex * targetR;
  const plannedStopIndex = action === "LONG"
    ? requestedEntryIndex - stopDistanceIndex
    : requestedEntryIndex + stopDistanceIndex;
  const plannedTargetIndex = action === "LONG"
    ? requestedEntryIndex + targetDistanceIndex
    : requestedEntryIndex - targetDistanceIndex;
  const tradeBlockers = action === "LONG" || action === "SHORT" ? [
    ...(evidence.length ? [] : ["select at least one evidence code"]),
    ...(thesis.trim().length >= 3 ? [] : ["add a trade remark"]),
    ...(triggerCondition.trim().length >= 3 ? [] : ["describe the trigger"]),
    ...(invalidation.trim().length >= 3 ? [] : ["define invalidation"]),
    ...(targetExplanation.trim().length >= 3 ? [] : ["explain the target"]),
    ...(chartAtCheckpoint ? [] : ["return to the decision checkpoint"]),
  ] : ["draw a valid long or short position"];
  const lockedPositionOverlay: PositionPlan | null = action === "LONG" || action === "SHORT" ? {
    direction: action,
    entryIndex: requestedEntryIndex,
    stopIndex: plannedStopIndex,
    targetIndex: plannedTargetIndex,
  } : null;

  function requestArmedTrade() {
    if (tradeBlockers.length) return `Cannot place trade: ${tradeBlockers.join("; ")}.`;
    if (!decisionForm.current) return "The frozen decision form is unavailable.";
    decisionForm.current.requestSubmit();
    return null;
  }

  return (
    <div className="mt-8 grid gap-6 text-[#131722]">
      <ReplayInstructions />
      <FundamentalSummary
        crossMarket={crossMarket}
        fundamental={fundamental}
        liquidity={liquidity}
        positioning={positioning}
      />
      <section className="rounded-2xl border border-[#D1D4DC] bg-white p-5 shadow-sm md:p-6">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <p className="text-xs font-semibold uppercase tracking-[0.18em] text-[#8A6200]">{replay.case.mode} · zero future information</p>
            <h3 className="mt-2 text-2xl font-semibold">Case {replay.case.case_alias} · {replay.case.session_code.replaceAll("_", " ")}</h3>
            <p className="mt-2 text-xs text-[#5D606B]">Checkpoint +60 minutes · normalized reference 100 · M15 ATR {replay.case.m15_atr_index.toFixed(4)} index points</p>
          </div>
          <div className="min-w-56 rounded-xl border border-[#E6E8EC] bg-[#F8F9FB] p-3 text-xs text-[#5D606B]">
            <div className="flex justify-between"><span>Locked</span><strong className="text-[#131722]">{progressValue} / {progressTotal}</strong></div>
            <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-[#E6E8EC]"><div className="h-full bg-[#2962FF]" style={{ width: `${(progressValue / progressTotal) * 100}%` }} /></div>
            <p className="mt-2">Dates, timestamps and absolute prices are hidden.</p>
          </div>
        </div>

        <div className="mt-5 flex flex-wrap gap-2" role="tablist" aria-label="Replay chart timeframe">
          {timeframes.map((candidate) => (
            <button
              aria-selected={timeframe === candidate}
              className={`rounded-lg border px-3 py-2 text-xs font-semibold ${timeframe === candidate ? "border-[#2962FF] bg-[#EAF0FF] text-[#1848CC]" : "border-[#D1D4DC] bg-white text-[#5D606B] hover:bg-[#F4F5F7]"}`}
              key={candidate}
              onClick={() => setTimeframe(candidate)}
              role="tab"
              type="button"
            >
              {candidate.toUpperCase()} · {replay.case.charts[candidate]?.length ?? 0}
            </button>
          ))}
        </div>
        <div className="mt-4">
          <ReplayChartWorkspace
            bars={bars}
            events={chartEvents}
            key={replay.case.case_alias}
            label={timeframe}
            levels={levels}
            m15AtrIndex={replay.case.m15_atr_index}
            onCheckpointReadyChange={setChartAtCheckpoint}
            onPositionPlan={applyPositionPlan}
            onPositionPlanCleared={clearPositionPlan}
            onPlaceArmedTrade={requestArmedTrade}
            onTradeRemarkChange={setThesis}
            tradeBlockers={tradeBlockers}
            tradeRemark={thesis}
          />
        </div>
      </section>

      <RetracementChecklist />

      <section className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
        <ContextCard title="Fundamental direction">
          <p><strong className="text-[#131722]">{text(fundamental.bias_label)}</strong> · score {text(fundamental.directional_score)} · confidence {text(fundamental.confidence)}%</p>
          <p className="mt-2">{text(fundamental.regime_label)} · {text(fundamental.reaction_function)}</p>
          <p className="mt-2 text-[#434651]">{text(fundamental.summary)}</p>
          <p className="mt-2">Driver: {text(fundamental.dominant_driver)}<br />Contradiction: {text(fundamental.main_contradiction)}<br />Event risk: {text(fundamental.event_risk)}</p>
        </ContextCard>
        <ContextCard title="Structure and location">
          {structureRows.length ? structureRows.map((item, index) => {
            const row = record(item);
            return <p className="border-b border-[#E6E8EC] py-1 last:border-0" key={`${text(row.timeframe)}-${index}`}><strong className="text-[#131722]">{text(row.timeframe)}</strong> · {text(row.trend)} · {text(row.status)}</p>;
          }) : <p>UNKNOWN</p>}
          <p className="mt-2">Known levels: {levels.map((level) => level.code.replaceAll("_", " ")).join(", ") || "UNKNOWN"}</p>
        </ContextCard>
        <ContextCard title="Liquidity and participation">
          <p>Status: {text(liquidity.status)} · current ticks {text(liquidity.current_tick_volume)} · baseline {text(liquidity.baseline_tick_volume)}</p>
          <p className="mt-2">Spread points: {text(liquidity.current_spread_points)} · range bps {text(liquidity.current_range_bps)}</p>
          <p className="mt-2">COT: {text(positioning.crowding_state)} · participation {text(positioning.participation_state)}</p>
        </ContextCard>
        <ContextCard title="Cross-market confirmation">
          <p>Status: {text(crossMarket.status)} · quality {text(crossMarket.quality)}</p>
          <p className="mt-2">Only synchronized observations available by the checkpoint are shown.</p>
        </ContextCard>
        <ContextCard title="GC futures order flow">
          <p>Status: {text(gcOrderFlow.status)}</p>
          <p className="mt-2">{text(gcOrderFlow.warning)}</p>
        </ContextCard>
        <ContextCard title="Released catalysts">
          {chartEvents.length ? chartEvents.map((event) => (
            <p className="border-b border-[#E6E8EC] py-1 last:border-0" key={`${event.eventCode}-${event.minutesBeforeCheckpoint}`}>
              <strong className="text-[#131722]">{event.eventCode.replaceAll("_", " ")}</strong> · T−{event.minutesBeforeCheckpoint}m
              {event.surpriseLabel ? ` · ${event.surpriseLabel}` : ""}
              {event.goldImpact ? ` · ${event.goldImpact} for gold` : ""}
            </p>
          )) : <p>No eligible release in the prior six hours.</p>}
          <p className="mt-2 text-xs">Upcoming markers are not fabricated: this sealed historical source does not certify when its future schedule first became knowable.</p>
        </ContextCard>
      </section>

      <section className="rounded-2xl border border-[#D1D4DC] bg-white p-5 shadow-sm md:p-6">
        {feedback ? (
          <div>
            <p className="text-xs font-semibold uppercase tracking-[0.18em] text-[#087363]">Decision locked · {feedback.record_sha256.slice(0, 16)}…</p>
            <h3 className="mt-2 text-xl font-semibold">This record cannot be edited or deleted.</h3>
            {feedback.practice_feedback ? (
              <div className="mt-5">
                <p className="mb-3 text-sm text-[#5D606B]">Practice feedback has zero research credit. The normalized path is revealed only after locking.</p>
                <ReplayChartWorkspace autoPlay bars={feedback.practice_feedback.bars} label="practice future path" positionOverlay={lockedPositionOverlay} showToolbar={false} />
              </div>
            ) : (
              <p className="mt-3 text-sm text-[#5D606B]">No outcome or directional feedback is available during scored labeling.</p>
            )}
            <button className="mt-5 rounded-lg bg-[#2962FF] px-5 py-2.5 text-sm font-semibold text-white" onClick={() => void loadNext()} type="button">Continue to next frozen case</button>
          </div>
        ) : (
          <form className="grid gap-5" onSubmit={submit} ref={decisionForm}>
            <div>
              <p className="text-xs font-semibold uppercase tracking-[0.16em] text-[#8A6200]">Append-only decision</p>
              <div className="mt-3 grid gap-3 sm:grid-cols-3">
                {(["LONG", "SHORT", "NO_TRADE"] as Action[]).map((candidate) => (
                  <button
                    className={`rounded-xl border px-4 py-4 text-sm font-semibold transition ${action === candidate ? "border-[#2962FF] bg-[#EAF0FF] text-[#1848CC]" : "border-[#D1D4DC] bg-white text-[#5D606B] hover:bg-[#F4F5F7]"}`}
                    key={candidate}
                    onClick={() => {
                      setAction(candidate);
                      setEntryOffset(offsetRule(candidate, trigger).initial);
                    }}
                    type="button"
                  >{candidate.replace("_", " ")}</button>
                ))}
              </div>
              <p className="mt-3 text-xs leading-5 text-[#5D606B]">
                LONG and SHORT mean you have both a directional thesis and an executable plan. NO TRADE is a valid, scored decision when the evidence conflicts or no observable trigger exists.
              </p>
            </div>

            <label className="grid gap-2 text-sm text-[#5D606B]">
              Confidence: <strong className="text-[#131722]">{confidence}%</strong>
              <input max="100" min="50" onChange={(event) => setConfidence(Number(event.target.value))} type="range" value={confidence} />
              <span className="text-xs leading-5">For a trade, estimate the probability that the completed trade finishes above 0R after costs—not how strongly you like the narrative. For NO TRADE, estimate confidence that abstention is appropriate.</span>
            </label>

            {action && action !== "NO_TRADE" ? (
              <div className="grid gap-4">
                <div className="grid gap-4 md:grid-cols-4">
                  <label className="grid gap-1 text-xs text-[#5D606B]">
                    Entry trigger
                    <select
                      className="field"
                      onChange={(event) => {
                        const next = event.target.value as Trigger;
                        setTrigger(next);
                        setEntryOffset(offsetRule(action, next).initial);
                      }}
                      value={trigger}
                    >
                      <option value="MARKET">Market after latency</option>
                      <option value="PULLBACK_LIMIT">Pullback limit</option>
                      <option value="BREAKOUT_STOP">Breakout stop</option>
                    </select>
                  </label>
                  <label className="grid gap-1 text-xs text-[#5D606B]">
                    Entry offset · M15 ATR
                    <input
                      className="field"
                      disabled={trigger === "MARKET"}
                      max={currentOffsetRule.maximum}
                      min={currentOffsetRule.minimum}
                      onChange={(event) => setEntryOffset(Number(event.target.value))}
                      step="0.05"
                      type="number"
                      value={entryOffset}
                    />
                  </label>
                  <label className="grid gap-1 text-xs text-[#5D606B]">
                    Structural stop · M15 ATR
                    <input className="field" max="3" min="0.25" onChange={(event) => setStopDistance(Number(event.target.value))} step="0.05" type="number" value={stopDistance} />
                  </label>
                  <label className="grid gap-1 text-xs text-[#5D606B]">
                    Liquidity target · R
                    <input className="field" max="5" min="0.5" onChange={(event) => setTargetR(Number(event.target.value))} step="0.1" type="number" value={targetR} />
                  </label>
                </div>
                <div className="rounded-xl border border-[#B7C7FF] bg-[#EEF3FF] p-4 text-xs leading-5 text-[#174EA6]">
                  <p><strong className="text-[#131722]">How this plan would execute:</strong> {currentOffsetRule.hint}</p>
                  {trigger === "MARKET" ? (
                    <p className="mt-2">The exact entry is unknown now: the evaluator uses the first eligible M1 open after one-minute latency. Your stop is {stopDistance.toFixed(2)} ATR from that fill and your target is {targetR.toFixed(2)}R.</p>
                  ) : (
                    <p className="mt-2">Requested entry index <strong className="text-[#131722]">{requestedEntryIndex.toFixed(4)}</strong> · planned stop index <strong className="text-[#B4232F]">{plannedStopIndex.toFixed(4)}</strong> · planned target index <strong className="text-[#087363]">{plannedTargetIndex.toFixed(4)}</strong>.</p>
                  )}
                  <p className="mt-2">Orders expire after 120 minutes or at session end. Same-bar ambiguity is stop-first. The evaluator sizes to no more than $50 planned risk and deducts frozen spread, commission, slippage and latency.</p>
                </div>
              </div>
            ) : null}

            <fieldset>
              <legend className="text-xs text-[#5D606B]">Evidence codes · select at least one</legend>
              <div className="mt-2 flex flex-wrap gap-2">
                {evidenceOptions.map((code) => (
                  <label className={`cursor-pointer rounded-full border px-3 py-1.5 text-xs ${evidence.includes(code) ? "border-[#2962FF] bg-[#EAF0FF] text-[#1848CC]" : "border-[#D1D4DC] bg-white text-[#5D606B]"}`} key={code}>
                    <input className="sr-only" checked={evidence.includes(code)} onChange={(event) => setEvidence((current) => event.target.checked ? [...current, code] : current.filter((item) => item !== code))} type="checkbox" />{code.replaceAll("_", " ")}
                  </label>
                ))}
              </div>
            </fieldset>

            <div className="grid gap-4 md:grid-cols-2">
              <label className="grid gap-1 text-xs text-[#5D606B]">
                {action === "NO_TRADE" ? "Why no trade?" : "Trade remark / directional thesis"}
                <textarea className="field min-h-24" maxLength={1000} onChange={(event) => setThesis(event.target.value)} placeholder={action === "NO_TRADE" ? "Explain the conflict, weak location or missing edge." : "State why the available evidence supports this direction."} required value={thesis} />
              </label>
              <label className="grid gap-1 text-xs text-[#5D606B]">
                {action === "NO_TRADE" ? "Confirmation that was missing" : "Observable trigger condition"}
                <textarea className="field min-h-24" maxLength={1000} onChange={(event) => setTriggerCondition(event.target.value)} placeholder={action === "NO_TRADE" ? "State what price would need to do before you could trade." : "Describe the completed-candle or level event required for entry."} required value={triggerCondition} />
              </label>
              <label className="grid gap-1 text-xs text-[#5D606B]">
                {action === "NO_TRADE" ? "What would change the abstention?" : "Structural invalidation"}
                <textarea className="field min-h-24" maxLength={1000} onChange={(event) => setInvalidation(event.target.value)} placeholder={action === "NO_TRADE" ? "Name the observation that would turn this into a valid setup." : "Name the structure or level whose loss proves the idea wrong."} required value={invalidation} />
              </label>
              <label className="grid gap-1 text-xs text-[#5D606B]">
                {action === "NO_TRADE" ? "Why is there no defensible target?" : "Target rationale"}
                <textarea className="field min-h-24" maxLength={1000} onChange={(event) => setTargetExplanation(event.target.value)} placeholder={action === "NO_TRADE" ? "Explain why no clean liquidity objective justifies a trade." : "Name the pre-existing liquidity or structural objective."} required value={targetExplanation} />
              </label>
            </div>

            {!chartAtCheckpoint ? <p className="rounded-lg border border-[#E8D28A] bg-[#FFF9E6] p-3 text-sm text-[#785D00]">Replay is away from the certified checkpoint. Return to the checkpoint before locking a decision.</p> : null}
            {error ? <p className="rounded-lg border border-[#F3B3B8] bg-[#FFF0F1] p-3 text-sm text-[#B4232F]">{error}</p> : null}
            <button className="rounded-lg bg-[#2962FF] px-5 py-3 text-sm font-semibold text-white disabled:cursor-not-allowed disabled:opacity-40" disabled={submitting || !action || evidence.length === 0 || !chartAtCheckpoint} type="submit">{submitting ? "Hashing and locking…" : "Lock decision permanently"}</button>
          </form>
        )}
      </section>
    </div>
  );
}
