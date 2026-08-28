# Gold Auction Liquidity-Hierarchy Hybrid Router V1 Report

Verdict: `REJECT_HYBRID_NO_UPSIZE_EXPOSED_BENCHMARK_ZERO_VALIDATION_CREDIT`

This was one frozen post-hoc exposed policy. It was run once without an alternative or retune. The sealed +45.7728R result is the comparison benchmark, not an unseen validation result.

| Track | Executed | Win rate | Net R | PnL USD | PF | Max DD R | Max displayed stop risk |
|---|---:|---:|---:|---:|---:|---:|---:|
| A: fixed original quantity | 648 | 56.33% | +55.4062 | $+2770.31 | 1.299 | 15.1502 | $998.76 |
| B: no-upsize, $50 cap | 645 | 56.12% | +21.3122 | $+1065.61 | 1.116 | 16.1463 | $49.98 |
| Frozen complete-negation benchmark | 648 | — | +45.7728 | $+2288.64 | 1.241 | 21.7582 | not risk-capped |

Track B benchmark met: **NO**.
Risk-infeasible whole-ounce identities retained: **3**.

## Track B by month

| Month | Trades | Win rate | Net R | PnL USD | PF |
|---|---:|---:|---:|---:|---:|
| 2022-01 | 111 | 46.85% | -0.7052 | $-35.26 | 0.981 |
| 2022-02 | 72 | 58.33% | +0.5652 | $+28.26 | 1.025 |
| 2022-03 | 119 | 57.14% | +10.1696 | $+508.48 | 1.323 |
| 2022-04 | 111 | 55.86% | -4.1757 | $-208.79 | 0.868 |
| 2022-05 | 105 | 66.67% | +18.1939 | $+909.69 | 1.973 |
| 2022-06 | 127 | 53.54% | -2.7356 | $-136.78 | 0.936 |

## Track B route contribution

| Frozen route | Trades | Net R | PF |
|---|---:|---:|---:|
| DESTINATION_AGE_LT_240M_PRESERVE | 28 | -1.1786 | 0.867 |
| H1_UNCONFIRMED_AGE_GTE_240M_NEGATE | 177 | +29.9596 | 2.696 |
| H4_DESTINATION_PRESERVE | 41 | +0.1040 | 1.012 |
| LOCAL_M15_LEVEL_CONFIRMS_DESTINATION_PRESERVE | 156 | -3.8066 | 0.931 |
| NON_CONTINUATION_UNCHANGED | 214 | -7.4052 | 0.915 |
| RANGE_CONTEXT_PRESERVE | 29 | +3.6390 | 1.639 |

## Integrity

- All 648 original executable identities were retained; no daily cap or overlap suppression was used.
- Track A reproduced either the sealed original or sealed fixed-quantity negated execution for every identity.
- Track B never increased quantity and never exceeded $50 displayed stop exposure.
- Primary and reference routes, executions, summaries and checksums matched exactly.
- No alternative policy, new data, 2025, 2026 or paid source was opened.
