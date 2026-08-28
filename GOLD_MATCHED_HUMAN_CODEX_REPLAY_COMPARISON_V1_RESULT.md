# Gold Matched Human-Codex Replay Comparison V1 — Result

## Verdict

**INCONCLUSIVE_ZERO_CREDIT_MATCHED_DIAGNOSTIC**

The comparison can tell us which operator handled these 30 exposed days better and where value was lost, but it cannot promote either result to a validated trading edge.

This is a zero-credit matched diagnostic over 30 already exposed days. It can diagnose method and execution differences; it cannot validate a durable edge.

## Performance

| Metric | Human | Codex |
|---|---:|---:|
| Trades / no-trades | 16 / 14 | 23 / 7 |
| Wins / losses / scratches | 3 / 13 / 0 | 7 / 15 / 1 |
| Win rate | 18.75% | 30.43% |
| Net R | -2.39 | -1.80 |
| Net PnL | $-119.49 | $-89.88 |
| Expectancy / trade | -0.149R | -0.078R |
| Profit factor | 0.657 | 0.819 |
| 95% bootstrap expectancy | [-0.56992836, 0.36888312] | [-0.47259278, 0.37996982] |
| Max drawdown | 6.60R | 4.59R |
| 1.5x-cost expectancy | -0.171R | -0.097R |

## Matched-decision agreement

- Same exact action: 8 / 30 (26.67%).
- Same trade/no-trade choice: 17 / 30 (56.67%).
- Both traded: 13; same direction in 4 / 13.
- Human-only trades: 3; Codex-only trades: 10; both no-trade: 4.

## Execution diagnosis

- Human losses with direction favourable by the frozen day close: 8.
- Human stops followed by the original target on a later completed M1 bar: 3.
- Human trades with at least +1 effective R available at some point: 12 / 16.
- Human targets that hit but captured at most half of the later full-day MFE: 1.
- Human post-fill geometry failures: 5.
- Codex stops followed by the original target later: 5.

These path labels are diagnostics, not hindsight permission to widen every stop or target. A stopped-then-target case may reflect premature entry, invalidation geometry, or a genuinely separate later setup.

## Rubric specificity

- Human mean observable six-step specificity: 3.12 / 6.
- Codex mean observable six-step specificity: 6 / 6.
- This measures whether the sealed text documents each step, not whether eloquent text predicts price.

## Action disagreements

| Case | Date | Human | Human R | Codex | Codex R |
|---|---|---:|---:|---:|---:|
| CBR-2022-001 | 2022-01-03 | NO_TRADE | 0.00 | SHORT | -1.13 |
| CBR-2022-002 | 2022-01-04 | LONG | -0.16 | NO_TRADE | 0 |
| CBR-2022-004 | 2022-01-10 | NO_TRADE | 0.00 | SHORT | 0.02 |
| CBR-2022-006 | 2022-01-12 | LONG | -0.05 | SHORT | -0.70 |
| CBR-2022-007 | 2022-01-13 | LONG | -0.73 | SHORT | 1.98 |
| CBR-2022-008 | 2022-01-14 | NO_TRADE | 0.00 | LONG | -1.03 |
| CBR-2022-009 | 2022-01-17 | LONG | -0.31 | SHORT | -0.38 |
| CBR-2022-010 | 2022-01-18 | NO_TRADE | 0.00 | SHORT | -0.54 |
| CBR-2022-011 | 2022-01-19 | NO_TRADE | 0.00 | SHORT | 0.02 |
| CBR-2022-012 | 2022-01-20 | NO_TRADE | 0.00 | SHORT | -0.61 |
| CBR-2022-013 | 2022-01-21 | LONG | -0.81 | SHORT | -0.81 |
| CBR-2022-014 | 2022-01-24 | LONG | -1.00 | SHORT | -0.32 |
| CBR-2022-015 | 2022-01-25 | LONG | -0.23 | NO_TRADE | 0 |
| CBR-2022-017 | 2022-01-28 | NO_TRADE | 0.00 | SHORT | 1.95 |
| CBR-2022-020 | 2022-02-02 | LONG | 0.38 | SHORT | -0.27 |
| CBR-2022-021 | 2022-02-03 | NO_TRADE | 0.00 | SHORT | 0 |
| CBR-2022-023 | 2022-02-07 | LONG | -0.08 | NO_TRADE | 0 |
| CBR-2022-024 | 2022-02-08 | LONG | -0.07 | SHORT | -1.03 |
| CBR-2022-025 | 2022-02-09 | NO_TRADE | 0.00 | SHORT | -0.07 |
| CBR-2022-026 | 2022-02-10 | LONG | -1.10 | SHORT | 2.30 |
| CBR-2022-029 | 2022-02-15 | NO_TRADE | 0.00 | SHORT | 1.82 |
| CBR-2022-030 | 2022-02-16 | LONG | 1.69 | SHORT | -0.88 |

## What the sample supports

- Codex Outperformed Human: human -2.39R versus Codex -1.80R.
- The human operator was more selective: 16 trades versus 23.
- Human and Codex chose the exact same action on 8 of 30 cases.
- Human stopped-then-later-target cases: 3; target-under-capture cases: 1.
- The human sample remains formally inconclusive because it has fewer than 30 trades, covers one quarter, and is zero-credit exposed calibration.

## What it does not support

- It does not prove a live edge: the dates and aggregate Codex result were already exposed.
- It does not support retuning from 16 human trades as though they were an independent sample.
- It does not inspect 2025 or 2026, which remain locked.

Detailed case rows and every rationale are preserved in `research_artifacts/gold_matched_human_replay_v1/comparison/matched_case_comparison.json`.
