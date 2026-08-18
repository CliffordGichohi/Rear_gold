# Gold Conditional Movement-Policy Edge Contract V1

Status: `FROZEN_BEFORE_CONDITIONAL_MODEL_OUTCOMES`

## Purpose

Test whether the complete point-in-time state—not the broad trend-pullback label alone—can identify which otherwise repeatable pullbacks have favourable post-entry payoff geometry.

Preserve the Movement Anatomy V1 zero-candidate verdict, its complete 4,860-test grid, and every earlier artifact. Use only sealed 2021–2024 development features and trade matrices. Keep 2025 and 2026 locked.

## Registered executions

Test exactly four transparent execution families on each timeframe:

1. `CONFIRMATION_EXTREME_BREAK::CONFIRMATION_EXTREME_BUFFER_0P05_ATR::FIXED_1P5_R::TIME_8_PARENT_BARS`
2. `BREAK_RETEST_CONFIRM::CONFIRMATION_EXTREME_BUFFER_0P05_ATR::FIXED_1P5_R::TIME_8_PARENT_BARS`
3. `RESPONSE_HALF_RETRACE_LIMIT::PIVOT_BUFFER_0P05_ATR::FIXED_2P0_R::TIME_8_PARENT_BARS`
4. `REFERENCE_LEVEL_RETEST_LIMIT::PIVOT_BUFFER_0P05_ATR::FIXED_2P0_R::TIME_8_PARENT_BARS`

These represent breakout, confirmed retest, discounted pullback and structural-level retest. Entries, stops, targets, time exits, costs and sizing remain exactly as sealed in Movement Anatomy V1.

## Predictors

Use only these fields sealed before the decision timestamp:

Numeric:

- trend age, event-to-pivot and impulse-to-pivot bars, prior continuation count;
- impulse extension and efficiency;
- pullback efficiency, retracement fraction/depth and compression;
- reference distance;
- pivot and confirmation range, body, close-location and rejection-wick geometry;
- response displacement, efficiency and aligned-close count;
- confirmation volume ratio;
- higher-timeframe alignment and known counts;
- fundamental aligned score, confidence and coverage;
- aligned real-yield, Fed-path, USD and two-year contributions; and
- COT percentile and aligned change.

Categorical or Boolean:

- direction, session and retracement zone;
- pivot/confirmation body state, displacement and aligned engulfing;
- reference, prior-day and Asia sweep-reclaim;
- H1/H4 structure alignment;
- fundamental alignment, regime, reaction function and event risk; and
- COT crowding and liquidation/short-covering risk.

Movement outcomes, structural resolution, MFE, MAE, barrier order and future prices are prohibited predictors.

## Transparent policy model

For each timeframe and execution family, fit a deterministic regression tree predicting net R:

- maximum depth 3;
- squared-error criterion and best splitter;
- fixed random seed 731911;
- numeric values clipped at training-only 1st/99th percentiles and median-imputed;
- categorical values mapped to explicit training one-hot states with unknown values ignored;
- minimum leaf: M15 120, H1 40, H4 15;
- minimum impurity decrease 0.0005; and
- trade only when predicted net R is at least +0.05R.

Every tree, threshold, leaf prediction and selected feature must be exported as a readable decision rule.

## Evaluation

Use the same three expanding walk-forward folds frozen in Movement Anatomy V1. Fit transformations and trees on training rows only; apply once to the next validation block. Evaluate all twelve timeframe/execution policies. Do not select a favourable execution after validation.

A development policy passes only if:

- OOF support is M15 120 trades/75 dates, H1 60/40, H4 30/25;
- at least 15 winners and 15 losers;
- net expectancy and its 95% date-cluster-bootstrap lower bound are positive;
- Holm-adjusted one-sided p is at most 0.05 across all twelve policies;
- profit factor is at least 1.20;
- at least two validation folds are positive and none with ten trades is below -0.10R;
- 1.5x-cost expectancy is positive and profit factor at least 1.05;
- maximum reference-account drawdown is at most 15%;
- profit concentration is at most 25%; and
- at least one split feature recurs in two fitted fold trees.

Permit at most two passing policies per timeframe. Fit the final tree for a passing policy on all 2021–2024 development rows and freeze it before opening forward values.

## Forward

Apply frozen passing policies once to 2025 and 2026 through 2026-07-29. Require positive net expectancy in each supported segment, combined 90% lower confidence above zero, profit factor at least 1.15 and positive 1.5x-cost expectancy. Do not retune. Initialize paper-only prospective tracking only for policies surviving forward robustness.

No paid acquisition or live trading is authorized. Zero candidates is acceptable and leaves forward values unopened.
