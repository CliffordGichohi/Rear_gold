# Gold Matched Human Coherent Auction Management — Amendment A

## Preserved result

The frozen V1 full structural runner remains unchanged. Its exposed calibration result is negative because M5 rejection at nearby internal levels exits several trades that later continue. That finding is preserved and receives zero validation credit.

## Reason for one bounded challenger

The operator's transition, invalidation and first meaningful structural objective are primarily M15 concepts. Managing the entire position from a single M5 rejection response introduces a timeframe mismatch. Amendment A permits exactly one post-result, zero-credit management challenger aligned to M15. It does not modify entry identity, actual fill, initial protected-low stop, position size, cost, deadline, case population or any prior track.

## `M15_PROTECTED_AUCTION_RUNNER_V0_1`

- Every frozen M15/H1 liquidity level is recorded when touched but is informational; no touch alone exits the trade.
- The original H1 target is not a mandatory take-profit. This challenger is intentionally an uncapped structural runner.
- Retain the initial buffered M15 protected-low stop until completed M15 evidence permits a change.
- After entry, each new bullish M15 structural break defined by the frozen V1 primitives raises the stop to that event's buffered protected M15 low if and only if it is higher than the current stop.
- The stop never moves downward.
- A new completed bearish M15 structural break is the opposite auction transition and exits the full position at the next M1 open, unless the protective stop resolves first.
- A bearish M15 structural break occurs when a completed M15 candle closes below the latest confirmed M15 swing low available before that candle opened by more than `max(0.10 * M15 ATR, $0.02)`.
- No breakeven move, partial exit, fixed-R target, M5 response exit, future-formed level, MFE threshold or outcome label is permitted.
- If neither the protective stop nor an opposite structural break resolves the trade, exit at the unchanged UTC-day deadline.

Report level touches, stop changes, opposite-break exits, net R, dollars, profit factor, drawdown and capture of the unchanged stop-feasible MFE oracle. Compare the challenger with the preserved original-H1 control and V1 M5-response runner. Do not tune or add a second challenger after viewing the result.

This amendment remains hypothesis-generation only. Any promising policy must be frozen and evaluated on fresh outcome-hidden or prospective cases before it can be called an edge.

