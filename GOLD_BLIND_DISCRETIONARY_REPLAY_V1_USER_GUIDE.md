# Gold Blind Discretionary Replay V1 — User Guide

## What you are doing

For each case, act as though the checkpoint is live. Record the trade plan you would actually execute using only the replay window. Do not attempt to label the eventual direction, and do not consult an external chart, historical calendar, another person, or an AI for case-specific advice.

The audit is asking whether your own point-in-time interpretation produces an executable edge after costs. `NO_TRADE` is therefore as important as `LONG` or `SHORT`.

## Required workflow for every case

1. Read the fundamental panel. Decide whether the available macro evidence supports gold, pressures gold, or conflicts. Fundamentals provide direction, not an entry.
2. Read W1, D1, H4 and H1. Identify trend/range, current location, pre-existing support/resistance and reachable liquidity.
3. Read M15, M5 and M1. Decide whether price has accepted, rejected, swept, reclaimed, broken or retested an important level.
4. Choose:
   - `LONG`: bullish context, acceptable location and an executable bullish trigger.
   - `SHORT`: bearish context, acceptable location and an executable bearish trigger.
   - `NO_TRADE`: conflict, poor location, missing trigger, unacceptable event/liquidity risk, or no defensible target.
5. Complete every reasoning field in plain language.
6. Review the normalized execution preview.
7. Lock the decision once. It cannot be edited or deleted.

Use the same workflow and personal standard across all scored cases. Do not change the method because several practice paths happen to win or lose.

## Entry mapping

Index `100.0000` is the last completed M1 close at the decision checkpoint. The displayed M15 ATR converts an offset into normalized index points.

| Direction | Trigger | Legal ATR offset | Meaning |
|---|---|---:|---|
| Long | Market | `0` | First eligible M1 open after one-minute latency |
| Short | Market | `0` | First eligible M1 open after one-minute latency |
| Long | Pullback limit | `-2.00` to `0.00` | Buy below the checkpoint reference |
| Short | Pullback limit | `0.00` to `+2.00` | Sell above the checkpoint reference |
| Long | Breakout stop | `0.00` to `+2.00` | Buy above the checkpoint reference |
| Short | Breakout stop | `-2.00` to `0.00` | Sell below the checkpoint reference |

The requested normalized entry is:

`100 + (entry offset × displayed M15 ATR index)`

Use `MARKET` only when you would enter after the fixed one-minute latency without demanding a further price level. Use `PULLBACK_LIMIT` when you require a better price at a pre-existing location. Use `BREAKOUT_STOP` when entry requires continuation through a level.

## Stop, target and risk

- Structural stop: `0.25`–`3.00` M15 ATR from the actual fill. Choose the distance that corresponds to a visible structural invalidation, not the amount you hope to lose.
- Target: `0.50`–`5.00R`. Tie it to pre-existing liquidity or structure that was visible at the checkpoint.
- Planned account risk: no more than `$50` on the frozen `$10,000` account.
- Pending orders expire after 120 minutes or at session end.
- Positions close at stop, target, 240 minutes after fill, or session end.
- If stop and target occur within the same one-minute bar, the evaluator records the stop first.
- Frozen observed spread, `$0.05` slippage per side and `$7` per standard-lot round-trip commission are deducted later.

The preview is arithmetic only. It does not reveal whether the order fills or what price does afterward.

## Confidence and text fields

- Confidence for a trade: your probability that the completed trade ends above `0R` after costs. It is not confidence that the macro narrative sounds convincing.
- Confidence for `NO_TRADE`: confidence that abstention is appropriate; it is reported separately from trade calibration.
- Thesis: why the available direction and context justify the action.
- Trigger condition: the observable completed-candle or level event required for entry.
- Invalidation: what structure or level proves the thesis wrong.
- Target rationale: which known liquidity or structural objective supports the target.

For `NO_TRADE`, explain the conflict or missing evidence, the confirmation that would have been required, what would turn the case into a valid setup, and why no defensible target currently exists.

## Practice and scored phases

- Practice `P-001` through `P-020`: zero research credit. After locking, the normalized subsequent path is revealed so you can learn the interface. Do not redesign the audit from practice results.
- Scored `S-001` through `S-240`: no direction, outcome or PnL feedback appears between cases. Complete all decisions honestly and in frozen order.

Only after all 240 scored decisions are locked may the separate evaluator calculate fills, accuracy, calibration, expectancy, profit factor, drawdown and chronological stability under the frozen contract.

