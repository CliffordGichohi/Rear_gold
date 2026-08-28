import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import type { MarketStructureSnapshot } from "@/lib/api";

import { MarketStructureChart } from "./market-structure-chart";


afterEach(cleanup);


const digest = "a".repeat(64);
const bars = Array.from({ length: 12 }, (_, index) => ({
  open_time: `2024-01-08T08:${String(index).padStart(2, "0")}:00Z`,
  close_time: `2024-01-08T08:${String(index + 1).padStart(2, "0")}:00Z`,
  open: 2020 + index * 0.1,
  high: 2021 + index * 0.1,
  low: 2019 + index * 0.1,
  close: 2020.5 + index * 0.1,
  volume: 10,
  complete: true,
  source_ids: [`bar-${index}`],
}));


const snapshot = {
  instrument: "XAUUSD",
  provider_code: "IC_MARKETS_MT5",
  provider_session_template: "IC_MARKETS_MT5_XAUUSD_V1",
  data_mode: "REAL_ONLY",
  is_synthetic: false,
  as_of: "2024-01-08T08:12:00Z",
  latest_bar_at: "2024-01-08T08:12:00Z",
  generated_at: "2024-01-08T08:12:01Z",
  source_staleness_seconds: 0,
  ruleset_version: "test",
  config: {},
  source_bar_count: bars.length,
  data_hash: digest,
  session: {
    primary: "LONDON",
    active: ["LONDON"],
    special_windows: [],
    calculated_at: "2024-01-08T08:12:00Z",
    evidence: {},
    ranges: [{
      name: "LONDON",
      timezone: "Europe/London",
      start_at: "2024-01-08T08:00:00Z",
      end_at: "2024-01-08T09:00:00Z",
      status: "ACTIVE",
      bar_count: 12,
      expected_bar_count: 60,
      completeness_pct: 20,
      open: 2020,
      high: 2022.1,
      low: 2019,
      close: 2021.6,
      range_size: 3.1,
      breakout_state: "INSIDE",
    }],
  },
  liquidity: {} as MarketStructureSnapshot["liquidity"],
  auction_automation: {
    as_of: "2024-01-08T08:12:00Z",
    ruleset_version: "gold-auction-automation-1",
    config: {},
    source_bar_count: bars.length,
    source_first_at: bars[0].open_time,
    source_last_at: bars.at(-1)?.close_time ?? null,
    data_hash: digest,
    macro_direction: "BULLISH",
    macro_bias_label: "MODERATELY_BULLISH",
    macro_available_at: "2024-01-08T07:30:00Z",
    liquidity_status: "NORMAL",
    timeframe_trends: { "15m": "BULLISH" },
    swings: [{
      identity: digest,
      timeframe: "15m",
      base_kind: "LOW",
      classification: "HIGHER_LOW",
      pivot_at: "2024-01-08T08:04:00Z",
      detected_at: "2024-01-08T08:06:00Z",
      price_level: 2019.4,
      atr14: 2,
      prominence_atr: 0.8,
      confidence: 70,
      epistemic_status: "CALCULATED",
      evidence: {},
    }],
    zones: [{
      identity: "b".repeat(64),
      timeframe: "15m",
      direction: "BULLISH",
      origin_at: "2024-01-08T08:02:00Z",
      created_at: "2024-01-08T08:03:00Z",
      detected_at: "2024-01-08T08:03:00Z",
      lower_bound: 2019.2,
      upper_bound: 2020.8,
      midpoint: 2020,
      broken_swing_identity: digest,
      broken_swing_level: 2020.7,
      creation_atr14: 2,
      state: "RETEST_CONFIRMED",
      first_touch_at: "2024-01-08T08:07:00Z",
      retest_confirmed_at: "2024-01-08T08:08:00Z",
      invalidated_at: null,
      expires_at: "2024-01-08T09:00:00Z",
      epistemic_status: "INFERRED",
      confidence: 74,
      detection_method: "M15_DISPLACEMENT_BREAK_V0_1",
      invalidation_condition: "M15 close below distal boundary",
      evidence: {},
    }],
    proposals: [{
      identity: "c".repeat(64),
      zone_identity: "b".repeat(64),
      family: "CONFIRMED_RETEST_V0_1",
      direction: "BULLISH",
      disposition: "PAPER_READY",
      triggered_at: "2024-01-08T08:09:00Z",
      entry_reference: 2020.7,
      stop: 2019,
      target: 2023,
      target_swing_identity: digest,
      planned_risk_usd: 49.3,
      quantity_ounces: 29,
      reward_to_risk: 1.35,
      macro_direction: "BULLISH",
      macro_relationship: "ALIGNED",
      liquidity_status: "NORMAL",
      epistemic_status: "INFERRED",
      explanation: "Paper-only proposal.",
      evidence: { live_order_permitted: false },
    }],
    warnings: [],
  },
  timeframes: [],
  chart_bars: bars,
} satisfies MarketStructureSnapshot;


describe("MarketStructureChart auction automation overlays", () => {
  it("renders confirmed swings, inferred zones, and paper proposals", () => {
    const { container } = render(<MarketStructureChart snapshot={snapshot} />);

    expect(screen.getByRole("img", { name: /confirmed swings/i })).toBeInTheDocument();
    expect(container.querySelectorAll("[data-swing-classification='HIGHER_LOW']")).toHaveLength(1);
    expect(container.querySelectorAll("[data-zone-state='RETEST_CONFIRMED']")).toHaveLength(1);
    expect(container.querySelectorAll("[data-proposal-disposition='PAPER_READY']")).toHaveLength(1);
    expect(screen.getByText(/paper proposals/i)).toBeInTheDocument();
  });
});
