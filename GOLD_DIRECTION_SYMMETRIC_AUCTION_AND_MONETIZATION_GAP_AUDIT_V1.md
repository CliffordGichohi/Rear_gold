# Gold Direction-Symmetric Auction and Monetization-Gap Audit V1

## Purpose

This exposed-data engineering and diagnostic branch answers two bounded
questions:

1. What happens when the existing LONG coherent-auction translator is allowed
   to recognize SHORT setups through an exact semantic mirror?
2. Where does the current system lose value: direction, admission, entry
   timing, invalidation, target placement, or post-entry management?

This is not fresh validation and cannot establish a live edge.

## Frozen population

- Every already-opened eligible trading day from 2022-01-03 through
  2022-02-16 and from 2022-03-01 through 2022-05-31.
- Exclude 2022-02-17 through 2022-02-28, the random 50-case population, 2025,
  and 2026.
- Reuse only sealed streams and the frozen translator. Acquire no data.
- Preserve all historical artifacts and verdicts unchanged.

## Direction symmetry

- LONG uses the existing feature row unchanged.
- SHORT uses the same fitted trees and threshold after the following exact
  involution: bullish/bearish exchange, high/low exchange, LONG/SHORT context
  exchange, signed-return negation, candle/trend direction exchange, and
  `range_position -> 1 - range_position`.
- Learned positive stop and target distances are mirrored around the same
  observable reference price.
- SHORT execution uses the same adverse half-spread, slippage, commission,
  contextual vetoes, target-room rule, family router, fixed risk, and
  lifecycle as LONG.
- No separate SHORT threshold, model fit, filter, family, or parameter is
  permitted.
- The existing LONG-only output must reproduce exactly before SHORT results
  receive engineering credit.
- Only New York checkpoints are eligible for the bidirectional experimental
  policy. This follows the user's instruction to stop seeking additional
  London setups. The unchanged all-session LONG control remains reported.
- At one checkpoint, if both directions pass, select the higher probability.
  An exact tie is `NO_TRADE_DIRECTION_CONFLICT`.
- Admit at most the first qualifying New York setup per day.

## Frozen diagnostic taxonomy

For each executed trade, classify all applicable losses of monetization:

- `DIRECTION_FAILURE`: the opposite side reaches +1R before the selected side
  reaches +1R, using the selected trade's structural risk.
- `STOP_THEN_TARGET`: structural stop occurs before the original target, but
  the original target is subsequently reached before the frozen deadline.
- `CLEAN_INVALIDATION`: stop occurs and the original target is not later
  reached before the deadline.
- `ENTRY_LATE`: at least 0.50R of same-direction movement occurred between the
  qualifying checkpoint and executable fill.
- `ENTRY_EARLY_OR_UNCONFIRMED`: adverse excursion reaches at least 0.50R before
  favourable excursion reaches 0.50R.
- `TARGET_TRUNCATION`: the target is reached and subsequent MFE exceeds the
  achieved target distance by at least 0.50R before the deadline.
- `MANAGEMENT_GIVEBACK`: MFE exceeds realized net R by at least 0.50R.
- `NORMAL_VARIANCE`: a losing trade with no deterministic stopped-then-target
  repair and no opposite-side first-passage classification.

These labels diagnose outcomes; they are not admission filters and may
overlap. No threshold may be changed after results are opened.

## Outputs

- Exact LONG-control reproduction result.
- Direction-symmetric daily ledger, including every no-trade day.
- Results by direction, session, month, and family.
- Counts and R attribution for the diagnostic taxonomy.
- Separate measures of signal/admission opportunity and execution/management
  retention.
- Primary/reference reproduction hashes.

No fresh period may be opened and no rule may be promoted for paper trading
from this audit alone.
