# Gold Matched Human Same-Timeframe Target Diagnostic V1 Report

## Verdict

The hypothesis is partly correct. The original study mixed lower-timeframe entry evidence with higher-timeframe targets:

- all 16 trades used M15 transition/invalidation logic;
- seven explicitly mentioned an M5 trigger;
- all 16 targets were registered on H1;
- fifteen targets were labelled H1 external liquidity.

A nearer M15 reference frequently traded before the original stop, but a complete exit at the nearest M15 swing did not materially improve economics. The stronger finding is that the M15 swing should have been an execution and management checkpoint, while many entries occurred after that local objective had already been reached.

## Frozen descriptive comparison

The diagnostic kept direction, decision time, actual fill, original stop and day deadline unchanged. It replaced only the target with the nearest uniquely confirmed M15 swing high above the intended entry. A target was constructed only from candles available at the decision. Quantity was recalculated from the actual fill to remove the already diagnosed stale-size failure and retain a $50 maximum risk.

| Target treatment | Target first | Positive after costs | Net R | Expectancy | Profit factor | Median target distance |
|---|---:|---:|---:|---:|---:|---:|
| Original H1 target control with actual-fill sizing | 5/16 | 8/16 | +5.051R | +0.316R | 1.719 | 2.538R |
| Nearest confirmed M15 swing high | 9/16 | 7/16 | +0.049R | +0.003R | 1.038 | 0.251R |
| Recorded trigger timeframe (M5 where explicitly recorded, otherwise M15) | 8/16 | 6/16 | -0.266R | -0.017R | 0.797 | 0.214R |

For the M15 target, ten cases retained valid target geometry after the one-minute fill. Nine of those ten reached the M15 target before the original stop. Six other trades filled at or beyond the nearest M15 target, so that local objective was already behind the executable entry. Two target-first cases had so little remaining room that the gross target did not cover the recorded costs.

## Correct-direction stop cases

| Case | Original result | M15 target distance | M15 result | Interpretation |
|---|---:|---:|---:|---|
| CBR-2022-005 | -1.062R | -0.052R after fill | Target geometry invalid | The nearest M15 objective had already been reached before executable entry. This was late relative to the local auction. |
| CBR-2022-013 | -0.814R after +1.858R MFE | +0.445R | +0.406R target-first | The M15 objective would have converted the correct bias into a small win before the later stop. |
| CBR-2022-014 | -1.004R after +2.029R MFE | +0.277R | +0.225R target-first | The M15 objective would also have produced a small win before the later stop. |

Thus two of the three correct-direction stop losses become small target-first wins under the frozen M15 proxy. The third exposes late entry rather than an excessively distant target alone.

## Why a full M15 exit is not the answer

The same closer target would have severely truncated the profitable trades:

- CBR-2022-020: actual +0.376R versus approximately +0.040R at the M15 reference.
- CBR-2022-027: actual +2.518R versus a target only +0.005R from the fill and slightly negative after cost.
- CBR-2022-030: actual +1.693R versus approximately +0.077R at the M15 reference.

The nearest M15 swing therefore improves first-passage hit rate but sacrifices payoff. It is better interpreted as the first opposing decision area, not an automatic full-position take-profit.

## Main finding

The data support a hierarchical target-management hypothesis:

1. H4/H1 defines directional context and the farther destination.
2. M5/M15 defines entry and the first opposing decision area.
3. A trade should not be chased when the first lower-timeframe objective is already reached or leaves insufficient room after spread and latency.
4. At the M15 decision area, observe acceptance, rejection or absorption as defined by the Reference Book.
5. Rejection can justify realization or protection; sustained acceptance can justify retaining a runner toward H1 liquidity.

No partial-realization percentage, break-even threshold or runner rule is authorized by this exposed diagnostic. Those mechanics require a separately frozen prospective comparison. The result does show why using H1 as the only target caused correct lower-timeframe reads to round-trip, while exiting everything at the nearest M15 swing would destroy the large winners.

## Evidence status and reproduction

- `POST_RESULT_ZERO_CREDIT_DESCRIPTIVE`
- Result SHA-256 remained identical across two complete runs: `14CB46651190E64E10EEA8D615E1FF1EEBC6B0B7FE2487BD9A49B1847C4F583A`.
- Python compilation passed.
- Calendar 2025 and 2026 remained untouched.

Artifacts:

- `research_artifacts/gold_same_timeframe_target_v1/same_timeframe_target_diagnostic.json`
- `research_artifacts/gold_same_timeframe_target_v1/same_timeframe_target_cases.csv`
- `tools/analyze_gold_same_timeframe_target_v1.py`
