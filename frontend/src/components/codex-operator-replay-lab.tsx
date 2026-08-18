"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import {
  replayTimeframes,
  replayTimeframeLabel,
  SynchronizedReplayChart,
  type ReplayTimeframe,
  type ReplayV2ChartEvent,
  type ReplayV2Drawing,
  type ReplayV2PositionPlan,
} from "@/components/synchronized-replay-chart";
import {
  codexOperatorReplayCaseSchema,
  codexOperatorReplayMutationSchema,
  publicApiUrl,
  type BlindReplayV3Bar,
  type CodexOperatorReplayPayload,
  type CodexOperatorReplayStatus,
} from "@/lib/api";


type DecisionAction = "LONG" | "SHORT" | "NO_TRADE";
type SetupClass = "MACRO_ALIGNED_CONTINUATION" | "COUNTER_MACRO_RANGE_ROTATION" | "MACRO_NEUTRAL_AUCTION_TRADE";
type Annotation = {
  setupClass: SetupClass;
  thesis: string;
  macroRegime: string;
  macroDirectionalPressure: string;
  macroRole: "DIRECTION_DRIVER" | "CONTEXT_ONLY" | "NEUTRAL";
  macroFreshness: string;
  dominantDriver: string;
  catalystRisk: string;
  higherTimeframeState: "TREND" | "RANGE" | "CONFLICTED" | "UNKNOWN";
  higherTimeframeContext: string;
  locationTimeframe: ReplayTimeframe;
  preexistingLocation: string;
  m15Transition: string;
  sessionLiquidityContext: string;
  invalidationTimeframe: ReplayTimeframe;
  invalidationCondition: string;
  targetTimeframe: ReplayTimeframe;
  targetType: "INTERNAL_LIQUIDITY" | "EXTERNAL_LIQUIDITY" | "NOT_APPLICABLE";
  targetLogic: string;
  macroConfidence: number;
  setupQuality: number;
  executionQuality: number;
  noTradeReason: string;
};

const emptyAnnotation: Annotation = {
  setupClass: "MACRO_ALIGNED_CONTINUATION",
  thesis: "",
  macroRegime: "",
  macroDirectionalPressure: "",
  macroRole: "CONTEXT_ONLY",
  macroFreshness: "",
  dominantDriver: "",
  catalystRisk: "",
  higherTimeframeState: "UNKNOWN",
  higherTimeframeContext: "",
  locationTimeframe: "1h",
  preexistingLocation: "",
  m15Transition: "",
  sessionLiquidityContext: "",
  invalidationTimeframe: "15m",
  invalidationCondition: "",
  targetTimeframe: "1h",
  targetType: "EXTERNAL_LIQUIDITY",
  targetLogic: "",
  macroConfidence: 50,
  setupQuality: 50,
  executionQuality: 50,
  noTradeReason: "",
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
  if (Array.isArray(detail)) return detail.map((item) => display(object(item).msg, "Invalid request")).join("; ");
  return `Replay request failed with HTTP ${status}`;
}

function randomKey() {
  return typeof crypto !== "undefined" && "randomUUID" in crypto
    ? crypto.randomUUID()
    : `codex-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

function minuteOffset(start: string, timestamp: string) {
  return Math.round((Date.parse(timestamp) - Date.parse(start)) / 60_000);
}

function timestampAt(start: string, minute: number) {
  return new Date(Date.parse(start) + minute * 60_000).toISOString().replace(".000Z", "Z");
}

function utcLabel(timestamp: string, includeDate = true) {
  const options: Intl.DateTimeFormatOptions = includeDate
    ? { day: "2-digit", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit", hour12: false, timeZone: "UTC" }
    : { hour: "2-digit", minute: "2-digit", hour12: false, timeZone: "UTC" };
  return `${new Intl.DateTimeFormat("en-GB", options).format(new Date(timestamp))} UTC`;
}

function toChartBar(bar: BlindReplayV3Bar, start: string) {
  return {
    bar_id: bar.bar_id,
    close_offset_minutes: minuteOffset(start, bar.close_at),
    available_offset_minutes: minuteOffset(start, bar.available_at),
    open: bar.open,
    high: bar.high,
    low: bar.low,
    close: bar.close,
    volume: bar.volume ?? null,
  };
}

function serverDrawings(drawings: ReplayV2Drawing[], start: string) {
  return drawings.map((drawing) => ({
    drawing_id: drawing.id,
    kind: drawing.kind,
    created_at_cursor: timestampAt(start, drawing.placedAtCursorMinute),
    anchors: drawing.anchors.map((anchor) => ({
      anchor_at: timestampAt(start, anchor.relativeMinute),
      price: Number(anchor.priceIndex.toFixed(8)),
      source_timeframe: anchor.sourceTimeframe,
    })),
  }));
}

function compactComponent(value: unknown) {
  const text = display(value).toLowerCase();
  if (/falling|declin|lower|weakening/.test(text)) return "FALLING / WEAKENING";
  if (/rising|increas|higher|strengthening/.test(text)) return "RISING / STRENGTHENING";
  if (/positive surprise/.test(text)) return "POSITIVE SURPRISE";
  if (/negative surprise/.test(text)) return "NEGATIVE SURPRISE";
  if (/disinflation/.test(text)) return "DISINFLATING";
  if (/tighten|hawkish/.test(text)) return "TIGHTENING / HAWKISH";
  if (/eas|dovish/.test(text)) return "EASING / DOVISH";
  if (/unknown|unavailable/.test(text)) return "UNKNOWN";
  return "MIXED";
}

function FundamentalTape({ replay }: { replay: CodexOperatorReplayPayload }) {
  const context = replay.context;
  const summary = object(context.fundamental_summary);
  const components = Array.isArray(summary.components) ? summary.components.map(object) : [];
  const events = Array.isArray(context.events) ? context.events.map(object) : [];
  const upcoming = events.find((event) => event.state === "SCHEDULED");
  const released = [...events].reverse().find((event) => event.state === "RELEASED");
  const bias = display(summary.bias_label);
  const biasClass = bias.includes("BULL")
    ? "border-emerald-300 bg-emerald-50 text-emerald-800"
    : bias.includes("BEAR")
      ? "border-red-300 bg-red-50 text-red-800"
      : "border-amber-300 bg-amber-50 text-amber-800";
  return (
    <section aria-label="Point-in-time fundamental context" className="rounded-xl border border-[#D1D4DC] bg-white p-3 shadow-sm">
      <div className="flex flex-wrap items-center gap-2">
        <span className={`rounded-full border px-3 py-1.5 text-xs font-bold ${biasClass}`}>{bias.replaceAll("_", " ")}</span>
        <span className="text-xs font-semibold">Score {display(summary.directional_score)} | confidence {display(summary.confidence)}%</span>
        <span className="rounded-full bg-[#F4F5F7] px-2 py-1 text-[10px]">Regime: {display(summary.regime_label)}</span>
        <span className="rounded-full bg-[#EEF3FF] px-2 py-1 text-[10px] text-[#174EA6]">Driver: {display(summary.dominant_driver)}</span>
        <span className="rounded-full bg-[#FFF8E1] px-2 py-1 text-[10px] text-[#6B5200]">Conflict: {display(summary.main_contradiction)}</span>
        <span className="rounded-full bg-[#F4F5F7] px-2 py-1 text-[10px]">Event risk: {display(summary.event_risk)}</span>
      </div>
      <div className="mt-2 grid gap-2 sm:grid-cols-2 lg:grid-cols-4 xl:grid-cols-7">
        {components.slice(0, 7).map((component, index) => {
          const direction = typeof component.direction === "number" ? component.direction : 0;
          return (
            <div className="rounded-lg border border-[#E6E8EC] bg-[#F8F9FB] px-2.5 py-2" key={`${display(component.code)}-${index}`} title={display(component.explanation)}>
              <p className="truncate text-[9px] font-bold uppercase text-[#787B86]">{display(component.code).replaceAll("_", " ")}</p>
              <p className="mt-1 truncate text-[10px] font-semibold">{compactComponent(component.explanation)}</p>
              <p className={`mt-1 text-[9px] font-bold ${direction > 0.05 ? "text-emerald-700" : direction < -0.05 ? "text-red-700" : "text-[#787B86]"}`}>
                {direction > 0.05 ? "GOLD SUPPORT" : direction < -0.05 ? "GOLD PRESSURE" : "NEUTRAL"} | {display(component.epistemic_status)}
              </p>
            </div>
          );
        })}
      </div>
      <div className="mt-2 flex flex-wrap gap-2 text-[10px]">
        {upcoming ? <span className="rounded bg-amber-50 px-2 py-1 text-amber-800">Upcoming: {display(upcoming.name)} | {utcLabel(String(upcoming.scheduled_at), false)}</span> : null}
        {released ? <span className="rounded bg-blue-50 px-2 py-1 text-blue-800">Released: {display(released.name)} | actual and surprise visible now</span> : null}
        <span className="rounded bg-[#F4F5F7] px-2 py-1">Snapshot available: {summary.available_at ? utcLabel(String(summary.available_at)) : "UNKNOWN"}</span>
      </div>
      <details className="mt-2 rounded border border-[#E6E8EC] px-3 py-2">
        <summary className="cursor-pointer text-xs font-semibold">Expand macro evidence</summary>
        <div className="mt-2 grid gap-2 md:grid-cols-2">
          {components.map((component, index) => <p className="rounded bg-[#F8F9FB] p-2 text-xs leading-5" key={`full-${index}`}><strong>{display(component.code).replaceAll("_", " ")}:</strong> {display(component.explanation)}</p>)}
        </div>
      </details>
    </section>
  );
}

function annotationBlockers(annotation: Annotation, action: DecisionAction) {
  if (action === "NO_TRADE") return annotation.noTradeReason.trim().length >= 3 ? [] : ["structured no-trade reason"];
  return [
    [annotation.thesis, "thesis"],
    [annotation.macroRegime, "macro regime"],
    [annotation.macroDirectionalPressure, "macro pressure"],
    [annotation.macroFreshness, "macro freshness"],
    [annotation.dominantDriver, "dominant driver"],
    [annotation.catalystRisk, "catalyst risk"],
    [annotation.higherTimeframeContext, "higher-timeframe context"],
    [annotation.preexistingLocation, "pre-existing location"],
    [annotation.m15Transition, "M15 transition"],
    [annotation.sessionLiquidityContext, "session/liquidity context"],
    [annotation.invalidationCondition, "invalidation"],
    [annotation.targetLogic, "target logic"],
  ].flatMap(([value, label]) => value.trim().length >= 3 ? [] : [label]);
}

type CodexOperatorReplayLabProps = {
  apiPath?: string;
  operatorLabel?: string;
  matchedHuman?: boolean;
};

export function CodexOperatorReplayLab({
  apiPath = "/codex-operator-replay-v1",
  operatorLabel = "Codex",
  matchedHuman = false,
}: CodexOperatorReplayLabProps = {}) {
  const [status, setStatus] = useState<CodexOperatorReplayStatus | null>(null);
  const [replay, setReplay] = useState<CodexOperatorReplayPayload | null>(null);
  const [timeframe, setTimeframe] = useState<ReplayTimeframe>("15m");
  const [drawings, setDrawings] = useState<ReplayV2Drawing[]>([]);
  const [positionPlan, setPositionPlan] = useState<ReplayV2PositionPlan | null>(null);
  const [annotation, setAnnotation] = useState<Annotation>(emptyAnnotation);
  const [decisionAction, setDecisionAction] = useState<DecisionAction | null>(null);
  const [evidenceSha, setEvidenceSha] = useState("");
  const [playing, setPlaying] = useState(false);
  const [stepInterval, setStepInterval] = useState<1 | 5 | 15>(15);
  const [speed, setSpeed] = useState<1 | 2 | 4 | 8>(4);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("Outcomes remain sealed.");
  const [error, setError] = useState<string | null>(null);
  const advanceInFlight = useRef(false);

  const install = useCallback((next: CodexOperatorReplayPayload | null, progress: CodexOperatorReplayStatus) => {
    setStatus(progress);
    setReplay(next);
    if (!next) return;
    setTimeframe("15m");
    setDrawings([]);
    setPositionPlan(null);
    setAnnotation(emptyAnnotation);
    setEvidenceSha("");
    setDecisionAction(null);
  }, []);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const response = await fetch(`${publicApiUrl}${apiPath}/next`, { cache: "no-store" });
      const body: unknown = await response.json();
      if (!response.ok) {
        if (response.status === 404) {
          setReplay(null);
          return;
        }
        throw new Error(apiError(body, response.status));
      }
      const parsed = codexOperatorReplayCaseSchema.parse(body);
      install(parsed.case, parsed.progress);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : `Unable to initialize the ${operatorLabel} replay.`);
    } finally {
      setLoading(false);
    }
  }, [apiPath, install, operatorLabel]);

  useEffect(() => {
    const timer = window.setTimeout(() => void load(), 0);
    return () => window.clearTimeout(timer);
  }, [load]);

  const mutate = useCallback(async (path: string, payload: Record<string, unknown>) => {
    setBusy(true);
    setError(null);
    try {
      const response = await fetch(`${publicApiUrl}${apiPath}${path}`, {
        method: "POST",
        headers: { "Content-Type": "application/json", "Idempotency-Key": randomKey() },
        body: JSON.stringify(payload),
      });
      const body: unknown = await response.json();
      if (!response.ok) throw new Error(apiError(body, response.status));
      const parsed = codexOperatorReplayMutationSchema.parse(body);
      setStatus(parsed.progress);
      setReplay(parsed.case);
      return parsed;
    } catch (reason) {
      setPlaying(false);
      setError(reason instanceof Error ? reason.message : "Replay mutation failed.");
      return null;
    } finally {
      setBusy(false);
    }
  }, [apiPath]);

  const advance = useCallback(async (minutes: 1 | 5 | 15) => {
    if (!replay || decisionAction || advanceInFlight.current || replay.cursor_at >= replay.observation_terminal_at) {
      setPlaying(false);
      return;
    }
    advanceInFlight.current = true;
    try {
      await mutate("/advance", {
        case_alias: replay.case_alias,
        expected_cursor_at: replay.cursor_at,
        increment_minutes: minutes,
        selected_timeframe: timeframe,
      });
    } finally {
      advanceInFlight.current = false;
    }
  }, [decisionAction, mutate, replay, timeframe]);

  useEffect(() => {
    if (!playing || busy || !replay || decisionAction) return;
    const timer = window.setTimeout(() => {
      if (replay.cursor_at >= replay.observation_terminal_at) setPlaying(false);
      else void advance(stepInterval);
    }, replay.cursor_at >= replay.observation_terminal_at ? 0 : Math.max(75, 850 / speed));
    return () => window.clearTimeout(timer);
  }, [advance, busy, decisionAction, playing, replay, speed, stepInterval]);

  const inspect = useCallback(async (next: ReplayTimeframe) => {
    setTimeframe(next);
    if (!replay) return;
    await mutate("/inspect", {
      case_alias: replay.case_alias,
      expected_cursor_at: replay.cursor_at,
      selected_timeframe: next,
      screenshot_sha256: null,
    });
  }, [mutate, replay]);

  const onPositionPlan = useCallback((plan: ReplayV2PositionPlan | null) => {
    if (!plan) {
      setPositionPlan(null);
      return null;
    }
    const risk = Math.abs(plan.entryIndex - plan.stopIndex);
    if (!(risk > 0)) return "ENTRY and SL must be different prices.";
    if (risk > 50) return "The stop is too wide for one whole ounce under the frozen $50 cap.";
    setPositionPlan(plan);
    return null;
  }, []);

  const openTradeForm = useCallback(() => {
    if (!positionPlan || !replay?.active_entry_session) return;
    setPlaying(false);
    setDecisionAction(positionPlan.direction);
  }, [positionPlan, replay]);

  const submitDecision = useCallback(async () => {
    if (!replay || !decisionAction) return;
    const blockers = annotationBlockers(annotation, decisionAction);
    const evidenceSeal = matchedHuman ? replay.visible_state_sha256 : evidenceSha;
    if (!/^[0-9a-f]{64}$/.test(evidenceSeal)) blockers.push("64-character pre-decision evidence SHA-256");
    if (blockers.length) {
      setError(`Complete: ${blockers.join(", ")}.`);
      return;
    }
    const trade = decisionAction !== "NO_TRADE";
    if (trade && !positionPlan) {
      setError("Draw and confirm exactly one position before sealing a trade.");
      return;
    }
    const plan = trade ? positionPlan : null;
    const parsed = await mutate("/decisions", {
      case_alias: replay.case_alias,
      expected_cursor_at: replay.cursor_at,
      selected_timeframe: timeframe,
      client_visible_state_sha256: replay.visible_state_sha256,
      predecision_evidence_sha256: evidenceSeal,
      inspected_timeframes: replay.inspected_timeframes,
      action: decisionAction,
      entry: plan?.entryIndex ?? null,
      stop: plan?.stopIndex ?? null,
      target: plan?.targetIndex ?? null,
      drawings: trade ? serverDrawings(drawings, replay.start_at) : [],
      annotation: {
        setup_class: trade ? annotation.setupClass : null,
        thesis: trade ? annotation.thesis : "No eligible setup was visible by the frozen terminal cursor.",
        macro_regime: annotation.macroRegime || "UNKNOWN",
        macro_directional_pressure: annotation.macroDirectionalPressure || "UNKNOWN",
        macro_role: annotation.macroRole,
        macro_freshness: annotation.macroFreshness || "UNKNOWN",
        dominant_driver: annotation.dominantDriver || "UNKNOWN",
        catalyst_risk: annotation.catalystRisk || "UNKNOWN",
        higher_timeframe_state: annotation.higherTimeframeState,
        higher_timeframe_context: annotation.higherTimeframeContext || "No eligible completed higher-timeframe location.",
        location_timeframe: annotation.locationTimeframe,
        preexisting_location: annotation.preexistingLocation || "No eligible pre-existing location.",
        m15_transition: annotation.m15Transition || "No qualifying completed M15 transition.",
        session_liquidity_context: annotation.sessionLiquidityContext || "Observation window completed without a qualifying setup.",
        invalidation_timeframe: annotation.invalidationTimeframe,
        invalidation_condition: annotation.invalidationCondition || "Not applicable because no trade was opened.",
        target_timeframe: annotation.targetTimeframe,
        target_type: trade ? annotation.targetType : "NOT_APPLICABLE",
        target_logic: annotation.targetLogic || "Not applicable because no trade was opened.",
        macro_confidence: annotation.macroConfidence,
        setup_quality: trade ? annotation.setupQuality : 0,
        execution_quality: trade ? annotation.executionQuality : 0,
        no_trade_reason: trade ? null : annotation.noTradeReason,
      },
    });
    if (!parsed) return;
    setDecisionAction(null);
    setDrawings([]);
    setPositionPlan(null);
    setAnnotation(emptyAnnotation);
    setEvidenceSha("");
    setMessage(`${replay.case_alias} sealed. Its outcome is hidden.`);
  }, [annotation, decisionAction, drawings, evidenceSha, matchedHuman, mutate, positionPlan, replay, timeframe]);

  const chartBars = useMemo(() => replay
    ? (replay.charts[timeframe] ?? []).map((bar) => toChartBar(bar, replay.start_at))
    : [], [replay, timeframe]);
  const cursorMinute = replay ? minuteOffset(replay.start_at, replay.cursor_at) : 0;
  const terminalMinute = replay ? minuteOffset(replay.start_at, replay.observation_terminal_at) : 0;

  const levels = useMemo(() => {
    if (!replay) return [];
    const output: Array<{ code: string; level: number }> = [];
    const sessions = Array.isArray(replay.context.sessions) ? replay.context.sessions.map(object) : [];
    for (const session of sessions) {
      const known = Array.isArray(session.known_levels) ? session.known_levels.map(object) : [];
      for (const level of known) if (typeof level.code === "string" && typeof level.price === "number") output.push({ code: level.code, level: level.price });
    }
    const structure = object(replay.context.structure);
    const frames = Array.isArray(structure.timeframes) ? structure.timeframes.map(object) : [];
    for (const frame of frames) {
      const detections = Array.isArray(frame.detections) ? frame.detections.map(object) : [];
      for (const detection of detections.slice(-4)) if (typeof detection.kind === "string" && typeof detection.price_level === "number") output.push({ code: detection.kind, level: detection.price_level });
    }
    return output.slice(-24);
  }, [replay]);

  const events = useMemo<ReplayV2ChartEvent[]>(() => {
    if (!replay || !Array.isArray(replay.context.events)) return [];
    return replay.context.events.flatMap((value) => {
      const event = object(value);
      const timestamp = typeof event.released_at === "string" ? event.released_at : event.scheduled_at;
      if (typeof timestamp !== "string" || typeof event.event_code !== "string") return [];
      return [{
        eventCode: event.event_code,
        name: display(event.name, event.event_code),
        relativeMinute: minuteOffset(replay.start_at, timestamp),
        surpriseLabel: event.state === "RELEASED" ? "RELEASED" : "SCHEDULED",
        goldImpact: null,
      }];
    });
  }, [replay]);

  const windows = useMemo(() => {
    if (!replay || !Array.isArray(replay.context.sessions)) return [];
    return replay.context.sessions.flatMap((value) => {
      const session = object(value);
      if (typeof session.session_code !== "string" || typeof session.decision_at !== "string" || typeof session.observation_end !== "string") return [];
      return [{
        code: session.session_code,
        startMinute: minuteOffset(replay.start_at, session.decision_at),
        endMinute: minuteOffset(replay.start_at, session.observation_end),
        color: session.session_code === "LONDON" ? "#1976D2" : "#D97706",
      }];
    });
  }, [replay]);

  const form = decisionAction && replay ? (
    <div aria-label={`${operatorLabel} decision form`} className="fixed inset-0 z-[100] grid place-items-center bg-black/35 p-3">
      <div className="max-h-[96vh] w-full max-w-5xl overflow-y-auto rounded-2xl border border-[#D1D4DC] bg-white p-5 text-[#131722] shadow-2xl">
        <div className="flex items-start justify-between gap-4">
          <div>
            <p className="text-[10px] font-bold uppercase tracking-[0.18em] text-[#787B86]">Immutable blind decision | {replay.case_alias}</p>
            <h3 className="mt-1 text-xl font-semibold">{decisionAction}{positionPlan ? ` | ENTRY ${positionPlan.entryIndex.toFixed(2)} | SL ${positionPlan.stopIndex.toFixed(2)} | TP ${positionPlan.targetIndex.toFixed(2)}` : ""}</h3>
            <p className="mt-1 text-xs text-[#5D606B]">Cursor: {utcLabel(replay.cursor_at)}. No future candle or outcome is loaded.</p>
          </div>
          <button aria-label={`Cancel ${operatorLabel} decision form`} className="chart-command" onClick={() => setDecisionAction(null)} type="button">Cancel</button>
        </div>
        {decisionAction === "NO_TRADE" ? (
          <label className="mt-4 block text-xs font-semibold">Why no eligible trade appeared
            <textarea aria-label="No-trade reason" className="mt-1 min-h-32 w-full rounded border border-[#D1D4DC] p-3 text-sm font-normal" onChange={(event) => setAnnotation((value) => ({ ...value, noTradeReason: event.target.value }))} value={annotation.noTradeReason} />
          </label>
        ) : (
          <div className="mt-4 grid gap-3 md:grid-cols-2">
            <label className="text-xs font-semibold">Setup class<select aria-label="Setup class" className="mt-1 w-full rounded border border-[#D1D4DC] p-2 text-sm font-normal" onChange={(event) => setAnnotation((value) => ({ ...value, setupClass: event.target.value as SetupClass }))} value={annotation.setupClass}><option>MACRO_ALIGNED_CONTINUATION</option><option>COUNTER_MACRO_RANGE_ROTATION</option><option>MACRO_NEUTRAL_AUCTION_TRADE</option></select></label>
            <label className="text-xs font-semibold">HTF state<select aria-label="Higher-timeframe state" className="mt-1 w-full rounded border border-[#D1D4DC] p-2 text-sm font-normal" onChange={(event) => setAnnotation((value) => ({ ...value, higherTimeframeState: event.target.value as Annotation["higherTimeframeState"] }))} value={annotation.higherTimeframeState}><option>TREND</option><option>RANGE</option><option>CONFLICTED</option><option>UNKNOWN</option></select></label>
            <label className="md:col-span-2 text-xs font-semibold">Why this trade exists now<textarea aria-label="Codex trade thesis" className="mt-1 min-h-24 w-full rounded border border-[#D1D4DC] p-3 text-sm font-normal" onChange={(event) => setAnnotation((value) => ({ ...value, thesis: event.target.value }))} value={annotation.thesis} /></label>
            <label className="text-xs font-semibold">Macro regime<input aria-label="Macro regime" className="mt-1 w-full rounded border border-[#D1D4DC] p-2 text-sm font-normal" onChange={(event) => setAnnotation((value) => ({ ...value, macroRegime: event.target.value }))} value={annotation.macroRegime} /></label>
            <label className="text-xs font-semibold">Macro directional pressure<input aria-label="Macro directional pressure" className="mt-1 w-full rounded border border-[#D1D4DC] p-2 text-sm font-normal" onChange={(event) => setAnnotation((value) => ({ ...value, macroDirectionalPressure: event.target.value }))} value={annotation.macroDirectionalPressure} /></label>
            <label className="text-xs font-semibold">Macro role<select aria-label="Macro role" className="mt-1 w-full rounded border border-[#D1D4DC] p-2 text-sm font-normal" onChange={(event) => setAnnotation((value) => ({ ...value, macroRole: event.target.value as Annotation["macroRole"] }))} value={annotation.macroRole}><option>DIRECTION_DRIVER</option><option>CONTEXT_ONLY</option><option>NEUTRAL</option></select></label>
            <label className="text-xs font-semibold">Macro freshness<input aria-label="Macro freshness" className="mt-1 w-full rounded border border-[#D1D4DC] p-2 text-sm font-normal" onChange={(event) => setAnnotation((value) => ({ ...value, macroFreshness: event.target.value }))} value={annotation.macroFreshness} /></label>
            <label className="text-xs font-semibold">Dominant driver<input aria-label="Codex dominant driver" className="mt-1 w-full rounded border border-[#D1D4DC] p-2 text-sm font-normal" onChange={(event) => setAnnotation((value) => ({ ...value, dominantDriver: event.target.value }))} value={annotation.dominantDriver} /></label>
            <label className="text-xs font-semibold">Catalyst risk<input aria-label="Catalyst risk" className="mt-1 w-full rounded border border-[#D1D4DC] p-2 text-sm font-normal" onChange={(event) => setAnnotation((value) => ({ ...value, catalystRisk: event.target.value }))} value={annotation.catalystRisk} /></label>
            <label className="md:col-span-2 text-xs font-semibold">Completed HTF structure and location<textarea aria-label="Codex higher-timeframe context" className="mt-1 min-h-20 w-full rounded border border-[#D1D4DC] p-2 text-sm font-normal" onChange={(event) => setAnnotation((value) => ({ ...value, higherTimeframeContext: event.target.value }))} value={annotation.higherTimeframeContext} /></label>
            <label className="text-xs font-semibold">Location timeframe<select aria-label="Location timeframe" className="mt-1 w-full rounded border border-[#D1D4DC] p-2 text-sm font-normal" onChange={(event) => setAnnotation((value) => ({ ...value, locationTimeframe: event.target.value as ReplayTimeframe }))} value={annotation.locationTimeframe}>{replayTimeframes.slice(0, 4).map((item) => <option key={item} value={item}>{replayTimeframeLabel(item)}</option>)}</select></label>
            <label className="text-xs font-semibold">Pre-existing level or liquidity<textarea aria-label="Pre-existing location" className="mt-1 min-h-20 w-full rounded border border-[#D1D4DC] p-2 text-sm font-normal" onChange={(event) => setAnnotation((value) => ({ ...value, preexistingLocation: event.target.value }))} value={annotation.preexistingLocation} /></label>
            <label className="md:col-span-2 text-xs font-semibold">Completed M15 transition at that location<textarea aria-label="M15 transition" className="mt-1 min-h-20 w-full rounded border border-[#D1D4DC] p-2 text-sm font-normal" onChange={(event) => setAnnotation((value) => ({ ...value, m15Transition: event.target.value }))} value={annotation.m15Transition} /></label>
            <label className="md:col-span-2 text-xs font-semibold">Session and liquidity context<textarea aria-label="Codex session and liquidity context" className="mt-1 min-h-20 w-full rounded border border-[#D1D4DC] p-2 text-sm font-normal" onChange={(event) => setAnnotation((value) => ({ ...value, sessionLiquidityContext: event.target.value }))} value={annotation.sessionLiquidityContext} /></label>
            <label className="text-xs font-semibold">Invalidation condition<textarea aria-label="Codex invalidation condition" className="mt-1 min-h-20 w-full rounded border border-[#D1D4DC] p-2 text-sm font-normal" onChange={(event) => setAnnotation((value) => ({ ...value, invalidationCondition: event.target.value }))} value={annotation.invalidationCondition} /></label>
            <label className="text-xs font-semibold">Target logic<textarea aria-label="Codex target logic" className="mt-1 min-h-20 w-full rounded border border-[#D1D4DC] p-2 text-sm font-normal" onChange={(event) => setAnnotation((value) => ({ ...value, targetLogic: event.target.value }))} value={annotation.targetLogic} /></label>
            <label className="text-xs font-semibold">Target type<select aria-label="Target type" className="mt-1 w-full rounded border border-[#D1D4DC] p-2 text-sm font-normal" onChange={(event) => setAnnotation((value) => ({ ...value, targetType: event.target.value as Annotation["targetType"] }))} value={annotation.targetType}><option>EXTERNAL_LIQUIDITY</option><option>INTERNAL_LIQUIDITY</option></select></label>
            <label className="text-xs font-semibold">Macro confidence {annotation.macroConfidence}%<input aria-label="Macro confidence" className="mt-2 w-full" max="100" min="0" onChange={(event) => setAnnotation((value) => ({ ...value, macroConfidence: Number(event.target.value) }))} type="range" value={annotation.macroConfidence} /></label>
            <label className="text-xs font-semibold">Setup quality {annotation.setupQuality}%<input aria-label="Setup quality" className="mt-2 w-full" max="100" min="0" onChange={(event) => setAnnotation((value) => ({ ...value, setupQuality: Number(event.target.value) }))} type="range" value={annotation.setupQuality} /></label>
            <label className="text-xs font-semibold">Execution quality {annotation.executionQuality}%<input aria-label="Execution quality" className="mt-2 w-full" max="100" min="0" onChange={(event) => setAnnotation((value) => ({ ...value, executionQuality: Number(event.target.value) }))} type="range" value={annotation.executionQuality} /></label>
          </div>
        )}
        {matchedHuman ? <p className="mt-4 rounded border border-[#A5DCCF] bg-[#EAF8F4] p-3 text-xs text-[#087363]">The point-in-time chart/context hash, drawings and complete rationale will be sealed automatically with this decision.</p> : <label className="mt-4 block text-xs font-semibold">Pre-decision evidence SHA-256
          <input aria-label="Pre-decision evidence SHA-256" autoComplete="off" className="mt-1 w-full rounded border border-[#D1D4DC] p-2 font-mono text-xs" maxLength={64} onChange={(event) => setEvidenceSha(event.target.value.trim().toLowerCase())} placeholder="Evidence recorder fills this after screenshots and action log are sealed" value={evidenceSha} />
        </label>}
        <div className="mt-5 flex flex-wrap justify-end gap-2">
          <button className="chart-command" onClick={() => setDecisionAction(null)} type="button">Return to chart</button>
          <button aria-label={`Seal ${operatorLabel} decision`} className="rounded-lg bg-[#087363] px-5 py-2 text-sm font-bold text-white disabled:opacity-40" disabled={busy} onClick={() => void submitDecision()} type="button">Seal Decision</button>
        </div>
      </div>
    </div>
  ) : null;

  if (loading) return <div className="mt-8 rounded-xl border border-[#D1D4DC] bg-white p-8 text-sm">Verifying the isolated browser pathway...</div>;
  if (!replay) return <section className="mt-8 rounded-xl border border-[#D1D4DC] bg-white p-6"><h3 className="text-xl font-semibold">Blind collection complete or unavailable</h3><p className="mt-2 text-sm text-[#5D606B]">{status?.cases_completed ?? 0} / {status?.cases_total ?? (matchedHuman ? 30 : 249)} cases terminal. Outcomes remain sealed until the final opening gate.</p>{error ? <p className="mt-3 text-sm text-red-700">{error}</p> : null}</section>;

  const atTerminal = replay.cursor_at === replay.observation_terminal_at;
  const playDisabled = busy || Boolean(decisionAction) || atTerminal;
  const tradeReady = Boolean(positionPlan) && Boolean(replay.active_entry_session);

  return (
    <div className="mt-6 space-y-3" data-testid="codex-operator-replay-lab">
      <section className="rounded-xl border border-[#D1D4DC] bg-white p-3 shadow-sm">
        <div className="flex flex-wrap items-center gap-2">
          <span className="rounded-full bg-[#131722] px-3 py-2 text-xs font-bold text-white">{replay.case_alias}</span>
          <span className="rounded-full bg-[#EEF3FF] px-3 py-2 text-xs font-bold text-[#174EA6]">{utcLabel(replay.cursor_at)}</span>
          <span className="rounded-full bg-[#F4F5F7] px-3 py-2 text-xs font-semibold">Session: {replay.active_entry_session?.replaceAll("_", " ") ?? "OBSERVATION / ASIA"}</span>
          <span className="rounded-full bg-[#FFF8E1] px-3 py-2 text-xs font-semibold text-[#6B5200]">Terminal: {utcLabel(replay.observation_terminal_at, false)}</span>
          <button aria-label={playing ? `Pause ${operatorLabel} replay` : `Play ${operatorLabel} replay`} className="ml-2 rounded-lg bg-[#2962FF] px-4 py-2 text-sm font-bold text-white disabled:opacity-35" disabled={playDisabled && !playing} onClick={() => setPlaying((value) => !value)} type="button">{playing ? "Pause" : "Play"}</button>
          {([1, 5, 15] as const).map((minutes) => <button aria-label={`Step ${operatorLabel} replay ${minutes} minute${minutes === 1 ? "" : "s"}`} className="chart-command" disabled={playDisabled} key={minutes} onClick={() => void advance(minutes)} type="button">+{minutes}m</button>)}
          <label className="text-[10px] font-bold uppercase text-[#787B86]">Interval<select aria-label="Codex replay interval" className="ml-1 rounded border border-[#D1D4DC] p-2 text-xs" onChange={(event) => setStepInterval(Number(event.target.value) as 1 | 5 | 15)} value={stepInterval}><option value="1">1m</option><option value="5">5m</option><option value="15">15m</option></select></label>
          <label className="text-[10px] font-bold uppercase text-[#787B86]">Speed<select aria-label="Codex replay speed" className="ml-1 rounded border border-[#D1D4DC] p-2 text-xs" onChange={(event) => setSpeed(Number(event.target.value) as 1 | 2 | 4 | 8)} value={speed}><option value="1">1x</option><option value="2">2x</option><option value="4">4x</option><option value="8">8x</option></select></label>
        </div>
        <div className="mt-2 flex flex-wrap items-center gap-2">
          {replayTimeframes.map((item) => <button aria-label={`Inspect ${replayTimeframeLabel(item)} timeframe`} aria-pressed={timeframe === item} className={`rounded border px-2 py-1 text-[10px] font-bold ${timeframe === item ? "border-[#2962FF] bg-[#EEF3FF] text-[#174EA6]" : "border-[#D1D4DC]"}`} key={item} onClick={() => void inspect(item)} type="button">{replayTimeframeLabel(item)} | {replay.visible_timeframes[item]?.count ?? 0}{replay.inspected_timeframes.includes(item) ? " | sealed" : ""}</button>)}
          <span className="ml-auto text-[10px] font-semibold text-[#5D606B]">Required before decision: W1, D1, H4, H1, M15</span>
        </div>
      </section>

      <FundamentalTape replay={replay} />

      <div className="grid gap-3 xl:grid-cols-[minmax(0,1fr)_310px]">
        <SynchronizedReplayChart
          bars={chartBars}
          cursorDisplayLabel={utcLabel(replay.cursor_at)}
          cursorMinute={cursorMinute}
          drawings={drawings}
          events={events}
          formatMinuteLabel={(minute) => utcLabel(timestampAt(replay.start_at, minute), minute < 0 || minute >= 1440)}
          fullscreenOverlay={form}
          fullscreenReplayControls={{
            playing,
            advancing: busy,
            playDisabled,
            advanceDisabled: playDisabled,
            cursorMinute,
            maximumCursorMinute: terminalMinute,
            timeframeCounts: Object.fromEntries(replayTimeframes.map((item) => [item, replay.visible_timeframes[item]?.count ?? 0])),
            onTogglePlay: () => setPlaying((value) => !value),
            onAdvance: (minutes) => void advance(minutes),
            onTimeframeChange: (item) => void inspect(item),
          }}
          label={timeframe}
          levels={levels}
          locked={false}
          onDrawingsChange={setDrawings}
          onPositionPlan={onPositionPlan}
          onRequestPositionDetails={openTradeForm}
          placeButtonLabel="Prepare Blind Decision"
          positionLifecycle="EDITABLE"
          positionReady={tradeReady}
          windows={windows}
        />

        <aside className="space-y-3">
          <section className="rounded-xl border border-[#D1D4DC] bg-white p-4 shadow-sm">
            <p className="text-[10px] font-bold uppercase tracking-[0.16em] text-[#787B86]">Frozen decision ticket</p>
            {positionPlan ? <div className="mt-3 space-y-1 rounded-lg bg-[#F8F9FB] p-3 text-xs"><p className="font-bold">{positionPlan.direction}</p><p>ENTRY {positionPlan.entryIndex.toFixed(2)}</p><p className="text-red-700">SL {positionPlan.stopIndex.toFixed(2)}</p><p className="text-emerald-700">TP {positionPlan.targetIndex.toFixed(2)}</p><p>R:R {(Math.abs(positionPlan.targetIndex - positionPlan.entryIndex) / Math.abs(positionPlan.entryIndex - positionPlan.stopIndex)).toFixed(2)}</p><p>Maximum planned risk: $50 | whole ounces</p></div> : <p className="mt-3 rounded bg-[#F8F9FB] p-3 text-xs text-[#5D606B]">Draw a Long or Short position at REPLAY NOW. Resize ENTRY, SL and TP before sealing.</p>}
            <button aria-label="Open blind trade decision form" className="mt-3 w-full rounded bg-[#087363] px-3 py-2 text-xs font-bold text-white disabled:opacity-35" disabled={!tradeReady} onClick={openTradeForm} type="button">Prepare Trade Decision</button>
            <button aria-label="Open no-trade decision form" className="mt-2 w-full rounded border border-[#D1D4DC] bg-white px-3 py-2 text-xs font-bold disabled:opacity-35" disabled={!atTerminal} onClick={() => { setPlaying(false); setDecisionAction("NO_TRADE"); }} type="button">Seal NO_TRADE at Terminal</button>
            {!replay.active_entry_session && !atTerminal ? <p className="mt-2 text-[10px] text-amber-700">A trade cannot be sealed outside London, overlap or New York.</p> : null}
          </section>
          <section aria-label="Blind audit status" className="rounded-xl border border-[#D1D4DC] bg-white p-4 text-xs shadow-sm">
            <p className="text-[10px] font-bold uppercase tracking-[0.16em] text-[#787B86]">Blind audit</p>
            <p className="mt-2">Complete: {status?.cases_completed ?? 0} / {status?.cases_total ?? 249}</p>
            <p>Visible ledger: {status?.visible_ledger_head_sha256.slice(0, 12)}...</p>
            <p>Outcome vault: SEALED</p><p>{matchedHuman ? "Codex decisions: HIDDEN" : "Human decisions: HIDDEN"}</p><p>2025 / 2026: LOCKED</p>
            <p className="mt-2 rounded bg-[#FFF8E1] p-2 text-[#6B5200]">No outcome, hit rate, PnL or interim feedback is available.</p>
          </section>
        </aside>
      </div>
      <p className="rounded-lg border border-[#D1D4DC] bg-white p-3 text-xs" role="status">{message}</p>
      {error ? <div className="rounded-lg border border-red-300 bg-red-50 p-3 text-sm text-red-800" role="alert">{error}</div> : null}
    </div>
  );
}
