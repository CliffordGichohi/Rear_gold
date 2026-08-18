# Multi-Asset Observable Auction-State Conditional Routing V1

## Verdict

**REJECT_NO_ECONOMICALLY_TRADABLE_CONDITIONAL_ROUTER**

- Point-in-time checkpoints: **23,836** across M15, H1 and H4.
- Stage-1 tests: **66**; relationship passes: **0**.
- Stage-2 interactions: **18**; relationship passes: **0**.
- Router-selected, cluster-accepted trades: **477** (13.25/month).
- OOF expectancy: **-0.1391139791 R/trade**; PF **0.7535918845**.
- OOF result: **-1.8432602227 R/month**, **$-181.3198899337/month**.
- Maximum drawdown: **69.7304923717 R**.
- 1.5x-cost expectancy: **-0.1966011495 R/trade**.
- Calibration Brier skill: **-0.0097932589**; ECE **0.0352459822**.

Failed economic gates: net_expectancy_gt_zero, profit_factor_gte_1p10, cluster_ci95_low_gt_zero, stress_expectancy_gt_zero, positive_folds_gte_4, positive_years_gte_2, brier_skill_gt_zero, maximum_drawdown_lte_15r, year_concentration_lte_0p70, session_concentration_lte_0p70.

XAUUSD remained outside this branch. No paid data were acquired. Calendar 2025 and 2026 were opened only if the frozen development router passed; forward disposition: **NOT_OPENED_NO_DEVELOPMENT_CANDIDATE**.
