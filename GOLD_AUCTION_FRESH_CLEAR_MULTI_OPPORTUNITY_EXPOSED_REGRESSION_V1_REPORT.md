# Gold Fresh-and-Clear Multi-Opportunity Exposed Regression V1 Report

Verdict: `COMPLETE_EXPOSED_ALL_VALID_SIGNAL_REGRESSION_ZERO_VALIDATION_CREDIT`

## What was implemented

The existing ten-trade scanner and its frozen `A3_FRESH_AND_CLEAR::E0::R0` selector were applied to every one of the 729 already exposed New York M15/M5 auction transitions. Every admitted setup was executed independently even when an earlier position was still open. No signal was suppressed, deferred, merged, netted, or resized because of overlap.

- Events scanned: **729** across **117** exposed days.
- Qualifying setups executed: **35** (5.83 per calendar month; maximum 2 in one day).
- Direction mix: **19 LONG / 16 SHORT**.
- Overlapping setups retained: **0**.
- Maximum concurrency: **1 positions / $49.95 planned risk**.

## Exposed economics

All-valid-signal primary: **+5.6391R / $+281.96**, 40.00% win rate, +0.1611R expectancy, PF 1.27, max drawdown 7.9182R.

Matched non-overlap diagnostic from the same signals: **+5.6391R / $+281.96**, 35 trades, PF 1.27. This diagnostic did not suppress any primary trade.

## Monthly results

| Month | Trades | Win rate | Net R | PnL USD | PF | Max DD R |
|---|---:|---:|---:|---:|---:|---:|
| 2022-01 | 6 | 66.67% | +6.2924 | $+314.62 | 4.46 | 0.9311 |
| 2022-02 | 4 | 25.00% | -0.9176 | $-45.88 | 0.69 | 2.1055 |
| 2022-03 | 8 | 50.00% | +6.8630 | $+343.15 | 3.37 | 1.3288 |
| 2022-04 | 2 | 0.00% | -1.9612 | $-98.06 | 0.00 | 1.9612 |
| 2022-05 | 7 | 57.14% | +3.2807 | $+164.03 | 2.16 | 1.0138 |
| 2022-06 | 8 | 12.50% | -7.9182 | $-395.91 | 0.07 | 7.9182 |

## Direction results

| Direction | Trades | Win rate | Net R | PnL USD | PF | Max DD R |
|---|---:|---:|---:|---:|---:|---:|
| LONG | 19 | 31.58% | -2.9357 | $-146.79 | 0.78 | 8.5844 |
| SHORT | 16 | 50.00% | +8.5748 | $+428.74 | 2.13 | 3.2352 |

## Integrity

- The same-ten decisions and the four admitted same-ten outcomes reproduced the frozen selector result exactly.
- Primary and reference compilations, executions, overlap diagnostics, summaries, and checksums matched exactly.
- The 2022-02-17 through 2022-02-28 gap remained unopened. No 2025 or 2026 data was accessed.
- This is an exposed implementation regression with zero validation credit; it measures what this exact scanner would have produced on already opened data.
- No data was acquired and no charge was incurred.
