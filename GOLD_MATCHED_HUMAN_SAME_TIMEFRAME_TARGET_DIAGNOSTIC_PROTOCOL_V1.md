# Gold Matched Human Same-Timeframe Target Diagnostic Protocol V1

## Status

This is a post-result descriptive diagnostic over the already exposed 30-case matched-human replay. It receives zero research or validation credit, changes no sealed decision or result, and cannot establish an edge. Calendar 2025 and 2026 remain untouched.

## Question

Did the human operator combine M5/M15 entry evidence with materially more distant H1 targets, and would point-in-time targets taken from the same lower timeframe have changed first-passage and economic outcomes while leaving direction, entry and stop unchanged?

## Frozen population and source policy

- Use all 16 human trades in `matched_case_comparison.json`; retain every loss and technical failure.
- Use each case's sealed primary private replay stream, falling back only to its sealed recovery-A primary stream where the original path is absent.
- Use only completed bars with `available_at <= submitted_at` when constructing a target.
- Use sealed post-fill M1 paths only after target construction.
- Keep the original action, intended entry, actual fill, stop, deadline and same-bar stop-first convention unchanged.

## Frozen target definitions

All trades were LONG. An opposing swing target is therefore a previously confirmed swing high above the intended entry.

1. `ORIGINAL_H1_TARGET_CONTROL`: the operator's recorded target.
2. `M15_NEAREST_CONFIRMED_SWING_HIGH`: the lowest-price confirmed M15 swing high strictly above the intended entry. A swing is confirmed only when its high is the unique maximum of itself, the two completed candles before it and the two completed candles after it. The confirming candles must be available by the decision timestamp.
3. `RECORDED_TRIGGER_TF_NEAREST_CONFIRMED_SWING_HIGH`: use M5 only when the already sealed `m15_transition` text explicitly mentions `m5`; otherwise use M15. Apply the identical two-candle confirmation and nearest-above-entry rule.

Do not choose a farther swing when the nearest swing loses, remove a target because its reward is small, or select between M15 and the recorded-trigger-timeframe result using outcomes.

## Frozen execution comparison

- Start path evaluation at the original `fill_at`.
- If the selected target is not strictly above the actual fill, classify it `POST_FILL_TARGET_GEOMETRY_INVALID`.
- Otherwise record `TARGET_FIRST`, `STOP_FIRST` or `TIME_EXIT`; a bar touching both is `STOP_FIRST`.
- To isolate target geometry from the already diagnosed stale-size risk-cap failure, calculate diagnostic quantity as `floor($50 / (actual fill - original stop))` whole ounces.
- Reuse each trade's recorded base cost per ounce conservatively for the diagnostic exit.
- Report target distance in effective R, target-first rate, positive-result rate, net R50, profit factor and case-level differences.
- Separately report the five original `POST_FILL_GEOMETRY_INVALID` trades so target effects are not confused with the known sizing defect.

## Interpretation limits

- A closer target can raise hit rate while reducing payoff; win rate alone is not an edge.
- The nearest confirmed swing is a reproducible proxy for the operator's phrase "same-timeframe swing," not proof that resting liquidity existed there.
- Results may generate a prospective hypothesis only. Any target policy must later be frozen and evaluated on fresh cases.
