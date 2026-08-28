# Gold Matched Human Same-Timeframe Joint Geometry V1 — Report

## Verdict

The prior target-only diagnostic was incomplete because it changed the target while retaining the original stop. This report reconstructs the stop and target together from point-in-time M15 structure for all 16 sealed LONG decisions.

The joint M15 geometry increased the executable win rate to 55.56%, but it did not produce positive expectancy: nine decisions were executable, five were profitable after costs, net performance was -0.7464R, expectancy was -0.0829R per executable decision, and profit factor was 0.7054.

This is a post-result, zero-credit descriptive diagnostic. It is not a validated strategy. Calendar 2025 and 2026 remain untouched.

## Frozen reconstruction

- Entry and actual fill remain unchanged.
- Stop is the latest confirmed M15 swing low available before the decision.
- Target is the nearest confirmed M15 swing high above the intended entry.
- Geometry must still be coherent at the actual fill: `stop < fill < target`.
- A newer already-broken structural low cannot be skipped in favour of an older lower low.
- Position size is recalculated at the actual fill to maintain at most $50 planned risk using whole ounces.
- Recorded costs, the original deadline, and stop-first same-bar treatment remain unchanged.
- The swing detector is the frozen five-candle confirmed-fractal proxy; it is reproducible but is not proof of resting liquidity or necessarily the operator's final discretionary swing definition.

## Aggregate results

| Measure | M15 joint stop/target | Recorded trigger-timeframe joint stop/target |
|---|---:|---:|
| Original decisions | 16 | 16 |
| Executable geometry | 9 | 8 |
| Technical/structural no-trades | 7 | 8 |
| Target first | 7 | 6 |
| Stop first | 2 | 2 |
| Profitable after costs | 5 | 4 |
| Win rate among executable decisions | 55.56% | 50.00% |
| Median planned reward/risk | 0.3882R | 0.3882R |
| Net performance | -0.7464R | -1.3176R |
| Expectancy per executable decision | -0.0829R | -0.1647R |
| Profit factor | 0.7054 | 0.4799 |

The M15 reconstruction is the stronger of the two descriptive tracks. Its five profitable outcomes were still outweighed by two complete stop losses because most available targets were small relative to their structural stops.

## Reward/risk distribution for executable M15 geometry

| Planned reward/risk | Support | Target first | Positive after costs | Net R |
|---|---:|---:|---:|---:|
| Below 0.5R | 5 | 4 | 2 | -0.5246R |
| 0.5R to below 1R | 3 | 3 | 3 | +1.3490R |
| 1R to below 2R | 0 | 0 | 0 | 0.0000R |
| 2R or more | 1 | 0 | 0 | -1.5708R |

No minimum reward/risk filter was selected from these exposed results. The bins are descriptive only.

## What the case review shows

Seven of the sixteen original entries did not have coherent M15 swing-to-swing geometry at execution:

- Five had already reached or passed the nearest confirmed M15 target by the actual fill. These were late or chased relative to that local auction objective.
- Two had already broken the latest confirmed M15 structural low before entry. Under this proxy, the claimed bullish transition was no longer structurally intact.

The hypothesis helped materially in two directionally correct stopped trades:

- `CBR-2022-013`: reconstructed M15 geometry reached target first for +0.5746R instead of the recorded stop loss.
- `CBR-2022-014`: reconstructed M15 geometry reached target first for +0.3136R instead of the recorded stop loss.

It also retained positive outcomes in two original winners:

- `CBR-2022-020`: +0.3520R with 0.5310 planned reward/risk.
- `CBR-2022-030`: +0.4224R with 0.5117 planned reward/risk.

But treating every nearest M15 fractal as the full target can truncate valid continuation severely. In `CBR-2022-027`, the nearest M15 target was only 0.0201R away; target was reached, yet the result was -0.0132R after costs versus the original +2.5184R outcome. That small swing is better interpreted as a possible decision or management level than automatically as the final destination.

## Interpretation

The evidence supports the operator's correction: stop and target must be evaluated as one coherent auction geometry. It also identifies the more precise monetization problem.

The main failure was not merely “the H1 target was too ambitious.” At many entries, the lower-timeframe auction was already delivered or structurally invalid by the time of the fill. Where geometry was valid, the nearest local objective was often too small relative to the structural stop and costs.

A defensible formulation is therefore:

1. Higher-timeframe context supplies direction and the broader destination.
2. The entry timeframe supplies the current structural invalidation and first meaningful opposing-liquidity decision level.
3. Entry is allowed only while the structural low remains intact and the local decision level remains ahead of the fill.
4. The first meaningful lower-timeframe level is not automatically the terminal target: rejection can justify realization or protection, while acceptance can justify retaining exposure toward the higher-timeframe destination.

The present five-bar fractal proxy is too mechanical to distinguish a meaningful liquidity objective from a tiny internal fluctuation. That distinction must be frozen from observable auction evidence before it can receive prospective or validation credit.

## Reproduction artifacts

- Protocol: `GOLD_MATCHED_HUMAN_SAME_TIMEFRAME_JOINT_GEOMETRY_AMENDMENT_A.md`
- Implementation: `tools/analyze_gold_same_timeframe_joint_geometry_v1.py`
- Machine-readable result: `research_artifacts/gold_same_timeframe_joint_geometry_v1/joint_geometry_diagnostic.json`
- Case table: `research_artifacts/gold_same_timeframe_joint_geometry_v1/joint_geometry_cases.csv`

