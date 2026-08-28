# Gold Matched Human Replay V1 — Post-Result Analysis

## Status and evidential limits

This is a descriptive interpretation of the sealed matched-comparison result. It does not alter the frozen protocol, the decisions, the outcome ledger, the formal verdict, or any sealed predecessor artifact.

- Formal verdict remains `INCONCLUSIVE_ZERO_CREDIT_MATCHED_DIAGNOSTIC`.
- No validated edge is claimed.
- The 30 dates were already exposed through the earlier Codex audit.
- Calendar 2025 and 2026 remain locked and uninspected.
- No rule below may be promoted from this report without a new pre-result freeze and fresh cases.

## Bottom line

The human result was negative, but it does not support the conclusion that the operator had no useful directional information.

- 30 completed cases produced 16 trades and 14 no-trades.
- All 16 trades were LONG.
- Net result was `-2.38971301R` (`-$119.49`) at the frozen $50 maximum planned risk.
- Expectancy was `-0.14935706R` per trade and profit factor was `0.65747528`.
- The 95% bootstrap interval for expectancy was `[-0.56992836R, +0.36888312R]`, so the small sample cannot distinguish a durable edge from noise.
- The frozen day-close directional diagnostic agreed with the chosen LONG direction in 11 of 16 trades (68.75%; approximate Wilson 95% interval 44.4%–85.9%).
- Ten of those eleven terminal-direction-correct cases eventually offered at least +1 effective R during the same UTC day, but only five did so before the actual frozen exit.

The main unresolved problem is therefore not simply “can direction ever be read?” It is whether the direction can be selected prospectively and converted into a fill, invalidation, and management policy before the move occurs.

## What was actually tested

The observed human policy in this sample was narrower than the stated six-step method:

- Direction: 16 LONG, 0 SHORT.
- Session: 15 New York trades and 1 London trade.
- Every trade was tagged `MACRO_ALIGNED_CONTINUATION`.
- The displayed point-in-time macro pressure was bearish on all 16 trade decisions.
- Macro was recorded as `CONTEXT_ONLY` on 15 of 16 trades and `DIRECTION_DRIVER` on only one.
- The free-text reasoning repeatedly described bullish H4/H1/M15 structure, discounted location, or a prior liquidity-shift area.
- The structured higher-timeframe state remained `UNKNOWN` on 15 of 16 trades even when the free text described a bullish trend or range.
- Setup quality was the default 50 on 13 of 16 trades; execution quality was the default 50 on 14 of 16 trades.

Consequently, this sample primarily tested bullish technical continuation or range-response decisions taken despite bearish macro pressure. It did not adequately test a bidirectional, fundamental-aligned process, and the default structured fields do not support a useful probability-calibration analysis.

## Exact loss decomposition

The 16 trades partition exactly as follows:

| Disposition | Cases | Net result | Interpretation |
|---|---:|---:|---|
| Terminal direction disagreed with LONG | 5 | `-3.50953272R` | No winning trade in this subset. Two still offered +1R later in the day, so terminal direction is not identical to intraday tradability. |
| Post-fill geometry invalid | 5 | `-0.58630000R` | The frozen market-next-M1 fill moved the effective risk above the $55 ceiling and the engine flattened immediately. |
| Terminal direction correct, but stopped after open profit | 3 | `-2.88092795R` | Each reached more than +1R before later stopping. |
| Profitable executions | 3 | `+4.58704766R` | One target hit and two positive time exits. |
| **Total** | **16** | **`-2.38971301R`** | Formal frozen result. |

Terminal-direction-disagreement cases:

- `CBR-2022-003`, `CBR-2022-007`, `CBR-2022-009`, `CBR-2022-019`, and `CBR-2022-026`.

Post-fill-geometry cases:

- `CBR-2022-002`, `CBR-2022-006`, `CBR-2022-015`, `CBR-2022-023`, and `CBR-2022-024`.

Correct-direction round-trip stop cases:

- `CBR-2022-005`: +1.058R pre-exit MFE, then -1.062R.
- `CBR-2022-013`: +1.858R pre-exit MFE, then -0.814R.
- `CBR-2022-014`: +2.029R pre-exit MFE, then -1.004R.

Profitable cases:

- `CBR-2022-020`: +0.376R at time exit.
- `CBR-2022-027`: +2.518R at target.
- `CBR-2022-030`: +1.693R at time exit.

## Direction versus monetization

The hindsight terminal-direction split is diagnostically strong but is not an actionable filter:

| Frozen descriptive subset | Trades | Net R | Expectancy | Profit factor |
|---|---:|---:|---:|---:|
| Terminal direction correct | 11 | `+1.119820R` | `+0.101802R` | `1.323` |
| Terminal direction wrong | 5 | `-3.509533R` | `-0.701907R` | `0.000` |
| Valid geometry and terminal direction correct | 6 | `+1.706120R` | `+0.284353R` | `1.5922` |
| All valid-geometry trades | 11 | `-1.803413R` | `-0.163947R` | `0.7178` |

This says that a reliable point-in-time directional discriminator would have economic value. It does not tell us what that discriminator is. Using the later day-close direction as a live filter would be look-ahead bias.

## Entry-model mismatch

The matched comparison intentionally used the earlier Codex execution model:

- only `MARKET` orders;
- fill at the first observed M1 open after confirmation;
- one-minute latency plus spread and slippage;
- quantity calculated from the drawn entry-to-stop distance before the later market fill;
- immediate flattening if effective fill-to-stop risk exceeded $55.

That is not the same as waiting for the market to touch a drawn pullback or retest entry. Five of sixteen human trades (31.25%) were therefore classified `POST_FILL_GEOMETRY_INVALID`. Their effective fill-to-stop risks were approximately $57.07–$61.78 even though their planned risks were approximately $48.25–$49.99.

All five invalid-geometry cases later closed in the intended direction and offered at least +1 effective R during the full-day path. This does **not** prove that a pending order would have filled and survived, but it proves that the market-only matched execution is unsuitable for evaluating a method whose entry is “wait for price to return to my level.”

## Stop and target behavior

- Mean planned reward-to-risk was 2.572R; the range was 1.667R–3.387R.
- Only one full target was hit.
- Three losing trades first reached +1.058R, +1.858R, and +2.029R respectively.
- Partial exits, moving stops, scratching, and structural trailing were prohibited by the frozen execution policy.

The data therefore identify an all-or-nothing capture problem, but they do not authorize the post-hoc conclusion that “move to break-even at +1R” or any other specific rule is profitable. Such a rule must be frozen and tested on fresh cases with the original fixed-target policy retained as the control.

## Human versus Codex

- Human: `-2.3897R`; Codex: `-1.7977R`; arithmetic difference `-0.5920R` for the human operator.
- Both results were negative and both expectancy intervals crossed zero.
- Both operators traded in 13 cases, but they used different sessions in 8 of those 13 cases.
- They traded the same session in only five cases.
- Exact action agreement was 8 of 30 cases.

Therefore, `CODEX_OUTPERFORMED_HUMAN` is only the frozen higher-net-R label. It is not evidence that Codex has greater trading skill, and it is not an apples-to-apples comparison of identical setups or timestamps.

## What the operator did well

- The rationale consistently attempted to connect higher-timeframe structure, discounted location, a prior liquidity-shift area, and lower-timeframe transition.
- The chosen direction matched the frozen day-close direction in 11 of 16 cases.
- The three profitable trades generated +4.587R, showing that the payoff geometry could be convex when the path cooperated.
- Fourteen no-trade decisions demonstrate selectivity rather than compulsory daily trading.

## What needs correction

1. **Direction was one-sided.** No SHORT trade was recorded, so the audit cannot show whether the method adapts when bearish macro and bearish structure align.
2. **Fundamentals did not actually govern direction.** Every trade was long while every displayed macro state was bearish; 15 were explicitly marked `CONTEXT_ONLY`.
3. **The structured record and the written reasoning diverged.** Bullish HTF reasoning was commonly stored alongside `higher_timeframe_state=UNKNOWN`, and `MACRO_ALIGNED_CONTINUATION` was used despite bearish macro pressure.
4. **Confidence fields were mostly defaults.** They cannot distinguish high-quality from marginal setups or support calibration.
5. **Execution did not match the intended entry concept.** A market-next-bar fill was used where the operator appears to have drawn a desired retracement or retest entry.
6. **Open profit was not managed.** Three trades gave more than +1R and later became full losses, but the audit prohibited any adaptive management.
7. **Session coverage was unbalanced.** Fifteen of sixteen trades were New York; London performance remains essentially unmeasured for the human operator.

## Evidence-based next experiment

Do not tune a winning rule from these 30 exposed cases. Before additional labeling, freeze a faithful prospective replay policy with:

1. explicit operator-selected gold bias (`BULLISH`, `BEARISH`, or `NEUTRAL`) and an explicit `ALIGNED`, `COUNTER_MACRO`, or `MACRO_NEUTRAL` relationship;
2. mandatory completed-candle HTF state, exact pre-existing level, transition timestamp, structural invalidation, and target source—without default `UNKNOWN` values;
3. explicit `MARKET`, `LIMIT`, or `STOP` entry semantics, with pending orders filling only after price activation and quantity recalculated from the actual fill;
4. the original full-target policy as a control and exactly one pre-frozen management challenger, such as partial realization at +1R followed by structural trailing;
5. both LONG and SHORT eligibility, with London and New York reported separately;
6. fresh, previously unopened cases and no feedback until the frozen block is complete.

The next experiment should answer two narrow questions: whether the operator can prospectively distinguish the six valid-geometry, direction-correct cases from the five valid-geometry, direction-wrong cases; and whether a pre-frozen management rule retains more of the three documented profit round trips without degrading the winners.

## Source artifacts

- Sealed formal result: `GOLD_MATCHED_HUMAN_CODEX_REPLAY_COMPARISON_V1_RESULT.md`
- Complete case comparison: `research_artifacts/gold_matched_human_replay_v1/comparison/matched_case_comparison.json`
- Flat case table: `research_artifacts/gold_matched_human_replay_v1/comparison/matched_case_comparison.csv`
- Independent reproduction: `research_artifacts/gold_matched_human_replay_v1/comparison/independent_reproduction.json`
- Formal final seal: `research_artifacts/gold_matched_human_replay_v1/comparison/final_seal.json`
