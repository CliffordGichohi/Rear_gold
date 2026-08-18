"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import {
  replayTimeframes,
  SynchronizedReplayChart,
  type ReplayTimeframe,
  type ReplayV2ChartEvent,
  type ReplayV2Drawing,
  type ReplayV2PositionLifecycle,
  type ReplayV2PositionPlan,
} from "@/components/synchronized-replay-chart";
import {
  blindReplayV2CaseSchema,
  blindReplayV2DecisionResponseSchema,
  blindReplayV2StatusSchema,
  publicApiUrl,
  type BlindReplayV2Case,
  type BlindReplayV2DecisionResponse,
  type BlindReplayV2Bar,
  type BlindReplayV2Status,
} from "@/lib/api";

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
type EntryTrigger = "MARKET" | "PULLBACK_LIMIT" | "BREAKOUT_STOP";
type Ticket = ReplayV2PositionPlan & {
  entryTrigger: EntryTrigger;
  entryOffsetAtr: number;
  stopDistanceAtr: number;
  targetR: number;
};

function object(value: unknown): Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value)
    ? value as Record<string, unknown>
    : {};
}

function display(value: unknown, fallback = "UNKNOWN") {
  if (value === null || value === undefined || value === "") return fallback;
  return typeof value === "number" ? value.toFixed(2) : String(value);
}

function apiError(value: unknown, status: number) {
  const detail = object(value).detail;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    return detail.map((item) => display(object(item).msg, "Invalid request")).join("; ");
  }
  return `Replay request failed with HTTP ${status}`;
}

function randomKey() {
  return typeof crypto !== "undefined" && "randomUUID" in crypto
    ? crypto.randomUUID()
    : `key-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

function compactState(value: unknown) {
  const explanation = display(value).toLowerCase();
  const states: Array<[RegExp, string]> = [
    [/unavailable|unknown/, "UNKNOWN"],
    [/positive surprise/, "POSITIVE SURPRISE"],
    [/negative surprise/, "NEGATIVE SURPRISE"],
    [/disinflation|decelerat/, "DISINFLATING"],
    [/accelerat|reflation/, "ACCELERATING"],
    [/falling|decreas|declin|lower/, "FALLING"],
    [/rising|increas|higher/, "RISING"],
    [/weakening|weaker/, "WEAKENING"],
    [/strengthening|stronger/, "STRENGTHENING"],
    [/tightening|tighter/, "TIGHTENING"],
    [/easing|easier/, "EASING"],
    [/defensive/, "DEFENSIVE"],
  ];
  return states.find(([pattern]) => pattern.test(explanation))?.[1] ?? "MIXED";
}

export function mapReplayPosition(
  plan: ReplayV2PositionPlan,
  latestM1: number,
  m15Atr: number,
): { ticket: Ticket; error: null } | { ticket: null; error: string } {
  if (!(m15Atr > 0)) {
    return { ticket: null, error: "The point-in-time M15 ATR is unavailable." };
  }
  const entryOffsetAtr = (plan.entryIndex - latestM1) / m15Atr;
  const stopDistanceAtr = Math.abs(plan.entryIndex - plan.stopIndex) / m15Atr;
  const risk = Math.abs(plan.entryIndex - plan.stopIndex);
  const targetR = Math.abs(plan.targetIndex - plan.entryIndex) / risk;
  if (Math.abs(entryOffsetAtr) > 2 + 1e-8) {
    return {
      ticket: null,
      error: `Entry is ${entryOffsetAtr.toFixed(2)} ATR from REPLAY NOW; maximum is 2.00 ATR.`,
    };
  }
  if (stopDistanceAtr < 0.25 || stopDistanceAtr > 3) {
    return {
      ticket: null,
      error: `Stop is ${stopDistanceAtr.toFixed(2)} ATR; required range is 0.25–3.00 ATR.`,
    };
  }
  if (targetR < 0.5 || targetR > 5) {
    return {
      ticket: null,
      error: `Target is ${targetR.toFixed(2)}R; required range is 0.50–5.00R.`,
    };
  }
  let entryTrigger: EntryTrigger = "MARKET";
  if (Math.abs(entryOffsetAtr) > 1e-6) {
    const pullback = (
      (plan.direction === "LONG" && entryOffsetAtr < 0)
      || (plan.direction === "SHORT" && entryOffsetAtr > 0)
    );
    entryTrigger = pullback ? "PULLBACK_LIMIT" : "BREAKOUT_STOP";
  }
  return {
    error: null,
    ticket: {
      ...plan,
      entryTrigger,
      entryOffsetAtr,
      stopDistanceAtr,
      targetR,
    },
  };
}

export function classifyReplayPositionLifecycle(
  ticket: Ticket | null,
  revealedBars: BlindReplayV2Bar[],
  playbackComplete: boolean,
): ReplayV2PositionLifecycle {
  if (!ticket) return "EDITABLE";
  let active = ticket.entryTrigger === "MARKET";
  for (const bar of revealedBars) {
    if (!active && bar.low <= ticket.entryIndex && ticket.entryIndex <= bar.high) active = true;
    if (!active) continue;
    const stopTouched = bar.low <= ticket.stopIndex && ticket.stopIndex <= bar.high;
    const targetTouched = bar.low <= ticket.targetIndex && ticket.targetIndex <= bar.high;
    if (stopTouched) return "STOPPED";
    if (targetTouched) return "TARGET_HIT";
  }
  if (active) return playbackComplete ? "EXPIRED" : "ACTIVE";
  return playbackComplete ? "EXPIRED" : "PENDING_ENTRY";
}

function toChartEvent(value: unknown): ReplayV2ChartEvent | null {
  const event = object(value);
  if (
    typeof event.event_code !== "string"
    || typeof event.minutes_before_checkpoint !== "number"
  ) return null;
  const surprises = Array.isArray(event.surprises) ? event.surprises.map(object) : [];
  const first = surprises[0];
  const raw = typeof first?.raw_surprise === "number" ? first.raw_surprise : null;
  const direction = typeof first?.gold_direction === "number" ? first.gold_direction : null;
  return {
    eventCode: event.event_code,
    name: display(event.name, event.event_code),
    relativeMinute: -Math.max(0, Math.round(event.minutes_before_checkpoint)),
    surpriseLabel: raw === null
      ? null
      : raw > 0 ? "POSITIVE SURPRISE" : raw < 0 ? "NEGATIVE SURPRISE" : "ON FORECAST",
    goldImpact: direction === null
      ? null
      : direction > 0.05 ? "SUPPORTIVE" : direction < -0.05 ? "PRESSURE" : "NEUTRAL",
  };
}

function FundamentalStrip({ context, cursor }: {
  context: Record<string, unknown>;
  cursor: number;
}) {
  const fundamental = object(context.fundamental);
  const crossMarket = object(context.cross_market);
  const positioning = object(context.positioning);
  const liquidity = object(context.liquidity);
  const components = Array.isArray(fundamental.components)
    ? fundamental.components.map(object)
    : [];
  const definitions = [
    ["REAL_YIELD", "Real yields"],
    ["TWO_YEAR_YIELD", "2-year yield"],
    ["INFLATION_REGIME", "Inflation"],
    ["GROWTH_REGIME", "Growth"],
    ["LABOUR_REGIME", "Labour"],
    ["USD", "US dollar"],
    ["CATALYST_SURPRISE", "Latest catalyst"],
  ] as const;
  const bias = display(fundamental.bias_label);
  const biasStyle = bias.includes("BULL")
    ? "border-[#A5DCCF] bg-[#EAF8F4] text-[#087363]"
    : bias.includes("BEAR")
      ? "border-[#F3B3B8] bg-[#FFF0F1] text-[#B4232F]"
      : "border-[#E8D28A] bg-[#FFF9E6] text-[#785D00]";

  return (
    <section className="rounded-2xl border border-[#D1D4DC] bg-white p-4 shadow-sm">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="flex flex-wrap items-center gap-2">
            <p className="text-[10px] font-bold uppercase tracking-[0.18em] text-[#787B86]">
              Fundamental snapshot
            </p>
            <span className="rounded-full border border-[#E8D28A] bg-[#FFF9E6] px-2 py-1 text-[9px] font-bold text-[#785D00]">
              CONTEXT FROZEN AT T0 · NOW {cursor}m OLD
            </span>
          </div>
          <p className="mt-2 text-sm font-semibold">
            Score {display(fundamental.directional_score)} · confidence {display(fundamental.confidence)}% · {display(fundamental.regime_label)}
          </p>
        </div>
        <span className={`rounded-full border px-4 py-2 text-xs font-bold ${biasStyle}`}>
          {bias.replaceAll("_", " ")}
        </span>
      </div>

      <div className="mt-3 grid gap-2 sm:grid-cols-2 lg:grid-cols-4 xl:grid-cols-7">
        {definitions.map(([code, label]) => {
          const component = components.find((row) => row.code === code);
          const direction = typeof component?.direction === "number" ? component.direction : 0;
          return (
            <div
              className="rounded-lg border border-[#E6E8EC] bg-[#F8F9FB] px-3 py-2"
              key={code}
              title={display(component?.explanation)}
            >
              <p className="text-[9px] font-semibold uppercase tracking-wide text-[#787B86]">{label}</p>
              <p className="mt-1 truncate text-xs font-bold">
                {component ? compactState(component.explanation) : "UNKNOWN"}
              </p>
              <p className={`mt-1 text-[9px] font-bold ${direction > 0.05 ? "text-[#087363]" : direction < -0.05 ? "text-[#B4232F]" : "text-[#787B86]"}`}>
                {direction > 0.05 ? "GOLD +" : direction < -0.05 ? "GOLD −" : "NEUTRAL"}
              </p>
            </div>
          );
        })}
      </div>

      <div className="mt-3 flex flex-wrap gap-2 text-[10px]">
        <span className="rounded-full bg-[#EEF3FF] px-3 py-1.5 text-[#174EA6]"><strong>Driver:</strong> {display(fundamental.dominant_driver)}</span>
        <span className="rounded-full bg-[#FFF8E1] px-3 py-1.5 text-[#6B5200]"><strong>Contradiction:</strong> {display(fundamental.main_contradiction)}</span>
        <span className="rounded-full bg-[#F4F5F7] px-3 py-1.5"><strong>Cross-market:</strong> {display(crossMarket.status)}</span>
        <span className="rounded-full bg-[#F4F5F7] px-3 py-1.5"><strong>COT:</strong> {display(positioning.crowding_state)}</span>
        <span className="rounded-full bg-[#F4F5F7] px-3 py-1.5"><strong>Liquidity:</strong> {display(liquidity.status)}</span>
        <span className="rounded-full bg-[#F4F5F7] px-3 py-1.5"><strong>Event risk:</strong> {display(fundamental.event_risk)}</span>
      </div>

      <details className="mt-3 rounded-lg border border-[#E6E8EC] bg-white px-3 py-2">
        <summary className="cursor-pointer text-xs font-semibold text-[#434651]">
          Expand source explanations
        </summary>
        <div className="mt-3 grid gap-2 md:grid-cols-2">
          {components.map((component, index) => (
            <p className="rounded bg-[#F8F9FB] p-2 text-xs leading-5 text-[#434651]" key={`${display(component.code)}-${index}`}>
              <strong>{display(component.code).replaceAll("_", " ")}:</strong> {display(component.explanation)}
            </p>
          ))}
          <p className="rounded bg-[#F8F9FB] p-2 text-xs leading-5 text-[#434651]">
            <strong>Engine summary:</strong> {display(fundamental.summary)}
          </p>
        </div>
      </details>
    </section>
  );
}

function serializedDrawings(drawings: ReplayV2Drawing[]) {
  return drawings.map((drawing) => ({
    drawing_id: drawing.id,
    kind: drawing.kind,
    placed_at_cursor_minute: drawing.placedAtCursorMinute,
    anchors: drawing.anchors.map((anchor) => ({
      relative_minute: anchor.relativeMinute,
      price_index: Number(anchor.priceIndex.toFixed(8)),
      source_timeframe: anchor.sourceTimeframe,
    })),
  }));
}

export function BlindReplayV2Lab() {
  const [replay, setReplay] = useState<BlindReplayV2Case | null>(null);
  const [status, setStatus] = useState<BlindReplayV2Status | null>(null);
  const [timeframe, setTimeframe] = useState<ReplayTimeframe>("15m");
  const [drawings, setDrawings] = useState<ReplayV2Drawing[]>([]);
  const [ticket, setTicket] = useState<Ticket | null>(null);
  const [action, setAction] = useState<Action | null>(null);
  const [confidence, setConfidence] = useState(65);
  const [evidence, setEvidence] = useState<string[]>([]);
  const [tradeReason, setTradeReason] = useState("");
  const [triggerCondition, setTriggerCondition] = useState("");
  const [invalidation, setInvalidation] = useState("");
  const [targetExplanation, setTargetExplanation] = useState("");
  const [feedback, setFeedback] = useState<BlindReplayV2DecisionResponse | null>(null);
  const [feedbackRevealCount, setFeedbackRevealCount] = useState(0);
  const [loading, setLoading] = useState(true);
  const [advancing, setAdvancing] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [playing, setPlaying] = useState(false);
  const [setupDialogOpen, setSetupDialogOpen] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const advanceInFlight = useRef(false);
  const setupKey = useRef<string | null>(null);

  const resetCase = useCallback(() => {
    setTimeframe("15m");
    setDrawings([]);
    setTicket(null);
    setAction(null);
    setConfidence(65);
    setEvidence([]);
    setTradeReason("");
    setTriggerCondition("");
    setInvalidation("");
    setTargetExplanation("");
    setFeedback(null);
    setFeedbackRevealCount(0);
    setPlaying(false);
    setSetupDialogOpen(false);
    setError(null);
    setupKey.current = null;
  }, []);

  const handleFullscreenChange = useCallback((active: boolean) => {
    if (!active) setSetupDialogOpen(false);
  }, []);

  const loadNext = useCallback(async () => {
    setLoading(true);
    try {
      const response = await fetch(`${publicApiUrl}/blind-replay-v2/next`, { cache: "no-store" });
      const payload: unknown = await response.json();
      if (response.status === 404) {
        const statusResponse = await fetch(`${publicApiUrl}/blind-replay-v2/status`, { cache: "no-store" });
        setStatus(blindReplayV2StatusSchema.parse(await statusResponse.json()));
        setReplay(null);
        return;
      }
      if (!response.ok) throw new Error(apiError(payload, response.status));
      const parsed = blindReplayV2CaseSchema.parse(payload);
      resetCase();
      setReplay(parsed);
      setStatus(parsed.progress);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Unable to load certified V2 practice.");
    } finally {
      setLoading(false);
    }
  }, [resetCase]);

  useEffect(() => {
    const task = window.setTimeout(() => void loadNext(), 0);
    return () => window.clearTimeout(task);
  }, [loadNext]);

  const advanceCursor = useCallback(async (increment: 1 | 5 | 15) => {
    if (!replay || feedback || ticket || advanceInFlight.current) return;
    const cursor = replay.case.cursor_minute;
    if (cursor + increment > replay.case.maximum_cursor_minute) {
      setPlaying(false);
      return;
    }
    advanceInFlight.current = true;
    setAdvancing(true);
    setError(null);
    try {
      const response = await fetch(`${publicApiUrl}/blind-replay-v2/advance`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "Idempotency-Key": randomKey(),
        },
        body: JSON.stringify({
          case_alias: replay.case.case_alias,
          expected_cursor_minute: cursor,
          increment_minutes: increment,
          selected_timeframe: timeframe,
        }),
      });
      const payload: unknown = await response.json();
      if (!response.ok) throw new Error(apiError(payload, response.status));
      const parsed = blindReplayV2CaseSchema.parse(payload);
      setReplay(parsed);
      setStatus(parsed.progress);
      if (parsed.case.cursor_minute >= parsed.case.maximum_cursor_minute) setPlaying(false);
    } catch (reason) {
      setPlaying(false);
      setError(reason instanceof Error ? reason.message : "The cursor did not advance.");
    } finally {
      advanceInFlight.current = false;
      setAdvancing(false);
    }
  }, [feedback, replay, ticket, timeframe]);

  useEffect(() => {
    if (!playing || advancing || feedback || ticket) return;
    const timer = window.setTimeout(() => void advanceCursor(1), 320);
    return () => window.clearTimeout(timer);
  }, [advanceCursor, advancing, feedback, playing, replay?.case.cursor_minute, ticket]);

  useEffect(() => {
    if (!playing || !feedback) return;
    if (feedbackRevealCount >= feedback.practice_feedback.bars.length) return;
    const timer = window.setTimeout(() => {
      const next = Math.min(feedbackRevealCount + 1, feedback.practice_feedback.bars.length);
      setFeedbackRevealCount(next);
      if (next >= feedback.practice_feedback.bars.length) setPlaying(false);
    }, 320);
    return () => window.clearTimeout(timer);
  }, [feedback, feedbackRevealCount, playing]);

  if (loading) {
    return (
      <div className="mt-8 rounded-2xl border border-[#D1D4DC] bg-white p-8 text-sm text-[#5D606B] shadow-sm">
        Verifying synchronized practice sources and ledger heads…
      </div>
    );
  }

  if (!replay) {
    return (
      <div className="mt-8 rounded-2xl border border-[#A5DCCF] bg-[#EAF8F4] p-8">
        <h3 className="text-xl font-semibold">V2 practice complete</h3>
        <p className="mt-2 text-sm text-[#5D606B]">
          {status?.practice_completed ?? 0} immutable practice setups are sealed. Scored labeling remains closed because V2 is practice-only.
        </p>
        {error ? <p className="mt-3 text-sm text-[#B4232F]">{error}</p> : null}
      </div>
    );
  }

  const currentCase = replay.case;
  const context = currentCase.context;
  const session = object(context.session);
  const levels = Array.isArray(session.known_levels)
    ? session.known_levels.flatMap((value) => {
      const row = object(value);
      return typeof row.code === "string" && typeof row.level === "number"
        ? [{ code: row.code, level: row.level }]
        : [];
    })
    : [];
  const events = Array.isArray(context.released_events)
    ? context.released_events.flatMap((value) => {
      const event = toChartEvent(value);
      return event ? [event] : [];
    })
    : [];
  const structure = object(context.structure);
  const structureRows = Array.isArray(structure.timeframes)
    ? structure.timeframes.map(object)
    : [];
  const revealedPracticeBars = feedback?.practice_feedback.bars.slice(0, feedbackRevealCount) ?? [];
  const bars = feedback && timeframe === "1m"
    ? [...(replay.case.charts["1m"] ?? []), ...revealedPracticeBars]
    : replay.case.charts[timeframe] ?? [];
  const playbackComplete = Boolean(feedback) && feedbackRevealCount >= (feedback?.practice_feedback.bars.length ?? 0);
  const positionLifecycle = feedback
    ? classifyReplayPositionLifecycle(ticket, revealedPracticeBars, playbackComplete)
    : "EDITABLE";
  const displayedCursorMinute = revealedPracticeBars.at(-1)?.close_offset_minutes ?? replay.case.cursor_minute;
  const playbackMaximumCursorMinute = feedback?.practice_feedback.bars.at(-1)?.close_offset_minutes
    ?? replay.case.maximum_cursor_minute;
  const directional = action === "LONG" || action === "SHORT";
  const blockers = [
    ...(!action ? ["choose LONG, SHORT, or NO TRADE"] : []),
    ...(directional && !ticket ? ["draw a valid three-level position at REPLAY NOW"] : []),
    ...(evidence.length ? [] : ["select at least one evidence code"]),
    ...(tradeReason.trim().length >= 3 ? [] : ["write why this trade exists now"]),
    ...(triggerCondition.trim().length >= 3 ? [] : ["state the observable trigger"]),
    ...(invalidation.trim().length >= 3 ? [] : ["state invalidation"]),
    ...(targetExplanation.trim().length >= 3 ? [] : ["state the target rationale"]),
  ];

  function toggleReplayPlayback() {
    if (feedback) {
      if (playbackComplete) return;
      setError(null);
      setPlaying((current) => !current);
      return;
    }
    if (ticket) {
      // A drawn order cannot advance unsealed. Route Play through the same
      // annotation transaction instead of presenting a mysteriously dead button.
      setPlaying(false);
      setError(null);
      setSetupDialogOpen(true);
      return;
    }
    if (currentCase.cursor_minute >= currentCase.maximum_cursor_minute) {
      setPlaying(false);
      setError(
        `The blind replay window has reached T+${currentCase.maximum_cursor_minute}. `
        + "Draw a position and use Place & Play, or record NO TRADE; future candles remain hidden until that decision is sealed.",
      );
      return;
    }
    setError(null);
    setPlaying((current) => !current);
  }

  function acceptPosition(plan: ReplayV2PositionPlan | null): string | null {
    setPlaying(false);
    if (!plan) {
      setTicket(null);
      if (action !== "NO_TRADE") setAction(null);
      return null;
    }
    const mapped = mapReplayPosition(
      plan,
      currentCase.latest_visible_m1_close_index,
      currentCase.latest_point_in_time_m15_atr_index,
    );
    if (!mapped.ticket) return mapped.error;
    setTicket(mapped.ticket);
    setAction(mapped.ticket.direction);
    setTriggerCondition(
      `${mapped.ticket.direction} ${mapped.ticket.entryTrigger.replaceAll("_", " ").toLowerCase()} at normalized index ${mapped.ticket.entryIndex.toFixed(4)}.`,
    );
    setInvalidation(`Structural invalidation at normalized index ${mapped.ticket.stopIndex.toFixed(4)}.`);
    setTargetExplanation(
      `Known-liquidity target at normalized index ${mapped.ticket.targetIndex.toFixed(4)} (${mapped.ticket.targetR.toFixed(2)}R).`,
    );
    return null;
  }

  async function placeAndPlay() {
    if (blockers.length || !action) return;
    setPlaying(false);
    setSubmitting(true);
    setError(null);
    setupKey.current ??= randomKey();
    const noTrade = action === "NO_TRADE";
    try {
      const response = await fetch(`${publicApiUrl}/blind-replay-v2/decisions`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "Idempotency-Key": setupKey.current,
        },
        body: JSON.stringify({
          case_alias: currentCase.case_alias,
          expected_cursor_minute: currentCase.cursor_minute,
          selected_timeframe: timeframe,
          client_visible_charts_sha256: currentCase.visible_charts_sha256,
          action,
          confidence,
          entry_trigger: noTrade ? null : ticket?.entryTrigger,
          entry_index: noTrade ? null : Number(ticket?.entryIndex.toFixed(8)),
          stop_index: noTrade ? null : Number(ticket?.stopIndex.toFixed(8)),
          target_index: noTrade ? null : Number(ticket?.targetIndex.toFixed(8)),
          drawings: serializedDrawings(drawings),
          evidence_codes: evidence,
          trade_reason: tradeReason,
          trigger_condition: triggerCondition,
          invalidation,
          target_explanation: targetExplanation,
        }),
      });
      const payload: unknown = await response.json();
      if (!response.ok) throw new Error(apiError(payload, response.status));
      const parsed = blindReplayV2DecisionResponseSchema.parse(payload);
      setFeedback(parsed);
      setStatus(parsed.progress);
      setSetupDialogOpen(false);
      setFeedbackRevealCount(0);
      setTimeframe("1m");
      setPlaying(true);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Place & Play did not seal the setup.");
    } finally {
      setSubmitting(false);
    }
  }

  const fullscreenSetupDialog = setupDialogOpen && ticket ? (
    <div
      aria-label="Complete Place & Play details"
      aria-modal="true"
      className="absolute inset-0 z-50 grid place-items-center bg-[#131722]/55 p-4 backdrop-blur-[2px]"
      role="dialog"
    >
      <div className="max-h-[92vh] w-full max-w-3xl overflow-y-auto rounded-2xl border border-[#B7C7FF] bg-white p-5 text-[#131722] shadow-2xl">
        <div className="flex items-start justify-between gap-4">
          <div>
            <p className="text-[10px] font-bold uppercase tracking-[0.18em] text-[#174EA6]">Setup details before immutable seal</p>
            <h3 className="mt-1 text-xl font-semibold">{ticket.direction} · Entry, SL and TP are already captured</h3>
            <p className="mt-1 text-xs text-[#5D606B]">Complete the reasoning below. Done &amp; Play locks every drawing and price level at T+{currentCase.cursor_minute}m, then resumes price one candle at a time.</p>
          </div>
          <button aria-label="Close setup details" className="chart-command" onClick={() => setSetupDialogOpen(false)} type="button">Close</button>
        </div>

        <div className="mt-4 grid gap-2 rounded-xl border border-[#D1D4DC] bg-[#F8FAFF] p-3 text-xs sm:grid-cols-3">
          <p><strong>Entry</strong><br />{ticket.entryIndex.toFixed(4)}</p>
          <p><strong>Stop</strong><br />{ticket.stopIndex.toFixed(4)} · {ticket.stopDistanceAtr.toFixed(2)} ATR</p>
          <p><strong>Target</strong><br />{ticket.targetIndex.toFixed(4)} · {ticket.targetR.toFixed(2)}R</p>
        </div>

        <label className="mt-4 block text-sm font-bold" htmlFor="fullscreen-trade-reason">WHY THIS TRADE NOW?</label>
        <textarea
          className="field mt-2 min-h-28 border-2"
          id="fullscreen-trade-reason"
          maxLength={2000}
          onChange={(event) => setTradeReason(event.target.value)}
          placeholder="Fundamental direction, higher-timeframe location, liquidity/structure response, and why this is not a chase."
          value={tradeReason}
        />

        <label className="mt-4 grid gap-1 text-xs text-[#5D606B]" htmlFor="fullscreen-confidence">
          Confidence · <strong className="text-[#131722]">{confidence}%</strong>
          <input id="fullscreen-confidence" max="100" min="50" onChange={(event) => setConfidence(Number(event.target.value))} type="range" value={confidence} />
        </label>

        <fieldset className="mt-4">
          <legend className="text-[10px] font-bold uppercase tracking-wide text-[#787B86]">Evidence · select at least one</legend>
          <div className="mt-2 flex flex-wrap gap-1.5">
            {evidenceOptions.map((code) => (
              <label className={`cursor-pointer rounded-full border px-2 py-1.5 text-[10px] font-semibold ${evidence.includes(code) ? "border-[#2962FF] bg-[#EAF0FF] text-[#1848CC]" : "border-[#D1D4DC] bg-white text-[#5D606B]"}`} key={`fullscreen-${code}`}>
                <input
                  checked={evidence.includes(code)}
                  className="sr-only"
                  onChange={(event) => setEvidence((current) => (
                    event.target.checked ? [...current, code] : current.filter((item) => item !== code)
                  ))}
                  type="checkbox"
                />
                {code.replaceAll("_", " ")}
              </label>
            ))}
          </div>
        </fieldset>

        <div className="mt-4 grid gap-3 md:grid-cols-3">
          <label className="text-[10px] font-semibold text-[#5D606B]" htmlFor="fullscreen-trigger">
            Observable trigger
            <textarea className="field mt-1 min-h-20" id="fullscreen-trigger" maxLength={1000} onChange={(event) => setTriggerCondition(event.target.value)} value={triggerCondition} />
          </label>
          <label className="text-[10px] font-semibold text-[#5D606B]" htmlFor="fullscreen-invalidation">
            Invalidation
            <textarea className="field mt-1 min-h-20" id="fullscreen-invalidation" maxLength={1000} onChange={(event) => setInvalidation(event.target.value)} value={invalidation} />
          </label>
          <label className="text-[10px] font-semibold text-[#5D606B]" htmlFor="fullscreen-target">
            Target rationale
            <textarea className="field mt-1 min-h-20" id="fullscreen-target" maxLength={1000} onChange={(event) => setTargetExplanation(event.target.value)} value={targetExplanation} />
          </label>
        </div>

        {blockers.length ? (
          <div className="mt-4 rounded-lg border border-[#E8D28A] bg-[#FFF9E6] p-3 text-[10px] leading-5 text-[#785D00]">
            <strong>Still required:</strong> {blockers.join("; ")}.
          </div>
        ) : null}
        {error ? <p className="mt-3 rounded-lg border border-[#F3B3B8] bg-[#FFF0F1] p-3 text-xs text-[#B4232F]">{error}</p> : null}

        <div className="mt-5 flex justify-end gap-2">
          <button className="chart-command" onClick={() => setSetupDialogOpen(false)} type="button">Keep editing chart</button>
          <button
            className="rounded-lg bg-[#087363] px-6 py-3 text-sm font-bold text-white disabled:cursor-not-allowed disabled:opacity-35"
            disabled={submitting || blockers.length > 0}
            onClick={() => void placeAndPlay()}
            type="button"
          >
            {submitting ? "Sealing setup…" : "Done & Play"}
          </button>
        </div>
      </div>
    </div>
  ) : null;

  return (
    <div className="mt-8 grid gap-5 text-[#131722]">
      <div className="sticky top-2 z-20 flex flex-wrap items-center justify-between gap-3 rounded-xl border border-[#E8D28A] bg-[#FFF9E6] px-4 py-3 shadow-sm">
        <p className="text-xs font-semibold text-[#6B5200]">
          V2 CERTIFIED · practice only · zero research credit · scored labeling CLOSED
        </p>
        <p className="text-xs text-[#785D00]">
          No rewind · no future bars in browser · setup immutable after Place &amp; Play
        </p>
      </div>

      <FundamentalStrip context={context} cursor={replay.case.cursor_minute} />

      <section className="rounded-2xl border border-[#D1D4DC] bg-white p-4 shadow-sm md:p-5">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <p className="text-[10px] font-bold uppercase tracking-[0.18em] text-[#8A6200]">
              Synchronized blind setup replay · V2
            </p>
            <h3 className="mt-1 text-2xl font-semibold">
              Case {replay.case.case_alias} · {replay.case.session_code.replaceAll("_", " ")}
            </h3>
            <p className="mt-1 text-xs text-[#5D606B]">
              Relative cursor T+{displayedCursorMinute}m · normalized price index · practice {replay.case.mode_sequence}/20
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-2" aria-label="Synchronized replay controls">
            <button
              aria-label={playing ? "Pause synchronized replay" : "Play synchronized replay"}
              className="rounded-lg bg-[#2962FF] px-4 py-2 text-xs font-bold text-white disabled:opacity-40"
              disabled={Boolean(feedback) && playbackComplete}
              onClick={toggleReplayPlayback}
              type="button"
            >
              {playing ? "Pause" : "▶ Play"}
            </button>
            {([1, 5, 15] as const).map((step) => (
              <button
                aria-label={`Advance ${step} minute${step === 1 ? "" : "s"}`}
                className="chart-command"
                disabled={
                  feedback
                    ? playbackComplete
                    : Boolean(ticket) || advancing || replay.case.cursor_minute + step > 180
                }
                key={step}
                onClick={() => {
                  if (feedback) {
                    setPlaying(false);
                    setFeedbackRevealCount((current) => Math.min(current + step, feedback.practice_feedback.bars.length));
                  } else {
                    void advanceCursor(step);
                  }
                }}
                type="button"
              >
                +{step}m
              </button>
            ))}
            <span className="rounded-full bg-[#EEF3FF] px-3 py-2 text-xs font-bold text-[#174EA6]">
              T+{displayedCursorMinute} / {playbackMaximumCursorMinute}m
            </span>
          </div>
        </div>

        <div className="mt-4 flex flex-wrap gap-2" role="tablist" aria-label="Synchronized timeframe">
          {replayTimeframes.map((candidate) => (
            <button
              aria-selected={timeframe === candidate}
              className={`rounded-lg border px-3 py-2 text-xs font-semibold ${timeframe === candidate ? "border-[#2962FF] bg-[#EAF0FF] text-[#1848CC]" : "border-[#D1D4DC] bg-white text-[#5D606B]"}`}
              disabled={Boolean(feedback) && candidate !== "1m"}
              key={candidate}
              onClick={() => {
                setTimeframe(candidate);
                setPlaying(false);
              }}
              role="tab"
              type="button"
            >
              {candidate.toUpperCase()} · {replay.case.charts[candidate]?.length ?? 0}
            </button>
          ))}
        </div>

        <div className="mt-4 grid gap-4 xl:grid-cols-[minmax(0,1fr)_330px]">
          <SynchronizedReplayChart
            bars={bars}
            cursorMinute={displayedCursorMinute}
            drawings={drawings}
            events={events}
            fullscreenOverlay={fullscreenSetupDialog}
            fullscreenReplayControls={{
              playing,
              advancing,
              playDisabled: Boolean(feedback) && playbackComplete,
              advanceDisabled: feedback ? playbackComplete : Boolean(ticket) || advancing,
              cursorMinute: displayedCursorMinute,
              maximumCursorMinute: playbackMaximumCursorMinute,
              timeframeCounts: Object.fromEntries(replayTimeframes.map((candidate) => [
                candidate,
                (replay.case.charts[candidate]?.length ?? 0) + (candidate === "1m" ? revealedPracticeBars.length : 0),
              ])),
              onTogglePlay: toggleReplayPlayback,
              onAdvance: (minutes) => {
                if (feedback) {
                  setPlaying(false);
                  setFeedbackRevealCount((current) => Math.min(current + minutes, feedback.practice_feedback.bars.length));
                } else {
                  void advanceCursor(minutes);
                }
              },
              onTimeframeChange: (candidate) => {
                if (feedback && candidate !== "1m") return;
                setTimeframe(candidate);
                setPlaying(false);
              },
            }}
            label={timeframe}
            levels={levels}
            locked={Boolean(feedback)}
            onDrawingsChange={(next) => {
              setPlaying(false);
              setDrawings(next);
            }}
            onFullscreenChange={handleFullscreenChange}
            onPositionPlan={acceptPosition}
            onRequestPositionDetails={() => {
              setPlaying(false);
              setSetupDialogOpen(true);
            }}
            positionLifecycle={positionLifecycle}
            positionReady={Boolean(ticket)}
          />

          <aside
            aria-label="Visible setup ticket"
            className="self-start rounded-xl border-2 border-[#2962FF] bg-[#F8FAFF] p-4 shadow-sm xl:sticky xl:top-20"
          >
            <p className="text-[10px] font-bold uppercase tracking-[0.18em] text-[#174EA6]">
              Setup ticket · cursor T+{replay.case.cursor_minute}m
            </p>
            <label className="mt-3 block text-sm font-bold text-[#131722]" htmlFor="trade-reason">
              WHY THIS TRADE NOW?
            </label>
            <textarea
              className="field mt-2 min-h-32 border-2"
              disabled={Boolean(feedback)}
              id="trade-reason"
              maxLength={2000}
              onChange={(event) => setTradeReason(event.target.value)}
              placeholder="State the observable reason now: fundamental direction, higher-timeframe location, liquidity/structure response, and why this is not a chase."
              value={tradeReason}
            />
            <p className="mt-1 text-[10px] text-[#5D606B]">
              This exact text is sealed with the visible charts and drawings.
            </p>

            <div className="mt-4 grid grid-cols-3 gap-2">
              {(["LONG", "SHORT", "NO_TRADE"] as Action[]).map((candidate) => (
                <button
                  className={`rounded-lg border px-2 py-3 text-xs font-bold ${action === candidate ? "border-[#2962FF] bg-[#EAF0FF] text-[#1848CC]" : "border-[#D1D4DC] bg-white text-[#5D606B]"}`}
                  disabled={Boolean(feedback) || (candidate !== "NO_TRADE" && ticket?.direction !== candidate)}
                  key={candidate}
                  onClick={() => {
                    setPlaying(false);
                    if (candidate === "NO_TRADE") {
                      setAction("NO_TRADE");
                      setTicket(null);
                      setDrawings((current) => current.filter((drawing) => (
                        drawing.kind !== "LONG_POSITION" && drawing.kind !== "SHORT_POSITION"
                      )));
                    } else if (ticket?.direction === candidate) {
                      setAction(candidate);
                    }
                  }}
                  type="button"
                >
                  {candidate.replace("_", " ")}
                </button>
              ))}
            </div>

            {ticket ? (
              <div className="mt-3 rounded-lg border border-[#B7C7FF] bg-white p-3 text-[11px] leading-5 text-[#434651]">
                <p><strong>{ticket.direction} · {ticket.entryTrigger.replaceAll("_", " ")}</strong></p>
                <p>Entry {ticket.entryIndex.toFixed(4)} · SL {ticket.stopIndex.toFixed(4)} · TP {ticket.targetIndex.toFixed(4)}</p>
                <p>{ticket.stopDistanceAtr.toFixed(2)} ATR stop · {ticket.targetR.toFixed(2)}R target · $50 maximum planned risk</p>
              </div>
            ) : (
              <p className="mt-3 rounded-lg bg-white p-3 text-[11px] leading-5 text-[#5D606B]">
                Choose Long or Short on the chart, then click ENTRY, SL, and TP. Or select NO TRADE here.
              </p>
            )}

            <label className="mt-4 grid gap-1 text-xs text-[#5D606B]">
              Confidence · <strong className="text-[#131722]">{confidence}%</strong>
              <input
                disabled={Boolean(feedback)}
                max="100"
                min="50"
                onChange={(event) => setConfidence(Number(event.target.value))}
                type="range"
                value={confidence}
              />
            </label>

            <fieldset className="mt-4">
              <legend className="text-[10px] font-bold uppercase tracking-wide text-[#787B86]">
                Evidence · select at least one
              </legend>
              <div className="mt-2 flex flex-wrap gap-1.5">
                {evidenceOptions.map((code) => (
                  <label className={`cursor-pointer rounded-full border px-2 py-1 text-[9px] font-semibold ${evidence.includes(code) ? "border-[#2962FF] bg-[#EAF0FF] text-[#1848CC]" : "border-[#D1D4DC] bg-white text-[#5D606B]"}`} key={code}>
                    <input
                      checked={evidence.includes(code)}
                      className="sr-only"
                      disabled={Boolean(feedback)}
                      onChange={(event) => setEvidence((current) => (
                        event.target.checked ? [...current, code] : current.filter((item) => item !== code)
                      ))}
                      type="checkbox"
                    />
                    {code.replaceAll("_", " ")}
                  </label>
                ))}
              </div>
            </fieldset>

            <div className="mt-4 grid gap-2">
              <label className="text-[10px] font-semibold text-[#5D606B]">
                Observable trigger
                <textarea className="field mt-1 min-h-16" disabled={Boolean(feedback)} maxLength={1000} onChange={(event) => setTriggerCondition(event.target.value)} value={triggerCondition} />
              </label>
              <label className="text-[10px] font-semibold text-[#5D606B]">
                Invalidation
                <textarea className="field mt-1 min-h-16" disabled={Boolean(feedback)} maxLength={1000} onChange={(event) => setInvalidation(event.target.value)} value={invalidation} />
              </label>
              <label className="text-[10px] font-semibold text-[#5D606B]">
                Target rationale
                <textarea className="field mt-1 min-h-16" disabled={Boolean(feedback)} maxLength={1000} onChange={(event) => setTargetExplanation(event.target.value)} value={targetExplanation} />
              </label>
            </div>

            {blockers.length && !feedback ? (
              <div className="mt-3 rounded-lg border border-[#E8D28A] bg-[#FFF9E6] p-3 text-[10px] leading-5 text-[#785D00]">
                <strong>Before Place &amp; Play:</strong> {blockers.join("; ")}.
              </div>
            ) : null}
            {error ? (
              <p className="mt-3 rounded-lg border border-[#F3B3B8] bg-[#FFF0F1] p-3 text-xs text-[#B4232F]">{error}</p>
            ) : null}
            <button
              className="mt-4 w-full rounded-lg bg-[#2962FF] px-5 py-3 text-sm font-bold text-white disabled:cursor-not-allowed disabled:opacity-35"
              disabled={Boolean(feedback) || submitting || (directional ? !ticket : blockers.length > 0)}
              onClick={() => {
                if (directional) {
                  setPlaying(false);
                  setSetupDialogOpen(true);
                } else {
                  void placeAndPlay();
                }
              }}
              type="button"
            >
              {submitting ? "Sealing setup before reveal…" : directional ? "Place & Play · add annotation" : "Place & Play"}
            </button>
          </aside>
        </div>
      </section>

      <section className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
        <article className="rounded-xl border border-[#D1D4DC] bg-white p-4">
          <p className="text-[10px] font-bold uppercase tracking-wide text-[#8A6200]">Higher-timeframe structure</p>
          {structureRows.map((row, index) => (
            <p className="mt-2 text-xs" key={`${display(row.timeframe)}-${index}`}>
              <strong>{display(row.timeframe)}</strong> · {display(row.trend)} · {display(row.status)}
            </p>
          ))}
        </article>
        <article className="rounded-xl border border-[#D1D4DC] bg-white p-4">
          <p className="text-[10px] font-bold uppercase tracking-wide text-[#8A6200]">Known levels</p>
          {levels.map((level) => (
            <p className="mt-2 text-xs" key={level.code}>
              <strong>{level.code.replaceAll("_", " ")}</strong> · {level.level.toFixed(4)}
            </p>
          ))}
        </article>
        <article className="rounded-xl border border-[#D1D4DC] bg-white p-4">
          <p className="text-[10px] font-bold uppercase tracking-wide text-[#8A6200]">Released events only</p>
          {events.length ? events.map((event) => (
            <p className="mt-2 text-xs" key={`${event.eventCode}-${event.relativeMinute}`}>
              {event.eventCode.replaceAll("_", " ")} · T{event.relativeMinute}m · {event.surpriseLabel ?? "released"}
            </p>
          )) : <p className="mt-2 text-xs text-[#5D606B]">No eligible release in the prior window.</p>}
        </article>
        <article className="rounded-xl border border-[#D1D4DC] bg-white p-4">
          <p className="text-[10px] font-bold uppercase tracking-wide text-[#8A6200]">Exact sealed visibility</p>
          <p className="mt-2 text-xs text-[#5D606B]">Hash {replay.case.visible_charts_sha256.slice(0, 16)}…</p>
          <p className="mt-2 text-xs text-[#5D606B]">
            Latest M1 {replay.case.latest_visible_m1_close_index.toFixed(4)} · M15 ATR {replay.case.latest_point_in_time_m15_atr_index.toFixed(4)}
          </p>
        </article>
      </section>

      {feedback ? (
        <section className="rounded-2xl border border-[#A5DCCF] bg-white p-5 shadow-sm">
          <p className="text-xs font-bold uppercase tracking-[0.16em] text-[#087363]">
            Setup sealed before reveal · {feedback.record_sha256.slice(0, 16)}…
          </p>
          <h3 className="mt-2 text-xl font-semibold">
            Decision, text, drawings, cursor, context, and visible hashes are now immutable.
          </h3>
          <p className="mt-2 text-sm text-[#5D606B]">
            Price resumes one completed M1 candle at a time on the locked chart above, strictly after cursor T+{feedback.locked_cursor_minute}m.
          </p>
          <div className="mt-4 flex flex-wrap items-center gap-2 rounded-xl border border-[#D1D4DC] bg-[#F8F9FB] p-3 text-xs">
            <strong>{positionLifecycle.replaceAll("_", " ")}</strong>
            <span>· revealed {feedbackRevealCount}/{feedback.practice_feedback.bars.length} post-decision minute bars</span>
            <span>· price is playing on the primary locked M1 chart above</span>
          </div>
          <button
            className="mt-4 rounded-lg bg-[#2962FF] px-5 py-3 text-sm font-bold text-white disabled:cursor-not-allowed disabled:opacity-35"
            disabled={!playbackComplete}
            onClick={() => void loadNext()}
            type="button"
          >
            Continue to next practice case
          </button>
        </section>
      ) : null}
    </div>
  );
}
