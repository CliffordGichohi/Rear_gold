# Gold Liquidity-Response M5 Structure-State Edge Contract V4

## Preserved evidence

Preserve every V1-V3 result and seal. V3 remains formally terminated at 0/16 corrected semantic matches. V4 is a materially different branch derived only from outcome-blind pre-decision evidence.

The frozen diagnostic found:

- a prior same-direction liquidity-zone contact for 16/16 human trades;
- a causal M5 same-direction pivot break for 16/16;
- median M5-break age of 30 minutes and maximum age of 195 minutes;
- median zone-contact age of 312.5 minutes and maximum age of 1,780 minutes; and
- only 1/16 trades inside V3's M15-transition state.

No post-decision outcome or PnL contributed to V4.

## V4 research question

After price reacts at a point-in-time-known M15, H1 or H4 liquidity-shift zone, does a causal M5 structure break establish a persistent, refreshable auction state that can be entered economically during London or New York?

## Location episode

A location episode begins at the completed V2 zone reaction and ends at the earliest of:

1. thirty-six elapsed hours; or
2. the source zone's already-frozen terminal timestamp.

All V2 pivot, zone, contact and reaction definitions remain unchanged under the previously documented 6.50-M15-ATR representation ceiling. No M15 transition is required.

## M5 structure activation

Within a location episode, an activation occurs on the first completed M5 close at least two XAUUSD ticks through the latest already-confirmed M5 pivot in the zone direction. Each M5 pivot may activate once per location episode. Range, body and displacement thresholds are deliberately absent because the pre-decision diagnostic showed they were not part of the human trigger semantics.

An activation state begins at that M5 close and ends at the earliest of:

1. four elapsed hours;
2. location-episode termination; or
3. a completed M5 close at least two ticks through the latest already-confirmed opposite M5 pivot.

A later same-direction causal M5 pivot break refreshes the four-hour state. Identical timestamp/direction activations are deduplicated by source-zone priority H4, H1, then M15.

## Semantic gates

Use the same 30 visible decisions with zero economic credit and no outcomes:

- at least 10 of 16 human trades must be inside a same-direction active V4 state at the decision timestamp; and
- no more than 7 of the 14 NO_TRADE days may contain any eligible V4 state during a London or New York window with at least thirty minutes remaining.

Both gates must pass. One semantic attempt is permitted. Failure terminates V4 before economic outcomes.

## Frozen execution if semantics pass

Exactly two entry families are allowed:

1. `M5_BREAK_NEXT_M1_V4`: next observed M1 open after the activating M5 close.
2. `M5_BROKEN_PIVOT_RETEST_V4`: limit at the broken M5 pivot, valid until activation-state termination.

For both, the stop is beyond the latest already-confirmed opposing M5 pivot at activation plus an adverse 0.10 M5 ATR buffer. Reject invalid or zero-risk geometry. The target is the nearest point-in-time-known opposing H1/H4 swing or opposing H1/H4 liquidity-zone midpoint providing at least 1.50R. Use the first touched target, structural stop, or the earliest of four hours and session close. Same-bar ambiguity is stop-first.

Require at least thirty minutes remaining in London or New York. Use one trade per entry-family/session, whole-ounce sizing, $50 planned risk, maximum $55 effective risk, $0.20 fallback spread and $0.05 adverse slippage per side. Apply the existing matched dates and six engineering-date exclusions.

## Context routes

Test separately and in frozen order:

1. `ALL_ZONE_RESPONSES` as the technical control;
2. `MACRO_ALIGNED_CONTINUATION`: point-in-time score at least +20 bullish or -20 bearish, coverage at least 50 and confidence at least 35; and
3. `OUTER_RANGE_ROTATION`: direction points inward from the outer 35% of the latest point-in-time-known H1 or H4 swing range, irrespective of macro sign.

Fundamentals remain context, not fabricated fact. Missing context is UNKNOWN and cannot satisfy a conditional route.

## Economic protocol

If and only if semantics pass, use 2021-08-01 through 2024-12-31 development data, excluding the 30 matched dates and six engineering dates. Keep 2025 and 2026 locked.

Analyse London and New York separately. Require per cell: at least 40 trades; positive net expectancy; PF at least 1.10; positive week-clustered 95% lower confidence bound; positive expectancy at 1.5x costs; at least three positive chronological blocks and two positive calendar years; no single year/session above 70% of positive PnL; and maximum drawdown no more than 15% of the $10,000 reference account. Apply Holm correction by session. Permit no more than two provisional candidates per session.

No rule may be inverted, repaired, retuned or selectively filtered after outcomes. Calendar 2025 and 2026 remain locked. No paid acquisition or live order is permitted.

