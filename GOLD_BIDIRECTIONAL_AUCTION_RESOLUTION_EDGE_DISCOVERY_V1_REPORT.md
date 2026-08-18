# Gold Bidirectional Auction-Resolution Edge Discovery V1

Development verdict: **REJECT_NO_DEVELOPMENT_ECONOMIC_EDGE**

The study compared the continuation-only control, reversal-only resolution, and a bidirectional one-flip policy on the same sealed 2021–2024 pullback population. Rules and risk splits were frozen before the price paths were opened. 2025 and 2026 remained locked throughout development.

## Development economics

| Timeframe | Model | Cases | Cases/mo | Win % | Exp R | PF | Net R | $/mo at $50 | DD $ | CI95 low | Flips | Verdict |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| M15 | CONTINUATION_ONLY_CONTROL | 2359 | 60.49 | 35.9 | -0.1532 | 0.743 | -361.41 | -463.35 | 18191.61 | -0.1986 | 0.0 | REJECT |
| M15 | REVERSAL_ONLY | 1865 | 47.82 | 33.7 | -0.3628 | 0.436 | -676.68 | -867.53 | 33833.86 | -0.4042 | 0.0 | REJECT |
| M15 | BIDIRECTIONAL_ONE_FLIP | 3656 | 93.74 | 37.1 | -0.0825 | 0.599 | -301.71 | -386.81 | 15085.62 | -0.0952 | 8.6 | REJECT |
| H1 | CONTINUATION_ONLY_CONTROL | 532 | 13.64 | 38.7 | -0.0548 | 0.898 | -29.13 | -37.35 | 2040.12 | -0.1509 | 0.0 | REJECT |
| H1 | REVERSAL_ONLY | 217 | 5.56 | 36.9 | -0.1977 | 0.684 | -42.90 | -55.00 | 2402.07 | -0.3524 | 0.0 | REJECT |
| H1 | BIDIRECTIONAL_ONE_FLIP | 705 | 18.08 | 39.6 | -0.0255 | 0.842 | -17.95 | -23.01 | 1147.66 | -0.0503 | 2.8 | REJECT |
| H4 | CONTINUATION_ONLY_CONTROL | 198 | 5.08 | 41.9 | 0.1913 | 1.366 | 37.88 | 48.56 | 948.76 | -0.0092 | 0.0 | REJECT |
| H4 | REVERSAL_ONLY | 126 | 3.23 | 26.2 | -0.3988 | 0.452 | -50.25 | -64.43 | 2560.10 | -0.5659 | 0.0 | REJECT |
| H4 | BIDIRECTIONAL_ONE_FLIP | 226 | 5.79 | 40.3 | 0.0335 | 1.090 | 7.56 | 9.69 | 710.27 | -0.0848 | 21.7 | REJECT |

## Contribution and gate findings

- `M15::CONTINUATION_ONLY_CONTROL`: continuation $-18070.50, reversal $0.00, 1.5x-cost expectancy -0.2190R, successful flips n/a%, oracle captured -5.822%; failed gates: net_expectancy_gt_zero, profit_factor_gte_1p10, cluster_ci95_low_gt_zero, holm_p_lte_0p10, cost_1p5x_expectancy_gt_zero, positive_validation_folds_gte_3, positive_calendar_years_gte_2, maximum_positive_year_share_lte_0p70, maximum_positive_session_share_lte_0p70, maximum_drawdown_pct_lte_15.
- `M15::REVERSAL_ONLY`: continuation $0.00, reversal $-33833.86, 1.5x-cost expectancy -0.5455R, successful flips n/a%, oracle captured -29.152%; failed gates: net_expectancy_gt_zero, profit_factor_gte_1p10, cluster_ci95_low_gt_zero, holm_p_lte_0p10, cost_1p5x_expectancy_gt_zero, positive_validation_folds_gte_3, positive_calendar_years_gte_2, maximum_positive_year_share_lte_0p70, maximum_positive_session_share_lte_0p70, maximum_drawdown_pct_lte_15.
- `M15::BIDIRECTIONAL_ONE_FLIP`: continuation $-5248.02, reversal $-9837.60, 1.5x-cost expectancy -0.1232R, successful flips 37.6%, oracle captured -4.087%; failed gates: net_expectancy_gt_zero, profit_factor_gte_1p10, cluster_ci95_low_gt_zero, holm_p_lte_0p10, cost_1p5x_expectancy_gt_zero, positive_validation_folds_gte_3, positive_calendar_years_gte_2, maximum_positive_year_share_lte_0p70, maximum_positive_session_share_lte_0p70, maximum_drawdown_pct_lte_15, bidirectional_positive_fixed_split_fraction_gte_2_of_3.
- `H1::CONTINUATION_ONLY_CONTROL`: continuation $-1456.74, reversal $0.00, 1.5x-cost expectancy -0.0849R, successful flips n/a%, oracle captured -2.183%; failed gates: net_expectancy_gt_zero, profit_factor_gte_1p10, cluster_ci95_low_gt_zero, holm_p_lte_0p10, cost_1p5x_expectancy_gt_zero, positive_validation_folds_gte_3, positive_calendar_years_gte_2, maximum_positive_year_share_lte_0p70, maximum_positive_session_share_lte_0p70, maximum_drawdown_pct_lte_15.
- `H1::REVERSAL_ONLY`: continuation $0.00, reversal $-2145.13, 1.5x-cost expectancy -0.2948R, successful flips n/a%, oracle captured -19.508%; failed gates: net_expectancy_gt_zero, profit_factor_gte_1p10, cluster_ci95_low_gt_zero, holm_p_lte_0p10, cost_1p5x_expectancy_gt_zero, positive_validation_folds_gte_3, positive_calendar_years_gte_2, maximum_positive_year_share_lte_0p70, maximum_positive_session_share_lte_0p70, maximum_drawdown_pct_lte_15.
- `H1::BIDIRECTIONAL_ONE_FLIP`: continuation $-266.49, reversal $-630.99, 1.5x-cost expectancy -0.0404R, successful flips 40.0%, oracle captured -1.217%; failed gates: net_expectancy_gt_zero, profit_factor_gte_1p10, cluster_ci95_low_gt_zero, holm_p_lte_0p10, cost_1p5x_expectancy_gt_zero, positive_validation_folds_gte_3, positive_calendar_years_gte_2, maximum_positive_year_share_lte_0p70, bidirectional_positive_fixed_split_fraction_gte_2_of_3.
- `H4::CONTINUATION_ONLY_CONTROL`: continuation $1893.82, reversal $0.00, 1.5x-cost expectancy 0.1754R, successful flips n/a%, oracle captured 7.972%; failed gates: cluster_ci95_low_gt_zero.
- `H4::REVERSAL_ONLY`: continuation $0.00, reversal $-2512.74, 1.5x-cost expectancy -0.4518R, successful flips n/a%, oracle captured -32.987%; failed gates: net_expectancy_gt_zero, profit_factor_gte_1p10, cluster_ci95_low_gt_zero, holm_p_lte_0p10, cost_1p5x_expectancy_gt_zero, positive_validation_folds_gte_3, positive_calendar_years_gte_2, maximum_positive_year_share_lte_0p70, maximum_positive_session_share_lte_0p70, maximum_drawdown_pct_lte_15.
- `H4::BIDIRECTIONAL_ONE_FLIP`: continuation $1141.02, reversal $-762.91, 1.5x-cost expectancy 0.0132R, successful flips 46.9%, oracle captured 1.562%; failed gates: profit_factor_gte_1p10, cluster_ci95_low_gt_zero, holm_p_lte_0p10.

## Integrity and disposition

- Population: 8,653 cases; 8,650 certified tapes; 43,265 frozen case-policy plans.
- Primary/reference plan payloads byte-identical: true.
- Advanced development candidates: none.
- 2025 accessed: false. 2026 accessed: false. Paid acquisition: $0.00.
- The reported oracle is the previously sealed original-direction visual-pivot ceiling; it is not a tradable or two-sided oracle.

Because no development candidate passed every gate, the forward periods remain locked and no prospective ledger is initialized.
