# Gold H4 Liquidity-Target Capture Falsification V1

Verdict: **TERMINATE_GOLD_ONLY_10R_BRANCH**

This final bounded study changed only management after the already-frozen original liquidity target. All 248 executable cases were evaluated; stop-first and time-exit cases remained in the denominator. Calendar 2025 and 2026 stayed locked.

## Economics

| Policy | Managed | Retained | R/month | $/month at 1% | PF | Incremental R/month | Absolute CI low | Incremental CI low | Verdict |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---|
| CONTROL_FULL_CLOSE | 0 | 198 | 0.971 | $97.12 | 1.366 | 0.000 | -0.004 | 0.000 | CONTROL |
| TARGET_TAKE_25_RUN_75 | 88 | 198 | 1.189 | $118.88 | 1.447 | 0.218 | 0.015 | -0.003 | REJECT |
| TARGET_TAKE_50_RUN_50 | 88 | 198 | 1.110 | $111.05 | 1.419 | 0.139 | 0.011 | -0.004 | REJECT |
| TARGET_TAKE_75_RUN_25 | 81 | 198 | 1.032 | $103.22 | 1.389 | 0.061 | -0.001 | -0.006 | REJECT |

## Target-only ceiling

- Fixed-disposition target-only perfect-exit ceiling: **8.220R/month** ($822.01/month at 1% risk).
- The same hindsight ceiling at 1.5x costs: **8.139R/month**.
- This ceiling is not tradable performance; it is an impossibility diagnostic that changes only original target-first cases.

## Decision

- Best observed policy: `TARGET_TAKE_25_RUN_75` at 1.189R/month.
- Selected provisional policy: `None`.
- Required disposition: `NO_NEW_GOLD_RESEARCH_BRANCH`.
- Termination reason: `NO_OPERATIONAL_POLICY_REACHED_10R_AND_PASSED_ALL_GATES`.
- `TARGET_TAKE_25_RUN_75` failed gates: r_per_month_gte_10, incremental_ci95_low_gt_zero, holm_incremental_p_lte_0p05, maximum_drawdown_pct_at_1pct_lte_15.
- `TARGET_TAKE_50_RUN_50` failed gates: r_per_month_gte_10, incremental_ci95_low_gt_zero, holm_incremental_p_lte_0p05, maximum_drawdown_pct_at_1pct_lte_15.
- `TARGET_TAKE_75_RUN_25` failed gates: r_per_month_gte_10, absolute_ci95_low_gt_zero, incremental_ci95_low_gt_zero, holm_incremental_p_lte_0p05, maximum_drawdown_pct_at_1pct_lte_15.

## Integrity

- Primary/reference case payloads byte-identical: true.
- Primary/reference result payloads byte-identical: true.
- The predecessor control PnL and overlap dispositions reproduced exactly.
- Calendar 2025/2026 accessed: false. Paid acquisition: $0.00.
