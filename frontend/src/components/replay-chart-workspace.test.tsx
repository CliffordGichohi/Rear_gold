import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ReplayChartWorkspace, type PositionPlan } from "./replay-chart-workspace";


afterEach(cleanup);


const bars = Array.from({ length: 40 }, (_, ordinal) => ({
  ordinal,
  open: 99.8 + (ordinal % 2) * 0.1,
  high: 100.5,
  low: 99.5,
  close: 100 + (ordinal % 2) * 0.1,
  volume: 10 + ordinal,
}));


describe("ReplayChartWorkspace", () => {
  it("exposes the frozen drawing and visible-history replay controls", () => {
    render(<ReplayChartWorkspace bars={bars} label="15m" />);

    for (const name of [
      "Crosshair",
      "Select drawing",
      "Trend line",
      "Horizontal level",
      "Fibonacci retracement",
      "Long position",
      "Short position",
      "Measure",
      "Undo last drawing",
      "Delete selected drawing",
      "Clear all drawings",
      "Zoom in",
      "Zoom out",
      "Move chart left",
      "Move chart right",
      "Reset chart camera",
    ]) {
      expect(screen.getByRole("button", { name })).toBeInTheDocument();
    }
    expect(screen.getAllByText(/decision checkpoint/).length).toBeGreaterThan(0);
    expect(document.body.textContent).toMatch(/T\+\d+ 15M bars/);
    expect(document.body.textContent).not.toMatch(/202[1-6]-\d{2}-\d{2}/);
  });

  it("keeps the replay cursor independent from zoom and future-space camera movement", () => {
    render(<ReplayChartWorkspace bars={bars} label="1m" />);
    const chart = screen.getByTestId("blind-replay-chart");

    fireEvent.click(screen.getByRole("button", { name: /Replay history/ }));
    expect(chart).toHaveAttribute("data-revealed-bars", "20");
    expect(chart.querySelectorAll("[data-bar-index]")).toHaveLength(20);

    fireEvent.click(screen.getByRole("button", { name: "Zoom in" }));
    expect(chart).toHaveAttribute("data-revealed-bars", "20");
    expect(chart.querySelectorAll("[data-bar-index]")).toHaveLength(20);

    const before = Number(chart.getAttribute("data-right-space-bars"));
    fireEvent.click(screen.getByRole("button", { name: "Move chart left" }));
    expect(Number(chart.getAttribute("data-right-space-bars"))).toBeGreaterThan(before);
    expect(chart).toHaveAttribute("data-revealed-bars", "20");
    expect(screen.getByText("REPLAY NOW")).toBeInTheDocument();
  });

  it("allows annotations on revealed replay candles while execution tools stay locked", () => {
    render(<ReplayChartWorkspace bars={bars} label="15m" />);
    const chart = screen.getByTestId("blind-replay-chart");
    Object.defineProperty(chart, "getBoundingClientRect", {
      value: () => ({ bottom: 560, height: 560, left: 0, right: 1180, top: 0, width: 1180, x: 0, y: 0, toJSON: () => ({}) }),
    });

    fireEvent.click(screen.getByRole("button", { name: /Replay history/ }));
    expect(screen.getByRole("button", { name: "Long position" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Short position" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Horizontal level" })).toBeEnabled();

    fireEvent.click(screen.getByRole("button", { name: "Horizontal level" }));
    fireEvent.click(chart, { clientX: 600, clientY: 280 });
    fireEvent.click(screen.getByRole("button", { name: "Crosshair" }));
    expect(chart.querySelectorAll('line[stroke="#7E57C2"]')).toHaveLength(1);
    expect(chart).toHaveAttribute("data-revealed-bars", "20");

    fireEvent.click(screen.getByRole("button", { name: "Return to checkpoint" }));
    expect(screen.getByRole("button", { name: "Long position" })).toBeEnabled();
    expect(chart.querySelectorAll('line[stroke="#7E57C2"]')).toHaveLength(1);
  });

  it("does not show a released-event marker before replay reaches its release point", () => {
    render(<ReplayChartWorkspace bars={bars} events={[{
      eventCode: "US_CPI",
      name: "Consumer Price Index",
      minutesBeforeCheckpoint: 5,
      importance: 5,
      surpriseLabel: "POSITIVE SURPRISE",
      goldImpact: "PRESSURE",
    }]} label="1m" />);

    expect(screen.getByTestId("released-event-marker")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /Replay history/ }));
    expect(screen.queryByTestId("released-event-marker")).not.toBeInTheDocument();
    for (let step = 0; step < 15; step += 1) fireEvent.click(screen.getByRole("button", { name: "Step one candle" }));
    expect(screen.getByTestId("released-event-marker")).toBeInTheDocument();
  });

  it("disables checkpoint readiness while replaying and restores it explicitly", async () => {
    const readiness = vi.fn();
    const view = render(<ReplayChartWorkspace bars={bars} label="15m" onCheckpointReadyChange={readiness} />);

    fireEvent.click(screen.getByRole("button", { name: /Replay/ }));
    await waitFor(() => expect(readiness).toHaveBeenLastCalledWith(false));
    expect(screen.getByText(/decision locking disabled/)).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Zoom in" }));
    await waitFor(() => expect(readiness).toHaveBeenLastCalledWith(false));
    expect(screen.getByRole("button", { name: "Play replay" })).toBeInTheDocument();

    view.rerender(<ReplayChartWorkspace bars={bars} label="1h" onCheckpointReadyChange={readiness} />);
    await waitFor(() => expect(readiness).toHaveBeenLastCalledWith(false));
    expect(screen.getByRole("button", { name: "Play replay" })).toBeInTheDocument();
    expect(screen.getByText(/decision locking disabled/)).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Return to checkpoint" }));
    await waitFor(() => expect(readiness).toHaveBeenLastCalledWith(true));
    expect(screen.getAllByText(/decision checkpoint/).length).toBeGreaterThan(0);
  });

  it("restores timeframe-local drawings after switching away and back", () => {
    const view = render(<ReplayChartWorkspace bars={bars} label="15m" />);
    const chart = screen.getByTestId("blind-replay-chart");
    Object.defineProperty(chart, "getBoundingClientRect", {
      value: () => ({ bottom: 560, height: 560, left: 0, right: 1180, top: 0, width: 1180, x: 0, y: 0, toJSON: () => ({}) }),
    });

    fireEvent.click(screen.getByRole("button", { name: "Horizontal level" }));
    fireEvent.click(chart, { clientX: 400, clientY: 260 });
    fireEvent.click(screen.getByRole("button", { name: "Crosshair" }));
    expect(chart.querySelectorAll('line[stroke="#7E57C2"]')).toHaveLength(1);

    view.rerender(<ReplayChartWorkspace bars={bars} label="1h" />);
    expect(chart.querySelectorAll('line[stroke="#7E57C2"]')).toHaveLength(0);

    view.rerender(<ReplayChartWorkspace bars={bars} label="15m" />);
    expect(chart.querySelectorAll('line[stroke="#7E57C2"]')).toHaveLength(1);
  });

  it("collects valid long geometry in entry-stop-target order", () => {
    const onPositionPlan = vi.fn<(plan: PositionPlan) => string | null>();
    const onPositionPlanCleared = vi.fn();
    const onPlaceArmedTrade = vi.fn(() => null);
    onPositionPlan.mockReturnValue(null);
    render(<ReplayChartWorkspace bars={bars} label="15m" m15AtrIndex={0.5} onPlaceArmedTrade={onPlaceArmedTrade} onPositionPlan={onPositionPlan} onPositionPlanCleared={onPositionPlanCleared} tradeBlockers={[]} tradeRemark="Rates and structure align." />);
    const chart = screen.getByTestId("blind-replay-chart");
    Object.defineProperty(chart, "getBoundingClientRect", {
      value: () => ({ bottom: 560, height: 560, left: 0, right: 1180, top: 0, width: 1180, x: 0, y: 0, toJSON: () => ({}) }),
    });

    fireEvent.click(screen.getByRole("button", { name: "Long position" }));
    fireEvent.click(chart, { clientX: 500, clientY: 264 });
    fireEvent.click(chart, { clientX: 500, clientY: 385 });
    fireEvent.click(chart, { clientX: 500, clientY: 100 });

    expect(onPositionPlan).toHaveBeenCalledTimes(1);
    const plan = onPositionPlan.mock.calls[0][0];
    expect(plan.direction).toBe("LONG");
    expect(plan.stopIndex).toBeLessThan(plan.entryIndex);
    expect(plan.targetIndex).toBeGreaterThan(plan.entryIndex);
    expect(screen.getByText(/Long entry, SL and TP/)).toBeInTheDocument();
    expect(screen.getByLabelText("long position drawing")).toBeInTheDocument();
    expect(screen.getByLabelText("Entry index")).toBeInTheDocument();
    expect(screen.getByLabelText("Stop-loss index")).toBeInTheDocument();
    expect(screen.getByLabelText("Take-profit index")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Zoom in" }));
    expect(screen.getByLabelText("long position drawing")).toBeInTheDocument();
    expect(onPositionPlanCleared).toHaveBeenCalledTimes(1);

    fireEvent.click(screen.getByLabelText("Arm this append-only paper trade"));
    fireEvent.click(screen.getByRole("button", { name: /Place armed trade/ }));
    expect(onPlaceArmedTrade).toHaveBeenCalledTimes(1);

    fireEvent.click(screen.getByRole("button", { name: "Delete selected" }));
    expect(screen.queryByLabelText("long position drawing")).not.toBeInTheDocument();
    expect(onPositionPlanCleared).toHaveBeenCalledTimes(2);
  });
});
