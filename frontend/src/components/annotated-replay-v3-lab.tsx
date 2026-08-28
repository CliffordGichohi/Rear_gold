"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import {
  replayTimeframes,
  replayTimeframeLabel,
  SynchronizedReplayChart,
  type ReplayTimeframe,
  type ReplayV2ChartEvent,
  type ReplayV2Drawing,
  type ReplayV2PositionLifecycle,
  type ReplayV2PositionPlan,
} from "@/components/synchronized-replay-chart";
import {
  blindReplayV3CaseSchema,
  blindReplayV3MutationSchema,
  blindReplayV3StatusSchema,
  coherentAuctionValidationCaseSchema,
  coherentAuctionValidationMutationSchema,
  coherentAuctionValidationStatusSchema,
  publicApiUrl,
  type BlindReplayV3Bar,
  type BlindReplayV3Order,
  type BlindReplayV3Payload,
  type BlindReplayV3Status,
  type CoherentAuctionValidationPayload,
  type CoherentAuctionValidationStatus,
} from "@/lib/api";


type OrderType = "MARKET" | "LIMIT" | "STOP";
type Annotation = {
  thesis: string;
  fundamentalDirection: string;
  dominantDriver: string;
  higherTimeframeContext: string;
  sessionLiquidityContext: string;
  entryTrigger: string;
  invalidationLogic: string;
  targetLogic: string;
  eventRisk: string;
  confidence: number;
  auctionFamily: "CONTINUATION_WITH_ROOM" | "RANGE_ROTATION" | "STRUCTURAL_REPAIR" | "OTHER_EXPLICIT";
  controllingH4State: "PULLBACK_WITH_ROOM" | "BALANCE_LOWER_ROTATION" | "BALANCE_UPPER_ROTATION" | "UPPER_BOUNDARY_EXTENDED" | "LOWER_BOUNDARY_EXTENDED" | "BEARISH_DAMAGE" | "BULLISH_DAMAGE" | "ACCEPTED_REPAIR" | "UNKNOWN";
  locationAssessment: "DISCOUNT" | "MIDRANGE" | "PREMIUM" | "AT_SUPPORT" | "AT_RESISTANCE" | "UNKNOWN";
  stopBasis: "ACTIVE_M15_PROTECTED_SWING" | "CONTROLLING_M15_RANGE_BOUNDARY" | "POST_REPAIR_ORIGIN" | "OTHER_EXPLICIT";
  macroOverrideReason: string;
};

type ReplayStatus = BlindReplayV3Status | CoherentAuctionValidationStatus;
type ReplayPayload = BlindReplayV3Payload | CoherentAuctionValidationPayload;

type AnnotatedReplayV3LabProps = {
  apiBasePath?: "/blind-replay-v3" | "/coherent-auction-validation";
  draftPrefix?: string;
  validationMode?: boolean;
};

const emptyAnnotation: Annotation = {
  thesis: "",
  fundamentalDirection: "UNKNOWN",
  dominantDriver: "",
  higherTimeframeContext: "",
  sessionLiquidityContext: "",
  entryTrigger: "",
  invalidationLogic: "",
  targetLogic: "",
  eventRisk: "NONE_KNOWN",
  confidence: 60,
  auctionFamily: "CONTINUATION_WITH_ROOM",
  controllingH4State: "PULLBACK_WITH_ROOM",
  locationAssessment: "MIDRANGE",
  stopBasis: "ACTIVE_M15_PROTECTED_SWING",
  macroOverrideReason: "NOT_AGAINST_DISPLAYED_MACRO",
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
    : `v3-${Date.now()}-${Math.random().toString(16).slice(2)}`;
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

function positionFromOrder(order: BlindReplayV3Order): ReplayV2PositionPlan {
  return {
    drawingId: `server-${order.order_id}`,
    direction: order.direction,
    entryIndex: order.entry,
    stopIndex: order.stop,
    targetIndex: order.target,
  };
}

function drawingsFromOrder(order: BlindReplayV3Order, start: string): ReplayV2Drawing[] {
  return order.drawings.flatMap((value) => {
    const drawing = object(value);
    const anchors = Array.isArray(drawing.anchors) ? drawing.anchors.map(object) : [];
    if (
      typeof drawing.drawing_id !== "string"
      || typeof drawing.kind !== "string"
      || typeof drawing.created_at_cursor !== "string"
      || anchors.some((anchor) => typeof anchor.anchor_at !== "string" || typeof anchor.price !== "number" || typeof anchor.source_timeframe !== "string")
    ) return [];
    return [{
      id: drawing.drawing_id,
      kind: drawing.kind as ReplayV2Drawing["kind"],
      placedAtCursorMinute: minuteOffset(start, drawing.created_at_cursor),
      anchors: anchors.map((anchor) => ({
        relativeMinute: minuteOffset(start, String(anchor.anchor_at)),
        priceIndex: Number(anchor.price),
        sourceTimeframe: String(anchor.source_timeframe) as ReplayTimeframe,
      })),
    }];
  });
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
  if (/tighten/.test(text)) return "TIGHTENING";
  if (/eas|dovish/.test(text)) return "EASING / DOVISH";
  if (/unknown|unavailable/.test(text)) return "UNKNOWN";
  return "MIXED";
}

function FundamentalTape({ replay }: { replay: ReplayPayload }) {
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
        <span className="text-xs font-semibold">Score {display(summary.directional_score)} · confidence {display(summary.confidence)}%</span>
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
                {direction > 0.05 ? "GOLD SUPPORT" : direction < -0.05 ? "GOLD PRESSURE" : "NEUTRAL"} · {display(component.epistemic_status)}
              </p>
            </div>
          );
        })}
      </div>
      <div className="mt-2 flex flex-wrap gap-2 text-[10px]">
        {upcoming ? <span className="rounded bg-amber-50 px-2 py-1 text-amber-800">Upcoming: {display(upcoming.name)} · {utcLabel(String(upcoming.scheduled_at), false)}</span> : null}
        {released ? <span className="rounded bg-blue-50 px-2 py-1 text-blue-800">Released: {display(released.name)} · actual/surprise now available</span> : null}
        <span className="rounded bg-[#F4F5F7] px-2 py-1">Snapshot available: {summary.available_at ? utcLabel(String(summary.available_at)) : "UNKNOWN"}</span>
      </div>
      <details className="mt-2 rounded border border-[#E6E8EC] px-3 py-2">
        <summary className="cursor-pointer text-xs font-semibold">Expand evidence and explanations</summary>
        <div className="mt-2 grid gap-2 md:grid-cols-2">
          {components.map((component, index) => (
            <p className="rounded bg-[#F8F9FB] p-2 text-xs leading-5" key={`full-${display(component.code)}-${index}`}>
              <strong>{display(component.code).replaceAll("_", " ")} · {display(component.epistemic_status)}:</strong> {display(component.explanation)}
            </p>
          ))}
        </div>
      </details>
    </section>
  );
}

function annotationBlockers(annotation: Annotation, validationMode: boolean) {
  const base = [
    [annotation.thesis, "why this trade exists now"],
    [annotation.dominantDriver, "dominant driver"],
    [annotation.higherTimeframeContext, "higher-timeframe context"],
    [annotation.sessionLiquidityContext, "session/liquidity context"],
    [annotation.entryTrigger, "observable entry trigger"],
    [annotation.invalidationLogic, "invalidation logic"],
    [annotation.targetLogic, "target logic"],
  ].flatMap(([value, label]) => value.trim().length >= 3 ? [] : [label]);
  if (validationMode && annotation.macroOverrideReason.trim().length < 3) {
    base.push("macro-alignment or override reason");
  }
  return base;
}

export function AnnotatedReplayV3Lab({
  apiBasePath = "/blind-replay-v3",
  draftPrefix = "gold-replay-v3-draft",
  validationMode = false,
}: AnnotatedReplayV3LabProps = {}) {
  const [status, setStatus] = useState<ReplayStatus | null>(null);
  const [replay, setReplay] = useState<ReplayPayload | null>(null);
  const [selectedAlias, setSelectedAlias] = useState("");
  const [initialTime, setInitialTime] = useState("00:00");
  const [started, setStarted] = useState(false);
  const [timeframe, setTimeframe] = useState<ReplayTimeframe>("15m");
  const [drawings, setDrawings] = useState<ReplayV2Drawing[]>([]);
  const [positionPlan, setPositionPlan] = useState<ReplayV2PositionPlan | null>(null);
  const [orderType, setOrderType] = useState<OrderType>("MARKET");
  const [annotation, setAnnotation] = useState<Annotation>(emptyAnnotation);
  const [amendReason, setAmendReason] = useState("");
  const [manualCloseReason, setManualCloseReason] = useState("");
  const [dialogOpen, setDialogOpen] = useState(false);
  const [playing, setPlaying] = useState(false);
  const [stepInterval, setStepInterval] = useState<1 | 5 | 15>(1);
  const [speed, setSpeed] = useState<1 | 2 | 4 | 8>(2);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const advanceInFlight = useRef(false);

  const installCase = useCallback((next: ReplayPayload, progress: ReplayStatus, forceServerOrder = false) => {
    setReplay(next);
    setStatus(progress);
    setSelectedAlias(next.case_alias);
    const live = next.live_order;
    if (live && (forceServerOrder || live.state === "ACTIVE_POSITION")) {
      setDrawings(drawingsFromOrder(live, next.start_at));
      setPositionPlan(positionFromOrder(live));
      setOrderType(live.order_type);
      if (live.state === "ACTIVE_POSITION") setDialogOpen(false);
    }
  }, []);

  const loadCase = useCallback(async (alias: string, restoreDraft = true) => {
    setLoading(true);
    setError(null);
    try {
      const response = await fetch(`${publicApiUrl}${apiBasePath}/next?case_alias=${encodeURIComponent(alias)}`, { cache: "no-store" });
      const body: unknown = await response.json();
      if (!response.ok) throw new Error(apiError(body, response.status));
      const parsed = validationMode
        ? coherentAuctionValidationCaseSchema.parse(body)
        : blindReplayV3CaseSchema.parse(body);
      installCase(parsed.case, parsed.progress, Boolean(parsed.case.live_order));
      setStarted(Boolean(parsed.progress.current_case_alias) || parsed.case.cursor_at !== parsed.case.start_at);
      setInitialTime(parsed.case.start_at.slice(11, 16));
      if (!parsed.case.live_order && restoreDraft) {
        const raw = window.localStorage.getItem(`${draftPrefix}:${parsed.case.case_alias}`);
        if (raw) {
          const draft = JSON.parse(raw) as { drawings?: ReplayV2Drawing[]; positionPlan?: ReplayV2PositionPlan | null; timeframe?: ReplayTimeframe; orderType?: OrderType; annotation?: Annotation };
          if (Array.isArray(draft.drawings)) setDrawings(draft.drawings);
          setPositionPlan(draft.positionPlan ?? null);
          if (draft.timeframe && replayTimeframes.includes(draft.timeframe)) setTimeframe(draft.timeframe);
          if (draft.orderType) setOrderType(draft.orderType);
          if (draft.annotation) setAnnotation({ ...emptyAnnotation, ...draft.annotation });
        } else {
          setDrawings([]);
          setPositionPlan(null);
          setAnnotation(emptyAnnotation);
        }
      }
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Unable to load V3 practice replay.");
    } finally {
      setLoading(false);
    }
  }, [apiBasePath, draftPrefix, installCase, validationMode]);

  const refreshStatus = useCallback(async () => {
    const response = await fetch(`${publicApiUrl}${apiBasePath}/status`, { cache: "no-store" });
    const body: unknown = await response.json();
    if (!response.ok) throw new Error(apiError(body, response.status));
    const parsed = validationMode
      ? coherentAuctionValidationStatusSchema.parse(body)
      : blindReplayV3StatusSchema.parse(body);
    setStatus(parsed);
    return parsed;
  }, [apiBasePath, validationMode]);

  useEffect(() => {
    const task = window.setTimeout(() => {
      void (async () => {
        try {
          const progress = await refreshStatus();
          const alias = progress.current_case_alias
            ?? progress.practice_cases.find((item) => !item.completed)?.case_alias;
          if (alias) await loadCase(alias);
          else setLoading(false);
        } catch (reason) {
          setError(reason instanceof Error ? reason.message : "Unable to initialize V3 replay.");
          setLoading(false);
        }
      })();
    }, 0);
    return () => window.clearTimeout(task);
  }, [loadCase, refreshStatus]);

  useEffect(() => {
    if (!replay) return;
    window.localStorage.setItem(`${draftPrefix}:${replay.case_alias}`, JSON.stringify({ drawings, positionPlan, timeframe, orderType, annotation }));
  }, [annotation, draftPrefix, drawings, orderType, positionPlan, replay, timeframe]);

  const applyMutation = useCallback((body: unknown, forceServerOrder = false) => {
    const parsed = validationMode
      ? coherentAuctionValidationMutationSchema.parse(body)
      : blindReplayV3MutationSchema.parse(body);
    setStatus(parsed.progress);
    if (parsed.case) {
      installCase(parsed.case, parsed.progress, forceServerOrder || parsed.case.live_order?.state === "ACTIVE_POSITION");
    } else {
      setReplay(null);
      setStarted(false);
      setPlaying(false);
      setDrawings([]);
      setPositionPlan(null);
      setDialogOpen(false);
    }
    return parsed;
  }, [installCase, validationMode]);

  const mutate = useCallback(async (path: string, payload: Record<string, unknown>, forceServerOrder = false) => {
    setBusy(true);
    setError(null);
    try {
      const response = await fetch(`${publicApiUrl}${apiBasePath}${path}`, {
        method: "POST",
        headers: { "Content-Type": "application/json", "Idempotency-Key": randomKey() },
        body: JSON.stringify(payload),
      });
      const body: unknown = await response.json();
      if (!response.ok) throw new Error(apiError(body, response.status));
      return applyMutation(body, forceServerOrder);
    } catch (reason) {
      setPlaying(false);
      setError(reason instanceof Error ? reason.message : "Replay mutation failed.");
      return null;
    } finally {
      setBusy(false);
    }
  }, [apiBasePath, applyMutation]);

  const advance = useCallback(async (minutes: 1 | 5 | 15) => {
    if (!replay || !started || dialogOpen || advanceInFlight.current) return;
    if (replay.cursor_at >= replay.end_at) {
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
  }, [dialogOpen, mutate, replay, started, timeframe]);

  useEffect(() => {
    if (!playing || busy || !replay || dialogOpen || !started) return;
    const timer = window.setTimeout(() => void advance(stepInterval), Math.max(75, 850 / speed));
    return () => window.clearTimeout(timer);
  }, [advance, busy, dialogOpen, playing, replay, speed, started, stepInterval]);

  const startReplay = useCallback(async () => {
    if (!replay) return;
    const target = `${replay.trading_date_utc}T${initialTime}:00Z`;
    if (target < replay.start_at || target >= replay.end_at) {
      setError("Initial time must fall inside the selected UTC practice day.");
      return;
    }
    if (target > replay.cursor_at) {
      const result = await mutate("/skip", {
        case_alias: replay.case_alias,
        expected_cursor_at: replay.cursor_at,
        target_cursor_at: target,
        reason: "User-selected initial replay time; interval logged as not observed in real time.",
        selected_timeframe: timeframe,
      });
      if (!result) return;
    }
    setStarted(true);
  }, [initialTime, mutate, replay, timeframe]);

  const skipToMinute = useCallback(async (targetMinute: number, reason: string) => {
    if (!replay || replay.live_order) return;
    const target = timestampAt(replay.start_at, targetMinute);
    if (target <= replay.cursor_at) {
      setError("That session boundary is already revealed. Camera movement remains available without rewinding the replay cursor.");
      return;
    }
    await mutate("/skip", {
      case_alias: replay.case_alias,
      expected_cursor_at: replay.cursor_at,
      target_cursor_at: target > replay.end_at ? replay.end_at : target,
      reason,
      selected_timeframe: timeframe,
    });
  }, [mutate, replay, timeframe]);

  const submitOrAmend = useCallback(async () => {
    if (!replay || !positionPlan) return;
    const live = replay.live_order;
    if (live?.state === "ACTIVE_POSITION") {
      setError("ENTRY, SL, TP, direction, and reasoning are immutable after fill.");
      return;
    }
    if (!live) {
      const blockers = annotationBlockers(annotation, validationMode);
      if (blockers.length) {
        setError(`Complete: ${blockers.join(", ")}.`);
        return;
      }
      const result = await mutate("/orders", {
        case_alias: replay.case_alias,
        expected_cursor_at: replay.cursor_at,
        selected_timeframe: timeframe,
        client_visible_state_sha256: replay.visible_state_sha256,
        direction: positionPlan.direction,
        order_type: orderType,
        entry: positionPlan.entryIndex,
        stop: positionPlan.stopIndex,
        target: positionPlan.targetIndex,
        expiry_at: replay.end_at,
        drawings: serverDrawings(drawings, replay.start_at),
        annotation: {
          thesis: annotation.thesis,
          fundamental_direction: annotation.fundamentalDirection,
          dominant_driver: annotation.dominantDriver,
          higher_timeframe_context: annotation.higherTimeframeContext,
          session_liquidity_context: annotation.sessionLiquidityContext,
          entry_trigger: annotation.entryTrigger,
          invalidation_logic: annotation.invalidationLogic,
          target_logic: annotation.targetLogic,
          event_risk: annotation.eventRisk,
          confidence: annotation.confidence,
          ...(validationMode ? {
            auction_family: annotation.auctionFamily,
            controlling_h4_state: annotation.controllingH4State,
            location_assessment: annotation.locationAssessment,
            stop_basis: annotation.stopBasis,
            target_timeframe: "H1_OPPOSING_LIQUIDITY",
            macro_override_reason: annotation.macroOverrideReason,
          } : {}),
        },
      }, true);
      if (!result) return;
    } else {
      const result = await mutate(`/orders/${encodeURIComponent(live.order_id)}/amend`, {
        case_alias: replay.case_alias,
        expected_cursor_at: replay.cursor_at,
        client_visible_state_sha256: replay.visible_state_sha256,
        order_type: orderType,
        entry: positionPlan.entryIndex,
        stop: positionPlan.stopIndex,
        target: positionPlan.targetIndex,
        expiry_at: replay.end_at,
        drawings: serverDrawings(drawings, replay.start_at),
        reason: amendReason || null,
      }, true);
      if (!result) return;
    }
    setDialogOpen(false);
    setAmendReason("");
    setPlaying(true);
  }, [amendReason, annotation, drawings, mutate, orderType, positionPlan, replay, timeframe, validationMode]);

  const cancelPending = useCallback(async () => {
    const live = replay?.live_order;
    if (!replay || !live || live.state !== "PENDING_ORDER") return;
    const result = await mutate(`/orders/${encodeURIComponent(live.order_id)}/cancel`, {
      case_alias: replay.case_alias,
      expected_cursor_at: replay.cursor_at,
      client_visible_state_sha256: replay.visible_state_sha256,
      reason: amendReason || "Cancelled by the user at the current replay cursor.",
    });
    if (result) {
      setDialogOpen(false);
      setAmendReason("");
    }
  }, [amendReason, mutate, replay]);

  const closeActive = useCallback(async () => {
    const live = replay?.live_order;
    if (!replay || !live || live.state !== "ACTIVE_POSITION") return;
    if (manualCloseReason.trim().length < 3) {
      setError("State why you are closing the active position now.");
      return;
    }
    const result = await mutate(`/orders/${encodeURIComponent(live.order_id)}/manual-close`, {
      case_alias: replay.case_alias,
      expected_cursor_at: replay.cursor_at,
      client_visible_state_sha256: replay.visible_state_sha256,
      reason: manualCloseReason,
    });
    if (result) setManualCloseReason("");
  }, [manualCloseReason, mutate, replay]);

  const onPositionPlan = useCallback((plan: ReplayV2PositionPlan | null) => {
    if (!plan) {
      setPositionPlan(null);
      return null;
    }
    const riskDistance = Math.abs(plan.entryIndex - plan.stopIndex);
    if (!(riskDistance > 0)) return "ENTRY and SL must be different prices.";
    if (riskDistance > 50) return "This stop is too wide for one whole ounce under the frozen $50 risk cap.";
    setPositionPlan(plan);
    return null;
  }, []);

  const chartBars = useMemo(() => replay
    ? (replay.charts[timeframe] ?? []).map((bar) => toChartBar(bar, replay.start_at))
    : [], [replay, timeframe]);
  const cursorMinute = replay ? minuteOffset(replay.start_at, replay.cursor_at) : 0;
  const maximumMinute = replay ? minuteOffset(replay.start_at, replay.end_at) : 1440;

  const levels = useMemo(() => {
    if (!replay) return [];
    const output: Array<{ code: string; level: number }> = [];
    const sessions = Array.isArray(replay.context.sessions) ? replay.context.sessions.map(object) : [];
    for (const session of sessions) {
      const known = Array.isArray(session.known_levels) ? session.known_levels.map(object) : [];
      for (const level of known) {
        if (typeof level.code === "string" && typeof level.price === "number") output.push({ code: level.code, level: level.price });
      }
    }
    const structure = object(replay.context.structure);
    const frames = Array.isArray(structure.timeframes) ? structure.timeframes.map(object) : [];
    for (const frame of frames) {
      const detections = Array.isArray(frame.detections) ? frame.detections.map(object) : [];
      for (const detection of detections.slice(-4)) {
        if (typeof detection.kind === "string" && typeof detection.price_level === "number") output.push({ code: detection.kind, level: detection.price_level });
      }
    }
    return output.slice(-24);
  }, [replay]);

  const chartEvents = useMemo<ReplayV2ChartEvent[]>(() => {
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
    if (!replay) return [];
    if (validationMode && "session_code" in replay) {
      return [{
        code: replay.session_code,
        startMinute: 0,
        endMinute: maximumMinute,
        color: replay.session_code === "LONDON" ? "#1976D2" : "#D97706",
      }];
    }
    const date = new Date(`${replay.trading_date_utc}T12:00:00Z`);
    const londonSummer = date < new Date("2021-10-31T01:00:00Z");
    const newYorkSummer = date < new Date("2021-11-07T06:00:00Z");
    const londonStart = londonSummer ? 420 : 480;
    const londonEnd = londonSummer ? 960 : 1020;
    const newYorkStart = newYorkSummer ? 720 : 780;
    const newYorkEnd = newYorkSummer ? 1260 : 1320;
    return [
      { code: "ASIA", startMinute: 0, endMinute: londonStart, color: "#7E57C2" },
      { code: "LONDON", startMinute: londonStart, endMinute: londonEnd, color: "#1976D2" },
      { code: "LONDON_NY_OVERLAP", startMinute: newYorkStart, endMinute: londonEnd, color: "#00897B" },
      { code: "NEW_YORK", startMinute: newYorkStart, endMinute: newYorkEnd, color: "#D97706" },
      { code: "ROLLOVER", startMinute: newYorkEnd, endMinute: Math.min(1440, newYorkEnd + 60), color: "#B4232F" },
    ];
  }, [maximumMinute, replay, validationMode]);

  const lastOrder = replay?.order_history.at(-1) ?? null;
  const lifecycle: ReplayV2PositionLifecycle = replay?.live_order?.state === "PENDING_ORDER"
    ? "PENDING_ENTRY"
    : replay?.live_order?.state === "ACTIVE_POSITION"
      ? "ACTIVE"
      : lastOrder?.state === "EXPIRED" ? "EXPIRED"
        : lastOrder?.state === "CANCELLED" ? "CANCELLED"
          : lastOrder?.state === "RESOLVED"
            ? (display(object(lastOrder.resolution).state) as ReplayV2PositionLifecycle)
            : "EDITABLE";
  const activeLocked = replay?.live_order?.state === "ACTIVE_POSITION";
  const actualFill = replay?.live_order?.fill ?? lastOrder?.fill;
  const actualFillPrice = typeof object(actualFill).actual_price === "number"
    ? Number(object(actualFill).actual_price)
    : null;
  const playBlocker = !started
    ? "Choose an initial time and click Start replay."
    : dialogOpen ? "Close or confirm the annotation dialog first."
      : busy ? "The previous event is being durably sealed."
        : replay?.cursor_at === replay?.end_at ? "This practice day is complete."
          : null;

  const annotationDialog = dialogOpen && replay && positionPlan ? (
    <div aria-label="Trade annotation dialog" className="fixed inset-0 z-[100] grid place-items-center bg-black/35 p-3">
      <div className="max-h-[94vh] w-full max-w-4xl overflow-y-auto rounded-2xl border border-[#D1D4DC] bg-white p-5 text-[#131722] shadow-2xl">
        <div className="flex items-start justify-between gap-3">
          <div>
            <p className="text-[10px] font-bold uppercase tracking-[0.18em] text-[#787B86]">{replay.live_order ? "Pending-order amendment" : "Original immutable trade annotation"}</p>
            <h3 className="mt-1 text-xl font-semibold">{positionPlan.direction} · {orderType} · ENTRY {positionPlan.entryIndex.toFixed(2)} · SL {positionPlan.stopIndex.toFixed(2)} · TP {positionPlan.targetIndex.toFixed(2)}</h3>
            <p className="mt-1 text-xs text-[#5D606B]">Cursor remains sealed at {utcLabel(replay.cursor_at)}. Opening or cancelling this dialog reveals no candle.</p>
          </div>
          <button aria-label="Cancel annotation and return to chart" className="chart-command" onClick={() => setDialogOpen(false)} type="button">Cancel</button>
        </div>
        {replay.live_order ? (
          <div className="mt-4 rounded-xl border border-amber-300 bg-amber-50 p-4">
            <p className="text-sm font-semibold">The original reasoning is immutable. This action changes only the still-pending order geometry.</p>
            <textarea aria-label="Pending amendment reason" className="mt-3 min-h-24 w-full rounded border border-[#D1D4DC] bg-white p-3 text-sm" onChange={(event) => setAmendReason(event.target.value)} placeholder="Optional: why are you amending the pending order now?" value={amendReason} />
          </div>
        ) : (
          <div className="mt-4 grid gap-3 md:grid-cols-2">
            <label className="md:col-span-2 text-xs font-semibold">Why this trade exists now
              <textarea aria-label="Why this trade exists now" className="mt-1 min-h-24 w-full rounded border border-[#D1D4DC] p-3 text-sm font-normal" onChange={(event) => setAnnotation((value) => ({ ...value, thesis: event.target.value }))} value={annotation.thesis} />
            </label>
            <label className="text-xs font-semibold">Fundamental direction
              <select aria-label="Fundamental direction" className="mt-1 w-full rounded border border-[#D1D4DC] p-2 text-sm font-normal" onChange={(event) => setAnnotation((value) => ({ ...value, fundamentalDirection: event.target.value }))} value={annotation.fundamentalDirection}>
                <option>BULLISH</option><option>BEARISH</option><option>NEUTRAL_OR_CONFLICTED</option><option>UNKNOWN</option>
              </select>
            </label>
            <label className="text-xs font-semibold">Dominant driver<input aria-label="Dominant driver" className="mt-1 w-full rounded border border-[#D1D4DC] p-2 text-sm font-normal" onChange={(event) => setAnnotation((value) => ({ ...value, dominantDriver: event.target.value }))} value={annotation.dominantDriver} /></label>
            {validationMode ? <>
              <label className="text-xs font-semibold">Auction family
                <select aria-label="Auction family" className="mt-1 w-full rounded border border-[#D1D4DC] p-2 text-sm font-normal" onChange={(event) => setAnnotation((value) => ({ ...value, auctionFamily: event.target.value as Annotation["auctionFamily"] }))} value={annotation.auctionFamily}>
                  <option value="CONTINUATION_WITH_ROOM">Continuation with room</option>
                  <option value="RANGE_ROTATION">Range rotation</option>
                  <option value="STRUCTURAL_REPAIR">Structural repair</option>
                  <option value="OTHER_EXPLICIT">Other — explain explicitly</option>
                </select>
              </label>
              <label className="text-xs font-semibold">Controlling H4 state
                <select aria-label="Controlling H4 state" className="mt-1 w-full rounded border border-[#D1D4DC] p-2 text-sm font-normal" onChange={(event) => setAnnotation((value) => ({ ...value, controllingH4State: event.target.value as Annotation["controllingH4State"] }))} value={annotation.controllingH4State}>
                  <option>PULLBACK_WITH_ROOM</option><option>BALANCE_LOWER_ROTATION</option><option>BALANCE_UPPER_ROTATION</option><option>UPPER_BOUNDARY_EXTENDED</option><option>LOWER_BOUNDARY_EXTENDED</option><option>BEARISH_DAMAGE</option><option>BULLISH_DAMAGE</option><option>ACCEPTED_REPAIR</option><option>UNKNOWN</option>
                </select>
              </label>
              <label className="text-xs font-semibold">Higher-timeframe location
                <select aria-label="Higher-timeframe location" className="mt-1 w-full rounded border border-[#D1D4DC] p-2 text-sm font-normal" onChange={(event) => setAnnotation((value) => ({ ...value, locationAssessment: event.target.value as Annotation["locationAssessment"] }))} value={annotation.locationAssessment}>
                  <option>DISCOUNT</option><option>MIDRANGE</option><option>PREMIUM</option><option>AT_SUPPORT</option><option>AT_RESISTANCE</option><option>UNKNOWN</option>
                </select>
              </label>
              <label className="text-xs font-semibold">Structural stop basis
                <select aria-label="Structural stop basis" className="mt-1 w-full rounded border border-[#D1D4DC] p-2 text-sm font-normal" onChange={(event) => setAnnotation((value) => ({ ...value, stopBasis: event.target.value as Annotation["stopBasis"] }))} value={annotation.stopBasis}>
                  <option>ACTIVE_M15_PROTECTED_SWING</option><option>CONTROLLING_M15_RANGE_BOUNDARY</option><option>POST_REPAIR_ORIGIN</option><option>OTHER_EXPLICIT</option>
                </select>
              </label>
              <label className="text-xs font-semibold">Target timeframe<input aria-label="Target timeframe" className="mt-1 w-full rounded border border-[#D1D4DC] bg-[#F4F5F7] p-2 text-sm font-normal" readOnly value="H1_OPPOSING_LIQUIDITY" /></label>
              <label className="text-xs font-semibold">Macro alignment / override reason<input aria-label="Macro override reason" className="mt-1 w-full rounded border border-[#D1D4DC] p-2 text-sm font-normal" onChange={(event) => setAnnotation((value) => ({ ...value, macroOverrideReason: event.target.value }))} value={annotation.macroOverrideReason} /></label>
            </> : null}
            <label className="text-xs font-semibold">Higher-timeframe structure and location<textarea aria-label="Higher-timeframe context" className="mt-1 min-h-20 w-full rounded border border-[#D1D4DC] p-2 text-sm font-normal" onChange={(event) => setAnnotation((value) => ({ ...value, higherTimeframeContext: event.target.value }))} value={annotation.higherTimeframeContext} /></label>
            <label className="text-xs font-semibold">Session and liquidity context<textarea aria-label="Session and liquidity context" className="mt-1 min-h-20 w-full rounded border border-[#D1D4DC] p-2 text-sm font-normal" onChange={(event) => setAnnotation((value) => ({ ...value, sessionLiquidityContext: event.target.value }))} value={annotation.sessionLiquidityContext} /></label>
            <label className="text-xs font-semibold">Observable entry trigger<textarea aria-label="Observable entry trigger" className="mt-1 min-h-20 w-full rounded border border-[#D1D4DC] p-2 text-sm font-normal" onChange={(event) => setAnnotation((value) => ({ ...value, entryTrigger: event.target.value }))} value={annotation.entryTrigger} /></label>
            <label className="text-xs font-semibold">Invalidation logic<textarea aria-label="Invalidation logic" className="mt-1 min-h-20 w-full rounded border border-[#D1D4DC] p-2 text-sm font-normal" onChange={(event) => setAnnotation((value) => ({ ...value, invalidationLogic: event.target.value }))} value={annotation.invalidationLogic} /></label>
            <label className="text-xs font-semibold">Target logic<textarea aria-label="Target logic" className="mt-1 min-h-20 w-full rounded border border-[#D1D4DC] p-2 text-sm font-normal" onChange={(event) => setAnnotation((value) => ({ ...value, targetLogic: event.target.value }))} value={annotation.targetLogic} /></label>
            <label className="text-xs font-semibold">Event risk<input aria-label="Event risk" className="mt-1 w-full rounded border border-[#D1D4DC] p-2 text-sm font-normal" onChange={(event) => setAnnotation((value) => ({ ...value, eventRisk: event.target.value }))} value={annotation.eventRisk} /></label>
            <label className="text-xs font-semibold">Confidence · {annotation.confidence}%<input aria-label="Trade confidence" className="mt-2 w-full" max="100" min="0" onChange={(event) => setAnnotation((value) => ({ ...value, confidence: Number(event.target.value) }))} type="range" value={annotation.confidence} /></label>
          </div>
        )}
        <div className="mt-5 flex flex-wrap justify-end gap-2">
          {replay.live_order?.state === "PENDING_ORDER" ? <button className="rounded-lg border border-red-300 bg-red-50 px-4 py-2 text-sm font-semibold text-red-800" onClick={() => void cancelPending()} type="button">Cancel pending order</button> : null}
          <button className="chart-command" onClick={() => setDialogOpen(false)} type="button">Return to editable chart</button>
          <button aria-label={replay.live_order ? "Confirm pending amendment and resume" : "Confirm order and resume"} className="rounded-lg bg-[#087363] px-5 py-2 text-sm font-bold text-white disabled:opacity-40" disabled={busy} onClick={() => void submitOrAmend()} type="button">
            {replay.live_order ? "Confirm Amendment & Resume" : "Confirm Order & Resume"}
          </button>
        </div>
      </div>
    </div>
  ) : null;

  if (loading) return <div className="mt-8 rounded-xl border border-[#D1D4DC] bg-white p-8 text-sm">Verifying V3 practice streams and isolated ledger…</div>;
  if (!replay) {
    return (
      <section className="mt-8 rounded-xl border border-[#D1D4DC] bg-white p-6">
        <h3 className="text-xl font-semibold">{status?.practice_completed === status?.practice_total ? "All replay sessions complete" : "Replay session completed"}</h3>
        <p className="mt-2 text-sm text-[#5D606B]">{status?.practice_completed ?? 0} / {status?.practice_total ?? (validationMode ? 50 : 20)} sessions complete. Aggregate results, 2025, and 2026 remain locked.</p>
        {status && status.practice_completed < status.practice_total ? <button className="mt-4 rounded-lg bg-[#2962FF] px-4 py-2 text-sm font-bold text-white" onClick={() => {
          const alias = status.practice_cases.find((item) => !item.completed)?.case_alias;
          if (alias) void loadCase(alias, false);
          }} type="button">Open next replay session</button> : null}
        {error ? <p className="mt-3 text-sm text-red-700">{error}</p> : null}
      </section>
    );
  }

  return (
    <div className="mt-6 space-y-3" data-testid="annotated-replay-v3-lab">
      <section className="rounded-xl border border-[#D1D4DC] bg-white p-3 shadow-sm">
        <div className="flex flex-wrap items-end gap-3">
          <label className="text-[10px] font-bold uppercase text-[#787B86]">{validationMode ? "Blind session" : "Practice date"}
            <select aria-label="Select practice date" className="mt-1 block rounded border border-[#D1D4DC] px-3 py-2 text-sm font-normal text-[#131722]" disabled={Boolean(status?.current_case_alias)} onChange={(event) => {
              setSelectedAlias(event.target.value);
              void loadCase(event.target.value);
            }} value={selectedAlias}>
              {status?.practice_cases.filter((item) => !item.completed || item.active).map((item) => <option key={item.case_alias} value={item.case_alias}>{item.trading_date_utc} · {"session_code" in item ? `${item.session_code} · ` : ""}{item.case_alias}</option>)}
            </select>
          </label>
          <label className="text-[10px] font-bold uppercase text-[#787B86]">Initial UTC time
            <input aria-label="Initial replay time" className="mt-1 block rounded border border-[#D1D4DC] px-3 py-2 text-sm font-normal" disabled={started} onChange={(event) => setInitialTime(event.target.value)} step="60" type="time" value={initialTime} />
          </label>
          <button aria-label="Start selected historical replay" className="rounded-lg bg-[#2962FF] px-4 py-2 text-sm font-bold text-white disabled:opacity-35" disabled={started || busy} onClick={() => void startReplay()} type="button">Start replay</button>
          <div className="h-9 w-px bg-[#D1D4DC]" />
          <button aria-label={playing ? "Pause replay" : "Play replay"} className="rounded-lg bg-[#2962FF] px-4 py-2 text-sm font-bold text-white disabled:cursor-not-allowed disabled:opacity-35" disabled={Boolean(playBlocker) && !playing} onClick={() => setPlaying((value) => !value)} title={playing ? "Pause after the in-flight event is durably sealed." : playBlocker ?? "Play the server-controlled cursor."} type="button">{playing ? "Pause" : "▶ Play"}</button>
          {([1, 5, 15] as const).map((minutes) => <button aria-label={`Step replay ${minutes} minute${minutes === 1 ? "" : "s"}`} className="chart-command" disabled={Boolean(playBlocker)} key={minutes} onClick={() => void advance(minutes)} type="button">+{minutes}m</button>)}
          <label className="text-[10px] font-bold uppercase text-[#787B86]">Interval
            <select aria-label="Replay interval" className="ml-1 rounded border border-[#D1D4DC] p-2 text-xs" onChange={(event) => setStepInterval(Number(event.target.value) as 1 | 5 | 15)} value={stepInterval}><option value="1">1m</option><option value="5">5m</option><option value="15">15m</option></select>
          </label>
          <label className="text-[10px] font-bold uppercase text-[#787B86]">Speed
            <select aria-label="Replay speed" className="ml-1 rounded border border-[#D1D4DC] p-2 text-xs" onChange={(event) => setSpeed(Number(event.target.value) as 1 | 2 | 4 | 8)} value={speed}><option value="1">1×</option><option value="2">2×</option><option value="4">4×</option><option value="8">8×</option></select>
          </label>
          <span className="ml-auto rounded-full bg-[#EEF3FF] px-3 py-2 text-xs font-bold text-[#174EA6]">{utcLabel(replay.cursor_at)}</span>
        </div>
        <div className="mt-2 flex flex-wrap items-center gap-2">
          {replayTimeframes.map((item) => <button aria-label={`Show ${replayTimeframeLabel(item)} timeframe`} aria-pressed={timeframe === item} className={`rounded border px-2 py-1 text-[10px] font-bold ${timeframe === item ? "border-[#2962FF] bg-[#EEF3FF] text-[#174EA6]" : "border-[#D1D4DC]"}`} key={item} onClick={() => setTimeframe(item)} type="button">{replayTimeframeLabel(item)} · {replay.visible_timeframes[item]?.count ?? 0}</button>)}
          <span className="mx-1 h-6 w-px bg-[#D1D4DC]" />
          {!validationMode ? <button className="chart-command" disabled={Boolean(replay.live_order) || cursorMinute >= 480} onClick={() => void skipToMinute(480, "Advance to London session; skipped interval not observed in real time.")} type="button">Go to London</button> : null}
          {!validationMode ? <button className="chart-command" disabled={Boolean(replay.live_order) || cursorMinute >= 780} onClick={() => void skipToMinute(780, "Advance to New York session; skipped interval not observed in real time.")} type="button">Go to New York</button> : null}
          <button className="chart-command" disabled={Boolean(replay.live_order)} onClick={() => void skipToMinute(maximumMinute, validationMode ? "No valid setup; finish blind session while flat." : "Finish practice day while flat; remaining interval not observed in real time.")} type="button">{validationMode ? "No trade / finish session" : "Finish day"}</button>
          {playBlocker ? <span className="text-[10px] font-semibold text-amber-700">Control constraint: {playBlocker}</span> : <span className="text-[10px] font-semibold text-emerald-700">Replay controls available.</span>}
        </div>
      </section>

      <FundamentalTape replay={replay} />

      <div className="grid gap-3 xl:grid-cols-[minmax(0,1fr)_300px]">
        <SynchronizedReplayChart
          actualFillPrice={actualFillPrice}
          bars={chartBars}
          cursorDisplayLabel={utcLabel(replay.cursor_at)}
          cursorMinute={cursorMinute}
          drawings={drawings}
          events={chartEvents}
          formatMinuteLabel={(minute) => utcLabel(timestampAt(replay.start_at, minute), minute < 0 || minute >= maximumMinute)}
          fullscreenOverlay={annotationDialog}
          fullscreenReplayControls={{
            playing,
            advancing: busy,
            playDisabled: Boolean(playBlocker) && !playing,
            advanceDisabled: Boolean(playBlocker),
            positionReady: Boolean(positionPlan) && !activeLocked && started,
            placeButtonLabel: replay.live_order?.state === "PENDING_ORDER" ? "Review Amendment" : "Place Order",
            cursorMinute,
            maximumCursorMinute: maximumMinute,
            timeframeCounts: Object.fromEntries(replayTimeframes.map((item) => [item, replay.visible_timeframes[item]?.count ?? 0])),
            onTogglePlay: () => setPlaying((value) => !value),
            onAdvance: (minutes) => void advance(minutes),
            onTimeframeChange: setTimeframe,
            onRequestPositionDetails: () => {
              setPlaying(false);
              setDialogOpen(true);
            },
          }}
          label={timeframe}
          levels={levels}
          locked={activeLocked}
          onDrawingsChange={setDrawings}
          onPositionPlan={onPositionPlan}
          onRequestPositionDetails={() => {
            setPlaying(false);
            setDialogOpen(true);
          }}
          placeButtonLabel={replay.live_order?.state === "PENDING_ORDER" ? "Review Amendment" : "Place Order"}
          positionLifecycle={lifecycle}
          positionReady={Boolean(positionPlan) && !activeLocked && started}
          windows={windows}
        />

        <aside className="space-y-3">
          <section className="rounded-xl border border-[#D1D4DC] bg-white p-4 shadow-sm">
            <p className="text-[10px] font-bold uppercase tracking-[0.16em] text-[#787B86]">Order ticket</p>
            <label className="mt-3 block text-xs font-semibold">Order type
              <select aria-label="Order type" className="mt-1 w-full rounded border border-[#D1D4DC] p-2 text-sm" disabled={activeLocked} onChange={(event) => setOrderType(event.target.value as OrderType)} value={orderType}><option>MARKET</option><option>LIMIT</option><option>STOP</option></select>
            </label>
            {positionPlan ? (
              <div className="mt-3 space-y-1 rounded-lg bg-[#F8F9FB] p-3 text-xs">
                <p className="font-bold">{positionPlan.direction} · {lifecycle.replaceAll("_", " ")}</p>
                <p>ENTRY {positionPlan.entryIndex.toFixed(2)}</p><p className="text-red-700">SL {positionPlan.stopIndex.toFixed(2)}</p><p className="text-emerald-700">TP {positionPlan.targetIndex.toFixed(2)}</p>
                <p>R:R {(Math.abs(positionPlan.targetIndex - positionPlan.entryIndex) / Math.abs(positionPlan.entryIndex - positionPlan.stopIndex)).toFixed(2)}</p>
                <p>Frozen planned risk ≤ $50 · whole ounces</p>
                {replay.live_order ? <p>Quantity {replay.live_order.quantity_ounces} oz · planned ${replay.live_order.risk_usd.toFixed(2)}</p> : null}
              </div>
            ) : <p className="mt-3 rounded bg-[#F8F9FB] p-3 text-xs text-[#5D606B]">Choose Long or Short on the chart, then click ENTRY, SL, and TP. Replay remains available while the plan is unsubmitted.</p>}
            {activeLocked ? (
              <div className="mt-3 rounded-lg border border-red-200 bg-red-50 p-3">
                <p className="text-xs font-bold text-red-800">Filled: ENTRY, SL, TP, and original reasoning are locked.</p>
                <textarea aria-label="Manual close reason" className="mt-2 min-h-20 w-full rounded border border-red-200 bg-white p-2 text-xs" onChange={(event) => setManualCloseReason(event.target.value)} placeholder="Why close now?" value={manualCloseReason} />
                <button className="mt-2 w-full rounded bg-red-700 px-3 py-2 text-xs font-bold text-white" onClick={() => void closeActive()} type="button">Close Position Now</button>
              </div>
            ) : null}
            {replay.live_order?.state === "PENDING_ORDER" ? <button className="mt-3 w-full rounded border border-amber-400 bg-amber-50 px-3 py-2 text-xs font-bold text-amber-900" onClick={() => { setPlaying(false); setDialogOpen(true); }} type="button">Amend or cancel pending order</button> : null}
          </section>

          <section className="rounded-xl border border-[#D1D4DC] bg-white p-4 text-xs shadow-sm">
            <p className="text-[10px] font-bold uppercase tracking-[0.16em] text-[#787B86]">Immutable audit</p>
            <p className="mt-2">Orders today: {replay.order_history.length}</p>
            <p>Ledger head: {status?.event_ledger_head_sha256.slice(0, 12)}…</p>
            <p>Research credit: {validationMode ? "HISTORICAL BLIND ROBUSTNESS" : "ZERO · PRACTICE"}</p>
            <p>Collection year {status?.collection_year}: {validationMode ? "OPEN · AGGREGATES LOCKED" : "CLOSED"}</p>
            <p>2025 / 2026: LOCKED</p>
            <p className="mt-2 rounded bg-[#FFF8E1] p-2 text-[#6B5200]">{validationMode ? "No aggregate hit rate, PnL, or failure feedback is released before all 50 sessions are sealed." : "No edge, aggregate win rate, or PnL is calculated during usability certification."}</p>
          </section>
        </aside>
      </div>
      {error ? <div className="rounded-lg border border-red-300 bg-red-50 p-3 text-sm text-red-800" role="alert">{error}</div> : null}
    </div>
  );
}
