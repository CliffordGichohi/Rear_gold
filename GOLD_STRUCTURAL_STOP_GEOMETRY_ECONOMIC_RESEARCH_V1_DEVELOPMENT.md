# Gold Structural Stop Geometry Economic Research V1 — Development

Status: **REJECT_NO_DEVELOPMENT_ECONOMIC_STOP_CANDIDATE**

## Verdict

- Economically evaluated tests: **53** (18 controls + 35 Stage-1 alternatives).
- Alternatives passing every frozen economic gate: **0**.
- Frozen shortlist: **0**.
- 2025 and 2026 remained locked during development evaluation.
- No data was acquired; charge: $0.00.

## Strongest alternatives by out-of-fold net expectancy

| Candidate | Trades | Exp R | PF | CI95 low | 1.5x-cost Exp R | DD R | Verdict | Failed gates |
|---|---:|---:|---:|---:|---:|---:|---|---|
| H4|TWO_SIDED_REFERENCE_RETEST|STOP_LATEST_KNOWN_OPPOSING_SWING_0P10_ATR | 44 | 0.1672 | 1.491361636184 | -0.103949782757 | 0.1437 | 3.58 | REJECT_ECONOMIC | positive_cluster_ci95_low, bh_q, maximum_positive_session_share |
| H4|TWO_SIDED_REFERENCE_RETEST|STOP_PIVOT_0P25_ATR | 45 | 0.1053 | 1.349496735913 | -0.117037416197 | 0.0853 | 3.66 | REJECT_ECONOMIC | positive_cluster_ci95_low, bh_q, maximum_positive_year_share |
| H4|RUNAWAY_BREAKOUT|STOP_CONFIRMATION_EXTREME_0P25_ATR | 170 | 0.0999 | 1.190183701355 | -0.075093909519 | 0.0847 | 9.64 | REJECT_ECONOMIC | positive_cluster_ci95_low, bh_q, maximum_positive_year_share |
| H4|BREAK_RETEST_CONTINUATION|STOP_CONFIRMATION_EXTREME_0P25_ATR | 157 | 0.0301 | 1.061225477466 | -0.127046833097 | 0.0154 | 11.69 | REJECT_ECONOMIC | positive_cluster_ci95_low, bh_q, maximum_positive_year_share, both_parameter_neighbours_positive |
| H1|IMMEDIATE_FAILURE_REVERSAL|STOP_CONFIRMATION_EXTREME_0P25_ATR | 230 | 0.0233 | 1.058515739944 | -0.10337403479 | 0.0084 | 7.23 | REJECT_ECONOMIC | positive_cluster_ci95_low, bh_q, maximum_positive_session_share |
| H1|IMMEDIATE_FAILURE_REVERSAL|STOP_LATEST_KNOWN_OPPOSING_SWING_0P10_ATR | 226 | 0.0135 | 1.039134181977 | -0.097453618132 | 0.0011 | 12.46 | REJECT_ECONOMIC | profit_factor, positive_cluster_ci95_low, bh_q, positive_validation_folds, positive_calendar_years, maximum_positive_year_share, positive_sessions, maximum_positive_session_share |
| H4|RUNAWAY_BREAKOUT|STOP_PIVOT_0P25_ATR | 164 | 0.0133 | 1.032901906477 | -0.122234604301 | 0.0046 | 11.33 | REJECT_ECONOMIC | profit_factor, positive_cluster_ci95_low, bh_q, positive_validation_folds, positive_calendar_years, maximum_positive_year_share |
| H4|RUNAWAY_BREAKOUT|STOP_LATEST_KNOWN_OPPOSING_SWING_0P10_ATR | 167 | 0.0006 | 1.001385659772 | -0.14578840118 | -0.0091 | 11.55 | REJECT_ECONOMIC | profit_factor, positive_cluster_ci95_low, bh_q, positive_cost_1p5x, positive_validation_folds, maximum_positive_year_share |
| H1|RUNAWAY_BREAKOUT|STOP_PIVOT_0P25_ATR | 638 | -0.0238 | 0.943199891136 | -0.090196674773 | -0.0426 | 31.09 | REJECT_ECONOMIC | positive_net_expectancy, profit_factor, positive_cluster_ci95_low, bh_q, positive_cost_1p5x, positive_validation_folds, positive_calendar_years, maximum_positive_year_share, positive_sessions, maximum_positive_session_share, both_parameter_neighbours_positive |
| H4|BREAK_RETEST_CONTINUATION|STOP_PIVOT_0P25_ATR | 153 | -0.0338 | 0.911464527156 | -0.157247784764 | -0.0423 | 11.67 | REJECT_ECONOMIC | positive_net_expectancy, profit_factor, positive_cluster_ci95_low, bh_q, positive_cost_1p5x, positive_validation_folds, positive_calendar_years, maximum_positive_year_share, both_parameter_neighbours_positive |
| M15|IMMEDIATE_FAILURE_REVERSAL|STOP_LATEST_KNOWN_OPPOSING_SWING_0P10_ATR | 995 | -0.0406 | 0.879719633627 | -0.08912468909 | -0.0691 | 54.36 | REJECT_ECONOMIC | positive_net_expectancy, profit_factor, positive_cluster_ci95_low, bh_q, positive_cost_1p5x, positive_validation_folds, positive_calendar_years, maximum_positive_year_share, positive_sessions, maximum_positive_session_share, both_parameter_neighbours_positive |
| H4|BREAK_RETEST_CONTINUATION|STOP_LATEST_KNOWN_OPPOSING_SWING_0P10_ATR | 155 | -0.0425 | 0.896971700585 | -0.177468923334 | -0.0521 | 10.65 | REJECT_ECONOMIC | positive_net_expectancy, profit_factor, positive_cluster_ci95_low, bh_q, positive_cost_1p5x, positive_calendar_years, maximum_positive_year_share, both_parameter_neighbours_positive |

## Forward disposition

The forward years may be opened only for the frozen shortlist above. If the shortlist is empty, the contract requires stopping without inspecting 2025/2026 values.
