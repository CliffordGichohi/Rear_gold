# Gold Coherent-Auction Unseen-Block Post-Result Diagnostic V1

Status: `POST_HOC_DIAGNOSTIC_ZERO_VALIDATION_CREDIT`

Source result:
`research_artifacts/gold_coherent_auction_frozen_translator_unseen_block_v1/unseen_result.json`
(`01c5f2a83b0f91eeee392dffeacc2eae9c0a2eb5f9ee82e000f216a39e7be79b`).

This report explains the frozen 50-session result after outcomes were opened.
It does not change the frozen translator, does not confer validation credit on
any proposed correction, and does not open 2025 or 2026.

## 1. Result decomposition

- 15 admitted executions: 8 wins and 7 losses.
- Net: `+3.69071261R`.
- Gross winning R: approximately `+7.5653R`.
- Gross losing R: approximately `-3.8746R`.
- Average win: approximately `+0.9457R`.
- Average loss: approximately `-0.5535R`.
- Three structural-stop losses contributed `-2.9012R`.
- Four losing time exits contributed approximately `-0.9734R`.
- Three target-touch trades contributed approximately `+5.8347R`.
- The other twelve executions contributed approximately `-2.1440R`.
- `GAV-2022-024` contributed `+4.3666R`, approximately 57.7% of all
  positive R and more than the final net result.

The payoff is positively skewed: many small outcomes plus an occasional large
liquidity-target realization. The runner should not be removed merely to make
the win distribution look more uniform.

## 2. Why the seven losses occurred

| Case | Result | Failure attribution | Evidence available at decision or during lifecycle |
|---|---:|---|---|
| GAV-2022-002 | -0.9859R | location/auction-room failure | Long continuation against a bearish H4 swing sequence at 0.730 signed range location; almost no favourable response (`0.011R`) and immediate structural-stop loss. The stop was also above the known M15 protected level. Price later reclaimed entry briefly but never reached target and ended substantially lower. |
| GAV-2022-003 | -0.9257R | location/thesis failure | Long continuation against bearish H4 structure above the range midpoint, with neutral macro. The stop was beyond the known protected level and therefore not the primary error. Price later recovered near entry but never reached target. |
| GAV-2022-008 | -0.3762R | no auction response | Mixed H4 structure, confirmed H4 damage and a negative 15-bar impulse. The trade produced no positive MFE and expired below entry. |
| GAV-2022-009 | -0.1160R | late/high-location no-response entry | Signal arrived 146 minutes into New York at 0.741 H4 range location with an 11.36-M15-ATR target. It achieved only `0.029R` MFE and expired slightly negative. |
| GAV-2022-010 | -0.9896R | invalid stop geometry | Direction was initially correct: price reached more than `+0.5` structural R within three minutes. The learned stop was 0.454 dollars above the already-known protected M15 level. Price swept the synthetic stop by only about `0.038` structural R, then rallied over `7R` and reached the frozen target. |
| GAV-2022-013 | -0.1122R | contextual contradiction | Macro was explicitly `OPPOSED`, H4 damage was present and the long produced only a small favourable excursion before expiring negative. |
| GAV-2022-041 | -0.3690R | contextual contradiction and no response | Macro was `OPPOSED`, H4 structure was bearish and the late structural-repair long never reached `+0.25R`. |

Five of the seven losses never reached `+0.25` structural R. Every eventual
winner did reach `+0.25R`. This is descriptive evidence for a causal response
or staged-risk test, not permission to use future `+0.25R` attainment as an
entry label.

## 3. Why the eight wins occurred

- All eight occurred while the frozen macro classifier was
  `NEUTRAL_OR_CONFLICTED`; this does not prove neutral macro is favourable.
  It mainly shows that both explicitly `OPPOSED` admitted longs lost, while
  the sole `ALIGNED` observation also lost.
- The two range-rotation trades both won (`+1.0915R` combined), but support is
  only two cases.
- The three trades that touched their known target all won.
- `GAV-2022-024`, the `+4.3666R` winner, combined:
  - price in the lower-middle part of its H4 range (`0.405`), despite a bearish
    H4 swing sequence;
  - moderately bullish fundamental context led by real yield;
  - an active M15 structure with its stop beyond the known protected level;
  - approximately `4.82` reward-to-structural-risk room;
  - very small realised MAE (`0.121R50`);
  - rapid response: `+0.25R` within four minutes, `+0.5R` within seven, and
    `+1R` within nineteen;
  - successful capture of the core liquidity target without truncating the
    move.

This case demonstrates why a crude rule such as “never buy under bearish H4
structure” is wrong. Auction location, available room, lower-timeframe
response and contextual alignment matter jointly.

## 4. Group evidence

| Condition | Support | Wins | Net R | Interpretation |
|---|---:|---:|---:|---|
| Macro neutral/conflicted | 12 | 8 | +5.1578 | Profitable here, but heterogeneous and partly carried by the large winner. |
| Macro opposed | 2 | 0 | -0.4812 | Candidate contextual warning; insufficient support for a universal rule. |
| Range rotation | 2 | 2 | +1.0915 | Promising but severely underpowered. |
| Continuation with room | 11 | 5 | +2.2281 | Positive but inconsistent; label admitted cases that did not truly have room. |
| High H4 location (>0.67) | 3 | 1 | -0.5727 | Weak on this block. |
| Wide learned stop (>3.5 M15 ATR) | 6 | 2 | -0.4284 | Wide geometry reduced sizing but did not resolve weak entries. |
| Structural stop | 3 | 0 | -2.9012 | Includes two thesis/location failures and one clear false invalidation. |
| Time exit | 10 | 6 | +5.1238 | Positive only because the large target/runner case is included. |

All twenty emitted signal probabilities were `1.0`. The fitted tree therefore
provided no useful probability calibration or quality ranking on unseen
signals. Risk must not be varied using that probability.

## 5. Frozen-veto attribution

The five contextual rejections were simulated only as a post-result
counterfactual. Forced execution would have produced approximately `-0.8146R`
combined. The vetoes rejected two small winners as well as three losers, but
were net protective. In particular, `NO_ACTIVE_M15_DIRECTIONAL_STRUCTURE`
must not be relaxed merely to increase trade count.

## 6. Bounded exploratory corrections

These are post-hoc hypotheses, not validated improvements.

### A. Structural-invalidation invariant

For every long, require the stop to be at or below the point-in-time
controlling protected M15 level with a fixed `0.10 x M15 ATR` buffer. If that
distance cannot support one whole ounce under the risk cap, skip the setup.

Applied universally as a diagnostic to this same exposed block, while keeping
targets and management unchanged, this changed net R from `+3.6907R` to
approximately `+5.8840R`. It rescued `GAV-2022-010` but reduced position size
and profit on four valid winners. The apparent `+2.1933R` improvement has zero
forward-validation credit.

The result also reveals that “latest protected M15 level” can be too remote in
some cases. The next protocol must define the *controlling entry structure*
causally rather than choosing a convenient swing after the outcome.

### B. Thesis-specific context, not one universal macro filter

- Continuation requires genuine remaining room relative to the H4 auction.
- Range rotation may override macro only at a pre-existing external boundary
  with an observable reclaim/rejection.
- Structural repair requires an observable repair and acceptance sequence.
- Explicitly opposed macro should prevent a full-risk continuation or repair
  entry unless the frozen range-rotation exception is satisfied.

Skipping the two `MACRO_OPPOSED` admitted longs would add `0.4812R` on this
block, but support is only two and the rule was seen after outcomes.

### C. Signal is not yet full-risk entry

The signal should establish an eligible setup. Full risk should require an
observable auction response, such as a completed reclaim/acceptance and first
valid retest. A bounded probe may be studied, but eventual MFE may never be
used at the decision point.

The diagnostic motivation is strong—five losses never reached `+0.25R`, while
all winners did—but the exact response definition and timing must be frozen
before another unseen block is opened.

## 7. Recommended order

1. Correct and causally define structural invalidation first.
2. Freeze one observable response/acceptance entry lifecycle.
3. Retain the existing vetoes and tail-preserving target/runner control.
4. Test context rules as thesis-specific interactions, not universal trend or
   macro filters.
5. Fit no rule and vary no risk from the current uncalibrated `1.0`
   probabilities.

Do not combine every favourable post-hoc observation and call the resulting
same-block number an edge. The corrected lifecycle needs a new untouched test
block or prospective decisions.
