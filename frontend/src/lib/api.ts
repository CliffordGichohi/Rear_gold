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

const sessionEdgeRobustnessRowSchema = z.object({
  label: z.string(),
  trades: z.number().int(),
  win_rate_pct: nullableMetric,
  net_expectancy_r: nullableMetric,
  total_net_pnl: z.number(),
  total_costs: z.number(),
  profit_factor: nullableMetric,
  exclusions: z.record(z.string(), z.number().int()),
  target_r: z.number().optional(),
  max_holding_minutes: z.number().int().optional(),
});

export const sessionEdgeStrategyMetricsSchema = backtestMetricsSchema.extend({
  candidate_version: z.string(),
  strategy_mode: z.string(),
  triggered_opportunities: z.number().int(),
  eligible_trades: z.number().int(),
  exclusion_funnel: z.record(z.string(), z.number().int()),
  gross_expectancy_r: nullableMetric,
  net_expectancy_r: nullableMetric,
  total_gross_pnl: z.number(),
  spread_costs: z.number(),
  slippage_costs: z.number(),
  commissions: z.number(),
  unknown_catalyst_trades: z.number().int(),
  performance_by_year: z.record(z.string(), groupedBacktestMetricsSchema),
  robustness: z.object({
    cost_stress: z.array(sessionEdgeRobustnessRowSchema),
    parameter_neighbourhood: z.array(sessionEdgeRobustnessRowSchema),
    selection_policy: z.string(),
  }),
  development_gate: z.object({
    status: z.enum(["PASS", "FAIL"]),
    continue_to_locked_validation: z.boolean(),
    criteria: z.record(z.string(), z.boolean()),
    largest_regime_share_pct: z.number(),
    holdout_policy: z.string(),
  }),
});

export const sessionEdgeStrategyRunSchema = backtestRunSchema.extend({
  metrics: sessionEdgeStrategyMetricsSchema,
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

const sessionEdgeCohortSchema = z.object({
  setup_count: z.number().int(),
  complete_outcome_count: z.number().int(),
  mean_gross_path_outcome_r_1r: z.number().nullable(),
  median_gross_path_outcome_r_1r: z.number().nullable(),
  gross_path_outcome_r_bootstrap_95ci: z.tuple([
    z.number().nullable(),
    z.number().nullable(),
  ]),
  mean_mfe_r: z.number().nullable(),
  median_mfe_r: z.number().nullable(),
  mean_mae_r: z.number().nullable(),
  median_mae_r: z.number().nullable(),
  target_before_stop_pct: z.record(z.string(), z.number().nullable()),
});

export const sessionOpportunitySchema = z.object({
  id: z.string(),
  run_id: z.string(),
  session_date: z.string(),
  fundamental_freeze_time: z.string(),
  level_freeze_time: z.string(),
  london_start_time: z.string(),
  london_end_time: z.string(),
  status: z.string(),
  no_trigger_reason: z.string().nullable(),
  setup_side: z.enum(["LONG", "SHORT"]).nullable(),
  signal_time: z.string().nullable(),
  entry_time: z.string().nullable(),
  bias_alignment: z.string(),
  directional_score: z.number().nullable(),
  fundamental_confidence: z.number().nullable(),
  fundamental_coverage: z.number().nullable(),
  regime_label: z.string(),
  dominant_driver: z.string().nullable(),
  event_risk: z.string(),
  asia_high: z.number().nullable(),
  asia_low: z.number().nullable(),
  asia_range_size: z.number().nullable(),
  asia_range_percentile: z.number().nullable(),
  asia_compression_state: z.string(),
  entry_reference_price: z.number().nullable(),
  invalidation_price: z.number().nullable(),
  risk_distance: z.number().nullable(),
  facts: z.record(z.string(), z.unknown()),
  outcomes: z.array(z.record(z.string(), z.unknown())),
  evidence: z.record(z.string(), z.unknown()),
  data_hash: z.string(),
  created_at: z.string(),
});

export const sessionEdgeStudyRunSchema = z.object({
  id: z.string(),
  strategy_name: z.string(),
  strategy_version: z.string(),
  instrument: z.string(),
  provider_code: z.string(),
  start: z.string(),
  end: z.string(),
  status: z.string(),
  parameters: z.record(z.string(), z.unknown()),
  data_hash: z.string(),
  source_bar_count: z.number().int(),
  session_count: z.number().int(),
  trigger_count: z.number().int(),
  results: z.object({
    research_status: z.string(),
    session_count: z.number().int(),
    complete_session_count: z.number().int(),
    trigger_count: z.number().int(),
    trigger_rate_pct: z.number().nullable(),
    status_funnel: z.record(z.string(), z.number().int()),
    cohorts: z.record(z.string(), sessionEdgeCohortSchema),
    interpretation: z.string(),
  }),
  provenance: z.record(z.string(), z.unknown()),
  created_at: z.string(),
  completed_at: z.string().nullable(),
  opportunities: z.array(sessionOpportunitySchema),
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

export const auctionSwingSchema = z.object({
  identity: z.string().regex(/^[0-9a-f]{64}$/),
  timeframe: z.string(),
  base_kind: z.enum(["HIGH", "LOW"]),
  classification: z.string(),
  pivot_at: z.string(),
  detected_at: z.string(),
  price_level: z.number(),
  atr14: z.number(),
  prominence_atr: z.number(),
  confidence: z.number().min(0).max(100),
  epistemic_status: z.literal("CALCULATED"),
  evidence: z.record(z.string(), z.unknown()),
});

export const auctionShiftZoneSchema = z.object({
  identity: z.string().regex(/^[0-9a-f]{64}$/),
  timeframe: z.literal("15m"),
  direction: z.enum(["BULLISH", "BEARISH"]),
  origin_at: z.string(),
  created_at: z.string(),
  detected_at: z.string(),
  lower_bound: z.number(),
  upper_bound: z.number(),
  midpoint: z.number(),
  broken_swing_identity: z.string().regex(/^[0-9a-f]{64}$/),
  broken_swing_level: z.number(),
  creation_atr14: z.number(),
  state: z.string(),
  first_touch_at: z.string().nullable(),
  retest_confirmed_at: z.string().nullable(),
  invalidated_at: z.string().nullable(),
  expires_at: z.string().nullable(),
  epistemic_status: z.literal("INFERRED"),
  confidence: z.number().min(0).max(100),
  detection_method: z.string(),
  invalidation_condition: z.string(),
  evidence: z.record(z.string(), z.unknown()),
});

export const auctionPaperProposalSchema = z.object({
  identity: z.string().regex(/^[0-9a-f]{64}$/),
  zone_identity: z.string().regex(/^[0-9a-f]{64}$/),
  family: z.enum(["RETEST_LIMIT_V0_1", "CONFIRMED_RETEST_V0_1"]),
  direction: z.enum(["BULLISH", "BEARISH"]),
  disposition: z.string(),
  triggered_at: z.string().nullable(),
  entry_reference: z.number().nullable(),
  stop: z.number(),
  target: z.number().nullable(),
  target_swing_identity: z.string().regex(/^[0-9a-f]{64}$/).nullable(),
  planned_risk_usd: z.number().min(0).max(50).nullable(),
  quantity_ounces: z.number().int().positive().nullable(),
  reward_to_risk: z.number().nonnegative().nullable(),
  macro_direction: z.enum(["BULLISH", "BEARISH", "NEUTRAL", "UNKNOWN"]),
  macro_relationship: z.string(),
  liquidity_status: z.string(),
  epistemic_status: z.literal("INFERRED"),
  explanation: z.string(),
  evidence: z.record(z.string(), z.unknown()),
});

export const auctionAutomationSchema = z.object({
  as_of: z.string(),
  ruleset_version: z.string(),
  config: z.record(z.string(), z.number()),
  source_bar_count: z.number().int().nonnegative(),
  source_first_at: z.string().nullable(),
  source_last_at: z.string().nullable(),
  data_hash: z.string().regex(/^[0-9a-f]{64}$/),
  macro_direction: z.enum(["BULLISH", "BEARISH", "NEUTRAL", "UNKNOWN"]),
  macro_bias_label: z.string(),
  macro_available_at: z.string().nullable(),
  liquidity_status: z.string(),
  timeframe_trends: z.record(z.string(), z.string()),
  swings: z.array(auctionSwingSchema),
  zones: z.array(auctionShiftZoneSchema),
  proposals: z.array(auctionPaperProposalSchema),
  warnings: z.array(z.string()),
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
  auction_automation: auctionAutomationSchema,
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

export const blindReplayStatusSchema = z.object({
  protocol: z.string(),
  ready: z.boolean(),
  phase: z.enum(["PRACTICE", "SCORED", "COMPLETE"]),
  practice_completed: z.number().int().min(0).max(20),
  practice_total: z.literal(20),
  scored_completed: z.number().int().min(0).max(240),
  scored_total: z.literal(240),
  total_locked: z.number().int().min(0).max(260),
  next_case_alias: z.string().nullable(),
  ledger_head_sha256: z.string().length(64),
  scored_outcomes_locked: z.boolean(),
  research_status: z.string(),
});

export const blindReplayBarSchema = z.object({
  ordinal: z.number().optional(),
  minutes_after_checkpoint: z.number().int().optional(),
  open: z.number(),
  high: z.number(),
  low: z.number(),
  close: z.number(),
  volume: z.number().nullable().optional(),
  spread_price_index: z.number().nullable().optional(),
});

export const blindReplayPayloadSchema = z
  .object({
    case_alias: z.string(),
    mode: z.enum(["PRACTICE", "SCORED"]),
    mode_sequence: z.number().int().positive(),
    global_sequence: z.number().int().positive(),
    session_code: z.enum(["LONDON", "NEW_YORK"]),
    checkpoint_label: z.literal("SESSION_OPEN_PLUS_60_MINUTES"),
    reference_index: z.literal(100),
    m15_atr_index: z.number().positive(),
    charts: z.record(z.string(), z.array(blindReplayBarSchema)),
    chart_availability: z.object({
      status: z.string(),
      counts: z.record(z.string(), z.number().int().nonnegative()),
      required: z.record(z.string(), z.number().int().positive()),
    }),
    session: z.record(z.string(), z.unknown()),
    structure: z.record(z.string(), z.unknown()),
    fundamental: z.record(z.string(), z.unknown()),
    cross_market: z.record(z.string(), z.unknown()),
    positioning: z.record(z.string(), z.unknown()),
    released_events: z.array(z.record(z.string(), z.unknown())),
    liquidity: z.record(z.string(), z.unknown()),
    gc_order_flow: z.record(z.string(), z.unknown()),
    display_policy: z.object({
      absolute_date_hidden: z.literal(true),
      absolute_time_hidden: z.literal(true),
      absolute_price_hidden: z.literal(true),
      completed_candles_only: z.literal(true),
      future_scored_path_present: z.literal(false),
    }),
    payload_sha256: z.string().length(64),
  })
  .passthrough();

export const blindReplayCaseSchema = z.object({
  case: blindReplayPayloadSchema,
  progress: blindReplayStatusSchema,
});

export const blindReplayDecisionResponseSchema = z.object({
  locked: z.literal(true),
  idempotent_replay: z.boolean(),
  record_sha256: z.string().length(64),
  case_alias: z.string(),
  mode: z.enum(["PRACTICE", "SCORED"]),
  progress: blindReplayStatusSchema,
  practice_feedback: z
    .object({
      case_alias: z.string(),
      status: z.string(),
      bars: z.array(blindReplayBarSchema),
      economic_result: z.string(),
    })
    .nullable(),
});

export const blindReplayV2BarSchema = z.object({
  bar_id: z.string().length(64),
  close_offset_minutes: z.number().int().max(180),
  available_offset_minutes: z.number().int().max(180),
  open: z.number(),
  high: z.number(),
  low: z.number(),
  close: z.number(),
  volume: z.number().nullable().optional(),
});

export const blindReplayV2StatusSchema = z.object({
  protocol: z.literal("GOLD_BLIND_SYNCHRONIZED_SETUP_REPLAY_V2_PROTOCOL_1_0"),
  ready: z.boolean(),
  phase: z.enum(["PRACTICE", "PRACTICE_COMPLETE_SCORED_CLOSED"]),
  practice_completed: z.number().int().min(0).max(20),
  practice_total: z.literal(20),
  total_locked: z.number().int().min(0).max(20),
  next_case_alias: z.string().nullable(),
  cursor_minute: z.number().int().min(0).max(180).nullable(),
  cursor_ledger_head_sha256: z.string().length(64),
  setup_ledger_head_sha256: z.string().length(64),
  scored_labeling: z.literal("CLOSED_V2_PRACTICE_ONLY_CERTIFIED"),
  research_credit: z.literal("ZERO_PRACTICE_ONLY"),
});

const blindReplayV2VisibilitySchema = z.object({
  count: z.number().int().nonnegative(),
  terminal_bar_id: z.string().length(64).nullable(),
  sha256: z.string().length(64),
});

export const blindReplayV2PayloadSchema = z.object({
  version: z.literal("GOLD_BLIND_SYNCHRONIZED_SETUP_REPLAY_V2_SNAPSHOT_1_0"),
  case_alias: z.string().regex(/^P-\d{3}$/),
  mode: z.literal("PRACTICE"),
  mode_sequence: z.number().int().min(1).max(20),
  session_code: z.enum(["LONDON", "NEW_YORK"]),
  cursor_minute: z.number().int().min(0).max(180),
  maximum_cursor_minute: z.literal(180),
  selected_timeframe_default: z.literal("15m"),
  reference_index: z.literal(100),
  latest_visible_m1_close_index: z.number(),
  latest_point_in_time_m15_atr_index: z.number().positive(),
  context_frozen_at_cursor_minute: z.literal(0),
  context_staleness_minutes: z.number().int().min(0).max(180),
  context: z.record(z.string(), z.unknown()),
  context_sha256: z.string().length(64),
  charts: z.record(z.string(), z.array(blindReplayV2BarSchema)),
  visible_timeframes: z.record(z.string(), blindReplayV2VisibilitySchema),
  visible_charts_sha256: z.string().length(64),
  display_policy: z.object({
    one_way_cursor: z.literal(true),
    future_values_in_response: z.literal(false),
    timeframe_switch_changes_cursor: z.literal(false),
    drawings_case_global: z.literal(true),
    scored_labeling_closed: z.literal(true),
    context_frozen_at_t0: z.literal(true),
  }),
});

export const blindReplayV2CaseSchema = z.object({
  case: blindReplayV2PayloadSchema,
  progress: blindReplayV2StatusSchema,
});

export const blindReplayV2DecisionResponseSchema = z.object({
  locked: z.literal(true),
  idempotent_replay: z.boolean(),
  record_sha256: z.string().length(64),
  case_alias: z.string(),
  locked_cursor_minute: z.number().int().min(0).max(180),
  progress: blindReplayV2StatusSchema,
  practice_feedback: z.object({
    status: z.literal("PRACTICE_RESOLUTION_REVEALED_ZERO_RESEARCH_CREDIT"),
    locked_cursor_minute: z.number().int().min(0).max(180),
    bars: z.array(blindReplayV2BarSchema),
    economic_result: z.string(),
  }),
});

export const blindReplayV3BarSchema = z.object({
  bar_id: z.string().length(64),
  timeframe: z.string(),
  open_at: z.string(),
  close_at: z.string(),
  available_at: z.string(),
  open: z.number(),
  high: z.number(),
  low: z.number(),
  close: z.number(),
  volume: z.number().nullable().optional(),
  spread_price: z.number().nullable().optional(),
  complete: z.boolean(),
  missing_source_minutes: z.number().int().nonnegative(),
});

export const blindReplayV3StatusSchema = z.object({
  protocol: z.literal("GOLD_ANNOTATED_TRADINGVIEW_STYLE_REPLAY_V3_PROTOCOL_1_0"),
  ready: z.boolean(),
  phase: z.enum(["PRACTICE", "PRACTICE_COMPLETE_COLLECTION_CLOSED"]),
  practice_completed: z.number().int().min(0).max(20),
  practice_total: z.literal(20),
  current_case_alias: z.string().nullable(),
  event_ledger_head_sha256: z.string().length(64),
  collection_year: z.number().int(),
  collection_state: z.literal("CLOSED_NOT_MATERIALIZED_OR_ACCESSIBLE"),
  calendar_2025: z.literal("LOCKED"),
  calendar_2026: z.literal("LOCKED"),
  research_credit: z.literal("ZERO_PRACTICE_ONLY"),
  practice_cases: z.array(z.object({
    case_alias: z.string(),
    trading_date_utc: z.string(),
    completed: z.boolean(),
    active: z.boolean(),
    research_credit: z.literal("ZERO_PRACTICE_ONLY"),
  })),
});

export const blindReplayV3OrderSchema = z.object({
  order_id: z.string(),
  case_alias: z.string(),
  state: z.enum(["PENDING_ORDER", "ACTIVE_POSITION", "CANCELLED", "EXPIRED", "RESOLVED"]),
  submitted_at: z.string(),
  effective_at: z.string(),
  direction: z.enum(["LONG", "SHORT"]),
  order_type: z.enum(["MARKET", "LIMIT", "STOP"]),
  entry: z.number(),
  stop: z.number(),
  target: z.number(),
  expiry_at: z.string(),
  quantity_ounces: z.number().int().positive(),
  risk_usd: z.number().nonnegative(),
  selected_timeframe: z.string(),
  drawings: z.array(z.record(z.string(), z.unknown())),
  annotation: z.record(z.string(), z.unknown()),
  fill: z.record(z.string(), z.unknown()).optional(),
  resolution: z.record(z.string(), z.unknown()).optional(),
}).passthrough();

const blindReplayV3VisibilitySchema = z.object({
  count: z.number().int().nonnegative(),
  terminal_bar_id: z.string().length(64).nullable(),
  sha256: z.string().length(64),
});

export const blindReplayV3PayloadSchema = z.object({
  version: z.literal("GOLD_ANNOTATED_REPLAY_V3_SNAPSHOT_1_0"),
  case_alias: z.string().regex(/^V3-P-\d{3}$/),
  mode: z.literal("PRACTICE"),
  mode_sequence: z.number().int().min(1).max(20),
  trading_date_utc: z.string(),
  start_at: z.string(),
  end_at: z.string(),
  cursor_at: z.string(),
  selected_timeframe_default: z.literal("15m"),
  charts: z.record(z.string(), z.array(blindReplayV3BarSchema)),
  visible_timeframes: z.record(z.string(), blindReplayV3VisibilitySchema),
  context: z.record(z.string(), z.unknown()),
  live_order: blindReplayV3OrderSchema.nullable(),
  order_history: z.array(blindReplayV3OrderSchema),
  visible_state_sha256: z.string().length(64),
  execution: z.object({
    maximum_planned_risk_usd: z.number(),
    account_equity_usd: z.number(),
    one_live_order_or_position: z.literal(true),
    post_fill_geometry_mutable: z.literal(false),
    same_bar_ambiguity: z.literal("STOP_FIRST"),
  }),
  display_policy: z.record(z.string(), z.unknown()),
});

export const blindReplayV3CaseSchema = z.object({
  case: blindReplayV3PayloadSchema,
  progress: blindReplayV3StatusSchema,
});

export const blindReplayV3MutationSchema = z.object({
  event_sha256: z.string().length(64),
  idempotent_replay: z.boolean(),
  case: blindReplayV3PayloadSchema.nullable(),
  progress: blindReplayV3StatusSchema,
});

export const coherentAuctionValidationStatusSchema = blindReplayV3StatusSchema.extend({
  protocol: z.literal("GOLD_COHERENT_AUCTION_BLIND_VALIDATION_V1_PROTOCOL_1_0"),
  phase: z.enum(["BLIND_COLLECTION", "BLIND_COLLECTION_COMPLETE_RESULTS_LOCKED"]),
  practice_completed: z.number().int().min(0).max(50),
  practice_total: z.literal(50),
  collection_state: z.literal("OPEN_BLIND_AGGREGATES_LOCKED"),
  research_credit: z.literal("HISTORICAL_BLIND_ROBUSTNESS_ONLY"),
  practice_cases: z.array(z.object({
    case_alias: z.string().regex(/^GAV-2022-\d{3}$/),
    trading_date_utc: z.string(),
    session_code: z.enum(["LONDON", "NEW_YORK"]),
    completed: z.boolean(),
    active: z.boolean(),
    research_credit: z.literal("HISTORICAL_BLIND_ROBUSTNESS_ONLY"),
  })),
});

export const coherentAuctionValidationPayloadSchema = blindReplayV3PayloadSchema.extend({
  version: z.literal("GOLD_COHERENT_AUCTION_BLIND_VALIDATION_V1_SNAPSHOT_1_0"),
  case_alias: z.string().regex(/^GAV-2022-\d{3}$/),
  mode: z.literal("BLIND_HISTORICAL_ROBUSTNESS"),
  mode_sequence: z.number().int().min(1).max(50),
  session_code: z.enum(["LONDON", "NEW_YORK"]),
});

export const coherentAuctionValidationCaseSchema = z.object({
  case: coherentAuctionValidationPayloadSchema,
  progress: coherentAuctionValidationStatusSchema,
});

export const coherentAuctionValidationMutationSchema = z.object({
  event_sha256: z.string().length(64),
  idempotent_replay: z.boolean(),
  case: coherentAuctionValidationPayloadSchema.nullable(),
  progress: coherentAuctionValidationStatusSchema,
});

export const codexOperatorReplayStatusSchema = z.object({
  protocol: z.enum([
    "GOLD_BLIND_CODEX_OPERATOR_REPLAY_AUDIT_V1_PROTOCOL_1_0",
    "GOLD_MATCHED_HUMAN_CODEX_REPLAY_COMPARISON_V1_PROTOCOL_1_0",
  ]),
  ready: z.boolean(),
  phase: z.enum(["BLIND_COLLECTION", "BLIND_COLLECTION_COMPLETE_OUTCOMES_LOCKED"]),
  cases_completed: z.number().int().nonnegative(),
  cases_total: z.number().int().positive(),
  current_case_alias: z.string().nullable(),
  visible_ledger_head_sha256: z.string().length(64),
  outcome_vault_state: z.literal("SEALED_OPERATOR_INACCESSIBLE"),
  human_decisions: z.enum(["HIDDEN", "CURRENT_OPERATOR_ONLY_CODEX_HIDDEN"]),
  calendar_2025: z.literal("LOCKED"),
  calendar_2026: z.literal("LOCKED"),
  research_credit: z.enum([
    "BLINDED_HISTORICAL_OPERATOR_EVIDENCE",
    "ZERO_CREDIT_MATCHED_METHOD_DIAGNOSTIC",
  ]),
  cases: z.array(z.object({
    case_alias: z.string(),
    trading_date_utc: z.string(),
    completed: z.boolean(),
    active: z.boolean(),
  })),
});

const codexOperatorReplayVisibilitySchema = z.object({
  count: z.number().int().nonnegative(),
  terminal_bar_id: z.string().nullable(),
  sha256: z.string().length(64),
});

export const codexOperatorReplayPayloadSchema = z.object({
  version: z.literal("GOLD_BLIND_CODEX_OPERATOR_REPLAY_V1_SNAPSHOT_1_0"),
  case_alias: z.string().regex(/^CBR-2022-\d{3}$/),
  mode: z.enum(["CODEX_BLIND", "MATCHED_HUMAN_DIAGNOSTIC"]),
  mode_sequence: z.number().int().positive(),
  trading_date_utc: z.string(),
  start_at: z.string(),
  end_at: z.string(),
  cursor_at: z.string(),
  observation_terminal_at: z.string(),
  active_entry_session: z.enum(["LONDON", "LONDON_NEW_YORK_OVERLAP", "NEW_YORK"]).nullable(),
  selected_timeframe_default: z.literal("15m"),
  charts: z.record(z.string(), z.array(blindReplayV3BarSchema)),
  visible_timeframes: z.record(z.string(), codexOperatorReplayVisibilitySchema),
  context: z.record(z.string(), z.unknown()),
  visible_state_sha256: z.string().length(64),
  inspected_timeframes: z.array(z.string()),
  execution: z.object({
    maximum_planned_risk_usd: z.literal(50),
    maximum_effective_risk_usd: z.literal(55),
    order_types: z.tuple([z.literal("MARKET")]),
    one_trade_per_case: z.literal(true),
    same_bar_ambiguity: z.literal("STOP_FIRST"),
  }),
  display_policy: z.record(z.string(), z.unknown()),
});

export const codexOperatorReplayCaseSchema = z.object({
  case: codexOperatorReplayPayloadSchema,
  progress: codexOperatorReplayStatusSchema,
});

export const codexOperatorReplayMutationSchema = z.object({
  event_sha256: z.string().length(64),
  idempotent_replay: z.boolean(),
  case: codexOperatorReplayPayloadSchema.nullable(),
  progress: codexOperatorReplayStatusSchema,
  outcome_hidden: z.literal(true),
});

export type IntelligenceSnapshot = z.infer<typeof intelligenceSnapshotSchema>;
export type DataHealth = z.infer<typeof dataHealthSchema>;
export type FundamentalComponent = z.infer<typeof fundamentalComponentSchema>;
export type FundamentalSnapshot = z.infer<typeof fundamentalSnapshotSchema>;
export type DecisionSnapshot = z.infer<typeof decisionSnapshotSchema>;
export type FactorCoverage = z.infer<typeof factorCoverageSchema>;
export type BacktestRun = z.infer<typeof backtestRunSchema>;
export type SessionEdgeStrategyRun = z.infer<
  typeof sessionEdgeStrategyRunSchema
>;
export type BacktestDataRange = z.infer<typeof backtestDataRangeSchema>;
export type EconomicEvent = z.infer<typeof economicEventSchema>;
export type EconomicSurprise = z.infer<typeof economicSurpriseSchema>;
export type EventStudyRun = z.infer<typeof eventStudyRunSchema>;
export type SessionEdgeStudyRun = z.infer<typeof sessionEdgeStudyRunSchema>;
export type SessionOpportunity = z.infer<typeof sessionOpportunitySchema>;
export type LicensedProviderHealth = z.infer<
  typeof licensedProviderHealthSchema
>;
export type MarketStructureSnapshot = z.infer<typeof marketStructureSnapshotSchema>;
export type AuctionAutomation = z.infer<typeof auctionAutomationSchema>;
export type MarketObservation = z.infer<typeof marketObservationSchema>;
export type BlindReplayStatus = z.infer<typeof blindReplayStatusSchema>;
export type BlindReplayBar = z.infer<typeof blindReplayBarSchema>;
export type BlindReplayPayload = z.infer<typeof blindReplayPayloadSchema>;
export type BlindReplayCase = z.infer<typeof blindReplayCaseSchema>;
export type BlindReplayDecisionResponse = z.infer<
  typeof blindReplayDecisionResponseSchema
>;
export type BlindReplayV2Bar = z.infer<typeof blindReplayV2BarSchema>;
export type BlindReplayV2Status = z.infer<typeof blindReplayV2StatusSchema>;
export type BlindReplayV2Payload = z.infer<typeof blindReplayV2PayloadSchema>;
export type BlindReplayV2Case = z.infer<typeof blindReplayV2CaseSchema>;
export type BlindReplayV2DecisionResponse = z.infer<
  typeof blindReplayV2DecisionResponseSchema
>;
export type BlindReplayV3Bar = z.infer<typeof blindReplayV3BarSchema>;
export type BlindReplayV3Status = z.infer<typeof blindReplayV3StatusSchema>;
export type BlindReplayV3Order = z.infer<typeof blindReplayV3OrderSchema>;
export type BlindReplayV3Payload = z.infer<typeof blindReplayV3PayloadSchema>;
export type BlindReplayV3Case = z.infer<typeof blindReplayV3CaseSchema>;
export type BlindReplayV3Mutation = z.infer<typeof blindReplayV3MutationSchema>;
export type CoherentAuctionValidationStatus = z.infer<typeof coherentAuctionValidationStatusSchema>;
export type CoherentAuctionValidationPayload = z.infer<typeof coherentAuctionValidationPayloadSchema>;
export type CodexOperatorReplayStatus = z.infer<typeof codexOperatorReplayStatusSchema>;
export type CodexOperatorReplayPayload = z.infer<typeof codexOperatorReplayPayloadSchema>;
export type CodexOperatorReplayCase = z.infer<typeof codexOperatorReplayCaseSchema>;
export type CodexOperatorReplayMutation = z.infer<typeof codexOperatorReplayMutationSchema>;

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
