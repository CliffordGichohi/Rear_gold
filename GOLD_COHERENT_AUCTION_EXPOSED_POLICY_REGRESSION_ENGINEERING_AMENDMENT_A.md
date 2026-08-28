# Gold Coherent-Auction Exposed-Policy Regression — Engineering Amendment A

Status: `FROZEN_AFTER_HASH_ONLY_REPRODUCTION_FAILURE_BEFORE_FIELD_DIAGNOSIS`

The first regression attempt stopped before writing results because the primary and reference payload hashes differed. No fresh validation case, 2025 value, or 2026 value was opened.

This amendment permits one value-blind implementation diagnosis:

- compare primary and reference payloads only by case alias, JSON field path, type, and equality;
- do not print economic or market values during diagnosis;
- classify each mismatch as output-shape, timestamp-boundary, structural-metadata, event-order, or unresolved;
- correct only a deterministic reproduction defect that leaves every frozen policy definition unchanged;
- preserve the original pre-run freeze and failed attempt record;
- create a new amended implementation freeze before rerunning the exposed regression;
- permit one amended reproduction attempt.

No threshold, split, swing rule, stop, target, population, cost, or interpretation may change.

