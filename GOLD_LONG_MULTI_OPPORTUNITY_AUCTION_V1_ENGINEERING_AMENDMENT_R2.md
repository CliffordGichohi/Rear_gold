# Gold LONG Multi-Opportunity Auction V1 — Engineering Amendment R2

Amendment R1 stopped formally after primary checkpoint 81 on `CAM-2022-052`. The sealed and rebuilt records had identical signal, direction, admission, room-gate side, quantities, lifecycle resolution and trade event. Their numeric differences were limited to floating-point reconstruction propagation: one representable price step (`2.2737367544323206e-13`), approximately `2.28e-12` dollars and `4.55e-14R`, plus hashes derived from those representations.

R2 replaces only the predecessor-reproduction comparison with a recursive numeric equivalence gate using `rel_tol=1e-13` and `abs_tol=1e-12`. Booleans, integers, strings, nulls, dictionary keys, list lengths, timestamps, identities, admission, direction, quantities, dispositions and resolutions remain exact. Both target-room values must remain on the same side of the frozen 1.5R gate. Only `source_lifecycle_sha256`, `correction_sha256`, and `effective_result.result_hash` may differ as explicitly derived hashes; all other hashes remain exact.

No checkpoint is rewritten. Both prior failures, Amendment R1, all 81 valid primary checkpoints, models, thresholds, research definitions, execution and outcomes remain preserved. Any mismatch outside this comparator is a formal failure.
