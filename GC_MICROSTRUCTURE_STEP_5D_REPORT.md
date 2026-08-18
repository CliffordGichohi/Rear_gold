# GC Microstructure Step 5D — Development Conditional-Edge Discovery

## Formal verdict

`FAIL_STEP_5D_OUTCOME_JOIN_COVERAGE`

## What happened

The pre-result protocol, all 148 tests, seeds, support rules, statistical gates, stability gates, ranking order, and implementation were sealed before outcome access. The metadata-only preflight passed.

The sealed development case source was then streamed exactly once. It contained 358 of the 374 required non-holiday selected session outcomes. Sixteen required London/New York outcome keys were absent. The frozen missing-data policy permitted only the two predeclared 2022-04-15 Good Friday UNKNOWN rows, so the one-to-one outcome-join integrity gate failed.

## Research disposition

- Stage 1 tests executed: `0/24`.
- Stage 2 tests executed: `0/124`.
- Candidates created: `0`.
- This is **not** a scientific zero-candidate result and says nothing about whether the registered conditions have an edge.
- No missing date was silently dropped, backfilled, relabelled, or substituted.

## Scope boundary

Calendar 2025 and every 2026 value remained locked. No execution, trade, PnL, R multiple, or account return was calculated. No data was acquired and no charge was incurred.

Step 5D is sealed as a formal integrity failure and stops here. A separate metadata-only coverage diagnostic is required before any new research attempt.
