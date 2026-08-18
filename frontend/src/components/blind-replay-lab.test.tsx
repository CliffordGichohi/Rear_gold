import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { BlindReplayLab, positionPlanToExecution } from "./blind-replay-lab";


afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});


const status = {
  protocol: "GOLD_BLIND_DISCRETIONARY_REPLAY_V1_PROTOCOL_1_0",
  ready: true,
  phase: "PRACTICE",
  practice_completed: 0,
  practice_total: 20,
  scored_completed: 0,
  scored_total: 240,
  total_locked: 0,
  next_case_alias: "P-001",
  ledger_head_sha256: "0".repeat(64),
  scored_outcomes_locked: true,
  research_status: "HUMAN_LABELING_REQUIRED_EDGE_NOT_EVALUATED",
};


const bar = { ordinal: 0, open: 99.9, high: 100.2, low: 99.8, close: 100.1, volume: 10 };
const casePayload = {
  case_alias: "P-001",
  mode: "PRACTICE",
  mode_sequence: 1,
  global_sequence: 1,
  session_code: "LONDON",
  checkpoint_label: "SESSION_OPEN_PLUS_60_MINUTES",
  reference_index: 100,
  m15_atr_index: 0.15,
  charts: { "1w": [bar], "1d": [bar], "4h": [bar], "1h": [bar], "15m": [bar], "5m": [bar], "1m": [bar] },
  chart_availability: { status: "PRACTICE_PARTIAL_HISTORY_ALLOWED_ZERO_CREDIT", counts: { "15m": 1 }, required: { "15m": 160 } },
  session: { known_levels: [{ code: "ASIA_HIGH", level: 100.15 }] },
  structure: { timeframes: [{ timeframe: "1h", trend: "UP", status: "AVAILABLE" }] },
  fundamental: {
    bias_label: "BULLISH",
    directional_score: 42,
    confidence: 70,
    summary: "Point-in-time context",
    components: [{
      code: "REAL_YIELD",
      direction: 1,
      epistemic_status: "CALCULATED",
      data_quality: 92,
      freshness: 80,
      explanation: "Falling real yield lowers gold's opportunity cost.",
    }],
  },
  cross_market: { status: "AVAILABLE", quality: 80 },
  positioning: { crowding_state: "NEUTRAL", participation_state: "UNKNOWN" },
  released_events: [],
  liquidity: { status: "AVAILABLE", current_tick_volume: 20, baseline_tick_volume: 18 },
  gc_order_flow: { status: "UNKNOWN_NOT_IN_SEALED_188_DATE_SAMPLE", warning: "Nothing was imputed." },
  display_policy: {
    absolute_date_hidden: true,
    absolute_time_hidden: true,
    absolute_price_hidden: true,
    completed_candles_only: true,
    future_scored_path_present: false,
  },
  payload_sha256: "a".repeat(64),
};


describe("BlindReplayLab", () => {
  it("maps valid position drawings arithmetically without changing frozen bounds", () => {
    expect(positionPlanToExecution({
      direction: "LONG",
      entryIndex: 99.9,
      stopIndex: 99.8,
      targetIndex: 100.1,
    }, 0.2)).toEqual({
      error: null,
      execution: {
        action: "LONG",
        trigger: "PULLBACK_LIMIT",
        entryOffsetAtr: -0.5,
        stopDistanceAtr: 0.5,
        targetR: 2,
      },
    });

    const invalid = positionPlanToExecution({
      direction: "SHORT",
      entryIndex: 100.6,
      stopIndex: 100.7,
      targetIndex: 100.4,
    }, 0.2);
    expect(invalid.execution).toBeNull();
    expect(invalid.error).toMatch(/maximum is 2\.00 ATR/);
  });

  it("renders a normalized checkpoint without calendar or absolute price labels", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => ({
      ok: true,
      status: 200,
      json: async () => ({ case: casePayload, progress: status }),
    })));
    render(<BlindReplayLab />);
    expect(await screen.findByText(/Case P-001/)).toBeInTheDocument();
    expect(screen.getByText(/How to label each case/)).toBeInTheDocument();
    expect(screen.getByText(/Point-in-time macro pulse/)).toBeInTheDocument();
    expect(screen.getByText("FALLING")).toBeInTheDocument();
    expect(screen.getByText(/Falling real yield lowers gold's opportunity cost/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Fibonacci retracement" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Long position" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Short position" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Replay/ })).toBeInTheDocument();
    expect(screen.getByText(/normalized reference 100/i)).toBeInTheDocument();
    expect(document.body.textContent).not.toMatch(/202[1-6]-\d{2}-\d{2}/);
    expect(screen.getByTestId("blind-replay-chart").querySelector('rect[fill="#089981"]')).not.toBeNull();
    expect(screen.getByRole("button", { name: "Lock decision permanently" })).toBeDisabled();

    fireEvent.click(screen.getByRole("button", { name: "LONG" }));
    fireEvent.change(screen.getByLabelText("Entry trigger"), {
      target: { value: "PULLBACK_LIMIT" },
    });
    const offset = screen.getByLabelText("Entry offset · M15 ATR");
    expect(offset).toHaveAttribute("min", "-2");
    expect(offset).toHaveAttribute("max", "0");
    expect(screen.getByText(/Long pullback: use a negative offset/)).toBeInTheDocument();
    expect(screen.getByText(/Requested entry index/)).toBeInTheDocument();
  });
});
