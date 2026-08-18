# Gold Blind Codex-Operator Replay V1 — Early-Stop Result

## Verdict

**INCONCLUSIVE — early-stop, zero-credit calibration.** The clean primary sample contains 29 cases and 22 filled trades, below the frozen 30-trade minimum. These numbers describe how Codex performed; they do not validate an edge.

## Primary clean performance

Case 019 is excluded. Across 29 cases, Codex traded 22 and passed on 7. It won 6, lost 15, and scratched 1.

- Net: **-1.814R ($-90.71)**.
- Win rate: **27.3%**; 95% Wilson interval 13.2%–48.2%.
- Expectancy: **-0.082R/trade** ($-4.12); bootstrap 95% interval -0.504R to +0.390R.
- Profit factor: **0.82**. Average win/loss: +1.350R / -0.661R.
- Maximum drawdown: **4.587R ($229.37)**, 2.29% of the frozen $10,000 account.
- Direction mix: 4 long and 18 short.
- Mean MFE/MAE: 0.935R / 0.591R.
- At 1.5× estimated execution costs: $-111.59.

## All-30 sensitivity

Including contaminated Case 019 changes the descriptive total to **-1.798R ($-89.88)**, with 7/23 wins, 30.4% win rate, 0.82 profit factor, and -0.078R/trade expectancy. This sensitivity receives no primary evidence credit.

## Gate disposition

The branch cannot PASS because the clean sample has only 22 filled trades and one calendar quarter. The uncertainty and gate details are preserved in the machine-readable result. Calendar 2025 and 2026 were not opened. Case 031 was not decided and is excluded.

## Per-case results

| Case | Date | Action | Setup | Resolution | Result | PnL | R |
|---|---|---|---|---|---:|---:|---:|
| CBR-2022-001 | 2022-01-03 | SHORT | MACRO_NEUTRAL_AUCTION_TRADE | STOPPED | LOSS | $-56.41 | -1.128 |
| CBR-2022-002 | 2022-01-04 | NO_TRADE | NO_TRADE | NO_TRADE | NO_TRADE | +$0.00 | +0.000 |
| CBR-2022-003 | 2022-01-06 | LONG | COUNTER_MACRO_RANGE_ROTATION | POST_FILL_GEOMETRY_INVALID | LOSS | $-1.24 | -0.025 |
| CBR-2022-004 | 2022-01-10 | SHORT | MACRO_ALIGNED_CONTINUATION | POST_FILL_GEOMETRY_INVALID | WIN | +$0.98 | +0.020 |
| CBR-2022-005 | 2022-01-11 | LONG | COUNTER_MACRO_RANGE_ROTATION | STOPPED | LOSS | $-54.16 | -1.083 |
| CBR-2022-006 | 2022-01-12 | SHORT | MACRO_ALIGNED_CONTINUATION | STOPPED | LOSS | $-34.90 | -0.698 |
| CBR-2022-007 | 2022-01-13 | SHORT | MACRO_ALIGNED_CONTINUATION | TARGET_HIT | WIN | +$99.17 | +1.983 |
| CBR-2022-008 | 2022-01-14 | LONG | MACRO_NEUTRAL_AUCTION_TRADE | STOPPED | LOSS | $-51.30 | -1.026 |
| CBR-2022-009 | 2022-01-17 | SHORT | MACRO_ALIGNED_CONTINUATION | STOPPED | LOSS | $-19.07 | -0.381 |
| CBR-2022-010 | 2022-01-18 | SHORT | MACRO_ALIGNED_CONTINUATION | STOPPED | LOSS | $-26.88 | -0.538 |
| CBR-2022-011 | 2022-01-19 | SHORT | MACRO_ALIGNED_CONTINUATION | POST_FILL_GEOMETRY_INVALID | WIN | +$1.21 | +0.024 |
| CBR-2022-012 | 2022-01-20 | SHORT | MACRO_ALIGNED_CONTINUATION | STOPPED | LOSS | $-30.65 | -0.613 |
| CBR-2022-013 | 2022-01-21 | SHORT | MACRO_ALIGNED_CONTINUATION | STOPPED | LOSS | $-40.34 | -0.807 |
| CBR-2022-014 | 2022-01-24 | SHORT | MACRO_ALIGNED_CONTINUATION | STOPPED | LOSS | $-15.77 | -0.315 |
| CBR-2022-015 | 2022-01-25 | NO_TRADE | NO_TRADE | NO_TRADE | NO_TRADE | +$0.00 | +0.000 |
| CBR-2022-016 | 2022-01-27 | NO_TRADE | NO_TRADE | NO_TRADE | NO_TRADE | +$0.00 | +0.000 |
| CBR-2022-017 | 2022-01-28 | SHORT | MACRO_ALIGNED_CONTINUATION | TARGET_HIT | WIN | +$97.53 | +1.951 |
| CBR-2022-018 | 2022-01-31 | NO_TRADE | NO_TRADE | NO_TRADE | NO_TRADE | +$0.00 | +0.000 |
| CBR-2022-019 | 2022-02-01 | LONG | COUNTER_MACRO_RANGE_ROTATION | POST_FILL_GEOMETRY_INVALID | WIN | +$0.82 | +0.017 |
| CBR-2022-020 | 2022-02-02 | SHORT | MACRO_ALIGNED_CONTINUATION | STOPPED | LOSS | $-13.40 | -0.268 |
| CBR-2022-021 | 2022-02-03 | SHORT | MACRO_NEUTRAL_AUCTION_TRADE | POST_FILL_GEOMETRY_INVALID | SCRATCH | +$0.00 | +0.000 |
| CBR-2022-022 | 2022-02-04 | NO_TRADE | NO_TRADE | NO_TRADE | NO_TRADE | +$0.00 | +0.000 |
| CBR-2022-023 | 2022-02-07 | NO_TRADE | NO_TRADE | NO_TRADE | NO_TRADE | +$0.00 | +0.000 |
| CBR-2022-024 | 2022-02-08 | SHORT | MACRO_ALIGNED_CONTINUATION | STOPPED | LOSS | $-51.39 | -1.028 |
| CBR-2022-025 | 2022-02-09 | SHORT | MACRO_ALIGNED_CONTINUATION | POST_FILL_GEOMETRY_INVALID | LOSS | $-3.65 | -0.073 |
| CBR-2022-026 | 2022-02-10 | SHORT | MACRO_ALIGNED_CONTINUATION | TARGET_HIT | WIN | +$114.93 | +2.299 |
| CBR-2022-027 | 2022-02-11 | LONG | COUNTER_MACRO_RANGE_ROTATION | STOPPED | LOSS | $-52.70 | -1.054 |
| CBR-2022-028 | 2022-02-14 | NO_TRADE | NO_TRADE | NO_TRADE | NO_TRADE | +$0.00 | +0.000 |
| CBR-2022-029 | 2022-02-15 | SHORT | MACRO_ALIGNED_CONTINUATION | TARGET_HIT | WIN | +$91.12 | +1.822 |
| CBR-2022-030 | 2022-02-16 | SHORT | MACRO_ALIGNED_CONTINUATION | STOPPED | LOSS | $-43.78 | -0.876 |

## Evidence

Use [the execution index](GOLD_BLIND_CODEX_OPERATOR_REPLAY_V1_EXECUTION_INDEX.md) for each pre-decision chart, trade geometry, browser recording, trace, sealed outcome image, and outcome replay. Machine-readable results are in [JSON](research_artifacts/gold_blind_codex_operator_replay_v1/early_stop_case_results.json) and [CSV](research_artifacts/gold_blind_codex_operator_replay_v1/early_stop_case_results.csv).
