# Gold Pullback Constant-Execution Baseline V1

Status: **COMPLETE_DEVELOPMENT_BASELINE — NOT AN EDGE**

This applies the already sealed constant execution to every eligible 2021-2024 STANDARD pullback before behavioural grouping. Calendar 2025 and 2026 were not accessed.

## Constant execution

- Next available M1 open, maximum five-minute delay.
- Stop beyond the confirmed pullback pivot by 0.15 ATR14.
- Target at the nearest known, unbroken trend-side STANDARD swing.
- Exit after 16 parent bars if neither stop nor target is reached; stop first on an ambiguous M1 bar.
- Observed spread (or $0.30/oz fallback), plus $0.07/oz commission and $0.10/oz slippage.
- $50 planned risk on a $10,000 account, whole-ounce sizing, no compounding and one open XAUUSD position.

## Standalone timeframe baselines

| TF | Signals | Accepted trades | Win rate | Exp. R | PF | Net PnL | Avg/month | Ending balance | Max DD |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| M15 | 6633 | 5238 | 50.1909% | -0.0909 | 0.8186 | $-20374.9780 | $-496.9507 | $-10374.9780 | 204.7543% |
| H1 | 1576 | 1203 | 47.2153% | -0.1286 | 0.7569 | $-6858.8973 | $-167.2902 | $3141.1027 | 72.9503% |
| H4 | 444 | 326 | 50.6135% | -0.0063 | 0.9875 | $-37.0511 | $-0.9037 | $9962.9489 | 10.0131% |

## Combined non-overlapping account

Signals: **8653**; accepted trades: **4687**; skipped overlaps: **3708**.

| Win rate | Expectancy | Profit factor | Gross PnL | Costs | Net PnL | Avg monthly | Total return | Ending balance | Max DD |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 50.2880% | -0.0937R | 0.8112 | $2015.0419 | $20674.9000 | $-18659.8581 | $-455.1185 | -186.5986% | $-8659.8581 | 192.1134% |

## Hindsight outcome attribution

These rows explain the baseline; the structural outcome is not known at entry and cannot be used as a live filter.

| Outcome | Trades | Win rate | Exp. R | PF | Net PnL |
|---|---:|---:|---:|---:|---:|
| CONTINUED | 2369 | 80.0760% | 0.5172R | 4.7142 | $52514.5207 |
| FAILED_STRUCTURE_SWITCH | 2318 | 19.8447% | -0.7179R | 0.1658 | $-71174.3788 |

## Interpretation

This is the honest no-grouping control. It establishes the account result when every objective pullback is treated alike. Behavioural grouping must improve this result out of sample; otherwise it has not identified an economic edge.
