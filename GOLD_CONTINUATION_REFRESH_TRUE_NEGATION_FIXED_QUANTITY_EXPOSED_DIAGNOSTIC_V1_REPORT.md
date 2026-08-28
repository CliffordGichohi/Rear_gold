# Gold Continuation-Refresh True Negation Fixed-Quantity Exposed Diagnostic V1 Report

Verdict: `COMPLETE_TRUE_NEGATION_FIXED_QUANTITY_EXPOSED_DIAGNOSTIC_ZERO_VALIDATION_CREDIT`

This is the requested strategy negation. Each of the 434 continuation trades retained its original sealed whole-ounce quantity; direction reversed, TP became SL, and SL became TP. No trade was re-sized against the new stop. The other 214 trades were unchanged.

| Track | Trades | Win rate | Net R | PnL USD | PF | Max DD R |
|---|---:|---:|---:|---:|---:|---:|
| Original continuation | 434 | 46.31% | -71.7264 | $-3586.32 | 0.57 | 73.9214 |
| Prior re-risked sizing diagnostic, not the answer | 434 | 52.07% | +467.0165 | $+23350.82 | 2.76 | 46.0067 |
| True-negated continuation, fixed original quantity | 434 | 52.07% | +53.1780 | $+2658.90 | 1.52 | 14.1865 |
| Unchanged non-continuation | 214 | 48.60% | -7.4052 | $-370.26 | 0.91 | 20.5216 |
| Complete replacement portfolio | 648 | 50.93% | +45.7728 | $+2288.64 | 1.24 | 21.7582 |

## Fixed-quantity proof

- All **434/434** continuation quantities matched the original sealed executions exactly.
- Quantity range: **1 to 86 ounces**; prior false headline used up to 5,000 ounces.
- Maximum actual inverted displayed stop exposure: **$998.76**. This was reported, not normalized or capped.
- Largest true-negated trade: **+1.4727R**, 86 ounces.
- Top five: **+6.1346R**; result excluding them: **+47.0434R**.

## Replacement portfolio by month

| Month | Trades | Win rate | Net R | PnL USD | PF |
|---|---:|---:|---:|---:|---:|
| 2022-01 | 111 | 45.05% | +10.9892 | $+549.46 | 1.35 |
| 2022-02 | 72 | 56.94% | +8.7961 | $+439.80 | 1.41 |
| 2022-03 | 122 | 50.82% | +16.6653 | $+833.26 | 1.53 |
| 2022-04 | 111 | 56.76% | +6.9510 | $+347.55 | 1.23 |
| 2022-05 | 105 | 55.24% | +7.9935 | $+399.67 | 1.28 |
| 2022-06 | 127 | 44.09% | -5.6222 | $-281.11 | 0.88 |

## Integrity

- Independent primary and reference plans, fixed quantities, executions, summaries, and checksums matched exactly.
- The unchanged 214 executions matched the original sealed results exactly.
- No cap, scale, re-sizing, filter, alternate inversion, new date, 2025, or 2026 was used.
- This remains a post-hoc exposed diagnostic with zero validation credit.
