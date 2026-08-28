# Gold Auction Trade Placement Examples V1

## Purpose

Render ten outcome-blind examples showing how the corrected auction and liquidity
semantics translate into a concrete trade plan. This is a visual and semantic
demonstration only. It does not establish an edge and it does not calculate PnL.

## Frozen source boundary

- Use only the already-exposed 729-event primary semantic census and its sealed
  Amendment B liquidity/range overlay.
- Use only candles and context available at each event's `decision_at` timestamp.
- Do not access post-decision bars, outcomes, trades, PnL, 2025, or 2026.
- Preserve every previous verdict and sealed artifact unchanged.

## Placement rule

For an event to be eligible for the ten-example atlas:

1. M15 and M5 active control must agree with the proposed direction.
2. The M5 protected internal pivot must remain unconsumed at the decision time.
3. The decision price must be no more than one contemporaneous M5 ATR from the
   broken M5 control pivot; otherwise the example is classified as chased.
4. Entry is the observed decision price after the completed M5 signal. No future
   retest or better fill is assumed.
5. For LONG, the stop is the protected M5 low minus the already-defined M5 break
   buffer. For SHORT, it is the protected M5 high plus that buffer.
6. The target is the nearest point-in-time unconsumed H1 or H4 liquidity pivot in
   the trade direction.
7. The planned target must provide at least 1.5R of room. This is a pre-trade
   geometry requirement, not a result-derived filter.
8. The nearest M15 unconsumed liquidity is displayed as a local obstacle, not
   silently substituted for the governing target.

## Outcome-blind selection

Select five LONG and five SHORT examples. Within each direction select, in this
order, the earliest eligible event on a previously unused date for:

- one `RANGE_ROTATION_WITH_LTF_CONTROL` example;
- two `TREND_PULLBACK_WITH_LTF_CONTROL` examples;
- two `TRANSITIONAL_CONTEXT_WITH_LTF_CONTROL` examples.

No event is selected using later price movement or trade outcome.

## Rendering

- Show H4, H1, M15, and M5 completed candles through the decision timestamp.
- Mark only exact source pivots with bounded rightward rays.
- Draw the position tool only in a blank region to the right of the last visible
  M5 candle; it must not create a full-width horizontal line.
- Display direction, entry, stop, target, planned R, macro context, governing
  context, control transition, and liquidity identities.
- Label liquidity and control interpretations as calculated or inferred; never
  present institutional orders as observed fact.

## Acceptance

- Exactly ten plans: five LONG and five SHORT.
- Exactly one range rotation, two trend pullbacks, and two transitional contexts
  per direction.
- Every plan passes the frozen point-in-time placement rule.
- Primary and reference implementations reproduce the same identities, values,
  classifications, checksums, and SVG bytes.
- No outcome or performance data is accessed.

