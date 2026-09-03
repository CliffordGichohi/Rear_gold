# Gold January H1 confirmation-only reclaim milestone V2

**Verdict:** `REJECT_EXPOSED_CONFIRMATION_ONLY_INCREMENT`

## Exposed matched comparison

| System | Setups | Trades | Win rate | Net R | PF | Expectancy/trade | Max DD | $ at $50/R |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Original control | 88 | 88 | 43.2% | +11.47 | 1.229 | +0.130 | 14.00 | +573.44 |
| Probe V1 | 88 | 88 | 50.0% | +12.00 | 1.405 | +0.136 | 9.38 | +599.98 |
| Confirmation-only V2 | 88 | 65 | 61.5% | +12.18 | 1.487 | +0.187 | 9.78 | +608.83 |

Increment versus original: **+0.71R**.
Increment versus V1: **+0.18R**.
Original winners participating: **32/38 (84.2%)**.
Original winner R retained: **26.73/61.47R (43.5%)**.

## Route counts

| Route | Setups |
|---|---:|
| INITIAL_CONFIRMATION_STOP | 22 |
| INITIAL_CONFIRMATION_TARGET | 32 |
| NO_TRADE_H1_CLOSE_INVALIDATED | 11 |
| NO_TRADE_LATER_H1_INVALIDATED | 6 |
| NO_TRADE_TARGET_BEFORE_CONFIRMATION | 6 |
| RECLAIM_CONFIRMATION_STOP | 3 |
| RECLAIM_CONFIRMATION_TARGET | 7 |
| RECLAIM_CONFIRMATION_TIME_EXIT | 1 |

This is an exposed gross comparison. No costs, overlap constraints, alternative sizing or parameter variants were introduced.
