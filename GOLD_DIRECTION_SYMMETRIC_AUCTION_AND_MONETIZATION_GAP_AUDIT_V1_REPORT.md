# Gold Direction-Symmetric Auction and Monetization-Gap Audit V1 — Result

Verdict: `COMPLETE_EXPOSED_DIRECTION_SYMMETRY_AND_MONETIZATION_GAP_AUDIT`

This is an exposed-data diagnostic with zero validation credit.

## Direction-symmetric New York result

| Scope | Signals | Trades | Wins | Losses | Win % | Net R | R/month | PF | DD R |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| COMBINED | 80 | 33 | 14 | 14 | 42.42 | +2.1625 | +0.4325 | 1.192861790640475 | 4.0481 |
| LONG | 42 | 19 | 10 | 7 | 52.63 | +6.3059 | +1.2612 | 2.034851933451273 | 2.3382 |
| SHORT | 37 | 14 | 4 | 7 | 28.57 | -4.1434 | -0.8287 | 0.1906167689235656 | 4.6884 |

## Monetization-gap taxonomy

- Realized: +2.1625R.
- Post-entry MFE ceiling: +83.0397R.
- Aggregate MFE retained: 2.60%.
- CLEAN_INVALIDATION: 10 trades; realized -6.5260R.
- DIRECTION_FAILURE: 9 trades; realized -8.4566R.
- ENTRY_EARLY_OR_UNCONFIRMED: 14 trades; realized -4.4124R.
- MANAGEMENT_GIVEBACK: 26 trades; realized -1.4655R.
- NORMAL_VARIANCE: 5 trades; realized -2.7561R.
- STOP_THEN_TARGET: 3 trades; realized -2.8987R.
- TARGET_TRUNCATION: 2 trades; realized +3.8044R.

The original all-session LONG implementation reproduced exactly. No fresh period, 2025, or 2026 was opened.
