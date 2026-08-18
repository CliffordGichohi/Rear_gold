# Gold Pullback Monetizability Gap Decomposition Contract V1

Status: **FROZEN BEFORE DECOMPOSITION RESULTS**

## Purpose

Explain, without creating another candidate, where the previously measured visual-pivot oracle value ceases to be monetizable under the six already-frozen entry models.

This is a diagnostic decomposition. It cannot rehabilitate a rejected strategy, receive validation credit, or authorize live trading.

## Preserved evidence and period

- Preserve every predecessor result, rejection, source, artifact, and seal.
- Use only sealed 2021-08-01 through 2024-12-31 development artifacts.
- Do not read or use 2025 or 2026 sources, values, outcomes, or forward results.
- Acquire no data and incur no charge.
- Retain the six entry models, checkpoints, structural stops, targets, time exits, costs, overlap policy, router, classifier, and risk tiers unchanged.

## Populations

Two views are required and must never be conflated:

1. **Formation-aware:** all 8,653 pullbacks crossed with all six frozen models (51,918 rows). A model that cannot form a valid executable checkpoint receives zero value from Stage 2 onward. This view attributes lost opportunity to trigger/checkpoint availability as well as later execution.
2. **Executed-only:** only rows for which the frozen model produced a valid trade. This view removes trigger absence and isolates checkpoint timing, stop feasibility, exit rules, and costs.

The variable-risk Stage 7 comparison is restricted to the frozen corrected out-of-fold population because no honest router prediction exists outside it. The full-development and out-of-fold populations must be reported separately.

Technical-unavailability rows remain present as `UNAVAILABLE_TECHNICAL`; they may not be silently deleted or relabelled.

## Common conventions

- Primary fixed-risk ledger: $50 per 1R, no compounding.
- `normalized_pnl_usd = 50 * stage_r` for Stages 1 through 6. This holds risk constant and prevents whole-ounce rounding from obscuring attribution.
- Existing whole-ounce PnL is retained as a separate diagnostic, not substituted for normalized PnL.
- The entry-model structural risk unit is `abs(entry - stop)` for Stages 2 through 6.
- Stage 1 deliberately retains the original atlas convention of one case ATR as 1R. Consequently the Stage 1-to-Stage 2 transition contains confirmation timing, entry location, trade-direction, and risk-denominator effects; those components cannot be causally separated by this artifact set and must be stated as a limitation.
- Missing/unformed trades contribute zero from Stage 2 onward in the formation-aware view; they are absent from active-trade denominators.
- All price-path intervals are exact `[entry minute open, frozen parent-bar deadline)` intervals.
- A same-minute stop and favourable-extreme event is stop-first.

## Frozen waterfall

### Stage 1 — `VISUAL_PIVOT_ORACLE`

Use the existing sealed `oracle_r` unchanged: complete visual-pivot-to-maximum movement for `CONTINUED`, exactly -1R for `FAILED_STRUCTURE_SWITCH`.

### Stage 2 — `CHECKPOINT_MFE_CEILING`

For each executable model row, start at its frozen M1 entry checkpoint and scan through that model's unchanged parent-bar time deadline. Measure maximum favourable excursion in the model's actual trade direction divided by its structural stop distance. Ignore stop, target, costs, and overlap. Unformed/non-executable rows equal zero.

### Stage 3 — `STOP_FEASIBLE_MFE_CEILING`

Use the identical Stage 2 path. Find the first structural-stop hit and the first minute attaining the Stage 2 global favourable maximum. If the stop occurs before or in the same minute as that maximum, return the frozen gap-aware stop loss in R. Otherwise return Stage 2 MFE. This is still an oracle exit ceiling; it only asks whether the Stage 2 maximum survived the structural stop.

### Stage 4 — `FROZEN_EXIT_GROSS`

Use the already-frozen gross R from the model's actual entry, structural stop, fixed target, time exit, stop-first ambiguity rule, spread-independent price path, and unchanged latency assumption.

### Stage 5 — `FROZEN_EXIT_NET_COSTS`

Use frozen net R after observed/fallback spread, $0.07/oz commission, and $0.10/oz slippage. Report 1.5x and 2x cost diagnostics without changing the primary stage.

### Stage 6 — `NON_OVERLAPPING_FIXED_RISK`

Apply one open XAUUSD position and one decision per timestamp. Sort candidates by entry timestamp, frozen model priority, H4/H1/M15 timeframe priority, and pullback identity. Accepted rows retain Stage 5 R; skipped rows equal zero. Reproduce the existing out-of-fold equal-risk decisions exactly.

### Stage 7 — `FROZEN_VARIABLE_RISK_ROUTER`

Use only existing corrected out-of-fold predictions and the unchanged $0/$25/$50/$75/$100 risk tiers. Use existing accepted variable-risk decision PnL exactly; nonselected rows equal zero. Report actual dollars and $50-equivalent R separately. Do not compare its raw trade count or dollar total with the unmatched full-development population.

## Required cells and statistics

Produce every available `timeframe × model × realised_archetype` cell, plus timeframe and total aggregates. For every stage report:

- opportunity rows and active rows;
- positive, negative, and zero counts;
- win rate among active rows;
- total and mean R per opportunity;
- mean R per active row;
- normalized dollars at $50 risk;
- profit factor;
- average MFE and MAE where an entry exists;
- gross-positive capture and net-value retention versus Stage 1;
- exact incremental R and dollar change from the preceding stage.

Report the complete fixed-order waterfall and an explicit zero residual check. The attribution is an accounting bridge, not a causal or order-invariant Shapley decomposition. Interactions between checkpoint availability, stop survival, exit timing, costs, overlap, selection, and sizing remain assigned to the stage order above.

## Dominant bottleneck and next direction

For each timeframe, identify the largest negative fixed-risk transition in both formation-aware and executed-only views. Stage 7 is reported separately because it changes both selection and risk scale.

Recommend exactly one bounded subsequent research direction, determined mechanically by the dominant executed-only bottleneck across timeframes:

- Stage 1→2: earlier point-in-time checkpoint/location research;
- Stage 2→3: structural-stop geometry research;
- Stage 3→4: exit/capture research using transparent structural or trailing exits;
- Stage 4→5: transaction-cost/turnover reduction;
- Stage 5→6: signal-priority/concurrency research;
- Stage 6→7: routing/calibration research.

Do not implement the recommendation in this contract.

## Integrity and stopping rules

- Verify every predecessor seal and source hash before calculations.
- Freeze a machine-readable protocol and source manifest before aggregate results.
- Run independent primary and reference path calculations.
- Require identical row identities, stages, metrics, checksums, and byte-identical paired Parquet payloads.
- Record all negative results honestly.
- Stop after documentation and sealing.

