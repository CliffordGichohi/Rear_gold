# Gold Coherent-Auction Consecutive Calendar-Month Test V1

Status: `FROZEN_BEFORE_MARCH_MAY_2022_OUTCOME_OPEN`

## Question

Apply the exact autonomous translator that reproduced `+10.69354658R` on the
exposed January--February calibration block to three consecutive, complete
calendar months without selecting isolated sessions or dates.

## Frozen period and population

- Calendar months: March, April and May 2022.
- One daily case for every market-open weekday from `2022-03-01` through
  `2022-05-31`.
- `2022-04-15` is excluded only because CME/spot gold was closed for Good
  Friday. It is reported as a documented market closure, not a no-trade.
- The frozen population contains 65 dates: 23 in March, 20 in April and 22 in
  May.
- Memorial Day (`2022-05-30`) remains included; its observed early close is
  the valid end of that day's price path.
- Each daily case scans every completed minute in both the London 08:00--12:00
  local window and New York 08:00--12:00 local window, DST-aware, in
  chronological order.
- The algorithm may issue at most one decision per day. It takes its first
  qualifying signal exactly as frozen. No date, session, trade or loss may be
  removed.

## Frozen algorithm and execution

- Translator artifact SHA-256:
  `c95e200194bece77ed435741202d1bacd4f267ab0f1d1ed7803dd9d4ebd30841`.
- Exposed control artifact SHA-256:
  `c2ff398eaf3cb865191e85bace5542a79a9d23063fe51d164c4b31bc7979637d`.
- Direction remains `LONG`, because the frozen translator was fitted from a
  human calibration population containing no SHORT example.
- Semantic tree, threshold, preprocessing, stop tree, target tree, thesis
  family tree, contextual admission gates and `COMPLETE_V2_POLICY` management
  remain byte-for-byte unchanged.
- Fill, spread, slippage, structural risk, whole-ounce sizing, maximum `$50`
  planned risk, target handling, protection, runner, stop-first ambiguity and
  daily time exit remain unchanged.
- No fitting, threshold change, geometry change, fallback, discretionary
  override or outcome-derived correction is permitted.

## Source and integrity policy

- Reuse only the sealed XAUUSD casebook and point-in-time context sources.
- Build primary and reference streams independently and require exact result
  equality.
- Require adequate observed quote coverage in both frozen session windows and
  preserve all source gaps and early closures.
- Acquire no data and incur no charge.
- Calendar 2025 and 2026 remain unopened.

## Reporting

Report March, April and May separately and combined: eligible dates, signals,
admissions, rejections, wins, losses, scratches, win rate, net R, dollars at
`$50/R`, expectancy, profit factor, maximum drawdown and 1.5-times-cost net R.
Also report the signal-session split and every daily disposition.

This is a historical robustness test of an exposed fitted translator. It does
not create independent validation credit. Any improvement research begins only
after this unchanged three-month result has been sealed.
