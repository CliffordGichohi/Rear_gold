# External Evidence Edge Replication and Transfer V1 — Final Report

Formal verdict: **REJECT_NO_EXTERNALLY_EVIDENCED_RULE_REPLICATED_ECONOMICALLY**

The three external rules were frozen before local market values were opened. All figures below are the unchanged 2022–2024 economic-gate results; partial 2021 data are descriptive only.

| Candidate | Verdict | Dates | Win rate | Expectancy R | PF | Net R/month | USD/month | Max DD R | 1.5x-cost expectancy | Failed gates |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| EER_C01_EQUITY_MIM_R1 | REJECT | 761 | 44.81% | -0.0964 | 0.755 | -2.037 | $-203.71 | 79.271 | -0.1254 | net_expectancy_gt_zero, profit_factor_gte_1p10, cluster_ci95_low_gt_zero, stress_1p5_expectancy_gt_zero, positive_folds_gte_4, positive_years_gte_2, maximum_drawdown_lte_15r, year_concentration_lte_0p70, instrument_concentration_lte_0p70, holm_p_lte_0p05 |
| EER_C02_EQUITY_MIM_R1_R12 | REJECT | 458 | 46.51% | -0.0690 | 0.820 | -0.878 | $-87.83 | 49.072 | -0.0967 | net_expectancy_gt_zero, profit_factor_gte_1p10, cluster_ci95_low_gt_zero, stress_1p5_expectancy_gt_zero, positive_folds_gte_4, positive_years_gte_2, maximum_drawdown_lte_15r, year_concentration_lte_0p70, instrument_concentration_lte_0p70, holm_p_lte_0p05 |
| EER_C03_WTI_MIM_R1 | REJECT | 771 | 46.04% | -0.0807 | 0.796 | -1.728 | $-172.82 | 62.487 | -0.1356 | net_expectancy_gt_zero, profit_factor_gte_1p10, cluster_ci95_low_gt_zero, stress_1p5_expectancy_gt_zero, positive_folds_gte_4, positive_years_gte_2, maximum_drawdown_lte_15r, year_concentration_lte_0p70, holm_p_lte_0p05 |

Passing candidates: none.
Frozen portfolio: none.
2025 disposition: LOCKED_NOT_OPENED_BY_FROZEN_POLICY.
2026 disposition: LOCKED_NOT_OPENED_BY_FROZEN_POLICY.
Prospective ledger: NOT_INITIALIZED_NO_PASSING_RULE.

No external rule was inverted, filtered, retuned, or cosmetically repaired. The primary pandas implementation and the independent CSV-stream implementation reproduced every base identity, direction, cost input, position size, daily result, statistic, and verdict exactly.
