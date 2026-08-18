# GC Session Trigger Edge Discovery Contract V2

Status: `PRE_DEVELOPMENT_STREAMING_RECERTIFICATION_CONTRACT`

## Purpose

V2 exists solely to complete the outcome-blind technical certification that V1 Milestone 2-R2 could not finish because Linux killed the memory-heavy process under global out-of-memory pressure. The V1 failure remains valid and permanently closed. V2 receives no research or validation credit from V1's partial temporary outputs.

This milestone may establish that the frozen technical inputs, features, event identities, and support counts are reproducible and eligible for later relationship discovery. It cannot establish an edge because development outcomes remain hidden and unjoined.

## Preserved history

- V1 Milestone 2: `FAIL_FULL_SESSION_TIMESTAMP_COVERAGE`.
- V1 Milestone 2-R1: `FAIL_DIAGNOSTIC_REPRODUCTION`.
- V1 Milestone 2-R1-A1: `PASS_M2_R1_A1_REFERENCE_REPRODUCTION`.
- V1 Milestone 2-R2: `FAIL_M2_R2_EXECUTION_BRANCH_TERMINATED` after the sole process was killed by the Linux OOM killer.
- The fifteen terminal continuous-matching crossed MBP-10 bucket-close findings remain `GENUINE_SOURCE_OR_STATE_FAILURE`.
- The three missing XAUUSD timestamps remain `UNRESOLVED`.
- Every earlier artifact, hash, receipt, status, and classification remains unchanged.

## Data and time boundary

- Use only the existing sealed 188-date sample from 8 November 2021 through 13 December 2024.
- The frozen registry contains 376 session rows: 374 expected-available sessions and two documented unavailable Good Friday sessions.
- Calendar 2025 and calendar 2026 remain locked.
- Development outcomes remain hidden and unjoined.
- No data acquisition, provider substitution, filtering, repair, imputation, relabelling, or charge is permitted.

## Frozen analytical definitions

V2 retains without modification:

- the 85 one-second GC microstructure features;
- the eight registered derived microstructure states;
- all point-in-time fundamental, price-level, and session contexts;
- the six event families and their direction semantics;
- all XAUUSD and GC timestamp-authority rules;
- the corrected nanosecond reference reader;
- all event-support floors;
- the universal V1 Milestone 2-R2 technical-unavailability policy;
- the requirement that no invalid state may contribute to an eligible microstructure event.

No threshold, feature, context, event definition, support rule, or market classification may be added, removed, inverted, repaired, or retuned.

## Permitted orchestration changes

V2 may change only resource-safe orchestration and persistence:

1. Each session feature pass executes in an isolated child process.
2. Primary completes and exits before reference starts.
3. Each child writes one immutable 18,900-row Parquet feature fragment and one packed technical-unavailability mask.
4. Minute contexts and event identities are materialized separately from the sealed feature fragments.
5. Final datasets are assembled by streaming one committed fragment at a time.
6. Incomplete temporary files are never research inputs. They may only be quarantined with their hashes before the same uncommitted pass is restarted.

## Resource policy

- Formal RSS cap: `4,294,967,296` bytes (4 GiB) for every parent or child process.
- Child guard threshold: `4,026,531,840` bytes (3.75 GiB).
- RSS sampling interval: no more than 50 milliseconds while a child is alive.
- A guard breach terminates the child and formally fails V2; it cannot be silently retried.
- Every worker and orchestration high-water mark must be recorded.

## Append-only checkpoint policy

- V2 permits one logical full-development materialization attempt.
- Every invocation is recorded in a new immutable invocation record.
- A primary or reference pass becomes reusable only after its immutable pass checkpoint binds its source identities, feature fragment, unavailable-mask fragment, diagnostics, and resource record.
- A session becomes committed only after both passes reproduce exactly and its feature, decision, event, missingness, and technical checks are bound in an immutable session commit.
- A resumed invocation must verify and skip every committed session byte-for-byte.
- A resumed invocation may restart only an uncommitted pass. It may not modify a committed artifact, definition, threshold, or source.
- Resume permission addresses power, transport, or operating-system interruption only; it does not permit retuning after observing technical results.

## Engineering gate

Before any development metadata is reopened, the frozen implementation must process the six permanently engineering-only dates—2024-01-05, 2024-01-09, 2024-01-11, 2024-01-30, 2024-01-31, and 2024-03-20—using London and New York session windows.

For all twelve windows:

- primary and reference source identities must match;
- primary and reference feature rows, schemas, null classifications, per-column checksums, complete-row checksums, masks, and diagnostics must match;
- the result must equal the corresponding slice of the already sealed Step 4A.3 or Step 4B.3 engineering payload;
- checkpoint verification and no-op resume verification must pass;
- every observed RSS high-water mark must remain below 4 GiB.

Only an engineering PASS permits the implementation and protocol to be sealed and development metadata to be reopened.

## Full-development PASS gates

- Every predecessor, protocol, implementation, source, and checkpoint binding is valid.
- Exactly 374 available sessions are committed; two remain documented unavailable.
- Exactly 7,068,600 one-second feature rows and 89,760 minute-context rows are produced per implementation.
- The original fifteen terminal crossed states and three unresolved XAUUSD timestamps are preserved.
- Universal technical-unavailability disposition leaves no invalid book state in an eligible event.
- Primary and reference row identities, source identities, missingness, schemas, null counts, feature checksums, decision rows, event identities, support counts, and diagnostics reproduce exactly.
- All twelve frozen session/event-family Stage-1 support tests remain support eligible.
- Every process remains below the 4-GiB RSS cap.
- No prohibited work occurs.

## Prohibited work

Do not open or construct development outcomes, calculate directional relationships, hit rates, effects, candidates, signals, execution rules, trades, PnL, R multiples, or returns. Do not inspect 2025 or 2026. Do not acquire data or incur a charge.

## Disposition

- `PASS`: seal V2 and stop. Relationship discovery requires separate authorization.
- `FAIL`: seal the honest reason and stop. No automatic repair, retuning, or research inference is permitted.

