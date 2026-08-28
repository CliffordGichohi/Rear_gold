# Gold Matched Human Coherent Auction Geometry and Management V1 — Report

## Verdict

The refined geometry materially improves the exposed matched sample, but neither tested full-position management rule improves it further.

The strongest descriptive track is:

> actual entry fill → buffered protected M15 low as structural stop → original preselected H1 liquidity target → fixed $50 maximum planned risk recalculated at the fill.

Across the 16 recorded LONG decisions, 15 retained an active point-in-time bullish M15 break and one (`CBR-2022-003`) became a structural no-trade. The 15 executable cases produced `+1.7932R` (`+$89.66`), 53.33% wins, `+0.1195R` expectancy, profit factor `1.2436`, and maximum drawdown `4.0375R`.

This is a material improvement over the sealed original `-2.3897R`, but it is post-result calibration on only 15 executable cases. It is not a validated edge, and no monthly projection is permitted. Calendar 2025 and 2026 remain untouched.

## What was changed

- Entries, actual fills, human H1 targets and deadlines were preserved.
- The stop was reconstructed from the protected M15 low associated with the latest still-active bullish M15 structural break, with the frozen 0.10-ATR buffer.
- Quantity was recalculated from the actual fill to that stop, eliminating stale pre-fill quantity geometry.
- Nearby confirmed M15/H1 highs were registered point-in-time as decision levels rather than assumed observed liquidity.
- Two management tracks were added after preserving the fixed-H1 control:
  - M5 acceptance/rejection at each frozen level with structural trailing.
  - One bounded M15 protected-low runner under Amendment A.

## Economic comparison

| Track | Executable | Win rate | Net R | Expectancy | Profit factor | Max drawdown |
|---|---:|---:|---:|---:|---:|---:|
| Protected M15 stop + original H1 target | 15 | 53.33% | **+1.7932R** | **+0.1195R** | **1.2436** | 4.0375R |
| Full exit at first meaningful level | 15 | 60.00% | -1.2490R | -0.0833R | 0.8030 | 2.7087R |
| M5 level-response full runner | 15 | 60.00% | -1.3823R | -0.0922R | 0.7820 | 2.7591R |
| M15 protected-auction full runner | 15 | 26.67% | -1.3612R | -0.0907R | 0.8317 | 4.0811R |
| Stop-feasible MFE hindsight ceiling | 15 | n/a | +26.4688R | n/a | n/a | n/a |

The higher win rate of the first-level exits did not make them profitable because their winners were too small relative to complete structural losses and costs. This directly confirms that win rate alone is not the edge.

## Why the fixed H1 track improved

The original replay sized positions from the drawn entry and then filled one minute later at market. Five trades were immediately flattened because the later fill made the old size exceed the risk ceiling. Recalculating size from the actual fill and a coherent M15 structural stop changed those cases as follows:

| Case | Original R | Refined fixed-H1 R |
|---|---:|---:|
| `CBR-2022-002` | -0.1584R | +0.7654R |
| `CBR-2022-006` | -0.0504R | +0.7247R |
| `CBR-2022-015` | -0.2256R | +0.4206R |
| `CBR-2022-023` | -0.0819R | +2.1112R |
| `CBR-2022-024` | -0.0700R | +2.4773R |

This does not delete the old failures. It demonstrates that stale quantity and mixed stop geometry were major evaluation errors for the operator's intended method.

The refined stop was not universally better. `CBR-2022-030` changed from `+1.6926R` to `-1.0709R` because the newly reconstructed M15 stop was much tighter and was hit before the larger continuation. That is an important negative result: the protected-low proxy still does not perfectly capture the operator's intended invalidation.

## Direction remains the main discriminator

Using the already-known terminal direction only as a non-tradable attribution:

| Hindsight subset | Support | Wins | Net R | Expectancy | Profit factor |
|---|---:|---:|---:|---:|---:|
| Direction eventually correct | 11 | 8 | +6.0267R | +0.5479R | 2.9269 |
| Direction eventually wrong | 4 | 0 | -4.2335R | -1.0584R | 0.0000 |

This does not authorize using future terminal direction. It shows what must be reproduced prospectively: the operator's directional reading supplied potential value, while four wrong-direction entries consumed most of that value.

## Why “let every winner run” failed

The M5-response runner helped the two previously identified profit round trips:

- `CBR-2022-013`: fixed H1 `+0.0544R`; M5 response `+1.2912R`.
- `CBR-2022-014`: fixed H1 `-1.0195R`; M5 response `+0.6510R`.

But it degraded seven cases because a local M5 rejection was not the same thing as failure of the H1 destination. It cut `CBR-2022-023`, `CBR-2022-024` and `CBR-2022-027` far before their larger outcomes.

The M15 runner was more patient and improved nine cases relative to the H1 control, but it still lost overall because it surrendered several large fixed-target winners. It finished at `-1.3612R`. A full-position uncapped runner therefore does not survive this calibration.

The hindsight stop-feasible ceiling was `+26.4688R`; the fixed-H1 track retained only 6.77% of that ceiling. The gap is real, but the ceiling chooses the future maximum and is not tradable. Neither structural runner converted that ceiling into a credible policy.

## Refined interpretation

The evidence supports this hierarchy:

1. The active M15 break supplies the protected structural low and therefore the initial risk.
2. Nearby M15 highs are internal auction information, not automatic full-position take-profit points.
3. The preselected H1 liquidity area remains the primary realizable destination.
4. A management overlay must preserve that profitable control. It should not replace the whole position with an uncapped runner or close the whole position on a single lower-timeframe rejection.

The next legitimate challenger should therefore be a frozen **core-plus-runner** policy on fresh outcome-hidden cases: preserve a fixed realization at the H1 destination, leave only a bounded minority as the structural runner after confirmed acceptance, and activate pre-target protection only after an objective profitable auction transition. The split and protection rule must be chosen before seeing those fresh outcomes; they must not be optimized on these 16 exposed trades.

## Formal status

- Geometry finding: `PROMISING_EXPOSED_CALIBRATION_NOT_VALIDATED`
- First-level fixed exit: `REJECT_NEGATIVE_EXPOSED_ECONOMICS`
- M5 level-response runner: `REJECT_NEGATIVE_EXPOSED_ECONOMICS`
- M15 protected-auction runner: `REJECT_NEGATIVE_EXPOSED_ECONOMICS`
- Edge claim: `NOT_YET_AUTHORIZED`
- 2025: `UNTOUCHED`
- 2026: `UNTOUCHED`

## Reproduction artifacts

- Frozen protocol: `GOLD_MATCHED_HUMAN_COHERENT_AUCTION_MANAGEMENT_CALIBRATION_PROTOCOL_V1.md`
- Bounded runner amendment: `GOLD_MATCHED_HUMAN_COHERENT_AUCTION_MANAGEMENT_AMENDMENT_A.md`
- Base implementation: `tools/analyze_gold_coherent_auction_management_v1.py`
- Amendment implementation: `tools/analyze_gold_m15_structural_runner_amendment_a.py`
- Base result: `research_artifacts/gold_coherent_auction_management_v1/coherent_auction_management_result.json`
- Base case table: `research_artifacts/gold_coherent_auction_management_v1/coherent_auction_management_cases.csv`
- M15 runner result: `research_artifacts/gold_coherent_auction_management_amendment_a/m15_structural_runner_result.json`
- M15 runner case table: `research_artifacts/gold_coherent_auction_management_amendment_a/m15_structural_runner_cases.csv`

Both implementations reproduce their complete payloads exactly in two independent runs.

