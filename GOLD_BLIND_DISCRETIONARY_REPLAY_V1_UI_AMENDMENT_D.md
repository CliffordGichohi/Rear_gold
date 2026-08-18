# Gold Blind Discretionary Replay V1 — Pre-Label UI Amendment D

Status: `FROZEN_REPLAY_STATE_PERSISTENCE_FIX_BEFORE_IMPLEMENTATION`

Authorized on 2026-08-14 before any human decision was collected. UI Amendment C was verified with zero mismatches, zero decisions, an absent decision ledger and next case `P-001`.

## Defect

The chart component was keyed by timeframe, so changing timeframe remounted it and reset its local replay cursor. Zoom also explicitly returned the chart to the checkpoint and cleared drawings. Consequently drawing objects disappeared and the Play/Pause/Step controls vanished during ordinary replay navigation.

## Bounded correction

1. Keep one chart-workspace component mounted across timeframe changes so the active replay cursor, playing/paused state and replay controls persist.
2. Preserve drawings separately for each timeframe; returning to a timeframe restores its browser-local objects.
3. Anchor drawing points to the full chart payload index so zooming changes the visible window without moving or deleting their underlying candle anchors.
4. Zoom must preserve active replay state, playing/paused state, drawings and the unsubmitted mapped trade plan.
5. Timeframe changes must preserve active replay state and the unsubmitted mapped trade plan.
6. Explicit `Return to checkpoint`, loading the next frozen case, or deleting/clearing the position remain the only relevant user actions that reset those respective states.

The active replay remains past-only. Switching timeframe or zoom may reveal only bars already present in that timeframe's certified past-only payload and may not expose a post-checkpoint scored bar. Decisions remain disabled whenever replay is before the checkpoint. No source, case, decision, execution, evaluation or outcome rule may change.

The Amendment C predecessor remains preserved. A successor seal requires automated reproduction of replay persistence through timeframe and zoom changes, all predecessor research/data/backend hashes unchanged, zero decisions and `P-001`, a healthy deployed route, and no acquisition or charge.
