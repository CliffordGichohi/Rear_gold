import { describe, expect, it } from "vitest";

import {
  backtestDataRangeSchema,
  backtestRunSchema,
  decisionSnapshotSchema,
  intelligenceSnapshotSchema,
  marketLiquiditySchema,
  marketObservationSchema,
} from "./api";

const snapshot = {
  id: "snapshot-1",
  instrument: "XAUUSD",
  as_of: "2026-07-17T16:00:00Z",
  overall_score: 15.583,
  bullish_score: 15.583,
  bearish_score: 0,
  neutrality_score: 84.417,
  conflict_score: 0,
  confidence: 25.544,
  evidence_coverage: 30,
  bias: "SLIGHTLY_BULLISH",
  execution_state: "ARMED",
  dominant_driver: "REAL_YIELD",
  main_contradiction: null,
  ruleset_version: "vertical-slice-1",
  reasoning: {
    session: "NEW_YORK",
    summary: "Falling real yields support gold; price acceptance is inferred.",
    contributions: [
      {
        name: "REAL_YIELD_5D_IMPULSE_V1",
        budget: 0.2,
        driver: "REAL_YIELD",
        formula: "budget * direction * strength * certainty",
        available: true,
        certainty: 0.92,
        signal_id: "signal-1",
        contribution: 10.38,
      },
    ],
    confirmation_requirement: "Two complete five-minute closes above resistance.",
    invalidation_requirement: "Real yield reverses higher and gold loses support.",
    confidence_is_probability_of_profit: false,
  },
  layers: Array.from({ length: 7 }, (_, index) => ({
    name: `LAYER_${index + 1}`,
    number: index + 1,
    status: index < 4 ? "UNKNOWN" : "PARTIAL",
    summary: "Explicit capability state.",
  })),
  signal_ids: ["signal-1"],
};

describe("intelligenceSnapshotSchema", () => {
  it("accepts the explainable vertical-slice contract", () => {
    const parsed = intelligenceSnapshotSchema.parse(snapshot);

    expect(parsed.bias).toBe("SLIGHTLY_BULLISH");
    expect(parsed.layers).toHaveLength(7);
    expect(parsed.reasoning.confidence_is_probability_of_profit).toBe(false);
  });

  it("rejects layer numbers outside the seven-layer model", () => {
    const invalid = structuredClone(snapshot);
    invalid.layers[0].number = 8;

    expect(() => intelligenceSnapshotSchema.parse(invalid)).toThrow();
  });
});

describe("decisionSnapshotSchema", () => {
  it("accepts one auditable seven-layer decision", () => {
    const parsed = decisionSnapshotSchema.parse({
      id: "decision-1",
      instrument: "XAUUSD",
      provider_code: "IC_MARKETS_MT5",
      as_of: "2026-07-24T12:00:00Z",
      epistemic_status: "INFERRED",
      directional_score: 12,
      bullish_score: 18,
      bearish_score: 6,
      neutral_conflict_score: 50,
      directional_confidence: 70,
      execution_confidence: 52,
      directional_evidence_coverage_pct: 60,
      phase1_factor_coverage_pct: 85,
      book_factor_coverage_pct: 62,
      book_usable_coverage_pct: 55,
      bias: "MODERATELY_BULLISH",
      regime: "SLOWDOWN",
      reaction_function: "GROWTH_LABOUR_FOCUS",
      dominant_driver: "REAL_YIELD",
      main_contradiction: "The dollar is strengthening.",
      highest_risk_assumption: "Portfolio risk is unknown.",
      upcoming_catalyst: null,
      event_risk: "LOW",
      current_session: "LONDON_NEW_YORK_OVERLAP",
      liquidity_state: "NORMAL",
      price_macro_alignment: "CONFIRMING",
      execution_state: "WAIT_ACCOUNT_RISK_STATE_UNKNOWN",
      layers: Array.from({ length: 7 }, (_, index) => ({
        number: index + 1,
        name: `LAYER_${index + 1}`,
        role: [5, 7].includes(index + 1) ? "EXECUTION_GATE" : "DIRECTIONAL",
        status: "PARTIAL",
        operational_status: index + 1 === 7 ? "GATED" : "ACTIVE",
        book_factor_count: 10,
        known_factor_count: 6,
        usable_factor_count: 5,
        book_coverage_pct: 60,
        phase1_coverage_pct: 80,
        directional_contribution: [5, 7].includes(index + 1) ? null : 2,
        confidence: [5, 7].includes(index + 1) ? null : 70,
        summary: "Traceable layer summary.",
        supporting_evidence: [],
        contradicting_evidence: [],
        unknown_factors: [],
      })),
      components: [],
      execution_plan: {
        trigger: { state: "CONFIRMED" },
        is_trade_instruction: false,
      },
      reasoning: {
        summary: "Macro is supportive but account risk is unknown.",
      },
      fundamental_snapshot_id: "fundamental-1",
      fundamental_data_hash: "f".repeat(64),
      structure_data_hash: "s".repeat(64),
      registry_hash: "r".repeat(64),
      data_hash: "d".repeat(64),
      ruleset_version: "gold-reference-book-7-layer-v1-decision-v1",
      created_at: "2026-07-24T12:00:01Z",
    });

    expect(parsed.layers).toHaveLength(7);
    expect(parsed.execution_state).toBe("WAIT_ACCOUNT_RISK_STATE_UNKNOWN");
    expect(parsed.execution_plan.is_trade_instruction).toBe(false);
  });
});

describe("backtest contracts", () => {
  it("accepts an auditable completed run", () => {
    const parsed = backtestRunSchema.parse({
      id: "run-1",
      strategy: "ASIA_RANGE_ACCEPTANCE_V1",
      strategy_version: "1.0.0",
      instrument: "XAUUSD",
      provider_code: "IC_MARKETS_MT5",
      start: "2026-06-29T00:00:00Z",
      end: "2026-07-23T08:15:00Z",
      status: "COMPLETED",
      parameters: { confirmation_bars: 2 },
      data_hash: "a".repeat(64),
      source_bar_count: 29_022,
      metrics: {
        observations: 4_961,
        trades: 9,
        wins: 4,
        losses: 5,
        win_rate_pct: 44.444,
        average_r: 0.252,
        median_r: -1.036,
        expectancy_r: 0.252,
        expectancy_r_95ci: [-0.779, 1.284],
        expectancy_r_bootstrap_95ci: [-0.701, 1.198],
        profit_factor: 1.416,
        total_net_pnl: 217.36,
        total_costs: 70.97,
        return_pct: 2.174,
        final_equity: 10_217.36,
        maximum_drawdown: 221.3,
        maximum_drawdown_pct: 2.158,
        sharpe_ratio: null,
        sortino_ratio: null,
        average_mfe_r: 1.362,
        average_mae_r: 0.717,
        average_holding_minutes: 57.22,
        benchmark_buy_hold_pct: 0.967,
        monte_carlo_trade_order: {
          status: "COMPLETED",
          iterations: 2_000,
          trade_count: 9,
          drawdown_pct_p50: 2.158,
          drawdown_pct_p95: 3.102,
          drawdown_pct_p99: 3.5,
          warning: "Sequence-risk diagnostic only.",
        },
      },
      equity_curve: [
        { timestamp: "2026-07-01T10:00:00Z", equity: 10_217.36 },
      ],
      provenance: { lookahead_policy: "AVAILABLE_AT_OR_BEFORE_CLOCK" },
      created_at: "2026-07-23T08:00:00Z",
      completed_at: "2026-07-23T08:00:01Z",
      trades: [],
    });

    expect(parsed.metrics.trades).toBe(9);
    expect(
      parsed.metrics.monte_carlo_trade_order?.drawdown_pct_p95,
    ).toBe(3.102);
    expect(parsed.provenance.lookahead_policy).toBe(
      "AVAILABLE_AT_OR_BEFORE_CLOCK",
    );
  });

  it("requires an explicit observed-data range contract", () => {
    expect(() =>
      backtestDataRangeSchema.parse({
        instrument: "XAUUSD",
        provider_code: "IC_MARKETS_MT5",
        earliest: null,
        latest: null,
        bar_count: 0,
      }),
    ).toThrow();
  });
});

describe("cross-market contracts", () => {
  it("accepts an auditable point-in-time observation", () => {
    const parsed = marketObservationSchema.parse({
      series_code: "US_REAL_YIELD_10Y",
      observation_time: "2026-07-21T20:00:00Z",
      value: 2.37,
      unit: "PERCENT",
      available_at: "2026-07-22T04:00:00Z",
      vintage: "2026-07-22",
      is_revision: false,
      source_record_key: "DFII10:2026-07-21",
    });

    expect(parsed.available_at).toBe("2026-07-22T04:00:00Z");
  });
});

describe("liquidity contracts", () => {
  it("accepts an execution-only broker-liquidity snapshot", () => {
    const parsed = marketLiquiditySchema.parse({
      as_of: "2026-07-23T08:15:00Z",
      latest_bar_at: "2026-07-23T08:15:00Z",
      primary_session: "LONDON",
      special_windows: [],
      status: "NORMAL",
      epistemic_status: "CALCULATED",
      ruleset_version: "broker-liquidity-1",
      current_window_minutes: 15,
      current_bar_count: 15,
      baseline_bar_count: 3766,
      spread_observation_count: 3766,
      current_spread_points: 6,
      current_spread_price: 0.06,
      current_spread_bps: 0.1456,
      baseline_spread_points: 5,
      p95_spread_points: 10,
      spread_percentile: 69.53,
      current_range_bps: 2.6204,
      baseline_range_bps: 3.5696,
      p95_range_bps: 8.2634,
      range_percentile: 25.28,
      current_tick_volume: 233,
      baseline_tick_volume: 292,
      tick_volume_percentile: 29.35,
      execution_confidence_multiplier: 1,
      data_quality_score: 100,
      freshness_score: 100,
      explanation: "Execution conditions are normal; this is not directional.",
      evidence: {
        source: "IC_MARKETS_MT5",
        volume_scope: "Broker tick activity",
      },
      warnings: [],
      data_hash: "b".repeat(64),
    });

    expect(parsed.execution_confidence_multiplier).toBe(1);
    expect(parsed.status).toBe("NORMAL");
  });
});
