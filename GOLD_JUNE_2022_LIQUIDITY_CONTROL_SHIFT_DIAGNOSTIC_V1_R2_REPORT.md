# Gold June 2022 Liquidity-Control Shift Diagnostic V1-R2

Verdict: `COMPLETE_EXPOSED_POST_RESULT_DIAGNOSTIC_ZERO_VALIDATION_CREDIT`

The frozen LONG control remains unchanged. This diagnostic separates H4 swing backdrop from completed-candle M5/M15 control transfer.

## Frozen descriptive semantics

- Causal 2-left/2-right pivots with 0.25 ATR prominence.
- M5 control break: close through a known pivot by 0.05 ATR, range >= 0.80 ATR and body/range >= 0.55.
- M15 control break: the same rule with range >= 0.90 ATR.
- Accepted session shift: M5 and M15 agree for 2 completed M5 closes.
- All events are INFERRED price-auction states, not observed institutional orders.

## Existing LONG trades

| Date | Net R | H4 | M5 at signal | M15 at signal | Confluent | First seller M5 | First seller M15 | Before exit? | Attribution |
|---|---:|---|---|---|---|---|---|---|---|
| 2022-06-06 | -0.9162 | BULLISH_SWING_SEQUENCE | LONG | LONG | LONG | 2022-06-06T15:40:00Z | 2022-06-06T16:45:00Z | True | SELLER_CONTROL_TRANSFER_BEFORE_LONG_EXIT |
| 2022-06-07 | +0.2898 | MIXED_OR_TRANSITIONAL_SEQUENCE | LONG | LONG | LONG | 2022-06-07T13:05:00Z | 2022-06-07T15:30:00Z | True | SELLER_CONTROL_TRANSFER_BEFORE_LONG_EXIT |
| 2022-06-08 | +0.2555 | BEARISH_SWING_SEQUENCE | LONG | LONG | LONG | 2022-06-08T13:45:00Z | 2022-06-08T15:30:00Z | True | SELLER_CONTROL_TRANSFER_BEFORE_LONG_EXIT |
| 2022-06-13 | -0.9422 | MIXED_OR_TRANSITIONAL_SEQUENCE | SHORT | SHORT | SHORT | 2022-06-13T14:50:00Z | 2022-06-13T15:45:00Z | True | SELLER_CONTROL_VISIBLE_BEFORE_LONG |
| 2022-06-21 | -0.3206 | BULLISH_SWING_SEQUENCE | SHORT | SHORT | SHORT | 2022-06-21T16:45:00Z | 2022-06-21T23:15:00Z | True | SELLER_CONTROL_VISIBLE_BEFORE_LONG |
| 2022-06-23 | -0.9791 | MIXED_OR_TRANSITIONAL_SEQUENCE | SHORT | SHORT | SHORT | 2022-06-23T18:05:00Z | 2022-06-23T14:15:00Z | False | SELLER_CONTROL_VISIBLE_BEFORE_LONG |
| 2022-06-24 | -0.9824 | BEARISH_SWING_SEQUENCE | SHORT | LONG | CONFLICTED_OR_UNRESOLVED | 2022-06-24T13:20:00Z | 2022-06-24T14:00:00Z | True | SELLER_CONTROL_TRANSFER_BEFORE_LONG_EXIT |
| 2022-06-27 | -0.9181 | BEARISH_SWING_SEQUENCE | LONG | SHORT | CONFLICTED_OR_UNRESOLVED | 2022-06-27T11:20:00Z | 2022-06-27T15:30:00Z | True | SELLER_CONTROL_TRANSFER_BEFORE_LONG_EXIT |
| 2022-06-29 | -0.5274 | MIXED_OR_TRANSITIONAL_SEQUENCE | LONG | LONG | LONG | 2022-06-29T16:15:00Z | 2022-06-29T16:45:00Z | True | SELLER_CONTROL_TRANSFER_BEFORE_LONG_EXIT |

## Summary

- Pre-entry confluent control: `{'CONFLICTED_OR_UNRESOLVED': 2, 'LONG': 4, 'SHORT': 3}`.
- Attribution: `{'SELLER_CONTROL_TRANSFER_BEFORE_LONG_EXIT': 6, 'SELLER_CONTROL_VISIBLE_BEFORE_LONG': 3}`.
- Seller transfer before the frozen LONG exit: 8/9.
- Seller transfers subsequently reaching +1 original LONG-risk unit before -1: 4.

## Session shift atlas

| Direction | Accepted shifts | +1 ATR first | -1 ATR/ambiguous first | Neither | Median favourable ATR | Median adverse ATR | Macro aligned | Macro opposed | Macro neutral/conflicted |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| LONG | 26 | 13 | 12 | 1 | 2.078824629093797 | 1.6306835799859054 | 3 | 7 | 16 |
| SHORT | 23 | 11 | 12 | 0 | 2.057314228590524 | 1.8308952603861863 | 3 | 2 | 18 |

## Scope

No policy was changed, no SHORT strategy was simulated, no new period was opened, and no edge is claimed.
