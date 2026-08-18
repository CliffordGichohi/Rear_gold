# Gold H4 Continuation Tradable-Ceiling and Monetization Audit V1

Verdict: **UPPER_BOUND_CAPACITY_PRESENT_NOT_DEMONSTRATED**

This audit did not create or test a new strategy. It measured the frozen H4 continuation control against increasingly realistic ceilings on the same 248 executable OOF cases; 176 no-trigger cases remained visible, and the 50 overlap-skipped cases received zero at post-overlap stages.

## Amendment A: behavioural-oracle coverage

The visual behavioural oracle exists for 215 of 248 executable cases. The 33 unavailable references were not imputed or filtered: all 248 cases remain in every observable, stop-feasible, execution, cost, overlap, and 10R decision stage. Oracle retention against those all-case stages is therefore reported as not comparable.

## Matched-case waterfall

| Stage | Total R | R/month | $/month at $50 | $/month at 1% | Oracle retained |
|---|---:|---:|---:|---:|---:|
| BEHAVIOURAL_ORACLE_AVAILABLE_SUBSET | 610.01 | 15.641 | $782.07 | $1564.13 | 100.00% |
| OBSERVABLE_ENTRY_PERFECT_EXIT_GROSS | 936.60 | 24.016 | $1200.78 | $2401.55 | n/a% |
| STOP_FEASIBLE_PERFECT_EXIT_GROSS | 615.11 | 15.772 | $788.60 | $1577.21 | n/a% |
| FROZEN_EXECUTION_GROSS_PRE_OVERLAP | 62.64 | 1.606 | $80.31 | $160.61 | n/a% |
| FROZEN_EXECUTION_NET_PRE_OVERLAP | 54.84 | 1.406 | $70.30 | $140.61 | n/a% |
| FROZEN_EXECUTION_NET_AFTER_OVERLAP | 37.88 | 0.971 | $48.56 | $97.12 | n/a% |

## Stop-feasible operational upper bound

- `STOP_FEASIBLE_NET_BASE_COST`: 607.31R total, 15.572R/month, $1557.20/month at 1% linear risk.
- `STOP_FEASIBLE_NET_1P5X_COST`: 603.41R total, 15.472R/month, $1547.20/month at 1% linear risk.
- `STOP_FEASIBLE_NET_BASE_COST_AFTER_OVERLAP`: 482.19R total, 12.364R/month, $1236.37/month at 1% linear risk.
- `STOP_FEASIBLE_NET_1P5X_COST_AFTER_OVERLAP`: 479.03R total, 12.283R/month, $1228.29/month at 1% linear risk.

## Path findings

- Stopped cases: 133 (53.6%).
- Stopped then +1R: 75 (56.4% of stopped cases).
- Stopped then +2R: 51 (38.3%).
- Stopped then original target: 45 (33.8%).
- Full-path MFE: mean 4.19R, median 2.65R.
- MFE before invalidation: mean 2.75R; stopped-case median 0.40R.

## Feasibility decision

- Mathematical observable-entry ceiling >=10R/month: **true** (24.016R/month).
- Stop-feasible, costed, post-overlap ceiling >=10R/month: **true** (12.364R/month).
- Demonstrated frozen execution >=10R/month: **false** (0.971R/month).
- Required disposition: `RECOMMEND_EXACTLY_ONE_BOUNDED_DIRECTION_WITHOUT_IMPLEMENTATION`.
- Exactly one bounded direction, not implemented: `H4_LIQUIDITY_TARGET_CAPTURE_RESEARCH`.

## Integrity

- Primary/reference per-case payloads byte-identical: true.
- Primary/reference result JSON byte-identical: true.
- Predecessor H4 PnL reproduced exactly. Calendar 2025/2026 remained locked. Paid acquisition: $0.00.
- Perfect-exit stages are diagnostic hindsight ceilings, not tradable performance.
