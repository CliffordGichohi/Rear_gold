import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { useState } from "react";

import {
  SynchronizedReplayChart,
  type ReplayTimeframe,
  type ReplayV2Drawing,
  type ReplayV2PositionPlan,
} from "./synchronized-replay-chart";


afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  Object.defineProperty(document, "fullscreenElement", {
    configurable: true,
    value: null,
  });
});


function makeBars(timeframe: ReplayTimeframe) {
  const step = timeframe === "1h" ? 60 : 15;
  return Array.from({ length: 40 }, (_, index) => {
    const closeOffset = (index - 39) * step;
    const close = 100 + Math.sin(index / 3) * 0.15;
    return {
      bar_id: `${timeframe.replace(/\W/g, "a")}-${String(index).padStart(4, "0")}`.padEnd(64, "0").slice(0, 64),
      close_offset_minutes: closeOffset,
      available_offset_minutes: closeOffset,
      open: close - 0.03,
      high: close + 0.12,
      low: close - 0.12,
      close,
      volume: 10 + index,
    };
  });
}


function Harness({ onPosition }: { onPosition?: (plan: ReplayV2PositionPlan | null) => string | null }) {
  const [timeframe, setTimeframe] = useState<ReplayTimeframe>("15m");
  const [drawings, setDrawings] = useState<ReplayV2Drawing[]>([]);
  return (
    <div>
      <button onClick={() => setTimeframe("1h")} type="button">Switch to H1</button>
      <button onClick={() => setTimeframe("15m")} type="button">Switch to M15</button>
      <SynchronizedReplayChart
        bars={makeBars(timeframe)}
        cursorMinute={0}
        drawings={drawings}
        label={timeframe}
        onDrawingsChange={setDrawings}
        onPositionPlan={onPosition ?? (() => null)}
      />
    </div>
  );
}


function chartBounds(chart: HTMLElement) {
  Object.defineProperty(chart, "getBoundingClientRect", {
    configurable: true,
    value: () => ({
      bottom: 585,
      height: 585,
      left: 0,
      right: 1180,
      top: 0,
      width: 1180,
      x: 0,
      y: 0,
      toJSON: () => ({}),
    }),
  });
}


describe("SynchronizedReplayChart", () => {
  it("changes the camera only through GUI controls and can enter full screen", () => {
    render(<Harness />);
    const chart = screen.getByTestId("synchronized-replay-chart");
    const replayWindow = screen.getByTestId("synchronized-replay-window");
    chartBounds(chart);
    expect(chart).toHaveAttribute("data-viewport-bars", "40");
    expect(chart).toHaveAttribute("data-pan-bars", "0");
    expect(chart).toHaveAttribute("data-automatic-level-count", "0");

    expect(fireEvent.wheel(chart, { deltaY: -120 })).toBe(true);
    fireEvent.pointerDown(chart, { clientX: 700, pointerId: 1 });
    fireEvent.pointerMove(chart, { clientX: 300, pointerId: 1 });
    fireEvent.pointerUp(chart, { clientX: 300, pointerId: 1 });
    expect(chart).toHaveAttribute("data-viewport-bars", "40");
    expect(chart).toHaveAttribute("data-pan-bars", "0");

    fireEvent.click(screen.getByRole("button", { name: "Zoom in" }));
    expect(chart).toHaveAttribute("data-viewport-bars", "24");
    const zoomedSlotWidth = chart.getAttribute("data-slot-width");
    fireEvent.click(screen.getByRole("button", { name: "Move chart left" }));
    expect(chart).toHaveAttribute("data-pan-bars", "-2");
    expect(chart).toHaveAttribute("data-slot-width", zoomedSlotWidth);
    fireEvent.click(screen.getByRole("button", { name: "Move chart up" }));
    expect(chart).toHaveAttribute("data-vertical-pan", "1");
    fireEvent.click(screen.getByRole("button", { name: "Move chart down" }));
    expect(chart).toHaveAttribute("data-vertical-pan", "0");
    expect(chart).toHaveAttribute("data-chart-height", "585");
    expect(chart).toHaveStyle({ height: "585px" });
    fireEvent.click(screen.getByRole("button", { name: "Increase chart height" }));
    expect(chart).toHaveAttribute("data-chart-height", "665");
    expect(chart).toHaveStyle({ height: "665px" });
    fireEvent.click(screen.getByRole("button", { name: "Decrease chart height" }));
    expect(chart).toHaveAttribute("data-chart-height", "585");
    expect(replayWindow).toHaveAttribute("data-chart-width-percent", "100");
    expect(replayWindow).toHaveStyle({ width: "100%" });
    fireEvent.click(screen.getByRole("button", { name: "Decrease chart width" }));
    expect(replayWindow).toHaveAttribute("data-chart-width-percent", "90");
    expect(replayWindow).toHaveStyle({ width: "90%" });
    fireEvent.click(screen.getByRole("button", { name: "Increase chart width" }));
    expect(replayWindow).toHaveAttribute("data-chart-width-percent", "100");

    const requestFullscreen = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(replayWindow, "requestFullscreen", {
      configurable: true,
      value: requestFullscreen,
    });
    fireEvent.click(screen.getByRole("button", { name: "Enter full screen" }));
    expect(requestFullscreen).toHaveBeenCalledTimes(1);
  });

  it("keeps one cursor and projects a case-global drawing across timeframes", () => {
    render(<Harness />);
    const chart = screen.getByTestId("synchronized-replay-chart");
    chartBounds(chart);
    expect(chart).toHaveAttribute("data-cursor-minute", "0");

    fireEvent.click(screen.getByRole("button", { name: "Horizontal level" }));
    fireEvent.click(chart, { clientX: 520, clientY: 280 });
    expect(screen.getByTestId("synchronized-replay-chart")).toHaveAttribute("data-drawing-count", "1");
    expect(screen.getByLabelText("horizontal line drawing")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Trend line" }));
    fireEvent.click(chart, { clientX: 420, clientY: 330 });
    fireEvent.click(chart, { clientX: 650, clientY: 220 });
    expect(screen.getByTestId("synchronized-replay-chart")).toHaveAttribute("data-drawing-count", "2");
    expect(screen.getByLabelText("trend line drawing")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Switch to H1" }));
    expect(screen.getByTestId("synchronized-replay-chart")).toHaveAttribute("data-cursor-minute", "0");
    expect(screen.getByTestId("synchronized-replay-chart")).toHaveAttribute("data-drawing-count", "2");
    expect(screen.getByLabelText("horizontal line drawing")).toBeInTheDocument();
    expect(screen.getByLabelText("trend line drawing")).toBeInTheDocument();
    fireEvent.click(screen.getByLabelText("horizontal line drawing"));
    expect(screen.getByLabelText("Resize horizontal line")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /rewind/i })).not.toBeInTheDocument();
  });

  it("draws a complete position zone at Replay Now and allows deletion before lock", () => {
    const onPosition = vi.fn<(plan: ReplayV2PositionPlan | null) => string | null>();
    onPosition.mockReturnValue(null);
    render(<Harness onPosition={onPosition} />);
    const chart = screen.getByTestId("synchronized-replay-chart");
    chartBounds(chart);

    fireEvent.click(screen.getByRole("button", { name: "Long position" }));
    fireEvent.click(chart, { clientX: 900, clientY: 285 });
    expect(screen.getByLabelText("long position draft")).toBeInTheDocument();
    fireEvent.click(chart, { clientX: 900, clientY: 120 });
    expect(screen.getByLabelText("long position draft")).toBeInTheDocument();
    fireEvent.click(chart, { clientX: 900, clientY: 390 });

    expect(onPosition).toHaveBeenCalledTimes(1);
    const plan = onPosition.mock.calls[0][0];
    expect(plan?.direction).toBe("LONG");
    expect(plan?.stopIndex).toBeLessThan(plan?.entryIndex ?? 0);
    expect(plan?.targetIndex).toBeGreaterThan(plan?.entryIndex ?? 0);
    expect(screen.getByLabelText("long position drawing")).toBeInTheDocument();
    expect(screen.getByText(/ENTRY/)).toBeInTheDocument();
    expect(screen.getByText(/SL/)).toBeInTheDocument();
    expect(screen.getByText(/TP/)).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Crosshair" }));
    expect(screen.getByLabelText("Resize long position entry")).toBeInTheDocument();
    expect(screen.getByLabelText("Resize long position stop")).toBeInTheDocument();
    expect(screen.getByLabelText("Resize long position target")).toBeInTheDocument();

    const originalPlan = onPosition.mock.calls.at(-1)?.[0];
    const callsBeforeResize = onPosition.mock.calls.length;
    fireEvent.pointerDown(screen.getByLabelText("Resize long position stop"), { pointerId: 2 });
    fireEvent.pointerMove(chart, { clientX: 900, clientY: 350, pointerId: 2 });
    fireEvent.pointerUp(chart, { pointerId: 2 });
    expect(onPosition.mock.calls.length).toBeGreaterThan(callsBeforeResize);
    const stopResizedPlan = onPosition.mock.calls.at(-1)?.[0];
    expect(stopResizedPlan?.entryIndex).toBe(originalPlan?.entryIndex);
    expect(stopResizedPlan?.targetIndex).toBe(originalPlan?.targetIndex);
    expect(stopResizedPlan?.stopIndex).not.toBe(originalPlan?.stopIndex);
    expect(screen.getByLabelText("long position drawing")).toBeInTheDocument();

    const callsBeforeTargetResize = onPosition.mock.calls.length;
    fireEvent.pointerDown(screen.getByLabelText("Resize long position target"), { pointerId: 3 });
    fireEvent.pointerMove(chart, { clientX: 900, clientY: 165, pointerId: 3 });
    fireEvent.pointerUp(chart, { pointerId: 3 });
    expect(onPosition.mock.calls.length).toBeGreaterThan(callsBeforeTargetResize);
    const targetResizedPlan = onPosition.mock.calls.at(-1)?.[0];
    expect(targetResizedPlan?.entryIndex).toBe(stopResizedPlan?.entryIndex);
    expect(targetResizedPlan?.stopIndex).toBe(stopResizedPlan?.stopIndex);
    expect(targetResizedPlan?.targetIndex).not.toBe(stopResizedPlan?.targetIndex);

    fireEvent.click(screen.getByRole("button", { name: "Switch to H1" }));
    expect(screen.getByLabelText("long position drawing")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Switch to M15" }));
    expect(screen.getByLabelText("long position drawing")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Delete selected drawing" }));
    expect(screen.queryByLabelText("long position drawing")).not.toBeInTheDocument();
    expect(onPosition).toHaveBeenLastCalledWith(null);
  });

  it("deletes the selected unlocked drawing with Backspace or Delete", () => {
    render(<Harness />);
    const chart = screen.getByTestId("synchronized-replay-chart");
    chartBounds(chart);

    fireEvent.click(screen.getByRole("button", { name: "Horizontal level" }));
    fireEvent.click(chart, { clientX: 520, clientY: 280 });
    expect(screen.getByLabelText("horizontal line drawing")).toBeInTheDocument();

    expect(fireEvent.keyDown(window, { key: "Backspace" })).toBe(false);
    expect(screen.queryByLabelText("horizontal line drawing")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Horizontal level" }));
    fireEvent.click(chart, { clientX: 560, clientY: 250 });
    expect(screen.getByLabelText("horizontal line drawing")).toBeInTheDocument();
    fireEvent.keyDown(window, { key: "Delete" });
    expect(screen.queryByLabelText("horizontal line drawing")).not.toBeInTheDocument();
  });

  it("keeps drawing tools immutable when the setup has been sealed", () => {
    const drawing: ReplayV2Drawing = {
      id: "sealed-level",
      kind: "HORIZONTAL_LINE",
      placedAtCursorMinute: 0,
      anchors: [{ relativeMinute: 0, priceIndex: 100, sourceTimeframe: "15m" }],
    };
    render(
      <SynchronizedReplayChart
        bars={makeBars("15m")}
        cursorMinute={0}
        drawings={[drawing]}
        label="15m"
        locked
        onDrawingsChange={() => undefined}
        onPositionPlan={() => null}
      />,
    );
    expect(screen.getByRole("button", { name: "Horizontal level" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Delete selected drawing" })).toBeDisabled();
    expect(screen.getByLabelText("horizontal line drawing")).toBeInTheDocument();
    expect(screen.queryByLabelText("Resize horizontal line")).not.toBeInTheDocument();
  });

  it("keeps full-screen playback stable and exposes trade placement", () => {
    const onPlace = vi.fn();
    const controls = {
      playing: true,
      advancing: true,
      playDisabled: false,
      advanceDisabled: true,
      positionReady: true,
      placeButtonLabel: "Prepare Trade Decision",
      cursorMinute: 60,
      maximumCursorMinute: 900,
      timeframeCounts: { "15m": 12 },
      onTogglePlay: vi.fn(),
      onAdvance: vi.fn(),
      onTimeframeChange: vi.fn(),
      onRequestPositionDetails: onPlace,
    };
    const { rerender } = render(
      <SynchronizedReplayChart
        bars={makeBars("15m")}
        cursorMinute={60}
        drawings={[]}
        fullscreenReplayControls={controls}
        label="15m"
        onDrawingsChange={() => undefined}
        onPositionPlan={() => null}
      />,
    );
    const replayWindow = screen.getByTestId("synchronized-replay-window");
    Object.defineProperty(document, "fullscreenElement", {
      configurable: true,
      value: replayWindow,
    });
    fireEvent(document, new Event("fullscreenchange"));

    const pause = screen.getByRole("button", { name: "Pause full-screen replay" });
    expect(pause).toBeEnabled();
    expect(pause).toHaveAttribute("aria-busy", "true");

    rerender(
      <SynchronizedReplayChart
        bars={makeBars("15m")}
        cursorMinute={60}
        drawings={[]}
        fullscreenReplayControls={{ ...controls, playing: false, advancing: false }}
        label="15m"
        onDrawingsChange={() => undefined}
        onPositionPlan={() => null}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Full-screen Prepare Trade Decision" }));
    expect(onPlace).toHaveBeenCalledTimes(1);
  });
});
