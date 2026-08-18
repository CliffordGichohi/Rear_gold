# Gold Annotated Replay V3 Post-Practice Diagnostic

Completed: `2026-08-17T14:30:23.688586+00:00`

Formal evidence status: `ZERO_CREDIT_DESCRIPTIVE`

Sample description: `DESCRIPTIVELY_POSITIVE_BUT_INCONCLUSIVE`

Edge verdict: `NOT_EVALUABLE_FROM_TWENTY_PRACTICE_DAYS`

## Bottom line

You completed all 20 practice days and placed 13 filled trades across 13 traded days; 7 days had no trade. The ledger is complete and internally reproducible.

At the frozen $50 risk unit, the practice sample produced **+3.013R ($+150.66)**, a **46.2%** win rate, **+0.232R/trade** expectancy, and profit factor **1.365111**. Maximum chronological drawdown was **3.612R ($180.60)**.

The 95% Wilson win-rate interval is 23.2% to 70.9%. The completed-day cluster-bootstrap expectancy interval is -0.646R to +1.115R. This uncertainty is too wide for an edge claim.

## Complete chronological trade record

| Case | Date | Side | TF | Session | Resolution | PnL | R50 | MFE R | MAE R | Confidence |
|---|---|---|---|---|---|---|---|---|---|---|
| V3-P-001 | 2021-08-02 | LONG | 15M | ROLLOVER | STOPPED | $-60.76 | -1.215 | 0.27 | 1.22 | 60% |
| V3-P-002 | 2021-08-06 | SHORT | 15M | LONDON_NEW_YORK_OVERLAP | TARGET_HIT | $-119.84 | -2.397 | 0.56 | 2.42 | 60% |
| V3-P-003 | 2021-08-19 | LONG | 1H | LONDON | TARGET_HIT | $91.50 | +1.830 | 1.94 | 0.45 | 30% |
| V3-P-004 | 2021-08-27 | LONG | 15M | LONDON_NEW_YORK_OVERLAP | STOPPED | $-47.92 | -0.958 | 0.51 | 1.27 | 30% |
| V3-P-005 | 2021-09-15 | LONG | 15M | LONDON_NEW_YORK_OVERLAP | TIME_EXIT | $-27.98 | -0.559 | 0.25 | 0.73 | 60% |
| V3-P-008 | 2021-09-29 | SHORT | 15M | LONDON_NEW_YORK_OVERLAP | TARGET_HIT | $91.49 | +1.830 | 2.08 | 0.60 | 60% |
| V3-P-010 | 2021-10-12 | SHORT | 4H | LONDON_NEW_YORK_OVERLAP | STOPPED | $-69.61 | -1.392 | 0.28 | 1.61 | 41% |
| V3-P-012 | 2021-10-18 | LONG | 15M | LONDON_NEW_YORK_OVERLAP | TARGET_HIT | $107.37 | +2.147 | 2.31 | 0.66 | 41% |
| V3-P-013 | 2021-11-10 | LONG | 15M | LONDON_NEW_YORK_OVERLAP | TARGET_HIT | $130.23 | +2.605 | 6.98 | 0.82 | 50% |
| V3-P-015 | 2021-11-19 | SHORT | 15M | LONDON_NEW_YORK_OVERLAP | STOPPED | $-28.75 | -0.575 | 1.54 | 0.99 | 50% |
| V3-P-017 | 2021-12-07 | LONG | 15M | LONDON_NEW_YORK_OVERLAP | STOPPED | $-57.81 | -1.156 | 0.81 | 1.58 | 28% |
| V3-P-018 | 2021-12-10 | LONG | 15M | LONDON_NEW_YORK_OVERLAP | TARGET_HIT | $82.49 | +1.650 | 3.53 | 0.20 | 28% |
| V3-P-019 | 2021-12-16 | LONG | 15M | LONDON_NEW_YORK_OVERLAP | TIME_EXIT | $60.24 | +1.205 | 1.25 | 0.12 | 28% |

## Frozen segment diagnostics

| Family | State | N | Win rate | Expectancy R | Net R | Support |
|---|---|---|---|---|---|---|
| direction | LONG | 9 | 55.6% | +0.616 | +5.547 | SUPPORTED_DESCRIPTIVE |
| direction | SHORT | 4 | 25.0% | -0.634 | -2.534 | SUPPORTED_DESCRIPTIVE |
| timeframe | 15m | 11 | 45.5% | +0.234 | +2.575 | SUPPORTED_DESCRIPTIVE |
| timeframe | 1h | 1 | 100.0% | +1.830 | +1.830 | LOW_SUPPORT_DESCRIPTIVE_ONLY |
| timeframe | 4h | 1 | 0.0% | -1.392 | -1.392 | LOW_SUPPORT_DESCRIPTIVE_ONLY |
| session | LONDON | 1 | 100.0% | +1.830 | +1.830 | LOW_SUPPORT_DESCRIPTIVE_ONLY |
| session | LONDON_NEW_YORK_OVERLAP | 11 | 45.5% | +0.218 | +2.398 | SUPPORTED_DESCRIPTIVE |
| session | ROLLOVER | 1 | 0.0% | -1.215 | -1.215 | LOW_SUPPORT_DESCRIPTIVE_ONLY |
| user_fundamental_alignment | CONFIRMING | 7 | 42.9% | +0.145 | +1.018 | SUPPORTED_DESCRIPTIVE |
| user_fundamental_alignment | CONTRADICTING | 6 | 50.0% | +0.333 | +1.995 | SUPPORTED_DESCRIPTIVE |
| system_macro_alignment | CONFIRMING | 4 | 50.0% | +0.366 | +1.463 | SUPPORTED_DESCRIPTIVE |
| system_macro_alignment | CONTRADICTING | 4 | 75.0% | +0.882 | +3.528 | SUPPORTED_DESCRIPTIVE |
| system_macro_alignment | NEUTRAL_OR_UNKNOWN | 5 | 20.0% | -0.396 | -1.978 | SUPPORTED_DESCRIPTIVE |
| selected_structure_alignment | CONFIRMING | 2 | 50.0% | +0.123 | +0.246 | LOW_SUPPORT_DESCRIPTIVE_ONLY |
| selected_structure_alignment | CONTRADICTING | 5 | 80.0% | +1.213 | +6.065 | SUPPORTED_DESCRIPTIVE |
| selected_structure_alignment | NEUTRAL_OR_UNKNOWN | 6 | 16.7% | -0.550 | -3.298 | SUPPORTED_DESCRIPTIVE |

Segments below three trades are descriptive only. Multi-label trigger and driver groups are preserved in the machine-readable result.

## Execution and path behavior

- Mean/median MFE: 1.716R / 1.252R.
- Mean/median MAE: 0.974R / 0.816R.
- Mean/median holding time: 155.1 / 81.0 minutes.
- Recorded entry/exit execution cost: $18.85.
- Stops: 5; stopped then original target later touched: 3.
- Losing trades that first achieved at least +0.5R MFE: 4.
- Objective recent-move chase flags: 4.
- Mean winner capture efficiency: 0.758588.

## Confidence and reasoning discipline

- Mean stated confidence: 43.5%.
- Observed practice win rate: 46.2%.
- Confidence minus win rate: -2.6 percentage points.
- Brier score: 0.304.
- All required annotation fields nonempty: 13/13.
- Macro-specific reasoning: 12/13.
- Higher-timeframe-specific reasoning: 0/13.
- Specific invalidation: 0/13; generic invalidation: 13/13.
- Specific target logic: 0/13; generic target logic: 13/13.
- Specific event-risk statement: 13/13.

## Interpretation boundary

The figures describe usability-practice behavior, not a validated strategy. The dates were selected outcome-blindly, but the sample is only twenty partial-2021 practice days, the operator was learning the interface, and two early lifecycle outcomes were viewed while confirming capture. No monthly extrapolation, risk scaling, or edge PASS is permitted.

The appropriate next discussion is about which parts of the decision process were repeatable, which annotations were too generic to test, and what must be frozen before opening the one-year scored collection. The machine-readable result and complete trade table retain every case, including losses and no-trade days.
