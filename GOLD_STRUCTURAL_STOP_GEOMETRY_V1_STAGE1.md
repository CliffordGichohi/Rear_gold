# Gold Structural Stop Geometry V1 — Stage 1

Status: **PASS_STAGE1_INDEPENDENT_REPRODUCTION**

## Result

- Unchanged executed entries: **22,193**
- Trade–stop paths: **88,772**
- Alternative model–stop cells passing survival gates: **35 / 54**
- Alternative model–stop cells rejected before economics: **19**
- Frozen baseline exits and entry costs reproduced with zero mismatches in both implementations.
- 2025/2026 values remained locked; acquisition cost was $0.00.

## Stage-1 dispositions

| Timeframe | Model | Stop | Paired N | Stop-before-MFE improvement | Target-first Δ | Disposition | Failed gates |
|---|---|---|---:|---:|---:|---|---|
| H4 | BREAK_RETEST_CONTINUATION | STOP_CONFIRMATION_EXTREME_0P25_ATR | 162 | 8.64 pp | 7.41 pp | PASS_STAGE1 | — |
| H4 | BREAK_RETEST_CONTINUATION | STOP_LATEST_KNOWN_OPPOSING_SWING_0P10_ATR | 162 | 17.28 pp | 12.35 pp | PASS_STAGE1 | — |
| H4 | BREAK_RETEST_CONTINUATION | STOP_PIVOT_0P25_ATR | 162 | 22.22 pp | 15.43 pp | PASS_STAGE1 | — |
| H4 | DEEP_RETRACE_CONTINUATION | STOP_CONFIRMATION_EXTREME_0P25_ATR | 107 | -14.02 pp | -7.48 pp | REJECT_STAGE1 | valid_stop_coverage, one_ounce_coverage, stop_before_mfe_improvement, target_first_not_lower |
| H4 | DEEP_RETRACE_CONTINUATION | STOP_LATEST_KNOWN_OPPOSING_SWING_0P10_ATR | 135 | -0.74 pp | 0.00 pp | REJECT_STAGE1 | stop_before_mfe_improvement |
| H4 | DEEP_RETRACE_CONTINUATION | STOP_PIVOT_0P25_ATR | 135 | 5.93 pp | 2.96 pp | PASS_STAGE1 | — |
| H4 | FALSE_CONTINUATION_REVERSAL | STOP_CONFIRMATION_EXTREME_0P25_ATR | 40 | 0.00 pp | 0.00 pp | REJECT_STAGE1 | stop_before_mfe_improvement |
| H4 | FALSE_CONTINUATION_REVERSAL | STOP_LATEST_KNOWN_OPPOSING_SWING_0P10_ATR | 39 | 0.00 pp | 0.00 pp | REJECT_STAGE1 | stop_before_mfe_improvement |
| H4 | FALSE_CONTINUATION_REVERSAL | STOP_PIVOT_0P25_ATR | 38 | -23.68 pp | -2.63 pp | REJECT_STAGE1 | stop_before_mfe_improvement, target_first_not_lower |
| H4 | IMMEDIATE_FAILURE_REVERSAL | STOP_CONFIRMATION_EXTREME_0P25_ATR | 37 | 5.41 pp | 2.70 pp | PASS_STAGE1 | — |
| H4 | IMMEDIATE_FAILURE_REVERSAL | STOP_LATEST_KNOWN_OPPOSING_SWING_0P10_ATR | 35 | 2.86 pp | 0.00 pp | PASS_STAGE1 | — |
| H4 | IMMEDIATE_FAILURE_REVERSAL | STOP_PIVOT_0P25_ATR | 36 | -19.44 pp | 0.00 pp | REJECT_STAGE1 | stop_before_mfe_improvement |
| H4 | RUNAWAY_BREAKOUT | STOP_CONFIRMATION_EXTREME_0P25_ATR | 176 | 9.09 pp | 6.82 pp | PASS_STAGE1 | — |
| H4 | RUNAWAY_BREAKOUT | STOP_LATEST_KNOWN_OPPOSING_SWING_0P10_ATR | 176 | 17.61 pp | 11.36 pp | PASS_STAGE1 | — |
| H4 | RUNAWAY_BREAKOUT | STOP_PIVOT_0P25_ATR | 176 | 22.16 pp | 13.64 pp | PASS_STAGE1 | — |
| H4 | TWO_SIDED_REFERENCE_RETEST | STOP_CONFIRMATION_EXTREME_0P25_ATR | 32 | -9.38 pp | -6.25 pp | REJECT_STAGE1 | valid_stop_coverage, one_ounce_coverage, stop_before_mfe_improvement, target_first_not_lower |
| H4 | TWO_SIDED_REFERENCE_RETEST | STOP_LATEST_KNOWN_OPPOSING_SWING_0P10_ATR | 44 | 4.55 pp | 2.27 pp | PASS_STAGE1 | — |
| H4 | TWO_SIDED_REFERENCE_RETEST | STOP_PIVOT_0P25_ATR | 45 | 2.22 pp | 6.67 pp | PASS_STAGE1 | — |
| H1 | BREAK_RETEST_CONTINUATION | STOP_CONFIRMATION_EXTREME_0P25_ATR | 669 | 7.62 pp | 3.89 pp | PASS_STAGE1 | — |
| H1 | BREAK_RETEST_CONTINUATION | STOP_LATEST_KNOWN_OPPOSING_SWING_0P10_ATR | 669 | 13.90 pp | 7.92 pp | PASS_STAGE1 | — |
| H1 | BREAK_RETEST_CONTINUATION | STOP_PIVOT_0P25_ATR | 669 | 17.49 pp | 10.46 pp | PASS_STAGE1 | — |
| H1 | DEEP_RETRACE_CONTINUATION | STOP_CONFIRMATION_EXTREME_0P25_ATR | 561 | -15.51 pp | -10.16 pp | REJECT_STAGE1 | valid_stop_coverage, one_ounce_coverage, stop_before_mfe_improvement, target_first_not_lower |
| H1 | DEEP_RETRACE_CONTINUATION | STOP_LATEST_KNOWN_OPPOSING_SWING_0P10_ATR | 685 | -2.34 pp | -2.04 pp | REJECT_STAGE1 | stop_before_mfe_improvement, target_first_not_lower |
| H1 | DEEP_RETRACE_CONTINUATION | STOP_PIVOT_0P25_ATR | 685 | 8.32 pp | 6.42 pp | PASS_STAGE1 | — |
| H1 | FALSE_CONTINUATION_REVERSAL | STOP_CONFIRMATION_EXTREME_0P25_ATR | 243 | 6.17 pp | 0.41 pp | PASS_STAGE1 | — |
| H1 | FALSE_CONTINUATION_REVERSAL | STOP_LATEST_KNOWN_OPPOSING_SWING_0P10_ATR | 242 | 10.74 pp | 4.13 pp | PASS_STAGE1 | — |
| H1 | FALSE_CONTINUATION_REVERSAL | STOP_PIVOT_0P25_ATR | 205 | -24.88 pp | -4.39 pp | REJECT_STAGE1 | valid_stop_coverage, one_ounce_coverage, stop_before_mfe_improvement, target_first_not_lower |
| H1 | IMMEDIATE_FAILURE_REVERSAL | STOP_CONFIRMATION_EXTREME_0P25_ATR | 262 | 2.67 pp | 1.15 pp | PASS_STAGE1 | — |
| H1 | IMMEDIATE_FAILURE_REVERSAL | STOP_LATEST_KNOWN_OPPOSING_SWING_0P10_ATR | 259 | 5.79 pp | 1.93 pp | PASS_STAGE1 | — |
| H1 | IMMEDIATE_FAILURE_REVERSAL | STOP_PIVOT_0P25_ATR | 245 | -24.49 pp | -4.90 pp | REJECT_STAGE1 | stop_before_mfe_improvement, target_first_not_lower |
| H1 | RUNAWAY_BREAKOUT | STOP_CONFIRMATION_EXTREME_0P25_ATR | 755 | 9.01 pp | 4.11 pp | PASS_STAGE1 | — |
| H1 | RUNAWAY_BREAKOUT | STOP_LATEST_KNOWN_OPPOSING_SWING_0P10_ATR | 755 | 15.63 pp | 6.89 pp | PASS_STAGE1 | — |
| H1 | RUNAWAY_BREAKOUT | STOP_PIVOT_0P25_ATR | 755 | 19.74 pp | 9.67 pp | PASS_STAGE1 | — |
| H1 | TWO_SIDED_REFERENCE_RETEST | STOP_CONFIRMATION_EXTREME_0P25_ATR | 170 | -18.82 pp | -7.65 pp | REJECT_STAGE1 | valid_stop_coverage, one_ounce_coverage, stop_before_mfe_improvement, target_first_not_lower |
| H1 | TWO_SIDED_REFERENCE_RETEST | STOP_LATEST_KNOWN_OPPOSING_SWING_0P10_ATR | 211 | 1.42 pp | 1.90 pp | REJECT_STAGE1 | stop_before_mfe_improvement |
| H1 | TWO_SIDED_REFERENCE_RETEST | STOP_PIVOT_0P25_ATR | 211 | 5.21 pp | 5.69 pp | PASS_STAGE1 | — |
| M15 | BREAK_RETEST_CONTINUATION | STOP_CONFIRMATION_EXTREME_0P25_ATR | 2,865 | 6.21 pp | 3.18 pp | PASS_STAGE1 | — |
| M15 | BREAK_RETEST_CONTINUATION | STOP_LATEST_KNOWN_OPPOSING_SWING_0P10_ATR | 2,865 | 10.92 pp | 5.65 pp | PASS_STAGE1 | — |
| M15 | BREAK_RETEST_CONTINUATION | STOP_PIVOT_0P25_ATR | 2,865 | 12.91 pp | 6.67 pp | PASS_STAGE1 | — |
| M15 | DEEP_RETRACE_CONTINUATION | STOP_CONFIRMATION_EXTREME_0P25_ATR | 2,560 | -19.80 pp | -11.64 pp | REJECT_STAGE1 | valid_stop_coverage, one_ounce_coverage, stop_before_mfe_improvement, target_first_not_lower |
| M15 | DEEP_RETRACE_CONTINUATION | STOP_LATEST_KNOWN_OPPOSING_SWING_0P10_ATR | 3,110 | -2.80 pp | -1.99 pp | REJECT_STAGE1 | stop_before_mfe_improvement, target_first_not_lower |
| M15 | DEEP_RETRACE_CONTINUATION | STOP_PIVOT_0P25_ATR | 3,110 | 5.24 pp | 3.63 pp | PASS_STAGE1 | — |
| M15 | FALSE_CONTINUATION_REVERSAL | STOP_CONFIRMATION_EXTREME_0P25_ATR | 1,171 | 2.99 pp | 0.94 pp | PASS_STAGE1 | — |
| M15 | FALSE_CONTINUATION_REVERSAL | STOP_LATEST_KNOWN_OPPOSING_SWING_0P10_ATR | 1,171 | 5.98 pp | 2.05 pp | PASS_STAGE1 | — |
| M15 | FALSE_CONTINUATION_REVERSAL | STOP_PIVOT_0P25_ATR | 1,020 | -28.82 pp | -4.12 pp | REJECT_STAGE1 | valid_stop_coverage, one_ounce_coverage, stop_before_mfe_improvement, target_first_not_lower |
| M15 | IMMEDIATE_FAILURE_REVERSAL | STOP_CONFIRMATION_EXTREME_0P25_ATR | 1,136 | 1.76 pp | 0.70 pp | REJECT_STAGE1 | stop_before_mfe_improvement |
| M15 | IMMEDIATE_FAILURE_REVERSAL | STOP_LATEST_KNOWN_OPPOSING_SWING_0P10_ATR | 1,136 | 3.61 pp | 1.76 pp | PASS_STAGE1 | — |
| M15 | IMMEDIATE_FAILURE_REVERSAL | STOP_PIVOT_0P25_ATR | 1,097 | -30.36 pp | -6.11 pp | REJECT_STAGE1 | stop_before_mfe_improvement, target_first_not_lower |
| M15 | RUNAWAY_BREAKOUT | STOP_CONFIRMATION_EXTREME_0P25_ATR | 3,501 | 7.31 pp | 3.28 pp | PASS_STAGE1 | — |
| M15 | RUNAWAY_BREAKOUT | STOP_LATEST_KNOWN_OPPOSING_SWING_0P10_ATR | 3,501 | 13.11 pp | 5.77 pp | PASS_STAGE1 | — |
| M15 | RUNAWAY_BREAKOUT | STOP_PIVOT_0P25_ATR | 3,501 | 15.37 pp | 6.80 pp | PASS_STAGE1 | — |
| M15 | TWO_SIDED_REFERENCE_RETEST | STOP_CONFIRMATION_EXTREME_0P25_ATR | 834 | -19.66 pp | -8.75 pp | REJECT_STAGE1 | valid_stop_coverage, one_ounce_coverage, stop_before_mfe_improvement, target_first_not_lower |
| M15 | TWO_SIDED_REFERENCE_RETEST | STOP_LATEST_KNOWN_OPPOSING_SWING_0P10_ATR | 1,036 | 2.41 pp | 2.32 pp | PASS_STAGE1 | — |
| M15 | TWO_SIDED_REFERENCE_RETEST | STOP_PIVOT_0P25_ATR | 1,036 | 3.47 pp | 3.09 pp | PASS_STAGE1 | — |

## Interpretation

Stage 1 asks only whether a point-in-time stop survives the unchanged path better without degrading target-first passage or becoming impractically wide. Passing here is not an economic edge; it only authorizes Stage 2 testing under the frozen costs, sizing, overlap, uncertainty and stability gates.
