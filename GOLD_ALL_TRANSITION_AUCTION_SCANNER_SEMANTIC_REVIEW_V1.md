# Gold All-Transition Auction Scanner Semantic Review V1

## Purpose

Correct the frequency and direction-semantics defect exposed by the sealed
`GOLD_DIRECTION_SYMMETRIC_AUCTION_CONTROL_ROUTER_V2` result.  V2 is retained as
a failed diagnostic: it routed at most one pre-filtered candidate per day and
therefore was not an all-opportunity day-trading scanner.

This branch performs outcome-blind semantic certification only.  It must not
calculate trade outcomes, R, PnL, win rate, profit factor, MFE, MAE, or use a
post-signal bar in an event snapshot or chart.

## Frozen population and scope

- Existing sealed January through June 2022 daily streams: 117 eligible days.
- The already-exposed dates retain zero validation credit.
- New York session only: bars opening from 08:00 inclusive through 12:00
  exclusive in `America/New_York`; the completed 11:55 M5 bar is observable at
  the 12:00 boundary. All times use the historical DST rule.
- February 17-28, July 2022, 2025, and 2026 remain closed.
- No source acquisition and no charge.

## Frozen structural semantics

The scanner reuses the previously documented causal structure definitions
unchanged:

- confirmed swing: strict two-left/two-right pivot with at least 0.25 ATR
  prominence; the pivot is unavailable until the second right-hand candle has
  completed;
- M5 break: completed close through a previously known pivot by 0.05 ATR,
  true range at least 0.80 ATR, and body/range at least 0.55;
- M15 break: the same definition with true range at least 0.90 ATR;
- active structure: the most recent qualifying break not yet invalidated by a
  completed close through its protected opposing swing plus 0.10 ATR;
- accepted directional control: active M5 and M15 breaks agree for two
  consecutive completed M5 observations;
- `BUYER_CONTROL` maps to `LONG`; `SELLER_CONTROL` maps to `SHORT` with no
  additional antecedent, retest, target-room, macro, or higher-timeframe veto.

All control and liquidity labels are `INFERRED`, not observations of orders or
institutions.

## Frozen event taxonomy

Every accepted directional state is scanned.  An event is emitted when one of
the following occurs:

1. `INITIAL_CONTROL`: the first accepted directional state in the session.
2. `REVERSAL_TRANSFER`: accepted control changes from the last accepted
   opposite direction.
3. `CONTROL_REASSERTION`: the prior accepted direction returns after an
   unresolved or conflicted interval.
4. `CONTINUATION_REFRESH`: accepted control remains in the same direction and
   a new qualifying M5 or M15 structural-break identity becomes active.

Remaining in an unchanged state does not emit repeated events.  Reversion to an
older active identity after invalidation is not a new event.  Every event is
identified by date, session, completed-M5 decision timestamp, direction,
event class, and the active M5/M15 structural identities.

## Point-in-time semantic fields

At the event timestamp only, record:

- the active M5 and M15 broken and protected swing identities and levels;
- which timeframe produced a new break at that checkpoint;
- completed-candle H1 and H4 swing relations and location context;
- point-in-time fundamental direction, confidence, data quality, dominant
  driver, and alignment relative to the event direction;
- aligned and opposing sweep/reclaim context already visible;
- the nearest still-unbroken same-timeframe and higher-timeframe opposing
  swing destinations known at the checkpoint;
- explicit epistemic classification and source lineage.

A broken pivot is described as an inferred consumed auction reference.  A
known swing beyond current price is described as an inferred unconsumed
liquidity destination.  Neither label asserts observed resting orders.
For this review, an M5/M15 swing becomes broken only through the frozen strong
break definition above. An H1/H4 swing becomes broken after a completed close
through it by the existing 0.05-ATR/tick-floor structural buffer. Future
touches and later invalidations are never included.

## Outcome-blind review atlas

Create deterministic examples using event metadata only, stratified by
direction, event class, and month.  Each chart must end at the event timestamp
and contain only completed candles whose `available_at` is no later than that
timestamp.  The atlas must show H4, H1, M15, and M5 views, active structural
levels, and the recorded macro/context summary.  It must show no future candle
and no outcome statistic.

## Integrity and stop gates

- Run primary and reference calculations independently and sequentially.
- Require exact event identities, fields, counts, null classifications,
  per-event hashes, complete payload hashes, selected example identities, and
  byte-identical charts.
- Require synthetic direction-mirror, event-deduplication, continuation,
  reversal, fallback-suppression, and pre-decision chart-boundary tests.
- Report events per day and counts by direction, class, month, and trigger
  timeframe before any economic test.
- Stop after semantic review.  No execution or outcome regression is permitted
  until the user confirms that the examples reflect the intended auction
  interpretation.
