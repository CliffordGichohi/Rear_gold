# Gold Trend-Pullback Continuation Economic Edge Validation V1 — Final

Verdict: **REJECT — no frozen candidate demonstrated a tradable economic edge.**

The nine relationship candidates were preserved unchanged and tested with the precommitted entry, structural stop, known-liquidity target, time exit, costs, sizing, and overlap policy. None passed the development gates. Calendar 2025 and 2026 were therefore not opened for this branch; testing rejected rules there would violate the contract.

## Standalone development results (2021–2024)

| Candidate | Trades | Win rate | Net exp. | PF | Net PnL | 95% CI | Verdict |
|---|---:|---:|---:|---:|---:|---|---|
| M15|S1|RESPONSE_DISPLACEMENT_HALF_ATR | 2501 | 59.02% | -0.0852R | 0.742602516928 | $-9161.62 | [-0.1142, -0.0552] | REJECT_DEVELOPMENT_ECONOMICS |
| M15|S1|CONFIRMATION_DISPLACEMENT | 736 | 61.68% | -0.0791R | 0.719255305267 | $-2547.94 | [-0.1267, -0.0297] | REJECT_DEVELOPMENT_ECONOMICS |
| M15|S2|REFERENCE_SWEEP_RECLAIM__CONFIRMATION_DISPLACEMENT | 426 | 64.32% | -0.0824R | 0.648402187455 | $-1585.81 | [-0.1366, -0.0282] | REJECT_DEVELOPMENT_ECONOMICS |
| H1|S1|RESPONSE_DISPLACEMENT_HALF_ATR | 525 | 60.76% | -0.0866R | 0.747808908086 | $-2046.05 | [-0.1506, -0.0226] | REJECT_DEVELOPMENT_ECONOMICS |
| H1|S1|CONFIRMATION_DISPLACEMENT | 146 | 67.12% | -0.0669R | 0.760718557394 | $-464.99 | [-0.1762, 0.0353] | REJECT_DEVELOPMENT_ECONOMICS |
| H1|S1|REFERENCE_SWEEP_RECLAIM | 437 | 61.56% | -0.0527R | 0.845710993473 | $-991.14 | [-0.1317, 0.0333] | REJECT_DEVELOPMENT_ECONOMICS |
| H4|S1|RESPONSE_DISPLACEMENT_HALF_ATR | 119 | 63.87% | -0.0805R | 0.777696279793 | $-487.16 | [-0.2233, 0.0645] | REJECT_DEVELOPMENT_ECONOMICS |
| H4|S1|REFERENCE_SWEEP_RECLAIM | 97 | 70.10% | 0.0217R | 1.075331536717 | $6.00 | [-0.1314, 0.1793] | REJECT_DEVELOPMENT_ECONOMICS |
| H4|S1|HTF_FULL_ALIGNMENT | 152 | 57.24% | -0.0408R | 0.90511975871 | $-257.99 | [-0.2255, 0.1675] | REJECT_DEVELOPMENT_ECONOMICS |

## Non-overlapping portfolio

The fixed portfolio accepted **2,604 trades**. Win rate was **59.91%**, but average win was **0.441R** versus an average loss of **-0.829R**. Net expectancy was **-0.0656R per trade**, profit factor **0.801033100365**, net PnL **$-7472.50**, and baseline friction **$7681.94**.

This is the key economic distinction: frequent continuation was observable, but the frozen nearby-liquidity targets were too small relative to structural-stop losses and costs. A high hit rate alone was not an edge.

## Closest result and negative evidence

The closest candidate was `H4|S1|REFERENCE_SWEEP_RECLAIM` at **0.0217R** expectancy and **1.075331536717** profit factor across **97 trades**. It still failed: **CI95_LOWER_NOT_POSITIVE, HOLM_P_GT_0_05, PROFIT_FACTOR_LT_1_20, POSITIVE_BLOCKS_LT_3, COST_1P5X_PF_LT_1_05**.

Every candidate, no-trade reason, cost stress, annual/block/session/side diagnostic, bootstrap interval, multiplicity result, and failed gate is retained in the sealed JSON and Parquet artifacts.

## Forward and prospective disposition

Forward status: **NOT_OPENED_ZERO_DEVELOPMENT_CANDIDATES**. The 2025 and 2026 values remained unopened. The prospective paper ledger was initialized with zero eligible candidates and is dormant; it authorizes no live trading and forbids backfilling.

## Integrity

Primary and reference paths, trades, portfolio decisions, statistics, and byte-level artifacts matched. No paid data was acquired, and no execution rule or candidate was retuned after outcomes were opened.
