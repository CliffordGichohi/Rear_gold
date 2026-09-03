# May 2022 confirmation-only V2 application

**Verdict:** `COMPLETED_UNCHANGED_MONTHLY_APPLICATION`

This is exposed historical regression evidence. The January V2 policy was applied unchanged.

| Policy | Setups | Trades | No trade | Win rate | Net R | PF | Expectancy/trade | Max DD | $50/R | $100/R |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Original control | 90 | 90 | 0 | 43.3% | -0.30 | 0.994 | -0.003 | 7.65 | -14.97 | -29.93 |
| Confirmation-only V2 | 90 | 61 | 29 | 57.4% | +7.39 | 1.284 | +0.121 | 6.63 | +369.33 | +738.67 |

## Route counts

- `INITIAL_CONFIRMATION_STOP`: 22
- `INITIAL_CONFIRMATION_TARGET`: 31
- `NO_TRADE_H1_CLOSE_INVALIDATED`: 16
- `NO_TRADE_LATER_H1_INVALIDATED`: 5
- `NO_TRADE_TARGET_BEFORE_CONFIRMATION`: 8
- `RECLAIM_CONFIRMATION_STOP`: 4
- `RECLAIM_CONFIRMATION_TARGET`: 4

All values are gross before costs and overlap controls, matching the frozen predecessor semantics.
