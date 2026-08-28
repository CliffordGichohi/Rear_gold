# Gold All-Transition Auction Scanner Liquidity and Range Semantics Amendment B

## Purpose

Correct the liquidity-label semantics in the sealed Gold All-Transition Auction
Scanner V1 without changing its 729 accepted M5/M15 control events. The sealed
V1 result and Visualization Amendment A remain unchanged.

This amendment is outcome-blind. It may classify only information observable at
each existing event timestamp. It must not access outcomes, calculate trades,
R, PnL, win rate, MFE, MAE, or inspect any unopened period.

## Governing clarification

The user-supplied `market instructs.svg` is the governing clarification for the
chart semantics below.

Liquidity consumption and structural acceptance are separate:

- a confirmed swing high is `CONSUMED` only when a later observed traded price
  is strictly greater than that swing high;
- a confirmed swing low is `CONSUMED` only when a later observed traded price
  is strictly less than that swing low;
- a later price equal to the pivot level is an engagement, not consumption;
- candle colour, body size, ATR displacement, closing location, acceptance and
  the visual appearance of a wick do not determine liquidity consumption;
- once consumed, a pivot remains consumed in the liquidity inventory. It can
  acquire a later structural role, but it does not become unconsumed again.

The classification uses completed bars from the pivot's own timeframe. Their
high and low contain the observed traded-price extrema. It begins strictly
after the pivot candle has completed, includes only bars available at the
decision timestamp, and uses strict inequalities with no ATR or tick buffer.

All swing pivots retain the frozen V1 confirmation rule: strict two-left and
two-right confirmation with at least 0.25 ATR prominence. A pivot cannot be
used before its frozen `detected_at` timestamp.

## Frozen liquidity states

At an existing event timestamp, every known confirmed pivot has exactly one
state:

1. `UNCONSUMED_UNTOUCHED`: no later completed bar has reached its price.
2. `UNCONSUMED_ENGAGED`: later price has equalled the pivot but never traded
   strictly beyond it.
3. `CONSUMED`: later price has traded strictly beyond it at least once.
4. `UNKNOWN_TECHNICAL`: the pivot identity or required price path cannot be
   resolved from the sealed source.

For a LONG event, unconsumed confirmed highs strictly above current price are
potential destinations. For a SHORT event, unconsumed confirmed lows strictly
below current price are potential destinations. The nearest candidate is
reported separately per timeframe. This is a destination inventory, not an
automatic take-profit instruction and not proof of resting institutional
orders.

The active M5/M15 broken pivot, the protected internal opposing pivot and the
destination pivots are each classified independently. A close-based structural
break may coexist with an already-consumed protected pivot; that conflict must
be shown rather than hidden.

## Frozen range semantics

The same lower-timeframe accepted-control price action used in a trend is also
examined inside an objectively identified H1 or H4 range. No separate or more
restrictive range trigger is introduced.

At each existing decision timestamp, a timeframe is an `ACTIVE_RANGE` only if:

- the latest 20 completed candles contain at least two known confirmed swing
  highs and at least two known confirmed swing lows;
- the highest and lowest of those confirmed pivots are the exact range-boundary
  identities;
- at least two confirmed highs lie within 0.50 of the current timeframe ATR
  below the upper boundary, and at least two confirmed lows lie within 0.50 ATR
  above the lower boundary, providing repeated two-sided rejection evidence;
- the boundary width is positive and no more than 5.0 current timeframe ATR;
- neither exact boundary pivot has been consumed at the decision timestamp;
- the current decision price is between the two boundaries, inclusive.

The range is point-in-time known only after every required boundary/rejection
pivot has been detected. Range boundaries must resolve to exact source pivots.
If these conditions are not met, the state is not labelled a range.

For an active range:

- LONG control at or below the range midpoint is
  `RANGE_ROTATION_WITH_LTF_CONTROL`;
- SHORT control at or above the range midpoint is
  `RANGE_ROTATION_WITH_LTF_CONTROL`;
- control pointing outward from the opposite half is reported as
  `RANGE_OPPOSITE_HALF_WITH_LTF_CONTROL`, not silently removed.

Outside an active range, completed H1/H4 swing relations provide descriptive
trend context only:

- `HH` plus `HL` = `UPTREND`;
- `LH` plus `LL` = `DOWNTREND`;
- every other combination = `MIXED_OR_TRANSITIONING`.

An event aligned with at least one H1/H4 trend is described as
`TREND_PULLBACK_WITH_LTF_CONTROL`. All remaining events are
`TRANSITIONAL_CONTEXT_WITH_LTF_CONTROL`. These descriptions are not trade
filters and do not change event eligibility.

## Visualization rules

The corrected atlas must:

- preserve the exact 24 selected event identities and all 729 original event
  identities;
- draw only pivots with a resolved source identity;
- place a marker on the exact pivot candle and price;
- use a bounded ray beginning at that pivot and spanning no more than 22% of
  the panel;
- label the pivot's semantic role and its strict traded-price lifecycle state;
- draw range boundaries only when the frozen active-range definition passes,
  and anchor both boundaries to exact confirmed pivots;
- omit generic full-width support/resistance lines and unqualified pattern
  labels;
- end every chart at the existing event timestamp.

## Reproduction and stop gates

- Verify every predecessor seal before materialization.
- Freeze this amendment, implementation, tests, governing diagram hash and
  exact constants before loading source values.
- Run primary and reference calculations independently and sequentially.
- Require identical augmented event identities, fields, counts, null states,
  hashes, summaries and byte-identical SVG charts.
- Require synthetic proofs for strict-above/strict-below consumption, equality
  engagement, future exclusion, direction symmetry, active-range recognition
  and range invalidation after a boundary is consumed.
- Preserve all original event data; store the corrected semantic overlay as a
  new append-only artifact.
- Stop for user visual review. Do not perform economic testing.

