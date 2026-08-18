# GC Session Trigger Edge Discovery Contract V2-R1

Status: `FROZEN_SCOPE_BEFORE_EXTERNAL_MEMORY_IMPLEMENTATION_PROOF`

## Purpose and predecessor disposition

V2-R1 is a narrow, outcome-blind resource-correction branch. It preserves the sealed V2 verdict `FAIL_GC_SESSION_TRIGGER_EDGE_V2_EXECUTION`, its 293 immutable session commits, its independently verified final-seal receipt `0f64374ad742ce60d00d0c381f3034b5170e028fc37391a44ad96e4d7c5831d3`, and every earlier verdict and artifact. V2 remains permanently terminated and is never overwritten, reopened, or represented as a pass.

V2-R1 exists only because the V2 primary worker for `TRIGGER_M2:2024-04-12:NEW_YORK` reached 4,120,739,840 bytes RSS and triggered the frozen 3.75-GiB safety guard before the 4-GiB hard cap. This was an infrastructure failure. No development outcome was opened, no relationship was calculated, and it supplies no evidence for or against a gold edge.

## Unchanged analytical scope

V2-R1 changes no analytical or market rule. It inherits unchanged:

- the sealed 2021-11-08 through 2024-12-13 development registry;
- the 85 one-second feature columns and formulas;
- the eight registered derived microstructure states;
- the six event families, directions, timestamps, and canonicalization rules;
- London and New York session definitions and IANA DST conversions;
- every point-in-time macro, structure, price-level, and positioning context;
- the V2-R2 universal technical-unavailability policy;
- the three unresolved XAUUSD timestamps and fifteen terminal crossed states;
- all support floors, feature-quality gates, and primary/reference equality requirements.

Development outcomes remain hidden and unjoined. Calendar 2025 and calendar 2026 remain locked. Relationship discovery, candidates, execution, trades, PnL, R multiples, and account returns remain prohibited.

## Sole implementation correction

The full-window in-memory source representation is replaced by deterministic bounded-memory processing:

1. The primary reader scans exact `[start, end)` rows in source order with 65,536-row batches.
2. The independent reference reader scans Parquet row groups in source order with 32,768-row batches and applies the same exact interval boundary independently.
3. MBO counts and quantities are accumulated into the frozen 18,900 one-second buckets per batch; no complete-session MBO array is retained.
4. MBP-10 counts, OFI transitions, integrity counts, and terminal bucket states are updated per batch. Only the anchor, previous-row transition state, aggregate bucket arrays, and final top-ten state for each bucket may survive a batch.
5. Primary and reference implementations use their previously frozen independent accumulation semantics. Batch boundaries cannot change a feature, state, event, or output.
6. Feature output remains the exact frozen Arrow schema and is written as a bounded 18,900-row fragment. Session data is released when each child exits.
7. Primary and reference passes run sequentially. Development sessions run sequentially.
8. Technical source identities use a deterministic value-blind streaming checksum over all selected fields in original row order. It may not be used to choose, filter, repair, or interpret a row.

No threshold, field, event, state, context, row, or market classification may be added, removed, inverted, filtered, repaired, or retuned.

## Resource policy

- Formal maximum observed RSS: 4,294,967,296 bytes (4 GiB) for every monitored process.
- Child termination guard: 3,758,096,384 bytes (3.5 GiB), sampled every 0.05 seconds.
- Engineering and stress-proof qualification target: no monitored child above 2,684,354,560 bytes (2.5 GiB).
- A guard event, process failure, source mismatch, output mismatch, or reproduction mismatch is a formal failure and stops V2-R1 without another correction.

The memory guard may not be raised after source access.

## Pre-development proof

Before reopening development metadata, V2-R1 must seal its contract, protocol, and implementation and then complete one outcome-blind proof:

- reproduce London and New York on the six permanently engineering-only dates 2024-01-05, 2024-01-09, 2024-01-11, 2024-01-30, 2024-01-31, and 2024-03-20;
- require exact primary/reference equality and exact equality with the corresponding sealed engineering feature slices;
- reproduce the already opened technical `2024-04-12 London` V2 commit exactly as an adjacent-session control;
- process `2024-04-12 New York` as the outcome-blind resource stress window and require exact primary/reference feature output, missingness, policy, and technical diagnostics;
- require every proof child to remain at or below 2.5 GiB RSS.

The April 2024 windows were selected only because of the sealed resource failure and never by outcome, return, direction, event performance, or feature value. They receive no validation credit from this proof. No outcome may be constructed or joined.

## Development continuation

If and only if the proof passes:

1. Verify every file, receipt, gate, and hash behind all 293 sealed V2 session commits.
2. Seal an append-only import ledger referencing those commits without copying, modifying, or recomputing them.
3. Process only the remaining 81 available sessions using the frozen V2-R1 worker.
4. Write new append-only pass and session checkpoints after exact primary/reference reproduction.
5. Assemble the full 374-session technical dataset from the 293 sealed V2 commits and the 81 V2-R1 commits.
6. Apply every unchanged V2 technical and support gate.
7. Independently verify and seal an honest PASS or FAIL, then stop.

Operational invocation may resume an interrupted V2-R1 run only by hash-verifying and skipping immutable commits. There is one logical research-infrastructure attempt and no automatic repair.

## Pass boundary

A V2-R1 pass certifies only that the frozen technical features, contexts, event identities, and support counts are reproducible and ready for a separately authorized outcome join. It does not certify a relationship, predictive edge, trading strategy, or expected return.

## Prohibitions

V2-R1 must not:

- modify or replace any V2 artifact;
- inspect or join development outcomes;
- inspect 2025 or 2026 values;
- calculate hit rates, directional effects, candidates, trades, PnL, R multiples, or returns;
- acquire data or incur a charge;
- raise a memory limit or add a second fallback after seeing proof or development results.
