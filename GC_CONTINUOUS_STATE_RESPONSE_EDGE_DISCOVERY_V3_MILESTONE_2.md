# GC Continuous State-Response Edge Discovery V3 — Milestone 2

Protocol version: `GC_CSR_EDGE_DISCOVERY_V3_M2_PROTOCOL_V1_0`

## Mandate

Milestone 2 materializes the frozen continuous predictor matrix without opening or constructing any outcome. It preserves the V3 Milestone 1 contract, feature registry, model registry, traceability catalog, power interpretation, predecessor verdicts, and all forward locks.

The study population remains 187 London sessions and 187 New York sessions from 2021-11-08 through 2024-12-13. Each available session has exactly 16 fixed anchors at local session-open plus `0, 15, ..., 225` minutes, for 2,992 anchors per session and 5,984 total.

## Permitted inputs

Only these already sealed sources may be opened:

- the V2-R1 primary and reference London/New York one-second GC feature payloads;
- the sealed outcome-blind Step 5C decision-context projection;
- the sealed Gold Casebook XAUUSD one-minute source, stopping before the first 2025 record;
- the frozen trigger row registry and V3 Milestone 1 registries/seals.

No acquisition, provider request, or charge is permitted.

## Streaming and resource policy

- Primary and reference passes run sequentially in separate child processes.
- XAUUSD records are consumed chronologically and a session is finalized before a later bar is admitted to that session's feature calculation.
- Exactly one session-date payload is calculated and written at a time; its GC table, context record, price slice, and calculated anchors are released immediately.
- One-second GC rows are allocated in the frozen row-registry order, never by price or outcome.
- Parquet writes use one append-only 16-row group per session date.
- Formal maximum observed resident memory is 4 GiB; the parent terminates a child at the frozen 3.75 GiB guard.

## Anchor and point-in-time policy

- `decision_at` is the IANA-timezone session open plus the frozen offset.
- A one-second bucket is eligible only when `bucket_end <= decision_at`; W60 is `(decision_at-60s, decision_at]` and W900 is `(decision_at-900s, decision_at]`.
- A one-minute XAUUSD bar is eligible only when complete, exactly one minute, and both `close_time` and `available_at` are no later than `decision_at`.
- UTC epoch-aligned 15-minute and one-hour aggregates are complete only when every expected constituent minute is present.
- `UNKNOWN` and `UNAVAILABLE_TECHNICAL` remain null and are never converted to zero or neutral.
- No later session record, later anchor, later vintage, 2025 record, or 2026 record may enter an earlier anchor.

## Frozen predictor mechanics

The twelve predictor IDs and their business formulas remain exactly those sealed in Milestone 1. Milestone 2 freezes only implementation detail required to make those formulas deterministic:

- valid book state means continuous matching, state available, two-sided, unlocked, uncrossed, and all required fields non-null;
- quote OFI and depth W60 require at least 57 valid terminal states;
- spread W60/W900 requires at least 57/855 valid terminal states;
- GC tick for spread fragility is exactly USD 0.10, or `100000000` in the sealed fixed-1e9 representation;
- the T0 microprice feature uses the terminal one-second state ending exactly at the anchor and never searches backward through an active technical latch;
- 15-minute momentum uses the latest complete UTC-aligned 15-minute close and the close exactly four contiguous 15-minute buckets earlier;
- one-hour ATR is the arithmetic mean of the latest 14 true ranges using the preceding complete hour close, consistent with the deterministic structure engine; fully absent closed-market hours may be skipped, but a partially populated hour in the required span makes the feature technical-unavailable;
- macro score and macro/cross-market changes use the latest sealed point-in-time session snapshot while it remains the latest available state; no intraday macro snapshot is fabricated;
- real-yield support is negative percentage-point change, two-year support is negative change converted to basis points, and USD support is `-10000*log(current/previous)`;
- session-level tension uses the completed Asia range, current point-in-time one-hour ATR, current complete XAUUSD minute close, and nearest session-open-known level.

## Output and lineage

Each session payload contains only anchor identity, block identity, decision timestamp, the twelve nullable float64 predictor values, and for every predictor an availability classification, maximum input-availability timestamp, and row-level lineage hash. There are no outcome, return, direction, hit-rate, candidate, signal, execution, trade, or PnL columns.

Primary and reference outputs must have identical schemas, row identities, null classifications, values, per-column semantic checksums, complete-row checksums, diagnostics, and byte-identical Parquet files.

## Outcome-blind support audit

Milestone 2 reports, separately for London and New York:

- completeness, known dates and blocks;
- positive- and negative-value date support;
- validation-fold dates and anchors;
- required-year out-of-fold date support;
- every Stage-1 support gate;
- every Stage-2 joint-coverage and frozen interaction-sign support gate.

A support failure is recorded and does not permit feature replacement, repair, threshold changes, or removal from the registered test family. Support statistics contain predictors only and are not relationship statistics.

## PASS/FAIL rule

`PASS_V3_M2_OUTCOME_BLIND_PREDICTOR_MATERIALIZATION` requires all predecessor/source seals, 5,984 unique fixed anchors, exact DST and source allocation, point-in-time and no-forward-access gates, the 4 GiB resource gate, complete lineage, primary/reference equality, byte-identical outputs, reproducible support diagnostics, and a sealed manifest. Predictor support failures are honest dispositions, not technical failures.

Any seal, population, source allocation, point-in-time, resource, equality, schema, or reproduction failure records a formal Milestone 2 failure and stops before outcome access.

## Prohibitions

Milestone 2 may not open or construct development outcomes, inspect 2025/2026, calculate any predictor-outcome relationship, create or rank candidates, optimize execution, or calculate trades, PnL, R multiples, or returns.
