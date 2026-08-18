# Gold Blind Discretionary Replay V1 — Pre-Label UI Amendment F

Status: `FROZEN_REPLAY_ANNOTATION_PERMISSION_FIX_BEFORE_IMPLEMENTATION`

Authorized on 2026-08-14 before any human decision was collected. UI Amendment E was verified with zero decisions, an absent decision ledger, and next case `P-001`.

## Defect

The history-replay guard correctly disables decision locking before the certified case checkpoint, but it also rejects all chart clicks. This prevents the user from marking structure on candles that have already been revealed.

## Bounded correction

1. During history replay, permit only non-execution annotations: trend line, horizontal level, Fibonacci retracement, ruler, selection and deletion.
2. Clamp every new annotation anchor to an already-revealed candle. Camera blank space and unrevealed candles cannot receive an anchor.
3. Keep Long Position, Short Position, position editing, arming, execution-plan mapping and permanent decision submission disabled until the chart returns to the certified checkpoint.
4. If history replay begins while a position tool is selected, switch safely to Crosshair and clear only the unfinished draft. Preserve completed drawings and the unsubmitted checkpoint plan.
5. Preserve all replay, camera, event-marker, point-in-time, blinding, execution and append-only rules from Amendment E.

No source, population, payload, research rule, outcome, execution assumption or decision schema changes. No acquisition or charge is authorized.

