# April 2022 confirmation-only V2 application

**Verdict:** `COMPLETED_UNCHANGED_MONTHLY_APPLICATION`

This is exposed historical regression evidence. The January V2 policy was applied unchanged.

| Policy | Setups | Trades | No trade | Win rate | Net R | PF | Expectancy/trade | Max DD | $50/R | $100/R |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Original control | 97 | 97 | 0 | 39.2% | -20.52 | 0.652 | -0.212 | 21.10 | -1026.08 | -2052.17 |
| Confirmation-only V2 | 97 | 60 | 37 | 50.0% | -9.08 | 0.697 | -0.151 | 11.51 | -453.91 | -907.83 |

## Route counts

- `INITIAL_CONFIRMATION_STOP`: 24
- `INITIAL_CONFIRMATION_TARGET`: 24
- `INITIAL_CONFIRMATION_TIME_EXIT`: 1
- `NO_TRADE_H1_CLOSE_INVALIDATED`: 17
- `NO_TRADE_LATER_H1_INVALIDATED`: 5
- `NO_TRADE_TARGET_BEFORE_CONFIRMATION`: 13
- `NO_TRADE_TARGET_BEFORE_H1_REVIEW`: 2
- `RECLAIM_CONFIRMATION_STOP`: 6
- `RECLAIM_CONFIRMATION_TARGET`: 5

All values are gross before costs and overlap controls, matching the frozen predecessor semantics.
