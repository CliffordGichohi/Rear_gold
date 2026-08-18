# GC Session State-Transition Edge Discovery V1 Report

Formal status: `PASS_RESEARCH_COMPLETE_ZERO_CANDIDATES`

This report is a development discovery result, not a backtest and not a claim of a validated trading edge. No execution, trades, PnL, R multiples, or account returns were calculated.

## Research population

- Sealed event rows: **19,345**.
- Primary-endpoint-valid event rows: **19,345**.
- Registered tests: **90**.
- Support eligible: **52**; support failures: **38**.
- Provisional London candidates: **0**.
- Provisional New York candidates: **0**.
- 2025/2026 accessed: **no**.

## Frozen-family event counts

| Session | Event family | Events | Valid 60m |
|---|---|---:|---:|
| LONDON | LEVEL_SWEEP_RECLAIM | 1993 | 1993 |
| LONDON | LEVEL_BREAK_ACCEPT | 2189 | 2189 |
| LONDON | LEVEL_FAILED_ACCEPTANCE | 1700 | 1700 |
| LONDON | STRUCTURE_BREAK_CONTINUATION | 885 | 885 |
| LONDON | STRUCTURE_STATE_REVERSAL | 1157 | 1157 |
| LONDON | COMPRESSION_EXPANSION_BREAK | 883 | 883 |
| LONDON | FLOW_DEPTH_ALIGNMENT_ONSET | 227 | 227 |
| LONDON | ABSORPTION_ONSET | 252 | 252 |
| LONDON | FRAGILITY_FLOW_ONSET | 257 | 257 |
| NEW_YORK | LEVEL_SWEEP_RECLAIM | 2143 | 2143 |
| NEW_YORK | LEVEL_BREAK_ACCEPT | 2314 | 2314 |
| NEW_YORK | LEVEL_FAILED_ACCEPTANCE | 1890 | 1890 |
| NEW_YORK | STRUCTURE_BREAK_CONTINUATION | 846 | 846 |
| NEW_YORK | STRUCTURE_STATE_REVERSAL | 1142 | 1142 |
| NEW_YORK | COMPRESSION_EXPANSION_BREAK | 814 | 814 |
| NEW_YORK | FLOW_DEPTH_ALIGNMENT_ONSET | 195 | 195 |
| NEW_YORK | ABSORPTION_ONSET | 239 | 239 |
| NEW_YORK | FRAGILITY_FLOW_ONSET | 219 | 219 |

## Provisional candidates

No test passed every preregistered support, effect, uncertainty, multiplicity, stability, symmetry, first-event, and horizon gate.

## Closest rejected relationships

These remain rejected and receive no candidate or validation credit.

| Test | Effect | q | Failed gates |
|---|---:|---:|---|
| LONDON|S1|STRUCTURE_STATE_REVERSAL | 0.0372 | 0.4875 | condition_mean_at_least_0p10, absolute_effect_ci_lower_positive, median_path_dominance_ci_lower_positive, favorable_minus_adverse_incidence_at_least_10pp, bh_q_at_most_0p05 |
| LONDON|S1|FRAGILITY_FLOW_ONSET | 0.0739 | 0.4875 | condition_mean_at_least_0p10, absolute_effect_ci_lower_positive, median_path_dominance_positive, median_path_dominance_ci_lower_positive, favorable_minus_adverse_incidence_at_least_10pp, annual_stability, bh_q_at_most_0p05 |
| NEW_YORK|S2|LEVEL_BREAK_ACCEPT|SESSION_OPEN_STRUCTURE_CONCORDANT | 0.1060 | 0.9878 | condition_mean_at_least_0p10, absolute_effect_ci_lower_positive, lift_ci_lower_positive, median_path_dominance_ci_lower_positive, favorable_minus_adverse_incidence_at_least_10pp, chronological_block_stability, bh_q_at_most_0p05 |
| LONDON|S2|LEVEL_SWEEP_RECLAIM|SESSION_OPEN_STRUCTURE_CONCORDANT | 0.1081 | 0.678 | condition_mean_at_least_0p10, absolute_effect_ci_lower_positive, lift_ci_lower_positive, median_path_dominance_ci_lower_positive, favorable_minus_adverse_incidence_at_least_10pp, annual_stability, first_event_robustness, bh_q_at_most_0p05 |
| LONDON|S2|STRUCTURE_BREAK_CONTINUATION|MACRO_CONCORDANT | 0.0936 | 0.678 | lift_at_least_0p10, absolute_effect_ci_lower_positive, lift_ci_lower_positive, median_path_dominance_positive, median_path_dominance_ci_lower_positive, chronological_block_stability, directional_symmetry, bh_q_at_most_0p05 |
| LONDON|S2|LEVEL_BREAK_ACCEPT|MACRO_CONCORDANT | 0.0874 | 0.678 | condition_mean_at_least_0p10, lift_at_least_0p10, absolute_effect_ci_lower_positive, lift_ci_lower_positive, median_path_dominance_ci_lower_positive, favorable_minus_adverse_incidence_at_least_10pp, directional_symmetry, bh_q_at_most_0p05 |
| LONDON|S1|STRUCTURE_BREAK_CONTINUATION | 0.0328 | 0.4875 | condition_mean_at_least_0p10, absolute_effect_ci_lower_positive, median_path_dominance_positive, median_path_dominance_ci_lower_positive, favorable_minus_adverse_incidence_at_least_10pp, annual_stability, chronological_block_stability, directional_symmetry, bh_q_at_most_0p05 |
| LONDON|S1|FLOW_DEPTH_ALIGNMENT_ONSET | 0.0396 | 0.4881 | condition_mean_at_least_0p10, absolute_effect_ci_lower_positive, median_path_dominance_positive, median_path_dominance_ci_lower_positive, favorable_minus_adverse_incidence_at_least_10pp, annual_stability, chronological_block_stability, directional_symmetry, bh_q_at_most_0p05 |
| LONDON|S1|COMPRESSION_EXPANSION_BREAK | 0.0249 | 0.4881 | condition_mean_at_least_0p10, absolute_effect_ci_lower_positive, median_path_dominance_positive, median_path_dominance_ci_lower_positive, favorable_minus_adverse_incidence_at_least_10pp, annual_stability, chronological_block_stability, first_event_robustness, bh_q_at_most_0p05 |
| LONDON|S2|STRUCTURE_BREAK_CONTINUATION|SESSION_OPEN_STRUCTURE_CONCORDANT | 0.0335 | 0.678 | condition_mean_at_least_0p10, lift_at_least_0p10, absolute_effect_ci_lower_positive, lift_ci_lower_positive, median_path_dominance_positive, median_path_dominance_ci_lower_positive, favorable_minus_adverse_incidence_at_least_10pp, chronological_block_stability, bh_q_at_most_0p05 |

## Complete negative-result accounting

- `absolute_effect_ci_lower_positive`: 52 tests.
- `bh_q_at_most_0p05`: 52 tests.
- `median_path_dominance_ci_lower_positive`: 52 tests.
- `condition_mean_at_least_0p10`: 51 tests.
- `favorable_minus_adverse_incidence_at_least_10pp`: 51 tests.
- `chronological_block_stability`: 48 tests.
- `annual_stability`: 46 tests.
- `directional_symmetry`: 44 tests.
- `median_path_dominance_positive`: 41 tests.
- `CONDITION_EVENTS_LT_50`: 38 tests.
- `CONDITION_DATES_LT_40`: 36 tests.
- `lift_ci_lower_positive`: 34 tests.
- `lift_at_least_0p10`: 32 tests.
- `CONDITION_UP_EVENTS_LT_15`: 27 tests.
- `CONDITION_YEAR_2024_DATES_LT_8`: 27 tests.
- `first_event_robustness`: 26 tests.
- `CONDITION_DOWN_EVENTS_LT_15`: 25 tests.
- `CONDITION_DOWN_DATES_LT_12`: 21 tests.
- `CONDITION_UP_DATES_LT_12`: 21 tests.
- `CONDITION_YEAR_2023_DATES_LT_8`: 20 tests.
- `CONDITION_YEAR_2022_DATES_LT_8`: 16 tests.
- `horizon_consistency`: 16 tests.
- `CONDITION_WEEKS_LT_16`: 15 tests.

## Integrity

- Primary and reference event populations matched exactly.
- Primary and reference first-passage and path outcomes matched exactly.
- Primary and reference test results and verdict checksums matched exactly.
- Every registered test, support failure, rejection, and negative result is retained in `complete_results.json`.
- No new market data was acquired and no charge was incurred.

## Stop

The V1 development branch is sealed and stopped. Any provisional candidate requires a separately frozen forward-validation protocol; it is not authorized for execution.
