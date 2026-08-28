# Gold Matched Human Same-Timeframe Joint Geometry — Amendment A

## Reason for amendment

The V1 target-only diagnostic held the original stop fixed while replacing the H1 target with a nearer lower-timeframe swing. That answered a narrow first-passage question but did not answer the operator's actual hypothesis because reward-to-risk is jointly determined by stop and target geometry.

The target-only result remains unchanged and is explicitly classified `INCOMPLETE_FOR_JOINT_R_GEOMETRY`.

## Evidence status

This remains an exposed, post-result, zero-credit descriptive diagnostic. It cannot validate a strategy or authorize a prospective rule. Calendar 2025 and 2026 remain untouched.

## Frozen joint geometry

For every LONG decision, construct geometry only from completed candles available at `submitted_at`.

### M15 track

- Entry: unchanged intended entry and unchanged actual fill.
- Stop reference: the most recently confirmed M15 swing low before the decision. A swing low is the unique minimum of itself, the two completed candles before it and the two completed candles after it.
- Structural-integrity gate: the most recent confirmed swing low must be strictly below the intended entry and actual fill. Do not skip it in favour of an older lower swing.
- Target reference: the nearest-price confirmed M15 swing high strictly above the intended entry.
- Executability gate: after the original one-minute fill, require `stop < fill < target`.

### Recorded-trigger-timeframe track

- Use M5 only where the sealed `m15_transition` text explicitly mentions `m5`; otherwise use M15.
- Apply the identical swing confirmation, latest-low stop, nearest-higher target and executability gates.

## Execution and metrics

- Trigger the stop at the selected swing low; do not add an outcome-fitted buffer.
- Start path evaluation at the original `fill_at` and use stop-first treatment when stop and target occur in the same M1 bar.
- Recalculate whole-ounce quantity as `floor($50 / (actual fill - reconstructed stop))`.
- Reuse the recorded per-ounce cost and retain the original day deadline.
- Report valid geometry, structural-integrity failures, target/stop R distances, planned reward-to-risk, target-first/stop-first/time-exit counts, win rate after costs, net R, expectancy and profit factor.
- Report every original profitable, direction-right-not-monetized and direction-wrong case separately.
- Do not impose or tune a minimum R:R after observing results. Report R:R bins descriptively only.

## Interpretation boundary

The confirmed two-sided swing is a reproducible proxy for the operator's structural level. It is not proof of resting liquidity. The result can show whether coherent same-timeframe stop/target geometry differed from the mixed M15-entry/H1-target geometry; it cannot prove the chosen swing definition is the operator's final discretionary model.
