# Gold Auction-Semantic Family Router Exposed Regression V2

Status: `APPROVED_EXPOSED_ENGINEERING_AND_REGRESSION`

## 1. Purpose, evidence boundary, and rollback

Correct the semantic defects identified in Auction Family Router V1 without
searching for a new directional signal. This remains an exposed engineering
regression and receives zero validation credit.

The following are immutable rollback points and must remain byte-for-byte
unchanged:

- Gold Day-by-Day Auction-Confirmation Exposed Regression V1;
- Gold Auction Family Router Exposed Regression V1;
- Gold Auction-Plan Compiler Semantic Amendment A and its certification.

Implement V2 only in new files and a new append-only artifact directory.

## 2. Exact population and prohibited access

Use the identical 95 already-opened daily cases:

- 2022-01-03 through 2022-02-16: 30 cases;
- 2022-03-01 through 2022-05-31: 65 cases.

Keep 2022-02-17 through 2022-02-28 closed. Exclude the random 50-case
population. Do not inspect another date, 2025, or 2026. Use only the frozen
translator's original first signal and LONG direction. Preserve the one-signal
and maximum-one-trade-per-day policy.

An original signal-time classification that was rejected may never be
re-admitted by V2.

## 3. Explicit point-in-time plan

At the original signal timestamp, compile Semantic Amendment A using the last
completed M1 reference close, never the later executable fill. Require an
`EXECUTABLE_PLAN` containing all six identities:

1. macro context;
2. governing auction;
3. controlling structure;
4. local trigger hierarchy;
5. structural invalidation;
6. liquidity destination.

An unresolved component produces `NO_TRADE_UNRESOLVED`. Use the compiler's
governing-auction family instead of the learned family tree. The stop is the
compiler's explicit structural-invalidation price. The target is its explicit
next active balance, H1, or H4 liquidity-destination level. Learned stop and
target distance trees are prohibited.

Reapply the unchanged signal-time contextual vetoes to the compiled family and
explicit geometry. Macro remains context/warning; do not add a universal macro
alignment veto.

## 4. Frozen entry routes

### 4.1 Continuation

Select the most refined point-in-time local trigger: the M5 refinement when it
exists, otherwise the M15 setup transition.

The trigger is `FRESH` only when its break became available no more than one
native trigger bar before the signal: five minutes for M5 or fifteen minutes
for M15. A fresh continuation uses the original next-M1 executable fill.

An inherited continuation is not rejected. It is routed through the first M5
retest within twelve completed M5 bars that reaches the trigger's broken level
within the existing 0.25 M5-ATR tolerance, closes back beyond it in the trade
direction, closes directionally relative to its own open, and occurs while the
trigger's protected level remains intact under the existing 0.10 transition-
ATR close buffer.

### 4.2 Structural repair

Always require the same first valid M5 retest of the most refined compiled
trigger within twelve completed M5 bars. Expire or reject on the unchanged
retest and protected-level rules.

### 4.3 Range rotation

Use the named directional boundary of the compiled active balance. Inspect at
most six completed M5 bars after the signal. A LONG reclaim must:

- trade strictly below the known lower boundary by at least the fixed tick
  floor;
- close strictly back above that boundary;
- close above its open; and
- close at or above its full candle midpoint.

Use the exact mirror at the upper boundary for SHORT. A wick that does not
sweep and reclaim the named boundary is not a range setup.

For every delayed route, enter at the first M1 open strictly after the
confirmation is available. Stop or target first passage before entry cancels
the setup with same-minute stop-first treatment.

## 5. Actual-fill economics

At every direct or delayed executable fill:

- the fill must remain strictly between the explicit invalidation and
  destination;
- the remaining destination room divided by structural price risk must be at
  least 1.50R;
- planned loss includes unchanged spread and $0.05/oz slippage per side;
- whole-ounce quantity is recalculated to keep maximum planned risk at $50 on
  the frozen $10,000 account;
- quantity below one ounce produces no trade.

Unlike V1, the 1.50R gate is mandatory at the actual fill. A confirmation may
not consume the economics of the original opportunity.

## 6. Structural management

Remove both performance-blind numeric full-position break-even mechanisms:

- do not use the extra M5-close-at-+1R overlay;
- do not move the full position to break-even solely because an R threshold
  was crossed.

Before the destination, advance the stop only after a new completed direction-
aligned M5 structural break. The proposed stop is the new break's protected
swing plus the existing adverse 0.10 event-ATR buffer. It may only tighten and
is effective from the first M1 open after the break is available.

For continuation only, preserve the existing 80% core / 20% runner split at
the explicit destination. Retain the runner only if the containing completed
M15 candle accepts beyond the destination by the existing 0.10 M15-ATR rule;
otherwise close it. After acceptance, trail only behind newly completed
aligned M15 protected swings. Range rotation and structural repair exit fully
at their explicit destination. Retain UTC-day time exit, stop-first ambiguity,
gap execution, spread, slippage, and latency.

## 7. Integrity and reporting

Before path replay:

- verify every predecessor seal and rollback hash;
- freeze this protocol, implementation, tests, runner, exact 95 identities,
  compiler version, and all constants;
- synthetically prove LONG/SHORT boundary reclaim, fresh/inherited routing,
  expiry, pre-entry first passage, actual-fill room, explicit geometry,
  structural trailing, gap handling, and target handling.

Run primary and reference streams independently. Require exact plans, routes,
trades, results, row identities, and canonical checksums.

Report control, rigid confirmation, Router V1, and Router V2 by month, compiled
family, and combined. Report plan coverage, route dispositions, trades, wins,
losses, scratches, expectancy, PF, net R/USD, drawdown, stressed costs, winner
retention, stopped-then-later-continuation diagnostics, and the exact
contribution of each semantic correction where mechanically identifiable.

Do not retune after replay, add another route, restore learned geometry, use a
month or macro label as a loss filter, open another period, or initialize paper
trading. Record the result honestly, independently reproduce, seal, and stop.
