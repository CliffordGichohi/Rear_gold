# Gold Point-in-Time Auction-State and Adaptive Management V1 — Final Verdict

## Verdict

**REJECT — no economically proven development edge.**

The frozen 2021–2024 blocked out-of-fold study produced no candidate that passed every economic, uncertainty, calibration, stability, and cost gate. The required matched-subset GC order-flow study also found no proven incremental value. Calendar 2025 and 2026 therefore remain locked for this branch, and no prospective paper-trading ledger was initialized.

## Base development result

The strongest result was:

- Candidate: `H4::LINEAR_COMPETING_RISK_V1::CONSTANT_50`
- Trades: 130 across 125 dates
- Win rate: 40.77%
- Net expectancy: +0.1231 R per trade
- Profit factor: 1.2665
- Net PnL at $50 planned risk: +$800.29
- Average over the 39-month evaluation: +$20.52 per month
- Maximum drawdown: $396.16
- 1.5×-cost expectancy: +0.0850 R
- Positive validation folds: 5
- Positive calendar years: 3
- 95% clustered expectancy interval: −0.1177 R to +0.3934 R
- Holm-adjusted p-value: 0.6839
- Brier skill: −0.0470

It was rejected because the uncertainty interval included losses, multiplicity-adjusted evidence was not significant, and its probabilities calibrated worse than the training base-rate benchmark. Scaling its observed $20.52 monthly average to $1,000 would require about 48.7× the frozen risk, which is not permitted or credible.

M15 and H1 candidates were net negative. The H4 additive candidates were also net negative in the full development population.

## GC order-flow incremental result

The already-sealed GC MBO/MBP-10 data supplied six point-in-time fields: aggression, quote OFI, depth imbalance, microprice pressure, absorption, and liquidity fragility. They were evaluated only on exactly matched London/New York checkpoints and received no standalone candidate or validation credit.

- Independent primary/reference checkpoints were byte-identical.
- Matched usable rows: 115,406 M15; 25,798 H1; 11,752 H4.
- Passing incremental comparisons: 0 of 12.
- Formal verdict: `NO_PROVEN_INCREMENTAL_GC_VALUE`.

The two support-eligible H4 additive comparisons improved Brier calibration but worsened trading economics:

| Track | Base expectancy | +GC expectancy | Base PF | +GC PF | PnL change |
|---|---:|---:|---:|---:|---:|
| Constant $50 risk | +0.2616 R | +0.1751 R | 1.6881 | 1.4428 | −$142.42 |
| Adaptive risk | +0.0942 R | +0.0563 R | 1.4708 | 1.3375 | −$65.34 |

Neither paired date-level lower confidence bound was positive, and both Holm-adjusted p-values were 1.0. Other comparisons either failed the frozen support floor or also failed to improve economics.

## Integrity and scope

- All calculations used existing sealed 2021–2024 sources.
- Two complete independent evaluations reproduced exactly.
- The two GC feature payloads and two final complete evaluation checkpoints were byte-identical.
- Earlier engineering failures and the host interruption remain recorded; none was converted into a research pass.
- Calendar 2025 and 2026 values were not accessed.
- Paid acquisition: $0.

This result rejects this specific frozen auction-state/adaptive-management branch. It does not establish that gold is random or that no other gold edge exists.
