# Gold Day-by-Day Auction-Confirmation Exposed Regression V1

Status: `APPROVED_EXPOSED_REGRESSION_PROTOCOL`

## 1. Question and credit

Determine how one fixed, point-in-time correction changes the already exposed
day-by-day coherent-auction result. This is an exposed regression and receives
zero validation credit. It cannot authorize real-money trading.

The unchanged autonomous translator remains the control. No translator tree,
probability threshold, auction family, contextual veto, stop, target, cost,
latency, risk, or overlap rule may be fitted or retuned.

## 2. Exact population

Use every existing daily stream, in chronological order, from:

- 2022-01-03 through 2022-02-16: 30 already exposed daily cases;
- 2022-03-01 through 2022-05-31: 65 already exposed daily cases.

The population is exactly 95 dates. The 2022-02-17 through 2022-02-28 gap
remains unopened. The random `GAV-2022-001` through `GAV-2022-050` block is
prohibited. No other date or source may be opened.

Each day is processed chronologically. London is scanned before New York in
actual UTC order. The existing translator's first semantic signal remains the
only setup identity for that date. A rejected or unconfirmed setup does not
permit a later replacement signal. Every no-signal and no-trade day remains in
the ledger.

## 3. Morning plan

At the London 08:00 local checkpoint, record only point-in-time information:

- macro state, score, confidence, and available component evidence;
- H4 swing sequence, completed-bar range location, and fifteen-bar change;
- active M15 directional structure and event-lock state;
- nearest already-confirmed H1 swing low below price and H1 swing high above
  price, when available.

These fields describe the morning plan and never select or veto a setup beyond
the unchanged contextual policy. Missing information remains `UNKNOWN`.

## 4. Frozen corrected policy

The corrected policy is long-only because the sealed translator is long-only.
The mirror-image short definitions are implemented and synthetically tested but
receive no market-data evaluation in this regression.

### 4.1 Original setup geometry

The frozen translator emits the original semantic signal, family, structural
stop, and liquidity target. Stop and target prices remain unchanged. The
corrected entry is delayed until confirmation and uses the next M1 open under
the existing one-minute latency, spread, and $0.05 adverse slippage rules.

The setup expires at the end of the signal's London or New York session. It is
rejected if its original structural stop or target is touched before entry.
Pre-entry same-minute ambiguity is stop/invalidation first.

### 4.2 Two-stage completed-M5 confirmation

Starting with the first completed M5 bar whose `available_at` is strictly after
the original signal, inspect adjacent completed M5 pairs inside the same
session. Select the first pair satisfying every condition below. No lookahead,
skipping, alternative pair after selection, or outcome-based choice is allowed.

For a long:

1. Failed-auction/reclaim bar A closes above its open, has a genuine lower wick
   (`low < min(open, close)`), and closes at or above its full-range midpoint.
2. The immediately following bar B actually pulls back (`low < A.close`) but
   remains above A's low.
3. Bar B closes above its own open and above A's close, demonstrating aligned
   price progression.

For a short, reverse every inequality: bar A closes below its open, has a
genuine upper wick, closes at or below its midpoint; bar B pulls above A's close
without reaching A's high; and closes below both its open and A's close.

If no adjacent pair qualifies before session expiry, disposition is
`NO_TWO_STAGE_M5_CONFIRMATION`.

### 4.3 Target room

At the delayed fill, geometry must remain ordered and gross structural target
room must be at least 1.50R:

`direction_sign * (target - fill) / abs(fill - stop) >= 1.50`.

Otherwise the disposition is `TARGET_ROOM_LT_1P5R` or
`DELAYED_GEOMETRY_INVALID` as applicable. Position size is recomputed with the
unchanged whole-ounce `$50 / planned_loss_per_ounce` rule.

### 4.4 Execution and protection

After admission, retain the unchanged complete V2 target, structural stop,
runner, costs, session deadline, and stop-first ambiguity policy. Overlay only
this protection rule:

- arm after the first completed M5 close at or beyond +1.00 structural R;
- from that timestamp onward, exit at the first M1 touch of the net break-even
  stop (`fill + direction_sign * cost_per_ounce`), unless the unchanged target
  resolves first;
- classify a changed exit as `M5_1R_NET_BREAK_EVEN`.

The overlay is evaluated on every admitted corrected trade. It may save a loss,
leave a scratch unchanged, or clip a winner; every disposition is reported.

## 5. Required comparison

Produce one row for every date containing the morning plan, unchanged control,
corrected signal lifecycle, entry, stop, target, disposition, net R, and running
equity. Report January, February-to-date, March, April, May, and combined:

- dates, signals, admitted trades, and no-trade days;
- wins, losses, scratches, win rate, expectancy, profit factor, net R and USD;
- maximum drawdown and longest winning and losing streaks;
- winner count and positive-R retention;
- avoided losses, saved losses, and valid control winners rejected;
- change attributable to target room, confirmation, and break-even.

The attribution order is fixed as target room, then confirmation/delayed entry,
then break-even. It is descriptive and order-dependent.

## 6. Integrity and stopping rules

- Freeze this protocol and exact source hashes before corrected row-level replay.
- Prove the confirmation, expiry, invalidation, target-room, latency, and
  break-even lifecycle on synthetic cases before market replay.
- Run primary and reference implementations independently and require exact row
  identities, classifications, results, metrics, and canonical checksums.
- Do not retune, repair, invert, add rules, inspect another date, acquire data,
  initialize paper trading, or calculate a later variant after seeing results.
- A semantic or reproduction failure is a formal `FAIL`; otherwise report the
  achieved exposed economic result honestly and stop.

