# Gold Hybrid Structural Execution Research V1 Report

Verdict: `REJECT_NO_PROVISIONAL_STRUCTURAL_EXECUTION_IMPROVEMENT_ZERO_VALIDATION_CREDIT`

This is exposed execution research with zero validation credit. The frozen hybrid directions were unchanged. Nine preregistered structural execution policies were evaluated once; no alternative was added or retuned afterward.

| Policy | Trades | Negated | Win rate | Net R | PF | Max DD | Delta vs control | Adjusted CI low | Positive months | Benchmark | Gate |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|---|
| E0_CONTROL_MECHANICAL::T0_PRIMARY_LIQUIDITY_FULL | 645 | 177 | 56.12% | +21.3122 | 1.116 | 16.1463 | +0.0000 | +0.0000 | 3 | NO | REJECT |
| E0_CONTROL_MECHANICAL::T1_LOCAL_M15_FIRST_FULL | 645 | 177 | 59.07% | +22.9410 | 1.140 | 12.7059 | +1.6288 | -24.8394 | 3 | NO | REJECT |
| E0_CONTROL_MECHANICAL::T2_HALF_AT_1R_THEN_PRIMARY | 645 | 177 | 56.59% | +19.6611 | 1.119 | 15.1640 | -1.6511 | -17.4714 | 2 | NO | REJECT |
| E1_IMMEDIATE_LOCAL_M15_INVALIDATION::T0_PRIMARY_LIQUIDITY_FULL | 610 | 142 | 53.77% | +20.3725 | 1.111 | 14.6518 | -0.9397 | -28.2420 | 2 | NO | REJECT |
| E1_IMMEDIATE_LOCAL_M15_INVALIDATION::T1_LOCAL_M15_FIRST_FULL | 610 | 142 | 56.89% | +22.0013 | 1.133 | 11.5181 | +0.6891 | -36.7379 | 3 | NO | REJECT |
| E1_IMMEDIATE_LOCAL_M15_INVALIDATION::T2_HALF_AT_1R_THEN_PRIMARY | 610 | 142 | 54.10% | +17.2145 | 1.103 | 13.9660 | -4.0977 | -36.9604 | 3 | NO | REJECT |
| E2_M5_SWEEP_RECLAIM_POST_STRUCTURE::T0_PRIMARY_LIQUIDITY_FULL | 513 | 45 | 53.61% | +6.6454 | 1.039 | 22.5458 | -14.6668 | -39.0511 | 3 | NO | REJECT |
| E2_M5_SWEEP_RECLAIM_POST_STRUCTURE::T1_LOCAL_M15_FIRST_FULL | 513 | 45 | 57.31% | +8.2742 | 1.055 | 19.6342 | -13.0380 | -46.2028 | 3 | NO | REJECT |
| E2_M5_SWEEP_RECLAIM_POST_STRUCTURE::T2_HALF_AT_1R_THEN_PRIMARY | 513 | 45 | 54.00% | +5.0976 | 1.033 | 20.8619 | -16.2146 | -45.7637 | 2 | NO | REJECT |

## Provisional disposition

- Provisional policies: `NONE`.
- Any policy reached +45.7728R under the $50/no-upsize rules: **NO**.
- The mechanical stop/target swap remains only the control; it is not treated as a logical invalidation model.
- The unopened February interval, 2025 and 2026 remained closed.

## Integrity

- Primary and reference plans, confirmations, executions, policy metrics and checksums matched exactly.
- No direction, date, case, loss or winner was removed after outcomes.
- Every executed setup stayed at or below $50 displayed risk and no quantity was upsized.
- Multiple simultaneous valid setups remained permitted.
