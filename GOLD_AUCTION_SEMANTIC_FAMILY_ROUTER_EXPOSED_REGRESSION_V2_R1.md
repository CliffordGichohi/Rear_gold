# Gold Auction-Semantic Family Router Exposed Regression V2-R1

Status: `APPROVED_IMPLEMENTATION_CORRECTION_ZERO_VALIDATION_CREDIT`

## Purpose

Correct only the semantic-integration failures documented after Router V2.
Preserve the sealed Router V2 result as `FAIL_SEMANTIC_INTEGRATION`; it is not a
strategy rejection. Preserve every predecessor byte-for-byte.

Use only the same 95 exposed dates from 2022-01-03 through 2022-02-16 and
2022-03-01 through 2022-05-31. Keep 2022-02-17 through 2022-02-28 and every
later period closed. This is implementation certification with zero validation
credit.

## One signal lifecycle

The frozen legacy signal is the sole decision anchor. Do not combine it with
the autonomous semantic detector or require an optional historical M5
refinement to become a second trigger.

- `CONTINUATION_WITH_ROOM`: use the original next-M1 executable fill.
- `STRUCTURAL_REPAIR`: use the plan's M15 setup transition and require its
  first valid M5 retest under the already frozen 12-bar rule.
- `RANGE_ROTATION`: require the first valid sweep/reclaim of the plan's named
  directional balance boundary under the already frozen six-bar rule.

The M5 refinement remains evidence only. It cannot override the execution
anchor or create an additional route.

## Invalidation before delayed entry

Between the signal and a delayed fill, cancel only when the explicit structural
invalidation is touched, retaining stop-first ambiguity. Do not cancel merely
because a liquidity reference price is touched.

## Liquidity lifecycle and destination

At the signal and again at any delayed confirmation, construct the destination
from information available at that timestamp:

- `ACTIVE_UNTOUCHED` and `ACTIVE_ENGAGED` H1/H4 liquidity may define the final
  destination;
- `CONSUMED_ACCEPTED` is unavailable as a destination;
- `REACTIVATED_REVERSE` is retained as an intermediate reaction/partial level,
  not by itself as the governing final destination;
- select the nearest eligible final destination in the trade direction;
- record the nearest reactivated level between entry reference and final
  destination as an intermediate level when one exists;
- range rotation retains the active named opposite balance boundary as its
  final destination and its midpoint as the partial reference.

For a delayed route, refresh the lifecycle at confirmation. A raw touch changes
an untouched level to engaged; only sustained acceptance may consume it.

## Geometry, execution, and management

Use the compiler's explicit structural invalidation and corrected liquidity
destination. At the actual fill require valid directional geometry, at least
1.50R of final-destination room, and at least one whole ounce at no more than
$50 planned risk including existing costs.

Keep spread, $0.05/oz slippage per side, latency, UTC-day exit, gap handling,
one-trade-per-day policy, stop-first ambiguity, and structural management
unchanged. Do not use the extra numeric M5 +1R full-position break-even overlay.

## Certification

Before replay, prove synthetically that:

- the execution anchor is not replaced by M5 refinement;
- continuation is direct;
- structural repair uses M15 setup;
- target touch without invalidation does not cancel a delayed entry;
- stop touch does cancel;
- engaged liquidity remains eligible;
- consumed liquidity is excluded;
- a nearer reactivated level is intermediate while the next eligible active
  level is final.

Run independent primary and reference streams and require exact rows and
checksums. Report every disposition, admitted and rejected trade, comparison
with control, Router V1, and failed Router V2, and seal the result. Do not
retune, test a second hierarchy, open fresh dates, acquire data, or initialize
paper trading.

