# Gold Exposed Bidirectional Auction-Capacity Engineering Amendment A

Status: `PASS_VALUE_BLIND_SCHEMA_CORRECTION`

The first capacity run stopped before result aggregation because one valid
accepted-breakout payload used `identity` while the auction compiler required
`row_identity`.

The correction changes identity normalization only:

1. use `row_identity` when present;
2. otherwise use `identity` when present;
3. otherwise derive a deterministic hash from the accepted-breakout metadata
   and direction.

The correction cannot change timestamps, prices, direction, admission,
invalidation, destination, execution, or outcome. Seven focused compiler tests
passed, including both schema generations and deterministic fallback.

Per-date primary and reference checkpoints were added after the correction.
All 95 dates and 190 session units reproduced exactly before the final result
was reported.
