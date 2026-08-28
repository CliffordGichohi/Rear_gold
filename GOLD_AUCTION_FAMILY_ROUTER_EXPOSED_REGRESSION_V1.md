# Gold Auction Family Router Exposed Regression V1

Status: `APPROVED_EXPOSED_ENGINEERING_AND_REGRESSION`

## 1. Purpose and rollback boundary

Replace the rejected universal two-stage M5 confirmation with one transparent
entry route per already-frozen auction family. This is exposed calibration and
receives zero validation credit.

The complete Gold Day-by-Day Auction-Confirmation Exposed Regression V1 is the
immutable rollback baseline. Its protocol, implementation, 95-row ledger,
result, report, and final seal must not be modified. This router is implemented
only in new files and a new append-only artifact directory.

## 2. Exact population and unchanged inputs

Use the identical 95 already-opened dates:

- 2022-01-03 through 2022-02-16: 30 existing daily streams;
- 2022-03-01 through 2022-05-31: 65 existing daily streams.

Keep 2022-02-17 through 2022-02-28 unopened. Prohibit the random `GAV` block,
additional dates, 2025, and 2026. Use the frozen autonomous translator's first
signal, LONG direction, auction family, structural stop, liquidity target,
costs, latency, and maximum-one-setup-per-day policy unchanged.

The original signal-time contextual classification must be `ADMIT`. A later
bar may not erase an initial macro, structure, event, or location rejection.

## 3. Universal pre-entry gates

1. The original executable fill must have ordered geometry and at least 1.50R
   of room to the pre-existing liquidity target.
2. The original stop and target remain absolute prices and may not be rebuilt.
3. For a delayed route, stop or target first passage before entry cancels the
   setup; same-minute ambiguity is stop first.
4. The delayed fill must remain strictly between the original stop and target.
   Quantity is recalculated from the actual fill and unchanged costs to retain
   the fixed $50 maximum planned risk.
5. A failed route does not permit a replacement signal or another family.

The 1.50R gate is measured at the original executable fill, before any optional
family confirmation. It is not remeasured after the delayed route, because the
purpose of this regression is to avoid allowing confirmation delay to redefine
the pre-existing opportunity. Ordered geometry is still mandatory at entry.

## 4. Frozen family routes

### 4.1 `CONTINUATION_WITH_ROOM`

The frozen translator signal and unchanged contextual policy already require an
active aligned M15 directional structure. Do not require redundant post-signal
candles. Enter at the original next-M1 executable fill.

### 4.2 `RANGE_ROTATION`

Starting after the signal, inspect at most the next six completed M5 bars in the
same session. Use the first self-contained failed-auction/reclaim bar:

- LONG: close above open, genuine lower wick, and close at or above the full
  candle midpoint;
- SHORT mirror: close below open, genuine upper wick, and close at or below the
  midpoint.

Enter at the first M1 open strictly after that M5 bar becomes available. No
second progression candle is required. If none occurs, return
`NO_RANGE_RECLAIM_WITHIN_6_M5`.

### 4.3 `STRUCTURAL_REPAIR`

At the signal, identify the latest active direction-aligned M15 structural
break using the existing frozen point-in-time swing and break detector. Inspect
at most the next twelve completed M5 bars in the same session.

Use the first completed M5 retest that:

- reaches the broken M15 level within the existing 0.25 M5-ATR tolerance;
- closes back beyond that level in the trade direction;
- closes in the trade direction relative to its own open; and
- occurs while the M15 break's protected level remains intact under the
  existing 0.10 transition-ATR close buffer.

Enter at the first M1 open strictly after the retest becomes available. If the
protected level is invalidated first, return `REPAIR_STRUCTURE_INVALIDATED`. If
no retest occurs, return `NO_REPAIR_RETEST_WITHIN_12_M5`.

## 5. Execution and management

Preserve `COMPLETE_V2_POLICY` unchanged:

- original absolute structural stop and liquidity target;
- fixed $50 maximum risk, whole-ounce sizing, spread and $0.05/oz slippage;
- one-minute latency and stop-first ambiguity;
- continuation-only bounded runner and unchanged session/day deadline.

Apply the already-frozen M5-close-at-+1R net-break-even overlay to every
executed family route. It remains a separately reported contribution.

## 6. Required outputs and integrity

Produce one row per day with the morning plan, original control, rejected rigid
confirmation result, routed family, route evidence, fill, stop, target,
disposition, net R, and chronological equity. Report by month, family, and
combined, including support, wins/losses/scratches, win rate, expectancy,
profit factor, drawdown, stressed costs, retained/recovered winners, avoided
losses, and break-even effects.

Before market replay:

- hash and seal the immutable rollback baseline and exact 95 identities;
- synthetically prove all three routes, expiry, invalidation, pre-entry
  first-passage, latency, and mirrored SHORT definitions;
- freeze all implementation files.

Run primary and reference streams independently and require exact rows,
classifications, results, and canonical checksums. Do not retune, add a fourth
route, alter thresholds, inspect another date, or initialize paper trading after
seeing results. Record the achieved exposed result honestly and stop.

