# March 2022 confirmation-only V2 application

**Verdict:** `COMPLETED_UNCHANGED_MONTHLY_APPLICATION`

This is exposed historical regression evidence. The January V2 policy was applied unchanged.

| Policy | Setups | Trades | No trade | Win rate | Net R | PF | Expectancy/trade | Max DD | $50/R | $100/R |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Original control | 110 | 110 | 0 | 42.7% | +1.27 | 1.021 | +0.012 | 13.55 | +63.73 | +127.46 |
| Confirmation-only V2 | 110 | 79 | 31 | 53.2% | +1.38 | 1.038 | +0.018 | 9.62 | +69.16 | +138.31 |

## Route counts

- `INITIAL_CONFIRMATION_STOP`: 32
- `INITIAL_CONFIRMATION_TARGET`: 40
- `INITIAL_CONFIRMATION_TIME_EXIT`: 1
- `NO_TRADE_H1_CLOSE_INVALIDATED`: 19
- `NO_TRADE_LATER_H1_INVALIDATED`: 4
- `NO_TRADE_TARGET_BEFORE_CONFIRMATION`: 7
- `NO_TRADE_TARGET_BEFORE_RECLAIM`: 1
- `RECLAIM_CONFIRMATION_STOP`: 4
- `RECLAIM_CONFIRMATION_TARGET`: 2

All values are gross before costs and overlap controls, matching the frozen predecessor semantics.
