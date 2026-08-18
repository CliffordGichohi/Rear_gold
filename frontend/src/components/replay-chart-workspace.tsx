"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { PointerEvent as ReactPointerEvent, SetStateAction } from "react";

import type { BlindReplayBar } from "@/lib/api";


export type PositionPlan = {
  direction: "LONG" | "SHORT";
  entryIndex: number;
  stopIndex: number;
  targetIndex: number;
};

export type ReplayChartEvent = {
  eventCode: string;
  name: string;
  minutesBeforeCheckpoint: number;
  importance: number | null;
  surpriseLabel: string | null;
  goldImpact: "SUPPORTIVE" | "PRESSURE" | "NEUTRAL" | null;
};

type ChartPoint = { barIndex: number; price: number };
type Tool =
  | "SELECT"
  | "CROSSHAIR"
  | "TREND_LINE"
  | "HORIZONTAL_LINE"
  | "FIBONACCI"
  | "LONG_POSITION"
  | "SHORT_POSITION"
  | "RULER";
type PositionDrawing = {
  id: string;
  type: "POSITION";
  direction: "LONG" | "SHORT";
  entry: ChartPoint;
  stop: ChartPoint;
  target: ChartPoint;
  validationError: string | null;
};
type Drawing =
  | { id: string; type: "TREND_LINE"; start: ChartPoint; end: ChartPoint }
  | { id: string; type: "RULER"; start: ChartPoint; end: ChartPoint }
  | { id: string; type: "HORIZONTAL_LINE"; point: ChartPoint }
  | { id: string; type: "FIBONACCI"; start: ChartPoint; end: ChartPoint }
  | PositionDrawing;
type PositionEditor = { entry: string; stop: string; target: string };

type Props = {
  bars: BlindReplayBar[];
  events?: ReplayChartEvent[];
  levels?: Array<{ code: string; level: number }>;
  label: string;
  m15AtrIndex?: number;
  showToolbar?: boolean;
  autoPlay?: boolean;
  positionOverlay?: PositionPlan | null;
  tradeRemark?: string;
  tradeBlockers?: string[];
  onTradeRemarkChange?: (remark: string) => void;
  onPositionPlan?: (plan: PositionPlan) => string | null;
  onPositionPlanCleared?: () => void;
  onPlaceArmedTrade?: () => string | null;
  onCheckpointReadyChange?: (ready: boolean) => void;
};

const palette = {
  background: "#FFFFFF",
  grid: "#E6E8EC",
  axis: "#5D606B",
  bullish: "#089981",
  bearish: "#F23645",
  checkpoint: "#2962FF",
  level: "#D89B00",
  drawing: "#7E57C2",
  fib: "#6C5CE7",
  measurement: "#1976D2",
  selected: "#131722",
};

const fibRatios = [0, 0.236, 0.382, 0.5, 0.618, 0.786, 1] as const;

const toolDefinitions: Array<{ tool: Tool; icon: string; label: string; instruction: string }> = [
  { tool: "SELECT", icon: "↖", label: "Select drawing", instruction: "Click a drawing to inspect or delete it. Delete/Backspace removes the selected drawing." },
  { tool: "CROSSHAIR", icon: "+", label: "Crosshair", instruction: "Move over a candle to inspect its relative bar and normalized price." },
  { tool: "TREND_LINE", icon: "／", label: "Trend line", instruction: "Click two points to connect swing structure." },
  { tool: "HORIZONTAL_LINE", icon: "—", label: "Horizontal level", instruction: "Click once to mark support, resistance or liquidity." },
  { tool: "FIBONACCI", icon: "Fib", label: "Fibonacci retracement", instruction: "Click the impulse origin, then the impulse extreme." },
  { tool: "LONG_POSITION", icon: "L", label: "Long position", instruction: "Mark three levels: entry, stop below entry, then take-profit above entry." },
  { tool: "SHORT_POSITION", icon: "S", label: "Short position", instruction: "Mark three levels: entry, stop above entry, then take-profit below entry." },
  { tool: "RULER", icon: "↔", label: "Measure", instruction: "Click two points to measure bars, index displacement and ATR distance." },
];

const nextDrawingId = () => crypto.randomUUID();

function ToolButton({
  active,
  disabled = false,
  icon,
  label,
  onClick,
}: {
  active: boolean;
  disabled?: boolean;
  icon: string;
  label: string;
  onClick: () => void;
}) {
  return (
    <button
      aria-label={label}
      aria-pressed={active}
      className={`grid h-10 min-w-10 place-items-center rounded-md border px-2 text-xs font-semibold transition disabled:cursor-not-allowed disabled:opacity-35 ${
        active
          ? "border-[#2962FF] bg-[#EAF0FF] text-[#1848CC]"
          : "border-transparent bg-white text-[#434651] hover:border-[#D1D4DC] hover:bg-[#F4F5F7]"
      }`}
      disabled={disabled}
      onClick={onClick}
      title={label}
      type="button"
    >
      {icon}
    </button>
  );
}

function relativeAxisLabel(bar: BlindReplayBar | undefined, timeframe: string) {
  if (!bar) return "";
  if (typeof bar.minutes_after_checkpoint === "number") {
    return bar.minutes_after_checkpoint === 0 ? "T" : `T+${bar.minutes_after_checkpoint}m`;
  }
  if (typeof bar.ordinal !== "number") return "relative";
  if (bar.ordinal === 0) return "checkpoint";
  const sign = bar.ordinal < 0 ? "−" : "+";
  return `T${sign}${Math.abs(bar.ordinal)} ${timeframe.toUpperCase()} bars`;
}

function drawingPrices(drawing: Drawing) {
  if (drawing.type === "HORIZONTAL_LINE") return [drawing.point.price];
  if (drawing.type === "POSITION") return [drawing.entry.price, drawing.stop.price, drawing.target.price];
  return [drawing.start.price, drawing.end.price];
}

function timeframeMinutes(label: string) {
  const normalized = label.toLowerCase();
  if (normalized === "1m") return 1;
  if (normalized === "5m") return 5;
  if (normalized === "15m") return 15;
  if (normalized === "1h") return 60;
  if (normalized === "4h") return 240;
  if (normalized === "1d") return 1_440;
  if (normalized === "1w") return 10_080;
  return null;
}

export function ReplayChartWorkspace({
  bars,
  events = [],
  levels = [],
  label,
  m15AtrIndex,
  showToolbar = true,
  autoPlay = false,
  positionOverlay = null,
  tradeRemark = "",
  tradeBlockers = [],
  onTradeRemarkChange,
  onPositionPlan,
  onPositionPlanCleared,
  onPlaceArmedTrade,
  onCheckpointReadyChange,
}: Props) {
  const width = 1180;
  const height = showToolbar ? 560 : 410;
  const padding = { top: 22, right: 82, bottom: 50, left: 18 };
  const svgRef = useRef<SVGSVGElement | null>(null);
  const [tool, setTool] = useState<Tool>("CROSSHAIR");
  const [drawingsByTimeframe, setDrawingsByTimeframe] = useState<Record<string, Drawing[]>>({});
  const [draftByTimeframe, setDraftByTimeframe] = useState<Record<string, ChartPoint[]>>({});
  const [hover, setHover] = useState<ChartPoint | null>(null);
  const [selectedDrawingId, setSelectedDrawingId] = useState<string | null>(null);
  const [positionEditor, setPositionEditor] = useState<PositionEditor | null>(null);
  const [tradeArmed, setTradeArmed] = useState(false);
  const [toolMessage, setToolMessage] = useState<string>(toolDefinitions[1].instruction);
  const [viewportBarsByTimeframe, setViewportBarsByTimeframe] = useState<Record<string, number>>({});
  const [rightSpaceByTimeframe, setRightSpaceByTimeframe] = useState<Record<string, number>>({});
  const [replayPosition, setReplayPosition] = useState<number | null>(() => autoPlay && bars.length ? 1 : null);
  const [playing, setPlaying] = useState(() => autoPlay && bars.length > 1);
  const dragState = useRef<{ clientX: number; initialRightSpace: number; moved: boolean } | null>(null);
  const suppressNextClick = useRef(false);

  const drawings = useMemo(() => drawingsByTimeframe[label] ?? [], [drawingsByTimeframe, label]);
  const draft = useMemo(() => draftByTimeframe[label] ?? [], [draftByTimeframe, label]);
  const setDrawings = useCallback((update: SetStateAction<Drawing[]>) => {
    setDrawingsByTimeframe((current) => {
      const existing = current[label] ?? [];
      const next = typeof update === "function"
        ? (update as (value: Drawing[]) => Drawing[])(existing)
        : update;
      return { ...current, [label]: next };
    });
  }, [label]);
  const setDraft = useCallback((update: SetStateAction<ChartPoint[]>) => {
    setDraftByTimeframe((current) => {
      const existing = current[label] ?? [];
      const next = typeof update === "function"
        ? (update as (value: ChartPoint[]) => ChartPoint[])(existing)
        : update;
      return { ...current, [label]: next };
    });
  }, [label]);

  const maximumViewportBars = Math.max(20, bars.length);
  const defaultViewportBars = Math.min(maximumViewportBars, 120);
  const viewportBars = Math.max(12, Math.min(
    viewportBarsByTimeframe[label] ?? defaultViewportBars,
    maximumViewportBars,
  ));
  const maximumRightSpace = Math.max(2, Math.floor(viewportBars * 0.6));
  const rightSpace = Math.max(2, Math.min(
    rightSpaceByTimeframe[label] ?? Math.max(6, Math.round(viewportBars * 0.12)),
    maximumRightSpace,
  ));
  const revealedCount = replayPosition === null
    ? bars.length
    : Math.max(1, Math.min(replayPosition, bars.length));
  const currentBarIndex = Math.max(0, revealedCount - 1);
  const viewportStartIndex = currentBarIndex - (viewportBars - rightSpace - 1);
  const viewportEndIndex = viewportStartIndex + viewportBars - 1;
  const visibleIndexedBars = useMemo(() => bars
    .map((bar, index) => ({ bar, index }))
    .filter(({ index }) => index < revealedCount && index >= viewportStartIndex && index <= viewportEndIndex), [
      bars,
      revealedCount,
      viewportEndIndex,
      viewportStartIndex,
    ]);
  const visibleBars = useMemo(() => visibleIndexedBars.map(({ bar }) => bar), [visibleIndexedBars]);
  const sourceStartIndex = visibleIndexedBars[0]?.index ?? 0;
  const visibleLastIndex = visibleIndexedBars.at(-1)?.index ?? currentBarIndex;
  const atCheckpoint = replayPosition === null || replayPosition >= bars.length;
  const executionToolSelected = tool === "LONG_POSITION" || tool === "SHORT_POSITION";
  const selectedDrawing = drawings.find((drawing) => drawing.id === selectedDrawingId) ?? null;
  const positionDrawing = drawings.find((drawing): drawing is PositionDrawing => drawing.type === "POSITION") ?? null;

  useEffect(() => {
    onCheckpointReadyChange?.(atCheckpoint);
  }, [atCheckpoint, onCheckpointReadyChange]);

  useEffect(() => {
    if (!playing || replayPosition === null) return;
    const timer = window.setInterval(() => {
      setReplayPosition((current) => {
        if (current === null || current >= bars.length) {
          setPlaying(false);
          return bars.length;
        }
        return current + 1;
      });
    }, 240);
    return () => window.clearInterval(timer);
  }, [bars.length, playing, replayPosition]);

  const deleteDrawing = useCallback((drawingId: string) => {
    const drawing = drawings.find((candidate) => candidate.id === drawingId);
    setDrawings((current) => current.filter((candidate) => candidate.id !== drawingId));
    setSelectedDrawingId(null);
    setPositionEditor(null);
    setTradeArmed(false);
    if (drawing?.type === "POSITION") onPositionPlanCleared?.();
    setToolMessage(drawing?.type === "POSITION" ? "Position drawing and its unsubmitted execution plan were cleared." : "Selected drawing deleted.");
  }, [drawings, onPositionPlanCleared, setDrawings]);

  useEffect(() => {
    if (!showToolbar) return;
    function handleKeyDown(event: KeyboardEvent) {
      const target = event.target as HTMLElement | null;
      if (target?.matches("input, textarea, select")) return;
      if ((event.key === "Delete" || event.key === "Backspace") && selectedDrawingId) {
        event.preventDefault();
        deleteDrawing(selectedDrawingId);
      } else if (event.key === "Escape") {
        setDraft([]);
        setSelectedDrawingId(null);
        setPositionEditor(null);
      }
    }
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [deleteDrawing, selectedDrawingId, setDraft, showToolbar]);

  const overlayDrawing: PositionDrawing | null = positionOverlay ? {
    id: "locked-position-overlay",
    type: "POSITION",
    direction: positionOverlay.direction,
    entry: { barIndex: sourceStartIndex, price: positionOverlay.entryIndex },
    stop: { barIndex: sourceStartIndex, price: positionOverlay.stopIndex },
    target: { barIndex: sourceStartIndex, price: positionOverlay.targetIndex },
    validationError: null,
  } : null;
  const scaleValues = [
    ...visibleBars.flatMap((bar) => [bar.low, bar.high]),
    ...drawings.flatMap(drawingPrices),
    ...(overlayDrawing ? drawingPrices(overlayDrawing) : []),
    ...draft.map((point) => point.price),
  ];
  const rawMinimum = scaleValues.length ? Math.min(...scaleValues) : 99;
  const rawMaximum = scaleValues.length ? Math.max(...scaleValues) : 101;
  const rawSpan = Math.max(rawMaximum - rawMinimum, 0.0001);
  const pricePadding = Math.max(rawSpan * 0.08, 0.00005);
  const minimum = rawMinimum - pricePadding;
  const maximum = rawMaximum + pricePadding;
  const span = Math.max(maximum - minimum, 0.0001);
  const chartWidth = width - padding.left - padding.right;
  const chartHeight = height - padding.top - padding.bottom;
  const slot = chartWidth / Math.max(1, viewportBars);
  const bodyWidth = Math.max(1.5, Math.min(9, slot * 0.64));
  const y = (value: number) => padding.top + ((maximum - value) / span) * chartHeight;
  const x = (barIndex: number) => padding.left + slot * (barIndex - viewportStartIndex + 0.5);
  const visibleLevels = levels.filter((level) => level.level >= minimum && level.level <= maximum);
  const levelsAbove = levels.filter((level) => level.level > maximum);
  const levelsBelow = levels.filter((level) => level.level < minimum);
  const timeframeLength = timeframeMinutes(label);
  const visibleEvents = timeframeLength === null ? [] : events.flatMap((event) => {
    const eventBarIndex = bars.length - 1 - event.minutesBeforeCheckpoint / timeframeLength;
    if (eventBarIndex > currentBarIndex || eventBarIndex < viewportStartIndex || eventBarIndex > viewportEndIndex) return [];
    return [{ ...event, eventBarIndex }];
  });

  const clampPoint = (event: ReactPointerEvent<SVGSVGElement>): ChartPoint | null => {
    const svg = svgRef.current;
    if (!svg || visibleBars.length === 0) return null;
    const bounds = svg.getBoundingClientRect();
    const localX = ((event.clientX - bounds.left) / bounds.width) * width;
    const localY = ((event.clientY - bounds.top) / bounds.height) * height;
    if (
      localX < padding.left ||
      localX > width - padding.right ||
      localY < padding.top ||
      localY > height - padding.bottom
    ) return null;
    const viewportBarIndex = viewportStartIndex + Math.round((localX - padding.left) / slot - 0.5);
    const barIndex = Math.max(0, Math.min(visibleLastIndex, viewportBarIndex));
    const price = maximum - ((localY - padding.top) / chartHeight) * span;
    return { barIndex, price };
  };

  function selectTool(next: Tool) {
    if (!atCheckpoint && (next === "LONG_POSITION" || next === "SHORT_POSITION")) {
      setToolMessage("Return to the certified checkpoint before drawing an executable Long or Short position.");
      return;
    }
    setTool(next);
    setDraft([]);
    setSelectedDrawingId(null);
    setPositionEditor(null);
    setToolMessage(toolDefinitions.find((item) => item.tool === next)?.instruction ?? "");
  }

  function selectDrawing(drawing: Drawing) {
    setSelectedDrawingId(drawing.id);
    setTool("SELECT");
    setDraft([]);
    setPositionEditor(drawing.type === "POSITION" ? {
      entry: drawing.entry.price.toFixed(4),
      stop: drawing.stop.price.toFixed(4),
      target: drawing.target.price.toFixed(4),
    } : null);
    setToolMessage(`${drawing.type.replaceAll("_", " ")} selected. Use Delete selected or press Delete/Backspace.`);
  }

  function storePosition(
    direction: "LONG" | "SHORT",
    entry: ChartPoint,
    stop: ChartPoint,
    target: ChartPoint,
    existingId?: string,
  ) {
    const directionValid = direction === "LONG"
      ? stop.price < entry.price && target.price > entry.price
      : stop.price > entry.price && target.price < entry.price;
    if (!directionValid) {
      setToolMessage(direction === "LONG"
        ? "Invalid long geometry: SL must be below entry and TP above entry. Click the TP again."
        : "Invalid short geometry: SL must be above entry and TP below entry. Click the TP again.");
      return false;
    }
    onPositionPlanCleared?.();
    const validationError = onPositionPlan?.({
      direction,
      entryIndex: entry.price,
      stopIndex: stop.price,
      targetIndex: target.price,
    }) ?? null;
    const id = existingId ?? nextDrawingId();
    const position: PositionDrawing = { id, type: "POSITION", direction, entry, stop, target, validationError };
    setDrawingsByTimeframe((current) => {
      const withoutPositions = Object.fromEntries(
        Object.entries(current).map(([timeframe, timeframeDrawings]) => [
          timeframe,
          timeframeDrawings.filter((drawing) => drawing.type !== "POSITION"),
        ]),
      );
      return {
        ...withoutPositions,
        [label]: [...(withoutPositions[label] ?? []), position],
      };
    });
    setSelectedDrawingId(id);
    setPositionEditor({ entry: entry.price.toFixed(4), stop: stop.price.toFixed(4), target: target.price.toFixed(4) });
    setTradeArmed(false);
    setDraft([]);
    setTool("SELECT");
    setToolMessage(validationError
      ? `Position is visible but not executable: ${validationError}`
      : `${direction === "LONG" ? "Long" : "Short"} entry, SL and TP are mapped to the decision form. Add your remark and evidence, then arm it.`);
    return true;
  }

  function finishPosition(points: ChartPoint[], direction: "LONG" | "SHORT") {
    const entry = points[0];
    const stop = points[1];
    const target = points[2];
    if (!storePosition(direction, entry, stop, target)) setDraft(points.slice(0, 2));
  }

  function handleChartClick(event: ReactPointerEvent<SVGSVGElement>) {
    if (suppressNextClick.current) {
      suppressNextClick.current = false;
      return;
    }
    if (!showToolbar) return;
    if (!atCheckpoint && executionToolSelected) {
      setToolMessage("Replay annotations are allowed, but executable Long/Short plans remain locked until the certified checkpoint.");
      return;
    }
    const point = clampPoint(event);
    if (!point || tool === "CROSSHAIR" || tool === "SELECT") return;
    if (tool === "HORIZONTAL_LINE") {
      const drawing: Drawing = { id: nextDrawingId(), type: "HORIZONTAL_LINE", point };
      setDrawings((current) => [...current, drawing]);
      selectDrawing(drawing);
      return;
    }
    const points = [...draft, point];
    if (tool === "LONG_POSITION" || tool === "SHORT_POSITION") {
      if (points.length < 3) {
        setDraft(points);
        setToolMessage(points.length === 1
          ? "ENTRY marked. Now click the structural SL."
          : "SL marked. Now click the TP / known-liquidity target.");
      } else {
        finishPosition(points, tool === "LONG_POSITION" ? "LONG" : "SHORT");
      }
      return;
    }
    if (points.length < 2) {
      setDraft(points);
      setToolMessage("First point marked. Click the second point.");
      return;
    }
    const drawingType = tool as "TREND_LINE" | "FIBONACCI" | "RULER";
    const drawing = { id: nextDrawingId(), type: drawingType, start: points[0], end: points[1] } as Drawing;
    setDrawings((current) => [...current, drawing]);
    setDraft([]);
    selectDrawing(drawing);
  }

  function applyPositionEditor() {
    if (!positionDrawing || !positionEditor) return;
    const entry = Number(positionEditor.entry);
    const stop = Number(positionEditor.stop);
    const target = Number(positionEditor.target);
    if (![entry, stop, target].every(Number.isFinite)) {
      setToolMessage("Entry, SL and TP must all be valid normalized numbers.");
      return;
    }
    storePosition(
      positionDrawing.direction,
      { ...positionDrawing.entry, price: entry },
      { ...positionDrawing.stop, price: stop },
      { ...positionDrawing.target, price: target },
      positionDrawing.id,
    );
  }

  function setViewportBars(next: number) {
    const bounded = Math.max(12, Math.min(maximumViewportBars, next));
    setViewportBarsByTimeframe((current) => ({ ...current, [label]: bounded }));
    setRightSpaceByTimeframe((current) => ({
      ...current,
      [label]: Math.min(current[label] ?? rightSpace, Math.max(2, Math.floor(bounded * 0.6))),
    }));
  }

  function changeZoom(direction: "IN" | "OUT") {
    const next = direction === "IN"
      ? Math.floor(viewportBars / 1.35)
      : Math.ceil(viewportBars * 1.35);
    setViewportBars(next);
    setToolMessage("Zoom changed. Replay, drawings and the unsubmitted plan were preserved.");
  }

  function changeRightSpace(delta: number) {
    setRightSpaceByTimeframe((current) => ({
      ...current,
      [label]: Math.max(2, Math.min(maximumRightSpace, (current[label] ?? rightSpace) + delta)),
    }));
    setToolMessage(delta > 0
      ? "Chart shifted left. The blank area is future canvas only; unrevealed price bars remain hidden."
      : "Chart shifted right. Replay position and revealed bars were preserved.");
  }

  function resetCamera() {
    setViewportBarsByTimeframe((current) => ({ ...current, [label]: defaultViewportBars }));
    setRightSpaceByTimeframe((current) => ({ ...current, [label]: Math.max(6, Math.round(defaultViewportBars * 0.12)) }));
    setToolMessage("Chart camera reset around the current replay candle. Replay position was preserved.");
  }

  function handlePointerDown(event: ReactPointerEvent<SVGSVGElement>) {
    if (!showToolbar || tool !== "CROSSHAIR" || event.button !== 0) return;
    dragState.current = { clientX: event.clientX, initialRightSpace: rightSpace, moved: false };
    event.currentTarget.setPointerCapture(event.pointerId);
  }

  function handlePointerMove(event: ReactPointerEvent<SVGSVGElement>) {
    setHover(clampPoint(event));
    const drag = dragState.current;
    if (!drag) return;
    const svg = svgRef.current;
    if (!svg) return;
    const bounds = svg.getBoundingClientRect();
    const pixelsPerSlot = (slot / width) * bounds.width;
    const deltaSlots = Math.round((drag.clientX - event.clientX) / Math.max(1, pixelsPerSlot));
    if (Math.abs(event.clientX - drag.clientX) >= 4) drag.moved = true;
    setRightSpaceByTimeframe((current) => ({
      ...current,
      [label]: Math.max(2, Math.min(maximumRightSpace, drag.initialRightSpace + deltaSlots)),
    }));
  }

  function handlePointerUp(event: ReactPointerEvent<SVGSVGElement>) {
    const drag = dragState.current;
    if (!drag) return;
    suppressNextClick.current = drag.moved;
    dragState.current = null;
    if (event.currentTarget.hasPointerCapture(event.pointerId)) event.currentTarget.releasePointerCapture(event.pointerId);
    if (drag.moved) setToolMessage("Chart camera moved. Only already-revealed bars were repositioned; future price remains hidden.");
  }

  function startHistoryReplay() {
    setPlaying(false);
    setReplayPosition(Math.min(20, bars.length));
    setDraft([]);
    setTradeArmed(false);
    if (executionToolSelected) setTool("CROSSHAIR");
    setToolMessage("Past-only replay is active. Trend, level, Fib and ruler annotations are enabled; execution plans stay locked until the checkpoint.");
  }

  function returnToCheckpoint() {
    setPlaying(false);
    setReplayPosition(null);
    setToolMessage("Returned to the frozen decision checkpoint. Drawing and decision controls are available.");
  }

  function placeArmedTrade() {
    if (!positionDrawing || positionDrawing.validationError) return;
    if (!tradeArmed) {
      setToolMessage("Arm the completed position before placing an irreversible paper trade.");
      return;
    }
    const error = onPlaceArmedTrade?.() ?? "The paper-trade submission handler is unavailable.";
    if (error) {
      setToolMessage(error);
      return;
    }
    setToolMessage("Paper-trade submission requested through the frozen append-only decision form.");
  }

  const axisTicks = [0, 0.25, 0.5, 0.75, 1].flatMap((fraction) => {
    const index = Math.round(viewportStartIndex + (viewportBars - 1) * fraction);
    if (index < 0 || index >= revealedCount || index >= bars.length) return [];
    return [{ fraction, index, bar: bars[index] }];
  });
  const activeInstruction = toolMessage || toolDefinitions.find((item) => item.tool === tool)?.instruction;

  function renderPosition(position: PositionDrawing, selected: boolean, interactive: boolean) {
    const startX = x(Math.max(sourceStartIndex, Math.min(position.entry.barIndex, visibleLastIndex)));
    const endX = Math.min(width - padding.right, startX + Math.max(160, chartWidth * 0.22));
    const rewardTop = Math.min(y(position.entry.price), y(position.target.price));
    const rewardHeight = Math.abs(y(position.entry.price) - y(position.target.price));
    const riskTop = Math.min(y(position.entry.price), y(position.stop.price));
    const riskHeight = Math.abs(y(position.entry.price) - y(position.stop.price));
    const risk = Math.abs(position.entry.price - position.stop.price);
    const reward = Math.abs(position.target.price - position.entry.price);
    const rr = reward / Math.max(risk, 0.000001);
    const selectionStroke = selected ? palette.selected : "transparent";
    return (
      <g
        aria-label={`${position.direction.toLowerCase()} position drawing`}
        className={interactive ? "cursor-pointer" : undefined}
        data-drawing-id={position.id}
        key={position.id}
        onClick={interactive ? (event) => { event.stopPropagation(); selectDrawing(position); } : undefined}
      >
        <rect fill="#089981" fillOpacity="0.20" height={Math.max(1, rewardHeight)} stroke="#089981" strokeWidth="1.5" width={endX - startX} x={startX} y={rewardTop} />
        <rect fill="#F23645" fillOpacity="0.18" height={Math.max(1, riskHeight)} stroke="#F23645" strokeWidth="1.5" width={endX - startX} x={startX} y={riskTop} />
        <rect fill="none" height={Math.max(2, rewardHeight + riskHeight)} stroke={selectionStroke} strokeDasharray="4 3" strokeWidth="2" width={endX - startX} x={startX} y={Math.min(rewardTop, riskTop)} />
        <line stroke="#089981" strokeWidth="2" x1={startX} x2={endX} y1={y(position.target.price)} y2={y(position.target.price)} />
        <line stroke="#2962FF" strokeWidth="2.5" x1={startX} x2={endX} y1={y(position.entry.price)} y2={y(position.entry.price)} />
        <line stroke="#F23645" strokeWidth="2" x1={startX} x2={endX} y1={y(position.stop.price)} y2={y(position.stop.price)} />
        <circle cx={startX} cy={y(position.target.price)} fill="#FFFFFF" r="4" stroke="#089981" strokeWidth="2" />
        <circle cx={startX} cy={y(position.entry.price)} fill="#FFFFFF" r="4" stroke="#2962FF" strokeWidth="2" />
        <circle cx={startX} cy={y(position.stop.price)} fill="#FFFFFF" r="4" stroke="#F23645" strokeWidth="2" />
        <rect fill="#087363" height="18" rx="3" width="122" x={endX - 122} y={y(position.target.price) - 19} />
        <text fill="#FFFFFF" fontSize="10" textAnchor="end" x={endX - 5} y={y(position.target.price) - 6}>TP {position.target.price.toFixed(3)} · +{rr.toFixed(2)}R</text>
        <rect fill="#2962FF" height="18" rx="3" width="132" x={endX - 132} y={y(position.entry.price) - 9} />
        <text fill="#FFFFFF" fontSize="10" textAnchor="end" x={endX - 5} y={y(position.entry.price) + 4}>{position.direction} ENTRY {position.entry.price.toFixed(3)}</text>
        <rect fill="#B4232F" height="18" rx="3" width="126" x={endX - 126} y={y(position.stop.price) + 1} />
        <text fill="#FFFFFF" fontSize="10" textAnchor="end" x={endX - 5} y={y(position.stop.price) + 14}>SL {position.stop.price.toFixed(3)} · risk $50</text>
        {position.validationError ? (
          <text fill="#B4232F" fontSize="10" fontWeight="700" x={startX + 5} y={Math.min(rewardTop, riskTop) - 6}>NON-EXECUTABLE</text>
        ) : null}
      </g>
    );
  }

  return (
    <div className="overflow-hidden rounded-xl border border-[#D1D4DC] bg-white shadow-sm">
      {showToolbar ? (
        <div className="flex flex-wrap items-center justify-between gap-2 border-b border-[#E6E8EC] bg-white px-3 py-2">
          <div className="flex flex-wrap gap-1" aria-label="Chart drawing tools" role="toolbar">
            {toolDefinitions.map((definition) => (
              <ToolButton
                active={tool === definition.tool}
                disabled={!atCheckpoint && (definition.tool === "LONG_POSITION" || definition.tool === "SHORT_POSITION")}
                icon={definition.icon}
                key={definition.tool}
                label={definition.label}
                onClick={() => selectTool(definition.tool)}
              />
            ))}
            <span className="mx-1 w-px bg-[#E6E8EC]" />
            <ToolButton active={false} icon="↶" label="Undo last drawing" onClick={() => {
              const last = drawings.at(-1);
              if (last) deleteDrawing(last.id);
            }} disabled={!drawings.length} />
            <ToolButton active={false} icon="⌫" label="Delete selected drawing" onClick={() => {
              if (selectedDrawingId) deleteDrawing(selectedDrawingId);
            }} disabled={!selectedDrawingId} />
            <ToolButton active={false} icon="×" label="Clear all drawings" onClick={() => {
              setDrawings([]);
              setDraft([]);
              setSelectedDrawingId(null);
              setPositionEditor(null);
              setTradeArmed(false);
              onPositionPlanCleared?.();
              setToolMessage("All client-local drawings and the unsubmitted chart plan were cleared.");
            }} disabled={!drawings.length && !draft.length} />
            <ToolButton active={false} icon="＋" label="Zoom in" onClick={() => changeZoom("IN")} />
            <ToolButton active={false} icon="−" label="Zoom out" onClick={() => changeZoom("OUT")} />
            <ToolButton active={false} icon="←" label="Move chart left" onClick={() => changeRightSpace(Math.max(2, Math.round(viewportBars * 0.08)))} />
            <ToolButton active={false} icon="→" label="Move chart right" onClick={() => changeRightSpace(-Math.max(2, Math.round(viewportBars * 0.08)))} />
            <ToolButton active={false} icon="◎" label="Reset chart camera" onClick={resetCamera} />
          </div>
          <div className="flex flex-wrap items-center gap-1" aria-label="Visible history replay controls">
            <button className="rounded-md border border-[#D1D4DC] bg-white px-3 py-2 text-xs font-semibold text-[#131722] hover:bg-[#F4F5F7]" onClick={startHistoryReplay} type="button">◀ Replay history</button>
            {replayPosition !== null ? (
              <>
                <button aria-label={playing ? "Pause replay" : "Play replay"} className="rounded-md border border-[#D1D4DC] px-3 py-2 text-xs" onClick={() => setPlaying((current) => !current)} type="button">{playing ? "Ⅱ" : "▶"}</button>
                <button aria-label="Step one candle" className="rounded-md border border-[#D1D4DC] px-3 py-2 text-xs" disabled={replayPosition >= bars.length} onClick={() => setReplayPosition((current) => Math.min(bars.length, (current ?? 0) + 1))} type="button">▶|</button>
                <button className="rounded-md bg-[#2962FF] px-3 py-2 text-xs font-semibold text-white" onClick={returnToCheckpoint} type="button">Return to checkpoint</button>
              </>
            ) : null}
          </div>
        </div>
      ) : null}

      {showToolbar ? (
        <div className={`flex flex-wrap items-center justify-between gap-2 border-b px-4 py-2 text-xs ${atCheckpoint ? "border-[#E6E8EC] bg-[#F8F9FB] text-[#5D606B]" : "border-[#F0B90B] bg-[#FFF8DB] text-[#6B5200]"}`}>
          <span><strong className="text-[#131722]">{toolDefinitions.find((item) => item.tool === tool)?.label}:</strong> {activeInstruction}</span>
          <span>{atCheckpoint ? `${bars.length} completed ${label.toUpperCase()} bars · decision checkpoint` : `Replay ${revealedCount}/${bars.length} · decision locking disabled`}</span>
        </div>
      ) : null}

      <svg
        aria-label={`${label} normalized candlestick chart`}
        className={`h-auto w-full ${tool === "CROSSHAIR" ? "cursor-grab active:cursor-grabbing" : !atCheckpoint && executionToolSelected ? "cursor-not-allowed" : "cursor-crosshair"}`}
        data-revealed-bars={revealedCount}
        data-right-space-bars={rightSpace}
        data-testid="blind-replay-chart"
        onClick={handleChartClick}
        onPointerDown={handlePointerDown}
        onPointerLeave={() => { if (!dragState.current) setHover(null); }}
        onPointerMove={handlePointerMove}
        onPointerUp={handlePointerUp}
        ref={svgRef}
        role="img"
        viewBox={`0 0 ${width} ${height}`}
      >
        <rect fill={palette.background} height={height} width={width} />
        {[0, 0.25, 0.5, 0.75, 1].map((fraction) => {
          const columnX = padding.left + fraction * chartWidth;
          return <line key={`v-${fraction}`} stroke={palette.grid} x1={columnX} x2={columnX} y1={padding.top} y2={height - padding.bottom} />;
        })}
        {[0, 0.2, 0.4, 0.6, 0.8, 1].map((fraction) => {
          const value = maximum - fraction * span;
          const rowY = padding.top + fraction * chartHeight;
          return (
            <g key={`h-${fraction}`}>
              <line stroke={palette.grid} x1={padding.left} x2={width - padding.right} y1={rowY} y2={rowY} />
              <text fill={palette.axis} fontSize="11" x={width - padding.right + 9} y={rowY + 4}>{value.toFixed(3)}</text>
            </g>
          );
        })}
        {visibleLevels.map((level) => (
          <g key={`${level.code}-${level.level}`}>
            <line stroke={palette.level} strokeDasharray="7 5" strokeOpacity="0.78" x1={padding.left} x2={width - padding.right} y1={y(level.level)} y2={y(level.level)} />
            <text fill={palette.level} fontSize="10" textAnchor="end" x={width - padding.right - 5} y={y(level.level) - 4}>{level.code.replaceAll("_", " ")}</text>
          </g>
        ))}
        {levelsAbove.length ? (
          <text fill={palette.level} fontSize="9" fontWeight="700" textAnchor="end" x={width - padding.right - 5} y={padding.top + 11}>
            ↑ {levelsAbove.map((level) => level.code.replaceAll("_", " ")).join(" · ")}
          </text>
        ) : null}
        {levelsBelow.length ? (
          <text fill={palette.level} fontSize="9" fontWeight="700" textAnchor="end" x={width - padding.right - 5} y={height - padding.bottom - 6}>
            ↓ {levelsBelow.map((level) => level.code.replaceAll("_", " ")).join(" · ")}
          </text>
        ) : null}
        {visibleIndexedBars.map(({ bar, index }) => {
          const candleX = x(index);
          const rising = bar.close >= bar.open;
          const openY = y(bar.open);
          const closeY = y(bar.close);
          const color = rising ? palette.bullish : palette.bearish;
          return (
            <g data-bar-index={index} key={`${index}-${bar.ordinal ?? bar.minutes_after_checkpoint ?? index}`}>
              <line stroke={color} x1={candleX} x2={candleX} y1={y(bar.high)} y2={y(bar.low)} />
              <rect fill={color} height={Math.max(1.4, Math.abs(closeY - openY))} width={bodyWidth} x={candleX - bodyWidth / 2} y={Math.min(openY, closeY)} />
            </g>
          );
        })}

        <g pointerEvents="none">
          <line
            stroke={atCheckpoint ? palette.checkpoint : "#8A6200"}
            strokeDasharray="4 4"
            strokeWidth="1.5"
            x1={x(currentBarIndex)}
            x2={x(currentBarIndex)}
            y1={padding.top}
            y2={height - padding.bottom}
          />
          <rect
            fill={atCheckpoint ? palette.checkpoint : "#8A6200"}
            height="17"
            rx="3"
            width={atCheckpoint ? 72 : 76}
            x={Math.max(padding.left, Math.min(width - padding.right - (atCheckpoint ? 72 : 76), x(currentBarIndex) - 36))}
            y={padding.top + 3}
          />
          <text
            fill="#FFFFFF"
            fontSize="9"
            fontWeight="700"
            textAnchor="middle"
            x={Math.max(padding.left + (atCheckpoint ? 36 : 38), Math.min(width - padding.right - (atCheckpoint ? 36 : 38), x(currentBarIndex)))}
            y={padding.top + 15}
          >{atCheckpoint ? "CHECKPOINT" : "REPLAY NOW"}</text>
        </g>

        {drawings.map((drawing) => {
          const selected = drawing.id === selectedDrawingId;
          const color = selected ? palette.selected : palette.drawing;
          if (drawing.type === "POSITION") return renderPosition(drawing, selected, true);
          if (drawing.type === "HORIZONTAL_LINE") {
            return (
              <g className="cursor-pointer" key={drawing.id} onClick={(event) => { event.stopPropagation(); selectDrawing(drawing); }}>
                <line stroke="transparent" strokeWidth="14" x1={padding.left} x2={width - padding.right} y1={y(drawing.point.price)} y2={y(drawing.point.price)} />
                <line stroke={color} strokeDasharray="6 4" strokeWidth={selected ? 2.5 : 1.5} x1={padding.left} x2={width - padding.right} y1={y(drawing.point.price)} y2={y(drawing.point.price)} />
              </g>
            );
          }
          if (drawing.type === "TREND_LINE") {
            return (
              <g className="cursor-pointer" key={drawing.id} onClick={(event) => { event.stopPropagation(); selectDrawing(drawing); }}>
                <line stroke="transparent" strokeWidth="14" x1={x(drawing.start.barIndex)} x2={x(drawing.end.barIndex)} y1={y(drawing.start.price)} y2={y(drawing.end.price)} />
                <line stroke={color} strokeWidth={selected ? 3 : 2} x1={x(drawing.start.barIndex)} x2={x(drawing.end.barIndex)} y1={y(drawing.start.price)} y2={y(drawing.end.price)} />
              </g>
            );
          }
          if (drawing.type === "FIBONACCI") {
            const fromX = Math.min(x(drawing.start.barIndex), x(drawing.end.barIndex));
            const toX = Math.max(x(drawing.start.barIndex), x(drawing.end.barIndex));
            return (
              <g className="cursor-pointer" key={drawing.id} onClick={(event) => { event.stopPropagation(); selectDrawing(drawing); }}>
                {fibRatios.map((ratio) => {
                  const price = drawing.start.price + (drawing.end.price - drawing.start.price) * ratio;
                  return (
                    <g key={ratio}>
                      <rect fill={ratio >= 0.382 && ratio <= 0.618 ? "#EEEAFE" : "transparent"} height="16" opacity="0.48" width={toX - fromX} x={fromX} y={y(price) - 8} />
                      <line stroke={selected ? palette.selected : palette.fib} strokeOpacity="0.82" strokeWidth={selected ? 2 : 1} x1={fromX} x2={toX} y1={y(price)} y2={y(price)} />
                      <text fill={palette.fib} fontSize="10" x={fromX + 4} y={y(price) - 3}>{ratio}</text>
                    </g>
                  );
                })}
              </g>
            );
          }
          const barsApart = Math.abs(drawing.end.barIndex - drawing.start.barIndex);
          const delta = drawing.end.price - drawing.start.price;
          const atr = m15AtrIndex && m15AtrIndex > 0 ? delta / m15AtrIndex : null;
          return (
            <g className="cursor-pointer" key={drawing.id} onClick={(event) => { event.stopPropagation(); selectDrawing(drawing); }}>
              <line stroke={selected ? palette.selected : palette.measurement} strokeDasharray="5 4" strokeWidth={selected ? 3 : 2} x1={x(drawing.start.barIndex)} x2={x(drawing.end.barIndex)} y1={y(drawing.start.price)} y2={y(drawing.end.price)} />
              <rect fill="#E8F2FF" height="36" rx="4" width="150" x={Math.min(x(drawing.start.barIndex), x(drawing.end.barIndex))} y={Math.min(y(drawing.start.price), y(drawing.end.price)) - 40} />
              <text fill="#174EA6" fontSize="10" x={Math.min(x(drawing.start.barIndex), x(drawing.end.barIndex)) + 7} y={Math.min(y(drawing.start.price), y(drawing.end.price)) - 25}>{barsApart} bars · {delta >= 0 ? "+" : ""}{delta.toFixed(4)}</text>
              <text fill="#174EA6" fontSize="10" x={Math.min(x(drawing.start.barIndex), x(drawing.end.barIndex)) + 7} y={Math.min(y(drawing.start.price), y(drawing.end.price)) - 12}>{atr === null ? "ATR unavailable" : `${atr.toFixed(2)} M15 ATR`}</text>
            </g>
          );
        })}

        {overlayDrawing ? renderPosition(overlayDrawing, false, false) : null}

        {draft.length && (tool === "LONG_POSITION" || tool === "SHORT_POSITION") ? (
          <g pointerEvents="none">
            <line stroke="#2962FF" strokeDasharray="5 4" strokeWidth="2" x1={padding.left} x2={width - padding.right} y1={y(draft[0].price)} y2={y(draft[0].price)} />
            <circle cx={x(draft[0].barIndex)} cy={y(draft[0].price)} fill="#FFFFFF" r="5" stroke="#2962FF" strokeWidth="2" />
            <text fill="#2962FF" fontSize="11" fontWeight="700" x={x(draft[0].barIndex) + 8} y={y(draft[0].price) - 7}>ENTRY</text>
            {draft[1] ? (
              <>
                <rect fill="#F23645" fillOpacity="0.16" height={Math.abs(y(draft[0].price) - y(draft[1].price))} stroke="#F23645" strokeDasharray="4 3" width={Math.max(140, chartWidth * 0.18)} x={x(draft[0].barIndex)} y={Math.min(y(draft[0].price), y(draft[1].price))} />
                <line stroke="#F23645" strokeWidth="2" x1={padding.left} x2={width - padding.right} y1={y(draft[1].price)} y2={y(draft[1].price)} />
                <circle cx={x(draft[1].barIndex)} cy={y(draft[1].price)} fill="#FFFFFF" r="5" stroke="#F23645" strokeWidth="2" />
                <text fill="#B4232F" fontSize="11" fontWeight="700" x={x(draft[1].barIndex) + 8} y={y(draft[1].price) - 7}>SL</text>
                {hover ? (
                  <>
                    <rect fill="#089981" fillOpacity="0.16" height={Math.abs(y(draft[0].price) - y(hover.price))} stroke="#089981" strokeDasharray="4 3" width={Math.max(140, chartWidth * 0.18)} x={x(draft[0].barIndex)} y={Math.min(y(draft[0].price), y(hover.price))} />
                    <line stroke="#089981" strokeDasharray="5 4" strokeWidth="2" x1={padding.left} x2={width - padding.right} y1={y(hover.price)} y2={y(hover.price)} />
                    <text fill="#087363" fontSize="11" fontWeight="700" x={x(draft[0].barIndex) + 8} y={y(hover.price) - 7}>TP preview</text>
                  </>
                ) : null}
              </>
            ) : hover ? (
              <line stroke="#F23645" strokeDasharray="5 4" x1={padding.left} x2={width - padding.right} y1={y(hover.price)} y2={y(hover.price)} />
            ) : null}
          </g>
        ) : draft.length ? draft.map((point, index) => (
          <g key={`draft-${index}`}>
            <circle cx={x(point.barIndex)} cy={y(point.price)} fill="#2962FF" r="4" />
            <text fill="#2962FF" fontSize="10" x={x(point.barIndex) + 6} y={y(point.price) - 6}>{index + 1}</text>
          </g>
        )) : null}

        {100 >= minimum && 100 <= maximum ? (
          <>
            <line stroke={palette.checkpoint} strokeDasharray="3 4" strokeWidth="1.5" x1={padding.left} x2={width - padding.right} y1={y(100)} y2={y(100)} />
            <rect fill={palette.checkpoint} height="18" rx="3" width="48" x={width - padding.right + 4} y={y(100) - 9} />
            <text fill="#FFFFFF" fontSize="10" textAnchor="middle" x={width - padding.right + 28} y={y(100) + 4}>100.000</text>
          </>
        ) : null}

        {hover ? (
          <g pointerEvents="none">
            <line stroke="#787B86" strokeDasharray="3 3" x1={x(hover.barIndex)} x2={x(hover.barIndex)} y1={padding.top} y2={height - padding.bottom} />
            <line stroke="#787B86" strokeDasharray="3 3" x1={padding.left} x2={width - padding.right} y1={y(hover.price)} y2={y(hover.price)} />
            <rect fill="#434651" height="18" rx="3" width="52" x={width - padding.right + 2} y={y(hover.price) - 9} />
            <text fill="#FFFFFF" fontSize="10" textAnchor="middle" x={width - padding.right + 28} y={y(hover.price) + 4}>{hover.price.toFixed(3)}</text>
          </g>
        ) : null}

        <line stroke="#D1D4DC" x1={padding.left} x2={width - padding.right} y1={height - padding.bottom} y2={height - padding.bottom} />
        {visibleEvents.map((event, index) => {
          const eventX = x(event.eventBarIndex);
          const fill = event.goldImpact === "SUPPORTIVE" ? "#089981" : event.goldImpact === "PRESSURE" ? "#F23645" : "#6C5CE7";
          return (
            <g aria-label={`Released event ${event.eventCode}`} data-testid="released-event-marker" key={`${event.eventCode}-${event.minutesBeforeCheckpoint}-${index}`}>
              <line stroke={fill} strokeDasharray="2 3" strokeOpacity="0.65" x1={eventX} x2={eventX} y1={height - padding.bottom - 22} y2={height - padding.bottom} />
              <circle cx={eventX} cy={height - padding.bottom + 13} fill="#FFFFFF" r="9" stroke={fill} strokeWidth="2" />
              <text fill={fill} fontSize="7" fontWeight="800" textAnchor="middle" x={eventX} y={height - padding.bottom + 16}>{event.importance ?? "E"}</text>
              <title>{`${event.name} · released T−${event.minutesBeforeCheckpoint}m${event.surpriseLabel ? ` · ${event.surpriseLabel}` : ""}`}</title>
            </g>
          );
        })}
        {axisTicks.map(({ fraction, index, bar }) => (
          <g key={`${fraction}-${index}`}>
            <line stroke="#A8ABB3" x1={x(index)} x2={x(index)} y1={height - padding.bottom} y2={height - padding.bottom + 5} />
            <text fill={palette.axis} fontSize="10" textAnchor={fraction === 0 ? "start" : fraction === 1 ? "end" : "middle"} x={x(index)} y={height - 18}>{relativeAxisLabel(bar, label)}</text>
          </g>
        ))}
        <text fill="#8A6200" fontSize="9" textAnchor="end" x={width - padding.right} y={height - 5}>blind axis · calendar date/time hidden</text>
      </svg>

      {showToolbar ? (
        <div className="flex flex-wrap items-center justify-between gap-2 border-t border-[#E6E8EC] bg-[#F8F9FB] px-4 py-2 text-[10px] leading-4 text-[#5D606B]">
          <span><strong className="text-[#131722]">Camera:</strong> drag with Crosshair, use ←/→ for future space, and +/− for candle density.</span>
          <span><strong className="text-[#131722]">Events:</strong> released markers only · upcoming schedule not certified in this sealed source.</span>
        </div>
      ) : null}

      {showToolbar && selectedDrawing ? (
        <div className="border-t border-[#E6E8EC] bg-[#F8F9FB] p-4">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div>
              <p className="text-[10px] font-semibold uppercase tracking-[0.16em] text-[#787B86]">Selected drawing</p>
              <p className="mt-1 text-sm font-semibold text-[#131722]">{selectedDrawing.type.replaceAll("_", " ")}</p>
            </div>
            <button className="rounded-md border border-[#F3B3B8] bg-white px-3 py-2 text-xs font-semibold text-[#B4232F]" onClick={() => deleteDrawing(selectedDrawing.id)} type="button">Delete selected</button>
          </div>

          {selectedDrawing.type === "POSITION" && positionEditor ? (
            <div className="mt-4 grid gap-4 xl:grid-cols-[1fr_1fr]">
              <div>
                <div className="grid gap-3 sm:grid-cols-3">
                  {(["entry", "stop", "target"] as const).map((field) => (
                    <label className="grid gap-1 text-xs text-[#5D606B]" key={field}>
                      {field === "entry" ? "Entry index" : field === "stop" ? "Stop-loss index" : "Take-profit index"}
                      <input className="rounded-md border border-[#D1D4DC] bg-white px-3 py-2 text-[#131722] outline-none focus:border-[#2962FF] disabled:cursor-not-allowed disabled:opacity-50" disabled={!atCheckpoint} onChange={(event) => setPositionEditor((current) => current ? { ...current, [field]: event.target.value } : current)} step="0.0001" type="number" value={positionEditor[field]} />
                    </label>
                  ))}
                </div>
                <div className="mt-3 flex flex-wrap items-center gap-3">
                  <button className="rounded-md bg-[#2962FF] px-4 py-2 text-xs font-semibold text-white disabled:cursor-not-allowed disabled:opacity-40" disabled={!atCheckpoint} onClick={applyPositionEditor} type="button">Apply entry / SL / TP</button>
                  <span className={`rounded-full px-3 py-1 text-xs font-semibold ${selectedDrawing.validationError ? "bg-[#FFF0F1] text-[#B4232F]" : "bg-[#EAF8F4] text-[#087363]"}`}>{selectedDrawing.validationError ? "NON-EXECUTABLE" : "EXECUTABLE"}</span>
                </div>
                {selectedDrawing.validationError ? <p className="mt-2 text-xs leading-5 text-[#B4232F]">{selectedDrawing.validationError}</p> : null}
              </div>

              <div className="grid gap-3">
                <label className="grid gap-1 text-xs text-[#5D606B]">
                  Trade remark · why are you taking it?
                  <textarea className="min-h-20 rounded-md border border-[#D1D4DC] bg-white px-3 py-2 text-sm text-[#131722] outline-none focus:border-[#2962FF]" maxLength={1000} onChange={(event) => onTradeRemarkChange?.(event.target.value)} placeholder="Example: Fundamentals support gold; H1 support held; M15 swept and reclaimed the level." value={tradeRemark} />
                </label>
                <div className="rounded-lg border border-[#B7C7FF] bg-[#EEF3FF] p-3">
                  <label className="flex cursor-pointer items-center gap-2 text-xs font-semibold text-[#174EA6]">
                    <input checked={tradeArmed} disabled={!atCheckpoint || Boolean(selectedDrawing.validationError)} onChange={(event) => setTradeArmed(event.target.checked)} type="checkbox" />
                    Arm this append-only paper trade
                  </label>
                  {tradeBlockers.length ? (
                    <p className="mt-2 text-xs leading-5 text-[#5D606B]">Before Play: {tradeBlockers.join(" · ")}</p>
                  ) : <p className="mt-2 text-xs text-[#087363]">All frozen decision fields are complete.</p>}
                  <button className="mt-3 w-full rounded-md bg-[#089981] px-4 py-2.5 text-xs font-bold text-white disabled:cursor-not-allowed disabled:opacity-40" disabled={!tradeArmed || Boolean(selectedDrawing.validationError) || tradeBlockers.length > 0} onClick={placeArmedTrade} type="button">▶ Place armed trade &amp; play</button>
                  <p className="mt-2 text-[10px] leading-4 text-[#787B86]">Practice paths animate only after locking. Scored paths stay hidden. Arming prevents an accidental irreversible submission.</p>
                </div>
              </div>
            </div>
          ) : (
            <p className="mt-2 text-xs text-[#5D606B]">Use Delete selected or the keyboard Delete/Backspace key. Re-draw the object to change its anchors.</p>
          )}
        </div>
      ) : null}
    </div>
  );
}
