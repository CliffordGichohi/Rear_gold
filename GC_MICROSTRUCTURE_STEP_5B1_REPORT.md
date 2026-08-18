# GC Microstructure Step 5B.1 — Metadata-Only Source Diagnostic

## Formal diagnostic verdict

`PASS_STEP_5B1_DIAGNOSTIC_REPRODUCTION`

The original Step 5B verdict remains `FAIL_STEP_5B_BUDGET_C_SOURCE_INTEGRITY` and was not changed.

## Reproduced technical scope

- Failed requests examined: 13.
- Technical source rows scanned by each implementation: 144,352,215.
- Receive-before-event occurrences: 719,524.
- Old snapshot-only BAD_TS_RECV violations: 174.
- Incomplete prediction windows: 4.
- Independent outputs identical: `true`.

## Request classifications

- `DOCUMENTED_VALID_SEMANTICS` (11): `Q007:mbo`, `Q008:mbp-10`, `Q035:mbo`, `Q037:mbo`, `Q039:mbo`, `Q041:mbo`, `Q043:mbo`, `Q045:mbo`, `Q063:mbo`, `Q077:mbo`, `Q083:mbo`
- `EXPECTED_CALENDAR_UNAVAILABILITY` (2): `Q017:mbo`, `Q018:mbp-10`
- `GENUINE_SOURCE_FAILURE` (0): none
- `UNRESOLVED` (0): none

## Recommendation

`TIMESTAMP_FLAG_AND_OFFICIAL_HOLIDAY_DISPOSITION_V0_1`

In a separately authorized recertification only: accept structurally valid F_BAD_TS_RECV live rows under the general provider flag semantics; accept structurally valid unflagged ts_recv-before-ts_event rows only when negative, unclamped ts_in_delta yields publisher send time at/after event time; and mark the four 2022-04-15 London/New York windows unavailable under the official Good Friday calendar. Keep every other Step 5B source, feature definition, and integrity gate unchanged.

The recommendation was not implemented.

## Restrictions honored

No source was filtered, repaired, relabeled, replaced, or reacquired. No charge was incurred. No price, depth, size, order-flow value, outcome, feature, relationship, signal, execution, trade, PnL, R multiple, or account return was inspected or calculated.

Step 5B.1 stops here.
