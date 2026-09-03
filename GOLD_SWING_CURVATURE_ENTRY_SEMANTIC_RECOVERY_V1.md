# Gold Swing-Curvature Entry Semantic Recovery V1

## Status and purpose

This is an outcome-blind semantic-recovery branch. It corrects the entry
translation before any further economic research. The earlier
`EXPECTED_VALUE_SIDE` / aligned-displacement market-entry branch remains
preserved but is quarantined from this branch.

The immediate deliverable is not a backtest. It is a deterministic detector
and twelve paired M15/M5 predecision charts that the human operator must
approve or reject for semantic fidelity.

## Governing sources and precedence

The entry semantics are governed, in this order, by:

1. the user's direct clarification that entries belong at or near the
   controlling swing curvature, with M5 used for the turn and retest;
2. the supplied `market instructs.svg` diagram;
3. the supplied `videoplayback.mp4` instructional video, whose visible
   decision chain is `environment -> location -> confirmation`;
4. the Gold & USD Market Intelligence Reference Book, especially its
   liquidity, acceptance/rejection, swing-structure and
   bias/trigger/invalidation distinctions; and
5. the human replay's predecision annotations and drawings.

If a statistical rule or an older implementation conflicts with those
sources, the semantic sources above govern. No result, PnL, MFE, MAE, winner
label, loser label or future candle may resolve an ambiguity.

## Quarantined branch

The following concepts are explicitly ineligible here:

- `ALIGNED_DISPLACEMENT` as the entry trigger;
- a minimum ATR expansion or body-size gate;
- two-close acceptance as an entry requirement;
- `EXPECTED_VALUE_SIDE` as a direction selector;
- first market open after a completed M15 displacement signal; and
- any stop, target or distance learned from later outcomes.

The old files are not edited or deleted. A separate quarantine manifest will
record their exact hashes and formal disposition.

## Frozen exposed population

- Source: the existing sealed primary and reference daily streams already used
  by the January-June 2022 exposed auction review.
- Session: New York, `08:00 <= local time < 12:00`, using
  `America/New_York` daylight-saving conversion.
- Direction: LONG and SHORT are symmetric.
- Selection: scan every eligible exposed day chronologically and retain the
  first twelve complete semantic plans by `(decision_at, direction,
  candidate_identity)`.
- A controlling swing may contribute at most one candidate per trading day.
- The twelve-case selection is based only on predecision identities and
  timestamps, never later path behaviour.
- No unopened date, 2025 or 2026 value may be accessed.

## Epistemic classification

- XAUUSD OHLC and timestamp: `OBSERVED`.
- Confirmed pivots, trend/range state, curvature zone, M5 turn, retest,
  invalidation and destination: `CALCULATED`.
- Governing-auction interpretation and likely liquidity role: `INFERRED`.
- Resting orders, institutional motive and hidden liquidity: `UNKNOWN`.

The word `liquidity` in a chart label means a calculated auction reference,
not direct observation of institutional orders.

## Frozen semantic chain

### 1. Environment

Point-in-time macro, H1/H4 structure, range state and session are recorded as
context. They do not manufacture an entry and macro is not a mandatory veto.
This preserves the human observation that a balanced range can rotate against
the broader macro pressure while a lower-timeframe auction turns from a known
location.

### 2. Governing M15 auction and controlling swing

Only completed, available M15 candles may be used.

- `TREND_LONG`: the latest M15 swing relations are `HH` and `HL`. The
  controlling swing is the latest known, not-yet-consumed confirmed M15 LOW.
- `TREND_SHORT`: the latest M15 swing relations are `LH` and `LL`. The
  controlling swing is the latest known, not-yet-consumed confirmed M15 HIGH.
- `RANGE_LONG`: an objective active M15 range exists and price is in its lower
  half. The controlling swing is the exact unconsumed lower-boundary pivot.
- `RANGE_SHORT`: an objective active M15 range exists and price is in its upper
  half. The controlling swing is the exact unconsumed upper-boundary pivot.

M15 pivots use the existing causal two-left/two-right confirmation and 0.25 ATR
prominence rule. A pivot is unavailable before `detected_at`.

### 3. Consumption and engagement

- A confirmed high is consumed only after later observed price trades strictly
  above it.
- A confirmed low is consumed only after later observed price trades strictly
  below it.
- Equality is engagement, not consumption.
- Once consumed, the pivot remains consumed.
- A wick shape is not acceptance. Acceptance/rejection and strict traded-price
  consumption remain separate classifications.

### 4. Near-curvature location

For a completed M15 trend impulse, the location zone is the video's exact
`0.705` through `0.886` retracement band of the latest known impulse:

- LONG: from the latest controlling M15 LOW to the subsequent terminal M15
  HIGH, projected downward from that high;
- SHORT: from the latest controlling M15 HIGH to the subsequent terminal M15
  LOW, projected upward from that low.

The 0.886 boundary is a point-in-time location invalidation. A candidate is not
formed after later price trades beyond it. Because the exposed XAUUSD stream
does not contain a volume-profile value area, `outside value` remains
`UNKNOWN`; the engine must not fabricate it from ordinary OHLC.

For an objective M15 range, where a directional trend impulse does not govern,
the location remains the directional half of the exact boundary-pivot candle:

- LONG: boundary-pivot low through the candle midpoint;
- SHORT: candle midpoint through the boundary-pivot high.

An engagement exists when an available M5 candle overlaps the applicable zone
without breaching its location invalidation or strictly consuming the
controlling swing. This is deliberately a location rule, not a
reward-to-risk or volatility filter.

### 5. M5 turn

After curvature engagement, the first completed direction-aligned M5 candle
within the next three M5 intervals that closes in the directional half of its
own range is the turn candle. It must overlap the curvature zone. This is the
price-only evidence that the adverse push stopped producing further progress.

There is no minimum ATR range, body ratio, displacement label, confirmed M15
break or second acceptance close. Without GC order-flow coverage, actual delta,
absorption, iceberg activity and aggressor imbalance remain `UNKNOWN`; the
candle response is a calculated price-response proxy, not observed absorption.

The turn is cancelled if the 0.886 location boundary or controlling M15 swing
is breached first.

### 6. First retest

After the turn, the first M5 candle within the next three intervals that makes
an adverse excursion back into the turn candle's real body or the curvature
zone is the retest attempt. No later attempt may be selected if the first is
inconvenient.

The retest confirms only when:

- LONG makes a higher low than the turn candle and closes bullish in the upper
  half of its own range;
- SHORT makes a lower high than the turn candle and closes bearish in the
  lower half of its own range; and
- the applicable location boundary and controlling swing remain intact.

The entry reference and candidate decision timestamp are the confirmed retest
candle's close and `available_at`. This implements the video's sequence:
adverse effort at the extreme, directional turn, a second adverse attempt that
fails at a better level, then entry on the aligned flip.

### 7. Invalidation and destination

- LONG invalidation is one minimum tick below the lower of the completed M5
  turn and retest lows.
- SHORT invalidation is one minimum tick above the higher of the completed M5
  turn and retest highs.
- The destination is the nearest pre-existing, unconsumed opposing M15 or H1
  pivot beyond entry, known no later than the retest-candle close.

No minimum R, target-room or profitability gate is allowed at this stage.
Entry, invalidation and destination must be geometrically ordered. If any of
the six plan components is unresolved, the observation is
`NO_CANDIDATE_UNRESOLVED` rather than an executable candidate.

## Six required plan components

Every rendered candidate must contain:

1. governing auction identity and state;
2. exact controlling M15 swing identity and curvature zone;
3. exact M5 turn-pivot and turn-candle identities;
4. first-retouch identity and planned entry level;
5. point-in-time internal M5 invalidation; and
6. exact pre-existing M15/H1 destination identity.

## Rendering rules

- Render the first twelve chronological complete candidates only.
- Each candidate has paired M15 and M5 views.
- The chart ends at the candidate decision timestamp. No outcome candle may be
  rendered.
- The controlling pivot, curvature zone, M5 turn pivot, turn candle, retest,
  entry, invalidation and destination must be individually labelled.
- Swing and destination rays are bounded to their relevant region; no generic
  full-width support/resistance lines are allowed.
- Partial as-of candles must be visually distinguishable from completed
  candles.
- Charts must use readable medium-width candles and must remain usable at
  desktop, 736-pixel and 360-pixel widths.

## Certification and stop rule

Before scanning exposed values:

- hash the governing sources and quarantined artifacts;
- prove direction symmetry, future exclusion, exact curvature construction,
  strict consumption, first-retest selection, retest expiry and complete-plan
  rejection on synthetic data; and
- seal this contract, implementation, tests, source lineage and constants.

Then independently reproduce candidate identities and fields from the sealed
primary and reference streams. Stop after rendering and browser-level visual
certification. Do not calculate PnL, win rate, expectancy, R, MFE, MAE,
profit factor or any other outcome statistic until the user approves the
visual classifications.
