# Gold LONG Multi-Opportunity Auction V1 — Engineering Amendment R1

The original sealed runner stopped formally after primary checkpoint 30 on `CAM-2022-001`.

Read-only diagnosis established exactly three differences between the sealed predecessor lifecycle and its deterministic rebuild:

- `actual_fill_target_room_r`: `2.5842570458393075` versus `2.584257045839317` (absolute difference below `1e-12`);
- `source_lifecycle_sha256`, derived from that representation; and
- `correction_sha256`, derived from the preceding fields.

The complete `effective_result`, signal timestamp, classification, admission, room-gate disposition, execution, and economic result were exactly equal.

This amendment changes only the predecessor-reproduction equality gate. It permits an absolute difference no greater than `1e-12` in `actual_fill_target_room_r` and ignores only the two hashes derived from the differing serialized float. Every other field, including the complete effective result, must remain exactly equal. Both values must remain on the same side of the frozen 1.5R room gate.

No checkpoint is rewritten. The original stop, error, first 30 checkpoints, model, threshold, opportunity identity, execution, management, outcomes, and all research rules remain unchanged. Any other mismatch is a formal failure.
