# Session State-Transition Edge Research

## Objective and hurdle

This protocol searches for a transparent, repeatable London/New York execution
portfolio rather than another single breakout rule. The commercial hurdle is an
average 10R per month before translating R to dollars. At 1% account risk per
trade, 10R is approximately 10% of starting equity; it is not assumed achievable
and is never used to select parameters.

The reference book remains the business specification:

```text
slow regime and positioning context
-> active session and liquidity state
-> accepted or rejected reference-level auction
-> cross-market confirmation or contradiction
-> trigger
-> logical invalidation and sized risk
```

## Locked data protocol

| Slice | Purpose |
|---|---|
| 2021-08-01 through 2022-12-31 | discovery and candidate selection only |
| calendar 2023 | validation |
| calendar 2024 | development-forward confirmation |
| calendar 2025 | locked; prohibited in this research stage |

All XAUUSD and EURUSD bars are observed IC Markets one-minute records aggregated
only after all five constituent minutes are complete. Signals use completed bars
and enter at the following five-minute open. Missing paths are excluded rather
than filled.

## Reference states

The ledger scans London and New York but admits at most the first signal from
each archetype in each session:

1. `ACCEPTANCE_MOMENTUM`: two closes beyond the Asian boundary, directional
   displacement, and aligned 60-minute gold momentum.
2. `ACCEPTED_RETEST`: a previously accepted Asian break retests and holds the
   boundary with a directional response.
3. `FAILED_AUCTION_REVERSAL`: one Asian boundary is breached, price returns
   inside, and displacement breaks the preceding three-bar micro structure.
4. `HANDOVER_CONFIRMATION`: London establishes a material direction and New
   York displaces in the same direction.
5. `HANDOVER_REJECTION`: London closes outside Asia, but New York returns inside
   and displaces against London.
6. `TREND_PULLBACK_RECLAIM`: four-hour momentum is material, price auctions
   through the active-session open against that trend, then reclaims it with
   displacement.
7. `OPENING_DRIVE`: the first 30 session minutes travel at least two
   five-minute ATR and close with directional displacement.

Each row records Asian range percentile, completed EURUSD 60-minute momentum,
relative volume, relative spread, session phase, gold 60-minute/four-hour
momentum, reference levels, and exact evidence clocks. EURUSD is an inferred
inverse USD proxy, not DXY.

## Predeclared context cohorts

Every archetype is reported without a filter and through these fixed cohorts:

- completed EURUSD 60-minute direction aligned;
- Asian range at or below its rolling 30th percentile;
- both EURUSD alignment and Asian compression;
- signal spread no more than 1.25 times its preceding 60-minute median; and
- signal volume at least 1.20 times its preceding 60-minute median.

These are parallel hypotheses. They cannot be combined after observing 2023 or
2024.

## Stops, exits, and friction

Initial invalidation is structural: beyond the Asian boundary, failed-auction
extreme, opening-range midpoint, recent micro swing, or session-auction extreme
according to the archetype. Risk must be between 0.30 and 8.00 five-minute ATR.

The frozen management alternatives are:

- fixed 1.50R target;
- fixed 2.00R target; and
- 50% at 1.00R, then a remaining half-position runner with break-even protection,
  a completed three-bar structure trail, a 4.00R cap, and a time exit.

London trades cannot outlive the New York research-window close. New York trades
cannot outlive New York noon. Same-bar ambiguity is stop-first. Friction is the
observed broker spread, 0.05 USD/oz adverse slippage per side, and 7 USD/lot
round-turn commission. Every candidate is also evaluated at 1.50 times costs.

## Discovery selection and portfolio

A candidate is selectable using discovery data only when it has:

- at least 40 discovery trades;
- at least +0.10R net expectancy;
- profit factor at least 1.15;
- positive discovery expectancy at 1.50 times costs; and
- bootstrap lower bound no worse than -0.05R.

At most one rule/management combination per archetype is selected. Its discovery
expectancy establishes priority when signals conflict. The portfolio allows one
open XAUUSD position, skips overlapping entries, risks 1% per accepted trade for
the commercial-hurdle report, and blocks new entries after -2R realized on a
session date.

No validation result can change the selected candidates, thresholds, priority,
stop, exit, or cost model. A portfolio is a serious lead only if both 2023 and
2024 remain positive after costs, its all-period profit factor exceeds 1.25, its
1.50-times-cost expectancy stays positive, and no single archetype supplies more
than 60% of profit.

## Interpretation boundary

This state engine tests whether session mechanics contain an execution edge. A
qualifying price/cross-market portfolio must still be overlaid with the book's
point-in-time regime, catalyst, positioning, and intraday-rates evidence before
being called fully book-aligned. Failure at this stage means adding fundamental
filters cannot manufacture edge from a negative execution substrate.

The completed auction-window, one-minute structural execution,
transparent-bias, and exact point-in-time fundamental-permission results are
documented in `AUCTION_EDGE_RESEARCH.md`. No candidate qualified, so calendar
2025 remains closed.
