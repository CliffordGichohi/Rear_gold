# Gold Continuation-Refresh Direct Inversion V1-R1 Report

Verdict: `COMPLETE_DIRECT_INVERSION_WITH_BOUNDED_RISK_EXCEPTION_ZERO_VALIDATION_CREDIT`

All 434 continuation-refresh trades were inverted exactly. Three required one ounce with displayed planned risk between $50.91 and $53.01; every other setup retained the original $50 whole-ounce sizing rule.

| Track | Trades | Win rate | Net R | PnL USD | PF | Max DD R |
|---|---:|---:|---:|---:|---:|---:|
| Original continuation | 434 | 46.31% | -71.7264 | $-3586.32 | 0.57 | 73.9214 |
| Inverted continuation | 434 | 52.07% | +467.0165 | $+23350.82 | 2.76 | 46.0067 |
| Unchanged non-continuation | 214 | 48.60% | -7.4052 | $-370.26 | 0.91 | 20.5216 |
| Complete replacement portfolio | 648 | 50.93% | +459.6113 | $+22980.56 | 2.30 | 47.0335 |

Frequency: **108.00 trades/month**. Overlapping signals retained: **364**. Maximum concurrency: **10 positions / $453.21 planned risk**.

## Replacement portfolio by month

| Month | Trades | Win rate | Net R | PF |
|---|---:|---:|---:|---:|
| 2022-01 | 111 | 45.05% | +41.4671 | 1.71 |
| 2022-02 | 72 | 56.94% | -2.5523 | 0.91 |
| 2022-03 | 122 | 50.82% | -18.5248 | 0.72 |
| 2022-04 | 111 | 56.76% | +112.1133 | 3.93 |
| 2022-05 | 105 | 55.24% | -33.5838 | 0.59 |
| 2022-06 | 127 | 44.09% | +360.6918 | 5.58 |

## Integrity

- Primary and reference results and checksums matched exactly.
- Only the exact three authorized one-ounce exceptions exceeded $50; none exceeded $53.01.
- No alternative inversion, filter, management rule, or fresh period was tested.
- This is post-hoc exposed evidence with zero validation credit.
