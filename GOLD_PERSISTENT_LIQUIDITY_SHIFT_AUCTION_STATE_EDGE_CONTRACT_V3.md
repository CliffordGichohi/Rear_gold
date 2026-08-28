# Gold Persistent Liquidity-Shift Auction-State Edge Contract V3

## Preserved evidence

Preserve every V1 and V2 result. In particular:

- V2 confirmed a same-direction prior liquidity-zone reaction for 16/16 human trades.
- V2 confirmed a later same-direction M15 transition for 11/16 human trades.
- Original V2 entry semantics matched 1/16.
- V2 Amendment A matched 6/16 and formally failed the frozen 7/16 requirement.

V3 does not lower that requirement. It replaces the rejected assumption that only the first sixty-minute retracement after the M15 transition is tradable.

## Research question

After price reacts at a point-in-time-known liquidity-shift zone and confirms an M15 auction transition, does that directional auction state remain useful for later, independently observable M5 continuation impulses and their retracements?

## Frozen state lifecycle

Reuse every V2 zone, contact, reaction and M15-transition definition unchanged under Amendment A's 6.50-M15-ATR representation ceiling.

An auction state begins at the completed M15 transition and ends at the earliest of:

1. thirty-six elapsed hours;
2. invalidation or expiry of the source zone; or
3. a qualifying opposite M15 transition: opposite completed M15 candle, true range at least 0.90 ATR, body/range at least 0.55, and close through the latest already-confirmed opposing pivot by at least 0.05 ATR.

Overlapping same-direction states are deduplicated at identical transition timestamps by preferring H4, then H1, then M15 source location. A later same-direction transition may refresh but never retroactively move the earlier state start.

## Repeated M5 impulses

Within an active state, a new M5 impulse is available only after its candle closes and must:

- point in the active-state direction;
- have true range at least 0.80 M5 ATR14;
- have body/range at least 0.55;
- close through the most recent already-confirmed same-side M5 pivot by at least 0.05 M5 ATR;
- use each broken M5 pivot at most once per auction state; and
- identify the last opposite-colour M5 origin candle among the preceding four completed M5 bars.

The impulse leg is frozen from that origin's far extreme to the impulse close. Its retracement band is 38.2%-78.6% and its half-retrace is 50%.

## Registered V3 entries

Exactly two families are permitted for every qualifying M5 impulse:

1. `STATE_M5_HALF_RETRACE_LIMIT_V3`: virtual limit at the frozen 50% retracement, expiring after twelve M5 bars or auction-state termination.
2. `STATE_M5_RETEST_CONFIRMATION_V3`: after a completed M5 bar overlaps the 38.2%-78.6% band, require an aligned completed M5 body/range of at least 0.55 closing beyond the preceding two M5 highs/lows; enter at the next observed M1 open.

The limit stop is the impulse-origin far extreme plus an adverse 0.10 M5 ATR buffer. The confirmation stop is the observed pullback extreme plus the same buffer. Stop distance must be at least 0.10 M15 ATR and no more than 6.50 M15 ATR. There must be at least thirty minutes remaining in the active London or New York session.

Targets, macro routes, point-in-time casebook joins, costs, $50 planned risk, $55 effective-risk ceiling, whole-ounce sizing, stop-first ambiguity, one-trade-per-cell-session rule and four-hour/session-close time exit remain exactly as frozen in V2.

## Semantic calibration

Use the same 16 exposed human trade decisions with outcomes prohibited. A match requires that a registered V3 entry was triggered or legitimately pending in a same-direction active auction state no later than the human decision. The frozen pass requirement remains at least 40%, meaning at least 7 of 16 trades.

One semantic attempt is permitted. A failure stops V3 before development outcomes. A pass seals the complete V3 implementation before development outcomes are opened.

## Development economics

If semantic calibration passes, use the same 2021-08-01 through 2024-12-31 sealed development sources, exclusions, routes, sessions, target hierarchy, 40-trade support floor, chronological blocks, week-cluster bootstrap, Holm multiplicity and economic PASS/REJECT gates specified by V2. Test every frozen session x route x V3-entry-family cell and record all negative results.

The 30 matched-replay dates and six engineering dates remain excluded from economic credit. Calendar 2025 and 2026 remain locked. No paid acquisition or broker order is permitted.

