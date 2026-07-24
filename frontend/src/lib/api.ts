import { z } from "zod";

const healthSchema = z.object({
  status: z.enum(["ok", "degraded"]),
  service: z.string(),
  checks: z.record(z.string(), z.string()),
});

export type Health = z.infer<typeof healthSchema>;

export const intelligenceLayerSchema = z.object({
  name: z.string(),
  number: z.number().int().min(1).max(7),
  status: z.string(),
  summary: z.string(),
});

export const contributionSchema = z.object({
  name: z.string(),
  budget: z.number(),
  driver: z.string(),
  formula: z.string(),
  available: z.boolean(),
  certainty: z.number(),
  signal_id: z.string().optional(),
  contribution: z.number(),
});

export const intelligenceSnapshotSchema = z.object({
  id: z.string(),
  instrument: z.string(),
  as_of: z.string(),
  overall_score: z.number(),
  bullish_score: z.number(),
  bearish_score: z.number(),
  neutrality_score: z.number(),
  conflict_score: z.number(),
  confidence: z.number(),
  evidence_coverage: z.number(),
  bias: z.string(),
  execution_state: z.string(),
  dominant_driver: z.string().nullable(),
  main_contradiction: z.string().nullable(),
  ruleset_version: z.string(),
  reasoning: z.object({
    session: z.string(),
    summary: z.string(),
    contributions: z.array(contributionSchema),
    confirmation_requirement: z.string(),
    invalidation_requirement: z.string(),
    confidence_is_probability_of_profit: z.boolean(),
  }),
  layers: z.array(intelligenceLayerSchema),
  signal_ids: z.array(z.string()),
});

export const dataHealthSchema = z.object({
  status: z.string(),
  open_issue_count: z.number().int(),
  warning_count: z.number().int(),
  error_count: z.number().int(),
  stale_series: z.array(z.string()),
});

export const fundamentalComponentSchema = z.object({
  code: z.string(),
  layer: z.number().int().min(1).max(7),
  direction: z.number().min(-1).max(1),
  strength: z.number().min(0).max(100),
  confidence: z.number().min(0).max(100),
  freshness: z.number().min(0).max(100),
  data_quality: z.number().min(0).max(100),
  weight: z.number().min(0).max(100),
  contribution: z.number().min(-100).max(100),
  epistemic_status: z.enum(["OBSERVED", "CALCULATED", "INFERRED", "UNKNOWN"]),
  explanation: z.string(),
  evidence: z.record(z.string(), z.unknown()),
});

export const fundamentalSnapshotSchema = z.object({
  id: z.string(),
  instrument: z.string(),
  as_of: z.string(),
  directional_score: z.number().min(-100).max(100),
  confidence: z.number().min(0).max(100),
  coverage: z.number().min(0).max(100),
  bias: z.string(),
  regime: z.string(),
  reaction_function: z.string(),
  dominant_driver: z.string().nullable(),
  main_contradiction: z.string().nullable(),
  event_risk: z.string(),
  upcoming_catalyst: z.record(z.string(), z.unknown()).nullable(),
  components: z.array(fundamentalComponentSchema),
  layers: z.array(
    z.object({
      layer: z.number().int().min(1).max(7),
      status: z.string(),
      known_components: z.array(z.string()),
      unknown_components: z.array(z.string()),
    }),
  ),
  reasoning: z
    .object({
      summary: z.string(),
      missing_drivers: z.array(z.string()),
      crowding: z.record(z.string(), z.unknown()),
      contradictions: z.array(z.string()),
      score_is_not_trade_signal: z.boolean(),
      confidence_is_not_win_probability: z.boolean(),
    })
    .passthrough(),
  registry_hash: z.string(),
  data_hash: z.string(),
  ruleset_version: z.string(),
  created_at: z.string(),
});

export const decisionLayerSchema = z.object({
  number: z.number().int().min(1).max(7),
  name: z.string(),
  role: z.enum(["DIRECTIONAL", "EXECUTION_GATE"]),
  status: z.enum(["COMPLETE", "PARTIAL", "UNKNOWN"]),
  operational_status: z.string(),
  book_factor_count: z.number().int().nonnegative(),
  known_factor_count: z.number().int().nonnegative(),
  usable_factor_count: z.number().int().nonnegative(),
  book_coverage_pct: z.number().min(0).max(100),
  phase1_coverage_pct: z.number().min(0).max(100),
  directional_contribution: z.number().nullable(),
  confidence: z.number().min(0).max(100).nullable(),
  summary: z.string(),
  supporting_evidence: z.array(z.string()),
  contradicting_evidence: z.array(z.string()),
  unknown_factors: z.array(z.string()),
});

export const decisionSnapshotSchema = z.object({
  id: z.string(),
  instrument: z.string(),
  provider_code: z.string().nullable(),
  as_of: z.string(),
  epistemic_status: z.literal("INFERRED"),
  directional_score: z.number().min(-100).max(100),
  bullish_score: z.number().min(0).max(100),
  bearish_score: z.number().min(0).max(100),
  neutral_conflict_score: z.number().min(0).max(100),
  directional_confidence: z.number().min(0).max(100),
  execution_confidence: z.number().min(0).max(100),
  directional_evidence_coverage_pct: z.number().min(0).max(100),
  phase1_factor_coverage_pct: z.number().min(0).max(100),
  book_factor_coverage_pct: z.number().min(0).max(100),
  book_usable_coverage_pct: z.number().min(0).max(100),
  bias: z.string(),
  regime: z.string(),
  reaction_function: z.string(),
  dominant_driver: z.string().nullable(),
  main_contradiction: z.string().nullable(),
  highest_risk_assumption: z.string(),
  upcoming_catalyst: z.record(z.string(), z.unknown()).nullable(),
  event_risk: z.string(),
  current_session: z.string(),
  liquidity_state: z.string(),
  price_macro_alignment: z.string(),
  execution_state: z.string(),
  layers: z.array(decisionLayerSchema),
  components: z.array(fundamentalComponentSchema),
  execution_plan: z.record(z.string(), z.unknown()),
  reasoning: z.record(z.string(), z.unknown()),
  fundamental_snapshot_id: z.string(),
  fundamental_data_hash: z.string(),
  structure_data_hash: z.string().nullable(),
  registry_hash: z.string(),
  data_hash: z.string(),
  ruleset_version: z.string(),
  created_at: z.string(),
});

export const factorCoverageItemSchema = z.object({
  code: z.string(),
  name: z.string(),
  domain: z.string(),
  layer: z.number().int().min(1).max(7).nullable(),
  declared_epistemic_status: z.string(),
  current_epistemic_status: z.string(),
  implementation_status: z.string(),
  phase1_required: z.boolean(),
  source_class: z.string(),
  record_count: z.number().int(),
  latest_available_at: z.string().nullable(),
  age_seconds: z.number().int().nonnegative().nullable(),
  freshness_status: z.enum(["FRESH", "STALE", "NOT_APPLICABLE", "UNKNOWN"]),
  usable_now: z.boolean(),
  dependencies: z.array(z.string()),
  dependency_mode: z.enum(["ALL", "ANY"]),
  missing_dependencies: z.array(z.string()),
  note: z.string(),
});

export const factorCoverageSchema = z.object({
  as_of: z.string(),
  registry_version: z.string(),
  registry_hash: z.string(),
  total_factors: z.number().int(),
  known_factors: z.number().int(),
  phase1_required_factors: z.number().int(),
  phase1_known_factors: z.number().int(),
  phase1_coverage_pct: z.number().min(0).max(100),
  book_layer_factors: z.number().int(),
  book_layer_known_factors: z.number().int(),
  book_layer_usable_factors: z.number().int(),
  book_factor_coverage_pct: z.number().min(0).max(100),
  book_usable_coverage_pct: z.number().min(0).max(100),
  layers: z.array(
    z.object({
      layer: z.number().int().min(1).max(7),
      factor_count: z.number().int(),
      known_factor_count: z.number().int(),
      usable_factor_count: z.number().int(),
      book_coverage_pct: z.number().min(0).max(100),
      book_usable_coverage_pct: z.number().min(0).max(100),
      phase1_required_count: z.number().int(),
      phase1_known_count: z.number().int(),
      phase1_coverage_pct: z.number().min(0).max(100),
    }),
  ),
  factors: z.array(factorCoverageItemSchema),
});

const nullableMetric = z.number().nullable();
const groupedBacktestMetricsSchema = z.object({
  trades: z.number().int(),
  win_rate_pct: nullableMetric,
  net_pnl: z.number(),
  average_r: nullableMetric,
});

export const backtestMetricsSchema = z
  .object({
    observations: z.number().int(),
    trades: z.number().int(),
    wins: z.number().int(),
    losses: z.number().int(),
    win_rate_pct: nullableMetric,
    average_r: nullableMetric,
    median_r: nullableMetric,
    expectancy_r: nullableMetric,
    expectancy_r_95ci: z.tuple([nullableMetric, nullableMetric]),
    expectancy_r_bootstrap_95ci: z
      .tuple([nullableMetric, nullableMetric])
      .optional(),
    profit_factor: nullableMetric,
    total_net_pnl: z.number(),
    total_costs: z.number(),
    return_pct: z.number(),
    final_equity: z.number(),
    maximum_drawdown: z.number(),
    maximum_drawdown_pct: z.number(),
    sharpe_ratio: nullableMetric,
    sortino_ratio: nullableMetric,
    average_mfe_r: nullableMetric,
    average_mae_r: nullableMetric,
    average_holding_minutes: nullableMetric,
    benchmark_buy_hold_pct: nullableMetric,
    monte_carlo_trade_order: z
      .object({
        status: z.string(),
        iterations: z.number().int(),
        trade_count: z.number().int(),
        drawdown_pct_p50: nullableMetric,
        drawdown_pct_p95: nullableMetric,
        drawdown_pct_p99: nullableMetric,
        warning: z.string(),
      })
      .optional(),
    performance_by_side: z
      .record(z.string(), groupedBacktestMetricsSchema)
      .optional(),
    performance_by_month: z
      .record(z.string(), groupedBacktestMetricsSchema)
      .optional(),
    performance_by_regime: z
      .record(z.string(), groupedBacktestMetricsSchema)
      .optional(),
  })
  .passthrough();

export const backtestTradeSchema = z.object({
  sequence: z.number().int(),
  side: z.string(),
  signal_time: z.string(),
  entry_time: z.string(),
  exit_time: z.string(),
  entry_price: z.number(),
  exit_price: z.number(),
  stop_price: z.number(),
  target_price: z.number(),
  quantity_lots: z.number(),
  exit_reason: z.string(),
  gross_pnl: z.number(),
  costs: z.number(),
  net_pnl: z.number(),
  r_multiple: z.number(),
  mfe_r: z.number(),
  mae_r: z.number(),
  holding_minutes: z.number().int(),
  evidence: z.record(z.string(), z.unknown()),
});

export const backtestRunSchema = z.object({
  id: z.string(),
  strategy: z.string(),
  strategy_version: z.string(),
  instrument: z.string(),
  provider_code: z.string(),
  start: z.string(),
  end: z.string(),
  status: z.string(),
  parameters: z.record(z.string(), z.unknown()),
  data_hash: z.string(),
  source_bar_count: z.number().int(),
  metrics: backtestMetricsSchema,
  equity_curve: z.array(
    z.object({
      timestamp: z.string(),
      equity: z.number(),
    }),
  ),
  provenance: z.record(z.string(), z.unknown()),
  created_at: z.string(),
  completed_at: z.string().nullable(),
  trades: z.array(backtestTradeSchema),
});

export const backtestDataRangeSchema = z.object({
  instrument: z.string(),
  provider_code: z.string(),
  earliest: z.string().nullable(),
  latest: z.string().nullable(),
  bar_count: z.number().int(),
  ready: z.boolean(),
});

export const economicEventSchema = z.object({
  id: z.string(),
  event_code: z.string(),
  name: z.string(),
  event_type: z.string(),
  scheduled_at: z.string(),
  released_at: z.string().nullable(),
  importance: z.number().int().min(1).max(5),
  status: z.string(),
  provider_code: z.string(),
  source_event_key: z.string(),
  available_at: z.string(),
  is_synthetic: z.boolean(),
  forecasts: z.array(z.record(z.string(), z.unknown())),
  releases: z.array(z.record(z.string(), z.unknown())),
});

export const economicSurpriseSchema = z.object({
  id: z.string(),
  event_id: z.string(),
  release_id: z.string(),
  forecast_id: z.string(),
  event_code: z.string(),
  event_name: z.string(),
  component_code: z.string(),
  released_at: z.string(),
  available_at: z.string(),
  raw_surprise: z.number(),
  standardized_surprise: z.number(),
  gold_direction: z.number().min(-1).max(1),
  strength: z.number().min(0).max(100),
  confidence: z.number().min(0).max(100),
  history_count: z.number().int(),
  method: z.string(),
  epistemic_status: z.string(),
  explanation: z.string(),
  evidence: z.record(z.string(), z.unknown()),
  ruleset_version: z.string(),
  data_hash: z.string(),
  is_synthetic: z.boolean(),
});

export const eventStudyRunSchema = z.object({
  id: z.string(),
  instrument: z.string(),
  provider_code: z.string(),
  start: z.string(),
  end: z.string(),
  status: z.string(),
  parameters: z.record(z.string(), z.unknown()),
  data_hash: z.string(),
  candidate_count: z.number().int(),
  eligible_count: z.number().int(),
  exclusions: z.record(z.string(), z.unknown()),
  results: z.record(z.string(), z.unknown()),
  created_at: z.string(),
  completed_at: z.string().nullable(),
});

export const licensedProviderHealthSchema = z
  .object({
    provider: z.enum([
      "trading_economics",
      "cme_fedwatch",
      "atlanta_fed_mpt",
    ]),
    configured: z.boolean(),
    connection_status: z.enum(["not_tested", "not_configured"]),
    note: z.string(),
  })
  .passthrough();

export const structureDetectionSchema = z.object({
  kind: z.string(),
  direction: z.string(),
  timestamp: z.string(),
  detected_at: z.string(),
  price_level: z.number(),
  timeframe: z.string(),
  detection_method: z.string(),
  confidence: z.number().min(0).max(100),
  epistemic_status: z.enum(["CALCULATED", "INFERRED"]),
  evidence: z.record(z.string(), z.unknown()),
  invalidation_condition: z.string(),
});

export const timeframeStructureSchema = z.object({
  timeframe: z.string(),
  status: z.string(),
  source_bar_count: z.number().int(),
  complete_bar_count: z.number().int(),
  last_close: z.number().nullable(),
  atr14: z.number().nullable(),
  trend: z.string(),
  support: z.number().nullable(),
  resistance: z.number().nullable(),
  range_low: z.number().nullable(),
  range_high: z.number().nullable(),
  compression_ratio: z.number().nullable(),
  momentum_atr: z.number().nullable(),
  detections: z.array(structureDetectionSchema),
});

export const marketLiquiditySchema = z.object({
  as_of: z.string(),
  latest_bar_at: z.string().nullable(),
  primary_session: z.string(),
  special_windows: z.array(z.string()),
  status: z.enum(["NORMAL", "ELEVATED", "ABNORMAL", "UNKNOWN"]),
  epistemic_status: z.enum(["CALCULATED", "UNKNOWN"]),
  ruleset_version: z.string(),
  current_window_minutes: z.number().int().positive(),
  current_bar_count: z.number().int().nonnegative(),
  baseline_bar_count: z.number().int().nonnegative(),
  spread_observation_count: z.number().int().nonnegative(),
  current_spread_points: z.number().nullable(),
  current_spread_price: z.number().nullable(),
  current_spread_bps: z.number().nullable(),
  baseline_spread_points: z.number().nullable(),
  p95_spread_points: z.number().nullable(),
  spread_percentile: z.number().min(0).max(100).nullable(),
  current_range_bps: z.number().nullable(),
  baseline_range_bps: z.number().nullable(),
  p95_range_bps: z.number().nullable(),
  range_percentile: z.number().min(0).max(100).nullable(),
  current_tick_volume: z.number().nullable(),
  baseline_tick_volume: z.number().nullable(),
  tick_volume_percentile: z.number().min(0).max(100).nullable(),
  execution_confidence_multiplier: z.number().min(0).max(1),
  data_quality_score: z.number().min(0).max(100),
  freshness_score: z.number().min(0).max(100),
  explanation: z.string(),
  evidence: z.record(z.string(), z.unknown()),
  warnings: z.array(z.string()),
  data_hash: z.string(),
});

export const marketStructureSnapshotSchema = z.object({
  instrument: z.string(),
  provider_code: z.string(),
  provider_session_template: z.string(),
  data_mode: z.enum(["REAL_ONLY", "SYNTHETIC_ONLY"]),
  is_synthetic: z.boolean(),
  as_of: z.string(),
  latest_bar_at: z.string(),
  generated_at: z.string(),
  source_staleness_seconds: z.number().int().nonnegative(),
  ruleset_version: z.string(),
  config: z.record(z.string(), z.union([z.number(), z.string()])),
  source_bar_count: z.number().int(),
  data_hash: z.string(),
  session: z.object({
    primary: z.string(),
    active: z.array(z.string()),
    special_windows: z.array(z.string()),
    calculated_at: z.string(),
    evidence: z.record(z.string(), z.string()),
    ranges: z.array(
      z.object({
        name: z.string(),
        timezone: z.string(),
        start_at: z.string(),
        end_at: z.string(),
        status: z.string(),
        bar_count: z.number().int(),
        expected_bar_count: z.number().int(),
        completeness_pct: z.number().min(0).max(100),
        open: z.number().nullable(),
        high: z.number().nullable(),
        low: z.number().nullable(),
        close: z.number().nullable(),
        range_size: z.number().nullable(),
        breakout_state: z.string(),
      }),
    ),
  }),
  liquidity: marketLiquiditySchema,
  timeframes: z.array(timeframeStructureSchema),
  chart_bars: z.array(
    z.object({
      open_time: z.string(),
      close_time: z.string(),
      open: z.number(),
      high: z.number(),
      low: z.number(),
      close: z.number(),
      volume: z.number().nullable(),
      complete: z.boolean(),
      source_ids: z.array(z.string()),
    }),
  ),
});

export const marketObservationSchema = z.object({
  series_code: z.string(),
  observation_time: z.string(),
  value: z.number(),
  unit: z.string(),
  available_at: z.string(),
  vintage: z.string(),
  is_revision: z.boolean(),
  source_record_key: z.string(),
});

export type IntelligenceSnapshot = z.infer<typeof intelligenceSnapshotSchema>;
export type DataHealth = z.infer<typeof dataHealthSchema>;
export type FundamentalComponent = z.infer<typeof fundamentalComponentSchema>;
export type FundamentalSnapshot = z.infer<typeof fundamentalSnapshotSchema>;
export type DecisionSnapshot = z.infer<typeof decisionSnapshotSchema>;
export type FactorCoverage = z.infer<typeof factorCoverageSchema>;
export type BacktestRun = z.infer<typeof backtestRunSchema>;
export type BacktestDataRange = z.infer<typeof backtestDataRangeSchema>;
export type EconomicEvent = z.infer<typeof economicEventSchema>;
export type EconomicSurprise = z.infer<typeof economicSurpriseSchema>;
export type EventStudyRun = z.infer<typeof eventStudyRunSchema>;
export type LicensedProviderHealth = z.infer<
  typeof licensedProviderHealthSchema
>;
export type MarketStructureSnapshot = z.infer<typeof marketStructureSnapshotSchema>;
export type MarketObservation = z.infer<typeof marketObservationSchema>;

export const publicApiUrl =
  process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000/api/v1";

export async function getLiveness(signal?: AbortSignal): Promise<Health> {
  const response = await fetch(`${publicApiUrl}/health/live`, {
    cache: "no-store",
    signal,
  });
  if (!response.ok) {
    throw new Error(`Health request failed with HTTP ${response.status}`);
  }
  return healthSchema.parse(await response.json());
}
