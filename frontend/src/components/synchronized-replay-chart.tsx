"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { PointerEvent as ReactPointerEvent, ReactNode } from "react";

import type { BlindReplayV2Bar } from "@/lib/api";

export const replayTimeframes = ["1w", "1d", "4h", "1h", "15m", "5m", "1m"] as const;
export type ReplayTimeframe = (typeof replayTimeframes)[number];
export function replayTimeframeLabel(timeframe: ReplayTimeframe) {
  return ({ "1w": "W1", "1d": "D1", "4h": "H4", "1h": "H1", "15m": "M15", "5m": "M5", "1m": "M1" } as const)[timeframe];
}
export type ReplayV2Tool =
  | "SELECT"
  | "CROSSHAIR"
  | "TREND_LINE"
  | "HORIZONTAL_LINE"
  | "FIBONACCI"
  | "LONG_POSITION"
  | "SHORT_POSITION"
  | "RULER";

export type ReplayV2Anchor = {
  relativeMinute: number;
  priceIndex: number;
  sourceTimeframe: ReplayTimeframe;
};

export type ReplayV2Drawing = {
  id: string;
  kind: Exclude<ReplayV2Tool, "SELECT" | "CROSSHAIR">;
  anchors: ReplayV2Anchor[];
  placedAtCursorMinute: number;
};

export type ReplayV2PositionPlan = {
  drawingId: string;
  direction: "LONG" | "SHORT";
  entryIndex: number;
  stopIndex: number;
  targetIndex: number;
};

export type ReplayV2PositionLifecycle = "EDITABLE" | "PENDING_ENTRY" | "ACTIVE" | "STOPPED" | "TARGET_HIT" | "MANUAL_CLOSE" | "TIME_EXIT" | "CANCELLED" | "EXPIRED";

export type ReplayV2ChartEvent = {
  eventCode: string;
  name: string;
  relativeMinute: number;
  surpriseLabel: string | null;
  goldImpact: "SUPPORTIVE" | "PRESSURE" | "NEUTRAL" | null;
};

export type ReplayV2FullscreenControls = {
  playing: boolean;
  advancing: boolean;
  playDisabled: boolean;
  advanceDisabled: boolean;
  cursorMinute: number;
  maximumCursorMinute: number;
  timeframeCounts: Partial<Record<ReplayTimeframe, number>>;
  onTogglePlay: () => void;
  onAdvance: (minutes: 1 | 5 | 15) => void;
  onTimeframeChange: (timeframe: ReplayTimeframe) => void;
};

type Props = {
  bars: BlindReplayV2Bar[];
  cursorMinute: number;
  drawings: ReplayV2Drawing[];
  events?: ReplayV2ChartEvent[];
  label: ReplayTimeframe;
  levels?: Array<{ code: string; level: number }>;
  locked?: boolean;
  fullscreenReplayControls?: ReplayV2FullscreenControls;
  fullscreenOverlay?: ReactNode;
  positionLifecycle?: ReplayV2PositionLifecycle;
  positionReady?: boolean;
  onDrawingsChange: (drawings: ReplayV2Drawing[]) => void;
  onFullscreenChange?: (active: boolean) => void;
  onPositionPlan: (plan: ReplayV2PositionPlan | null) => string | null;
  onRequestPositionDetails?: () => void;
  formatMinuteLabel?: (offset: number) => string;
  cursorDisplayLabel?: string;
  placeButtonLabel?: string;
  actualFillPrice?: number | null;
  windows?: Array<{
    code: string;
    startMinute: number;
    endMinute: number;
    color: string;
  }>;
};

const tools: Array<{ tool: ReplayV2Tool; icon: string; label: string; instruction: string }> = [
  { tool: "SELECT", icon: "↖", label: "Select drawing", instruction: "Select a drawing, then delete it if needed." },
  { tool: "CROSSHAIR", icon: "+", label: "Crosshair", instruction: "Inspect a completed candle and normalized price." },
  { tool: "TREND_LINE", icon: "╱", label: "Trend line", instruction: "Mark two completed-candle anchors." },
  { tool: "HORIZONTAL_LINE", icon: "—", label: "Horizontal level", instruction: "Mark support, resistance, or liquidity." },
  { tool: "FIBONACCI", icon: "Fib", label: "Fibonacci retracement", instruction: "Mark the completed impulse origin and extreme." },
  { tool: "LONG_POSITION", icon: "L", label: "Long position", instruction: "At REPLAY NOW click ENTRY, then SL and TP in either order." },
  { tool: "SHORT_POSITION", icon: "S", label: "Short position", instruction: "At REPLAY NOW click ENTRY, then SL and TP in either order." },
  { tool: "RULER", icon: "↔", label: "Measure", instruction: "Mark two points to measure time and normalized displacement." },
];

const fibRatios = [0, 0.236, 0.382, 0.5, 0.618, 0.786, 1] as const;
const width = 1180;
const height = 585;
const padding = { top: 22, right: 84, bottom: 54, left: 20 };

function nextId() {
  return typeof crypto !== "undefined" && "randomUUID" in crypto
    ? crypto.randomUUID()
    : `drawing-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

function relativeLabel(offset: number) {
  if (offset === 0) return "T0";
  return offset > 0 ? `T+${offset}m` : `T−${Math.abs(offset)}m`;
}

function positionFromDrawing(drawing: ReplayV2Drawing): ReplayV2PositionPlan | null {
  if (drawing.kind !== "LONG_POSITION" && drawing.kind !== "SHORT_POSITION") return null;
  return {
    drawingId: drawing.id,
    direction: drawing.kind === "LONG_POSITION" ? "LONG" : "SHORT",
    entryIndex: drawing.anchors[0].priceIndex,
    stopIndex: drawing.anchors[1].priceIndex,
    targetIndex: drawing.anchors[2].priceIndex,
  };
}

function normalizedPositionAnchors(
  kind: "LONG_POSITION" | "SHORT_POSITION",
  anchors: ReplayV2Anchor[],
): ReplayV2Anchor[] | null {
  if (anchors.length !== 3) return null;
  const entry = anchors[0];
  const boundaries = anchors.slice(1);
  const lower = boundaries.find((anchor) => anchor.priceIndex < entry.priceIndex);
  const upper = boundaries.find((anchor) => anchor.priceIndex > entry.priceIndex);
  if (!lower || !upper) return null;
  return kind === "LONG_POSITION"
    ? [entry, lower, upper]
    : [entry, upper, lower];
}

export function resizeReplayDrawingAnchor(
  drawing: ReplayV2Drawing,
  anchorIndex: number,
  point: ReplayV2Anchor,
): ReplayV2Drawing {
  if (anchorIndex < 0 || anchorIndex >= drawing.anchors.length) return drawing;
  const position = drawing.kind === "LONG_POSITION" || drawing.kind === "SHORT_POSITION";
  const original = drawing.anchors[anchorIndex];
  const replacement = position
    ? {
      ...point,
      // A position is placed at one decision time. Resizing a price level must
      // never drag the other levels or silently move the decision timestamp.
      relativeMinute: original.relativeMinute,
    }
    : point;
  return {
    ...drawing,
    anchors: drawing.anchors.map((anchor, index) => (
      index === anchorIndex ? replacement : anchor
    )),
  };
}

export function SynchronizedReplayChart({
  bars,
  cursorMinute,
  drawings,
  events = [],
  label,
  levels = [],
  locked = false,
  fullscreenReplayControls,
  fullscreenOverlay,
  positionLifecycle = "EDITABLE",
  positionReady = false,
  onDrawingsChange,
  onFullscreenChange,
  onPositionPlan,
  onRequestPositionDetails,
  formatMinuteLabel = relativeLabel,
  cursorDisplayLabel,
  placeButtonLabel = "Place & Play",
  actualFillPrice = null,
  windows = [],
}: Props) {
  const frameRef = useRef<HTMLDivElement | null>(null);
  const svgRef = useRef<SVGSVGElement | null>(null);
  const [tool, setTool] = useState<ReplayV2Tool>("CROSSHAIR");
  const [draft, setDraft] = useState<ReplayV2Anchor[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const draggingAnchorRef = useRef<{
    drawingId: string;
    anchorIndex: number;
    baseDrawing: ReplayV2Drawing;
  } | null>(null);
  const [hover, setHover] = useState<{ bar: BlindReplayV2Bar; price: number } | null>(null);
  const [message, setMessage] = useState(tools[1].instruction);
  const [viewportByTimeframe, setViewportByTimeframe] = useState<Record<string, number>>({});
  const [panByTimeframe, setPanByTimeframe] = useState<Record<string, number>>({});
  const [verticalPanByTimeframe, setVerticalPanByTimeframe] = useState<Record<string, number>>({});
  const [isFullscreen, setIsFullscreen] = useState(false);

  const deleteDrawing = useCallback((id: string) => {
    if (locked) return;
    const target = drawings.find((drawing) => drawing.id === id);
    onDrawingsChange(drawings.filter((drawing) => drawing.id !== id));
    if (target && (target.kind === "LONG_POSITION" || target.kind === "SHORT_POSITION")) {
      onPositionPlan(null);
    }
    setSelectedId(null);
    setMessage("Selected drawing deleted.");
  }, [drawings, locked, onDrawingsChange, onPositionPlan]);

  useEffect(() => {
    const synchronizeFullscreenState = () => {
      const active = document.fullscreenElement === frameRef.current;
      setIsFullscreen(active);
      onFullscreenChange?.(active);
    };
    document.addEventListener("fullscreenchange", synchronizeFullscreenState);
    return () => document.removeEventListener("fullscreenchange", synchronizeFullscreenState);
  }, [onFullscreenChange]);

  useEffect(() => {
    const removeSelectedDrawing = (event: KeyboardEvent) => {
      if (locked || !selectedId || (event.key !== "Backspace" && event.key !== "Delete")) return;
      const eventTarget = event.target;
      if (
        eventTarget instanceof HTMLElement
        && (eventTarget.matches("input, textarea, select") || eventTarget.isContentEditable)
      ) return;
      event.preventDefault();
      deleteDrawing(selectedId);
    };
    window.addEventListener("keydown", removeSelectedDrawing);
    return () => window.removeEventListener("keydown", removeSelectedDrawing);
  }, [deleteDrawing, locked, selectedId]);

  const maximumViewport = Math.max(20, bars.length);
  const viewport = Math.max(16, Math.min(viewportByTimeframe[label] ?? 100, maximumViewport));
  const futureSlots = Math.max(7, Math.round(viewport * 0.15));
  const totalSlots = Math.max(1, viewport + futureSlots);
  const chartWidth = width - padding.left - padding.right;
  const chartHeight = height - padding.top - padding.bottom;
  const slot = chartWidth / totalSlots;
  const bodyWidth = Math.max(1.5, Math.min(9, slot * 0.64));
  const maximumPan = Math.max(0, bars.length - viewport);
  const minimumPan = -Math.max(0, futureSlots - 2);
  const pan = Math.max(minimumPan, Math.min(panByTimeframe[label] ?? 0, maximumPan));
  const verticalPan = Math.max(-8, Math.min(verticalPanByTimeframe[label] ?? 0, 8));
  const baseStartIndex = bars.length - viewport;
  const xForIndex = (index: number) => (
    padding.left + slot * (index - baseStartIndex + 0.5 + pan)
  );
  const visibleBarRows = bars.flatMap((bar, index) => {
    const x = xForIndex(index);
    return x >= padding.left - bodyWidth && x <= width - padding.right + bodyWidth
      ? [{ bar, index, x }]
      : [];
  });
  const visibleBars = visibleBarRows.map((row) => row.bar);

  const projected = useCallback((anchor: ReplayV2Anchor) => {
    const eligible = bars.filter((bar) => bar.available_offset_minutes <= cursorMinute);
    const prior = eligible.filter((bar) => bar.close_offset_minutes <= anchor.relativeMinute);
    return prior.at(-1) ?? eligible[0] ?? null;
  }, [bars, cursorMinute]);

  const renderedDrawings = useMemo(() => drawings.flatMap((drawing) => {
    const projectedBars = drawing.anchors.map(projected);
    return projectedBars.every(Boolean) ? [{ drawing, projectedBars: projectedBars as BlindReplayV2Bar[] }] : [];
  }), [drawings, projected]);
  const incompatibleCount = drawings.length - renderedDrawings.length;

  const scalePrices = visibleBars.flatMap((bar) => [bar.low, bar.high]);
  const rawMin = scalePrices.length ? Math.min(...scalePrices) : 99;
  const rawMax = scalePrices.length ? Math.max(...scalePrices) : 101;
  const rawSpan = Math.max(rawMax - rawMin, 0.0001);
  const scaleMargin = Math.max(rawSpan * 0.08, 0.00005);
  const baseMinimum = rawMin - scaleMargin;
  const baseMaximum = rawMax + scaleMargin;
  const baseDisplaySpan = baseMaximum - baseMinimum;
  const verticalShift = verticalPan * baseDisplaySpan * 0.12;
  const minimum = baseMinimum - verticalShift;
  const maximum = baseMaximum - verticalShift;
  const span = maximum - minimum;
  const y = (price: number) => padding.top + ((maximum - price) / span) * chartHeight;
  const globalIndex = new Map(bars.map((bar, index) => [bar.bar_id, index]));
  const xForBarRaw = (bar: BlindReplayV2Bar) => {
    const index = globalIndex.get(bar.bar_id);
    return index === undefined ? null : xForIndex(index);
  };
  const xForBar = (bar: BlindReplayV2Bar) => {
    const x = xForBarRaw(bar);
    if (x === null) return null;
    return x >= padding.left - bodyWidth && x <= width - padding.right + bodyWidth ? x : null;
  };
  const replayNowX = padding.left + slot * (viewport + 0.4 + pan);
  const replayNowVisible = replayNowX >= padding.left && replayNowX <= width - padding.right;

  const updateCamera = (nextViewport: number, nextPan: number) => {
    const normalizedViewport = Math.max(16, Math.min(maximumViewport, nextViewport));
    const nextFutureSlots = Math.max(7, Math.round(normalizedViewport * 0.15));
    const nextMinimumPan = -Math.max(0, nextFutureSlots - 2);
    const nextMaximumPan = Math.max(0, bars.length - normalizedViewport);
    setViewportByTimeframe((current) => ({ ...current, [label]: normalizedViewport }));
    setPanByTimeframe((current) => ({
      ...current,
      [label]: Math.max(nextMinimumPan, Math.min(nextPan, nextMaximumPan)),
    }));
  };

  const updateVerticalPan = (next: number) => {
    setVerticalPanByTimeframe((current) => ({
      ...current,
      [label]: Math.max(-8, Math.min(next, 8)),
    }));
  };

  function selectTool(next: ReplayV2Tool) {
    if (locked) return;
    setTool(next);
    setDraft([]);
    setSelectedId(null);
    setMessage(tools.find((item) => item.tool === next)?.instruction ?? "");
  }

  function pointFromEvent(event: ReactPointerEvent<SVGSVGElement>): ReplayV2Anchor | null {
    const svg = svgRef.current;
    if (!svg || visibleBarRows.length === 0) return null;
    const bounds = svg.getBoundingClientRect();
    const localX = ((event.clientX - bounds.left) / bounds.width) * width;
    const localY = ((event.clientY - bounds.top) / bounds.height) * height;
    if (
      localX < padding.left
      || localX > width - padding.right
      || localY < padding.top
      || localY > height - padding.bottom
    ) return null;
    const source = visibleBarRows.reduce((nearest, candidate) => (
      Math.abs(candidate.x - localX) < Math.abs(nearest.x - localX) ? candidate : nearest
    )).bar;
    return {
      relativeMinute: source.close_offset_minutes,
      priceIndex: maximum - ((localY - padding.top) / chartHeight) * span,
      sourceTimeframe: label,
    };
  }

  function storeDrawing(drawing: ReplayV2Drawing) {
    if (drawing.kind === "LONG_POSITION" || drawing.kind === "SHORT_POSITION") {
      const plan = positionFromDrawing(drawing);
      if (!plan) return;
      const valid = plan.direction === "LONG"
        ? plan.stopIndex < plan.entryIndex && plan.entryIndex < plan.targetIndex
        : plan.targetIndex < plan.entryIndex && plan.entryIndex < plan.stopIndex;
      if (!valid) {
        setMessage(plan.direction === "LONG"
          ? "Invalid long: mark entry, then SL below entry, then TP above entry."
          : "Invalid short: mark entry, then SL above entry, then TP below entry.");
        setDraft(drawing.anchors.slice(0, 2));
        return;
      }
      const error = onPositionPlan(plan);
      if (error) {
        setMessage(error);
        setDraft([]);
        return;
      }
      const withoutPosition = drawings.filter((candidate) => (
        candidate.kind !== "LONG_POSITION" && candidate.kind !== "SHORT_POSITION"
      ));
      onDrawingsChange([...withoutPosition, drawing]);
      setMessage(`${plan.direction} ticket mapped at REPLAY NOW. Complete “WHY THIS TRADE NOW?” and Place & Play.`);
    } else {
      onDrawingsChange([...drawings, drawing]);
      setMessage(`${drawing.kind.replaceAll("_", " ")} saved across compatible timeframes.`);
    }
    setDraft([]);
    setSelectedId(drawing.id);
    setTool("SELECT");
  }

  function handleClick(event: ReactPointerEvent<SVGSVGElement>) {
    if (locked) return;
    if (tool === "SELECT" || tool === "CROSSHAIR") return;
    const point = pointFromEvent(event);
    if (!point) return;
    const isPosition = tool === "LONG_POSITION" || tool === "SHORT_POSITION";
    if (isPosition && !replayNowVisible) {
      setMessage("REPLAY NOW is outside the camera. Press Reset before placing a position.");
      return;
    }
    const anchoredPoint = isPosition
      ? { ...point, relativeMinute: cursorMinute }
      : point;
    if (tool === "HORIZONTAL_LINE") {
      storeDrawing({
        id: nextId(),
        kind: tool,
        anchors: [anchoredPoint],
        placedAtCursorMinute: cursorMinute,
      });
      return;
    }
    const points = [...draft, anchoredPoint];
    const required = isPosition ? 3 : 2;
    if (points.length < required) {
      setDraft(points);
      setMessage(isPosition
        ? points.length === 1
          ? "ENTRY marked. Click either SL or TP."
          : "One boundary marked. Click the opposite side of ENTRY to complete the position."
        : "First anchor marked. Click the second completed-candle anchor.");
      return;
    }
    const normalized = isPosition
      ? normalizedPositionAnchors(tool as "LONG_POSITION" | "SHORT_POSITION", points)
      : points;
    if (!normalized) {
      setDraft([points[0]]);
      setMessage("SL and TP must be on opposite sides of ENTRY. ENTRY was retained; mark both boundaries again.");
      return;
    }
    storeDrawing({
      id: nextId(),
      kind: tool as ReplayV2Drawing["kind"],
      anchors: normalized,
      placedAtCursorMinute: cursorMinute,
    });
  }

  function resizeDrawingAnchor(point: ReplayV2Anchor) {
    const drag = draggingAnchorRef.current;
    if (locked || !drag) return;
    const target = drag.baseDrawing;
    const position = target.kind === "LONG_POSITION" || target.kind === "SHORT_POSITION";
    const resized = resizeReplayDrawingAnchor(target, drag.anchorIndex, point);
    if (position) {
      const plan = positionFromDrawing(resized);
      if (!plan) return;
      const valid = plan.direction === "LONG"
        ? plan.stopIndex < plan.entryIndex && plan.entryIndex < plan.targetIndex
        : plan.targetIndex < plan.entryIndex && plan.entryIndex < plan.stopIndex;
      if (!valid) {
        setMessage("Resize blocked: SL and TP must remain on opposite sides of ENTRY.");
        return;
      }
      const error = onPositionPlan(plan);
      if (error) {
        setMessage(error);
        return;
      }
      setMessage(`${plan.direction} position resized. It remains editable until Done & Play.`);
    } else {
      setMessage(`${target.kind.replaceAll("_", " ")} resized across synchronized timeframes.`);
    }
    onDrawingsChange(drawings.map((drawing) => drawing.id === target.id ? resized : drawing));
  }

  async function toggleFullscreen() {
    const frame = frameRef.current;
    if (!frame) return;
    try {
      if (document.fullscreenElement === frame) {
        await document.exitFullscreen();
      } else {
        await frame.requestFullscreen();
      }
    } catch {
      setMessage("Full screen was blocked by the browser. Allow full-screen access and try again.");
    }
  }

  const hoveredOffset = hover?.bar.close_offset_minutes;
  const cameraStep = Math.max(1, Math.round(viewport * 0.1));
  const isPositionTool = tool === "LONG_POSITION" || tool === "SHORT_POSITION";
  const positionDraft = isPositionTool && draft[0]
    ? (() => {
      const direction = tool === "LONG_POSITION" ? "LONG" : "SHORT";
      const entry = draft[0].priceIndex;
      const boundary = draft[1]?.priceIndex;
      const defaultRisk = Math.max(span * 0.12, 0.0001);
      let stop = direction === "LONG" ? entry - defaultRisk : entry + defaultRisk;
      let target = direction === "LONG" ? entry + defaultRisk * 2 : entry - defaultRisk * 2;
      if (boundary !== undefined) {
        if (direction === "LONG" && boundary < entry) {
          stop = boundary;
          target = entry + Math.abs(entry - boundary) * 2;
        } else if (direction === "LONG") {
          target = boundary;
          stop = entry - Math.abs(boundary - entry) / 2;
        } else if (boundary > entry) {
          stop = boundary;
          target = entry - Math.abs(boundary - entry) * 2;
        } else {
          target = boundary;
          stop = entry + Math.abs(entry - boundary) / 2;
        }
      }
      return { direction, entry, stop, target };
    })()
    : null;

  return (
    <div
      className={`relative overflow-hidden border border-[#D1D4DC] bg-white shadow-sm ${isFullscreen ? "flex h-screen w-screen flex-col rounded-none border-0" : "rounded-xl"}`}
      data-testid="synchronized-replay-window"
      ref={frameRef}
    >
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-[#E6E8EC] bg-[#F8F9FB] px-3 py-2">
        <div className="flex flex-wrap gap-1">
          {tools.map((item) => (
            <button
              aria-label={item.label}
              aria-pressed={tool === item.tool}
              className={`grid h-9 min-w-9 place-items-center rounded border px-2 text-xs font-semibold ${tool === item.tool ? "border-[#2962FF] bg-[#EAF0FF] text-[#1848CC]" : "border-transparent bg-white text-[#434651] hover:border-[#D1D4DC]"}`}
              disabled={locked}
              key={item.tool}
              onClick={() => selectTool(item.tool)}
              title={item.label}
              type="button"
            >
              {item.icon}
            </button>
          ))}
          <span className="mx-1 h-9 w-px bg-[#D1D4DC]" />
          <button aria-label="Undo last drawing" className="chart-command" disabled={locked || drawings.length === 0} onClick={() => {
            const target = drawings.at(-1);
            if (target) deleteDrawing(target.id);
          }} type="button">Undo</button>
          <button aria-label="Delete selected drawing" className="chart-command" disabled={locked || !selectedId} onClick={() => selectedId && deleteDrawing(selectedId)} type="button">Delete</button>
          <button aria-label="Clear all drawings" className="chart-command" disabled={locked || drawings.length === 0} onClick={() => {
            onDrawingsChange([]);
            onPositionPlan(null);
            setSelectedId(null);
            setMessage("All unlocked drawings cleared.");
          }} type="button">Clear</button>
        </div>
        <div className="flex flex-wrap items-center gap-1">
          <button aria-label="Zoom in" className="chart-command" onClick={() => updateCamera(viewport - 16, pan)} title="Zoom in" type="button">＋</button>
          <button aria-label="Zoom out" className="chart-command" onClick={() => updateCamera(viewport + 16, pan)} title="Zoom out" type="button">−</button>
          <button aria-label="Move chart left" className="chart-command" onClick={() => updateCamera(viewport, pan - cameraStep)} title="Slide candles left" type="button">←</button>
          <button aria-label="Move chart right" className="chart-command" onClick={() => updateCamera(viewport, pan + cameraStep)} title="Slide candles right" type="button">→</button>
          <button aria-label="Move chart up" className="chart-command" onClick={() => updateVerticalPan(verticalPan + 1)} title="Move candles up" type="button">↑</button>
          <button aria-label="Move chart down" className="chart-command" onClick={() => updateVerticalPan(verticalPan - 1)} title="Move candles down" type="button">↓</button>
          <button aria-label="Reset chart camera" className="chart-command" onClick={() => {
            updateCamera(Math.min(100, maximumViewport), 0);
            updateVerticalPan(0);
          }} type="button">Reset</button>
          <button
            aria-label={isFullscreen ? "Exit full screen" : "Enter full screen"}
            className="chart-command"
            onClick={() => void toggleFullscreen()}
            type="button"
          >
            {isFullscreen ? "Exit full screen" : "Full screen"}
          </button>
          {positionReady && onRequestPositionDetails && !locked ? (
            <button
              aria-label={placeButtonLabel}
              className="rounded-lg bg-[#087363] px-4 py-2 text-xs font-bold text-white"
              onClick={onRequestPositionDetails}
              type="button"
            >
              {placeButtonLabel}
            </button>
          ) : null}
          <span className="ml-2 rounded-full border border-[#B7C7FF] bg-[#EEF3FF] px-3 py-1 text-[10px] font-bold text-[#174EA6]">REPLAY NOW · {cursorDisplayLabel ?? relativeLabel(cursorMinute)}</span>
        </div>
      </div>

      {isFullscreen && fullscreenReplayControls ? (
        <div
          aria-label="Full-screen synchronized replay controls"
          className="flex flex-wrap items-center gap-2 border-b border-[#D1D4DC] bg-white px-3 py-2"
        >
          <button
            aria-label={fullscreenReplayControls.playing ? "Pause full-screen replay" : "Play full-screen replay"}
            className="rounded-lg bg-[#2962FF] px-4 py-2 text-xs font-bold text-white disabled:cursor-not-allowed disabled:opacity-35"
            disabled={fullscreenReplayControls.playDisabled}
            onClick={fullscreenReplayControls.onTogglePlay}
            type="button"
          >
            {fullscreenReplayControls.playing ? "Pause" : "▶ Play"}
          </button>
          {([1, 5, 15] as const).map((minutes) => (
            <button
              aria-label={`Advance full-screen replay ${minutes} minute${minutes === 1 ? "" : "s"}`}
              className="chart-command"
              disabled={
                fullscreenReplayControls.advanceDisabled
                || fullscreenReplayControls.advancing
                || fullscreenReplayControls.cursorMinute + minutes > fullscreenReplayControls.maximumCursorMinute
              }
              key={minutes}
              onClick={() => fullscreenReplayControls.onAdvance(minutes)}
              type="button"
            >
              +{minutes}m
            </button>
          ))}
          <span className="mx-1 h-8 w-px bg-[#D1D4DC]" />
          {replayTimeframes.map((timeframe) => (
            <button
              aria-label={`Show ${replayTimeframeLabel(timeframe)} in full screen`}
              aria-pressed={label === timeframe}
              className={`rounded border px-2 py-1.5 text-[10px] font-bold ${label === timeframe ? "border-[#2962FF] bg-[#EAF0FF] text-[#1848CC]" : "border-[#D1D4DC] bg-white text-[#5D606B]"}`}
              key={timeframe}
              onClick={() => fullscreenReplayControls.onTimeframeChange(timeframe)}
              type="button"
            >
              {replayTimeframeLabel(timeframe)} · {fullscreenReplayControls.timeframeCounts[timeframe] ?? 0}
            </button>
          ))}
          <span className="ml-auto rounded-full bg-[#EEF3FF] px-3 py-2 text-xs font-bold text-[#174EA6]">
            {cursorDisplayLabel ?? relativeLabel(fullscreenReplayControls.cursorMinute)}
          </span>
        </div>
      ) : null}

      <svg
        aria-label={`${label.toUpperCase()} synchronized blind replay chart`}
        className={`block w-full select-none bg-white ${isFullscreen ? "min-h-0 flex-1" : "h-auto"}`}
        data-cursor-minute={cursorMinute}
        data-drawing-count={drawings.length}
        data-pan-bars={pan}
        data-slot-width={slot.toFixed(6)}
        data-testid="synchronized-replay-chart"
        data-vertical-pan={verticalPan}
        data-visible-bars={visibleBars.length}
        data-viewport-bars={viewport}
        onClick={handleClick}
        onPointerMove={(event) => {
          const point = pointFromEvent(event);
          if (point) {
            resizeDrawingAnchor(point);
            const bar = bars.find((candidate) => candidate.close_offset_minutes === point.relativeMinute);
            if (bar) setHover({ bar, price: point.priceIndex });
          }
        }}
        onPointerLeave={() => {
          setHover(null);
          draggingAnchorRef.current = null;
        }}
        onPointerUp={() => {
          draggingAnchorRef.current = null;
        }}
        preserveAspectRatio="xMidYMid meet"
        ref={svgRef}
        role="img"
        viewBox={`0 0 ${width} ${height}`}
      >
        <rect fill="#FFFFFF" height={height} width={width} />
        {Array.from({ length: 6 }, (_, index) => {
          const lineY = padding.top + (chartHeight / 5) * index;
          const price = maximum - (span / 5) * index;
          return (
            <g key={`grid-${index}`}>
              <line stroke="#E6E8EC" strokeWidth="1" x1={padding.left} x2={width - padding.right} y1={lineY} y2={lineY} />
              <text fill="#5D606B" fontSize="11" x={width - padding.right + 8} y={lineY + 4}>{price.toFixed(4)}</text>
            </g>
          );
        })}

        {windows.flatMap((window) => {
          const first = bars.find((bar) => bar.close_offset_minutes >= window.startMinute);
          const last = [...bars].reverse().find((bar) => bar.close_offset_minutes <= window.endMinute);
          if (!first || !last) return [];
          const startX = xForBarRaw(first);
          const endX = xForBarRaw(last);
          if (startX === null || endX === null || endX < padding.left || startX > width - padding.right) return [];
          return [(
            <g key={`${window.code}-${window.startMinute}`} pointerEvents="none">
              <rect
                fill={window.color}
                fillOpacity="0.075"
                height={chartHeight}
                width={Math.max(1, endX - startX + slot)}
                x={startX - slot / 2}
                y={padding.top}
              />
              <text fill={window.color} fontSize="9" fontWeight="700" x={startX + 3} y={padding.top + 11}>
                {window.code.replaceAll("_", " ")}
              </text>
            </g>
          )];
        })}

        {visibleBarRows.map(({ bar, x: candleX }, index) => {
          const bullish = bar.close >= bar.open;
          const color = bullish ? "#089981" : "#F23645";
          const top = y(Math.max(bar.open, bar.close));
          const bottom = y(Math.min(bar.open, bar.close));
          return (
            <g data-bar-id={bar.bar_id} key={bar.bar_id}>
              <line stroke={color} strokeWidth="1.2" x1={candleX} x2={candleX} y1={y(bar.high)} y2={y(bar.low)} />
              <rect fill={color} height={Math.max(1, bottom - top)} rx="0.5" width={bodyWidth} x={candleX - bodyWidth / 2} y={top} />
              {(index === 0 || index === visibleBars.length - 1 || index % Math.max(1, Math.floor(visibleBars.length / 6)) === 0) ? (
                <text fill="#5D606B" fontSize="10" textAnchor="middle" x={candleX} y={height - 18}>{formatMinuteLabel(bar.close_offset_minutes)}</text>
              ) : null}
            </g>
          );
        })}

        {levels.filter((level) => level.level >= minimum && level.level <= maximum).map((level) => (
          <g key={`${level.code}-${level.level}`}>
            <line stroke="#D89B00" strokeDasharray="5 4" x1={padding.left} x2={width - padding.right} y1={y(level.level)} y2={y(level.level)} />
            <text fill="#8A6200" fontSize="10" textAnchor="end" x={width - padding.right - 5} y={y(level.level) - 4}>{level.code.replaceAll("_", " ")}</text>
          </g>
        ))}

        {events.flatMap((event) => {
          const bar = [...bars].reverse().find((candidate) => candidate.close_offset_minutes <= event.relativeMinute);
          if (!bar) return [];
          const eventX = xForBar(bar);
          if (eventX === null) return [];
          return [(
            <g data-testid="released-event-marker" key={`${event.eventCode}-${event.relativeMinute}`}>
              <line stroke="#A46500" strokeDasharray="3 3" x1={eventX} x2={eventX} y1={padding.top} y2={height - padding.bottom} />
              <circle cx={eventX} cy={height - padding.bottom + 13} fill="#FFF4CE" r="10" stroke="#A46500" />
              <text fill="#6B4500" fontSize="8" fontWeight="700" textAnchor="middle" x={eventX} y={height - padding.bottom + 16}>E</text>
              <title>{`${event.name} · ${event.surpriseLabel ?? "released"} · ${event.goldImpact ?? "impact unknown"}`}</title>
            </g>
          )];
        })}

        {renderedDrawings.map(({ drawing, projectedBars }) => {
          const xs = projectedBars.map(xForBarRaw);
          if (xs.some((value) => value === null)) return null;
          const coordinates = xs as number[];
          const selected = selectedId === drawing.id;
          const stroke = selected ? "#131722" : "#7E57C2";
          const select = (event: ReactPointerEvent<SVGGElement>) => {
            event.stopPropagation();
            if (!locked) {
              setSelectedId(drawing.id);
              setTool("SELECT");
              setMessage("Drawing selected. Drag its blue-outlined handles to resize it, or Delete to remove it before lock.");
            }
          };
          const resizeHandle = (anchorIndex: number, x: number, handleY: number, name: string) => (
            !locked && selected ? (
              <circle
                aria-label={`Resize ${name}`}
                className="cursor-move"
                cx={Math.max(padding.left + 6, Math.min(x, width - padding.right - 6))}
                cy={handleY}
                fill="#FFFFFF"
                key={`handle-${anchorIndex}`}
                onPointerDown={(event) => {
                  event.stopPropagation();
                  draggingAnchorRef.current = {
                    drawingId: drawing.id,
                    anchorIndex,
                    baseDrawing: drawing,
                  };
                  if ("setPointerCapture" in event.currentTarget) {
                    try {
                      event.currentTarget.setPointerCapture(event.pointerId);
                    } catch {
                      // Pointer capture is an enhancement; SVG-level tracking remains deterministic.
                    }
                  }
                }}
                r="6"
                stroke="#2962FF"
                strokeWidth="2.5"
              />
            ) : null
          );
          if (drawing.kind === "HORIZONTAL_LINE") {
            return (
              <g aria-label="horizontal line drawing" key={drawing.id} onClick={select}>
                <line stroke={stroke} strokeWidth={selected ? 2.5 : 1.5} x1={padding.left} x2={width - padding.right} y1={y(drawing.anchors[0].priceIndex)} y2={y(drawing.anchors[0].priceIndex)} />
                {resizeHandle(0, coordinates[0], y(drawing.anchors[0].priceIndex), "horizontal line")}
              </g>
            );
          }
          if (drawing.kind === "LONG_POSITION" || drawing.kind === "SHORT_POSITION") {
            const entry = drawing.anchors[0].priceIndex;
            const stop = drawing.anchors[1].priceIndex;
            const target = drawing.anchors[2].priceIndex;
            const right = width - padding.right;
            const left = Math.max(padding.left, Math.min(coordinates[0] - slot * 0.35, right - 150));
            const rewardR = Math.abs(target - entry) / Math.max(Math.abs(entry - stop), 0.0000001);
            const lifecycleLabel = positionLifecycle.replaceAll("_", " ");
            return (
              <g aria-label={`${drawing.kind === "LONG_POSITION" ? "long" : "short"} position drawing`} key={drawing.id} onClick={select}>
                <rect fill="#089981" fillOpacity="0.14" height={Math.abs(y(target) - y(entry))} stroke="#089981" strokeWidth={selected ? 2 : 1} width={right - left} x={left} y={Math.min(y(target), y(entry))} />
                <rect fill="#F23645" fillOpacity="0.14" height={Math.abs(y(stop) - y(entry))} stroke="#F23645" strokeWidth={selected ? 2 : 1} width={right - left} x={left} y={Math.min(y(stop), y(entry))} />
                <line stroke="#2962FF" strokeWidth="2" x1={left} x2={right} y1={y(entry)} y2={y(entry)} />
                <line stroke="#B4232F" strokeWidth="1.5" x1={left} x2={right} y1={y(stop)} y2={y(stop)} />
                <line stroke="#087363" strokeWidth="1.5" x1={left} x2={right} y1={y(target)} y2={y(target)} />
                <text fill="#174EA6" fontSize="10" fontWeight="700" x={left + 5} y={y(entry) - 5}>ENTRY {entry.toFixed(4)}</text>
                <text fill="#B4232F" fontSize="10" fontWeight="700" x={left + 5} y={y(stop) + (stop > entry ? -5 : 13)}>SL {stop.toFixed(4)}</text>
                <text fill="#087363" fontSize="10" fontWeight="700" x={left + 5} y={y(target) + (target > entry ? 13 : -5)}>TP {target.toFixed(4)} · {rewardR.toFixed(2)}R</text>
                {actualFillPrice !== null ? (
                  <>
                    <line stroke="#F59E0B" strokeDasharray="4 3" strokeWidth="1.5" x1={left} x2={right} y1={y(actualFillPrice)} y2={y(actualFillPrice)} />
                    <text fill="#9A6700" fontSize="9" fontWeight="700" x={left + 5} y={y(actualFillPrice) - 4}>ACTUAL FILL {actualFillPrice.toFixed(4)}</text>
                  </>
                ) : null}
                <rect fill={positionLifecycle === "EDITABLE" ? "#174EA6" : positionLifecycle === "PENDING_ENTRY" ? "#8A6200" : "#087363"} height="20" rx="4" width="116" x={right - 120} y={padding.top + 5} />
                <text fill="white" fontSize="9" fontWeight="700" textAnchor="middle" x={right - 62} y={padding.top + 18}>{lifecycleLabel}</text>
                {resizeHandle(0, right - 8, y(entry), `${drawing.kind === "LONG_POSITION" ? "long" : "short"} position entry`)}
                {resizeHandle(1, right - 8, y(stop), `${drawing.kind === "LONG_POSITION" ? "long" : "short"} position stop`)}
                {resizeHandle(2, right - 8, y(target), `${drawing.kind === "LONG_POSITION" ? "long" : "short"} position target`)}
              </g>
            );
          }
          if (drawing.kind === "FIBONACCI") {
            const startPrice = drawing.anchors[0].priceIndex;
            const endPrice = drawing.anchors[1].priceIndex;
            return (
              <g aria-label="fibonacci drawing" key={drawing.id} onClick={select}>
                {fibRatios.map((ratio) => {
                  const price = startPrice + (endPrice - startPrice) * ratio;
                  return <g key={ratio}><line stroke={stroke} strokeOpacity="0.8" x1={coordinates[0]} x2={width - padding.right} y1={y(price)} y2={y(price)} /><text fill="#6C5CE7" fontSize="9" x={coordinates[0] + 4} y={y(price) - 3}>{ratio.toFixed(3)}</text></g>;
                })}
                {resizeHandle(0, coordinates[0], y(startPrice), "Fibonacci origin")}
                {resizeHandle(1, coordinates[1], y(endPrice), "Fibonacci extreme")}
              </g>
            );
          }
          const first = drawing.anchors[0];
          const second = drawing.anchors[1];
          return (
            <g aria-label={`${drawing.kind.toLowerCase().replaceAll("_", " ")} drawing`} key={drawing.id} onClick={select}>
              <line stroke={stroke} strokeWidth={selected ? 2.5 : 1.5} x1={coordinates[0]} x2={coordinates[1]} y1={y(first.priceIndex)} y2={y(second.priceIndex)} />
              {resizeHandle(0, coordinates[0], y(first.priceIndex), `${drawing.kind.toLowerCase().replaceAll("_", " ")} first anchor`)}
              {resizeHandle(1, coordinates[1], y(second.priceIndex), `${drawing.kind.toLowerCase().replaceAll("_", " ")} second anchor`)}
              {drawing.kind === "RULER" ? <text fill="#1976D2" fontSize="10" x={(coordinates[0] + coordinates[1]) / 2} y={(y(first.priceIndex) + y(second.priceIndex)) / 2 - 6}>{Math.abs(second.relativeMinute - first.relativeMinute)}m · {Math.abs(second.priceIndex - first.priceIndex).toFixed(4)}</text> : null}
            </g>
          );
        })}

        {positionDraft && replayNowVisible ? (() => {
          const plotRight = width - padding.right;
          const left = Math.max(padding.left, Math.min(replayNowX - slot * 0.35, plotRight - 150));
          const risk = Math.max(Math.abs(positionDraft.entry - positionDraft.stop), 0.0000001);
          const rewardR = Math.abs(positionDraft.target - positionDraft.entry) / risk;
          return (
            <g aria-label={`${positionDraft.direction.toLowerCase()} position draft`} pointerEvents="none">
              <rect
                fill="#089981"
                fillOpacity="0.18"
                height={Math.abs(y(positionDraft.target) - y(positionDraft.entry))}
                stroke="#089981"
                strokeDasharray="5 3"
                width={plotRight - left}
                x={left}
                y={Math.min(y(positionDraft.target), y(positionDraft.entry))}
              />
              <rect
                fill="#F23645"
                fillOpacity="0.18"
                height={Math.abs(y(positionDraft.stop) - y(positionDraft.entry))}
                stroke="#F23645"
                strokeDasharray="5 3"
                width={plotRight - left}
                x={left}
                y={Math.min(y(positionDraft.stop), y(positionDraft.entry))}
              />
              <line stroke="#2962FF" strokeWidth="2" x1={left} x2={plotRight} y1={y(positionDraft.entry)} y2={y(positionDraft.entry)} />
              <line stroke="#B4232F" strokeDasharray="4 3" x1={left} x2={plotRight} y1={y(positionDraft.stop)} y2={y(positionDraft.stop)} />
              <line stroke="#087363" strokeDasharray="4 3" x1={left} x2={plotRight} y1={y(positionDraft.target)} y2={y(positionDraft.target)} />
              <text fill="#174EA6" fontSize="10" fontWeight="700" x={left + 6} y={y(positionDraft.entry) - 6}>ENTRY {positionDraft.entry.toFixed(4)}</text>
              <text fill="#B4232F" fontSize="10" fontWeight="700" x={left + 6} y={y(positionDraft.stop) + (positionDraft.stop > positionDraft.entry ? -6 : 14)}>SL {positionDraft.stop.toFixed(4)}</text>
              <text fill="#087363" fontSize="10" fontWeight="700" x={left + 6} y={y(positionDraft.target) + (positionDraft.target > positionDraft.entry ? 14 : -6)}>TP {positionDraft.target.toFixed(4)} · {rewardR.toFixed(2)}R</text>
              <rect fill="#174EA6" height="20" rx="4" width="118" x={plotRight - 122} y={y(positionDraft.entry) - 10} />
              <text fill="white" fontSize="9" fontWeight="700" textAnchor="middle" x={plotRight - 63} y={y(positionDraft.entry) + 3}>
                {draft.length === 1 ? "CLICK SL OR TP" : "CLICK OPPOSITE SIDE"}
              </text>
            </g>
          );
        })() : null}

        {!positionDraft ? draft.map((anchor, index) => {
          const bar = projected(anchor);
          const anchorX = bar ? xForBar(bar) : null;
          return anchorX === null ? null : <circle cx={anchorX} cy={y(anchor.priceIndex)} fill="#2962FF" key={`draft-${index}`} r="4" />;
        }) : null}

        {replayNowVisible ? (
          <g>
            <line stroke="#2962FF" strokeDasharray="5 4" strokeWidth="1.5" x1={replayNowX} x2={replayNowX} y1={padding.top} y2={height - padding.bottom} />
            <text fill="#174EA6" fontSize="10" fontWeight="700" textAnchor="middle" x={replayNowX} y={padding.top + 12}>REPLAY NOW</text>
          </g>
        ) : null}

        {hover ? (
          <g pointerEvents="none">
            <line stroke="#787B86" strokeDasharray="3 3" x1={padding.left} x2={width - padding.right} y1={y(hover.price)} y2={y(hover.price)} />
            <rect fill="#131722" height="22" rx="4" width="86" x={width - padding.right - 88} y={y(hover.price) - 11} />
            <text fill="white" fontSize="10" textAnchor="middle" x={width - padding.right - 45} y={y(hover.price) + 4}>{hover.price.toFixed(4)}</text>
          </g>
        ) : null}
      </svg>

      <div className="flex flex-wrap items-center justify-between gap-2 border-t border-[#E6E8EC] bg-[#F8F9FB] px-3 py-2 text-[11px] text-[#5D606B]">
        <span>{message}</span>
        <span>{hoveredOffset === undefined ? `Shared cursor ${cursorDisplayLabel ?? relativeLabel(cursorMinute)}` : `${formatMinuteLabel(hoveredOffset)} · ${hover?.price.toFixed(4)}`}{incompatibleCount ? ` · ${incompatibleCount} drawing(s) incompatible on ${label.toUpperCase()}` : ""}</span>
      </div>
      {fullscreenOverlay}
    </div>
  );
}
