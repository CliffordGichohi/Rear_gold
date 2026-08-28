# Gold Auction Family Router V1-R1 Mechanical Correction

Status: `APPROVED_EXPOSED_IMPLEMENTATION_CORRECTION_ZERO_VALIDATION_CREDIT`

## Purpose

Certify the exact two mechanical corrections already identified in the sealed
Router V1 attribution. This is not a new strategy, family classifier, geometry
model, or semantic replacement.

Preserve all earlier artifacts, including the failed semantic Router V2 and its
V2-R1 diagnostic replay. Use only the sealed Router V1 rows for the same 95
exposed dates. Open no price source and no additional date.

## Frozen changes

1. Remove the extra M5-close-at-+1R full-position break-even overlay. The
   independently reproduced `pre_overlay_result` becomes the effective result.
2. For a delayed range or structural-repair entry, enforce the already approved
   1.50R target-room gate using the actual delayed fill geometry. A delayed
   trade with less than 1.50R remaining room is not executed.

Everything else is unchanged:

- signal identities and timestamps;
- family assignment;
- continuation, range and repair routing;
- entry, stop, target and deadline;
- spread, slippage, costs, latency and position size;
- one-trade-per-day policy;
- structural management and runner logic before the removed overlay;
- original contextual exclusions and no-signal days.

Do not use the semantic compiler to replace the working Router V1 geometry in
this correction. Do not retune the 1.50R threshold, add filters, alter losses,
or test another variant.

## Reproduction and interpretation

Run two deterministic calculations over the sealed Router V1 rows in opposite
iteration orders, restore frozen chronological order, and require identical
row payloads and checksums. Report every retained and rejected routed trade,
monthly and combined performance, the exact contribution of each correction,
and preserve zero validation credit.

Passing proves only that the intended working implementation is reproducible on
the already exposed regression. It neither validates nor rejects the strategy.

