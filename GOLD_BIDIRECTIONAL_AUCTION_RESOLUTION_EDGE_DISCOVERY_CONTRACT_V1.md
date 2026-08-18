# Gold Bidirectional Auction-Resolution Edge Discovery Contract V1

Status: **FROZEN BEFORE DEVELOPMENT OUTCOME ACCESS**  
Branch: `GOLD_BIDIRECTIONAL_AUCTION_RESOLUTION_V1`

## 1. Purpose and prior-result preservation

This is a new, bounded research branch. It tests whether the already documented and repeatable gold pullback formation is a monetizable *auction-resolution opportunity*: the auction may resolve with the established trend or fail and resolve in the opposite direction.

Every prior result, rejection, artifact, and seal remains unchanged. In particular, continuation-only, fixed-entry, stop-only, sequential-confirmation, and adaptive-management branches remain completed and rejected. Their development results receive no validation credit here.

The research population is the sealed, de-duplicated set of 8,653 M15, H1, and H4 pullbacks from 2021-08-01 through 2024-12-31. The 8,650 cases with certified decision tapes are technically evaluable; the three unavailable cases remain in the population and are reported as unavailable, never deleted. Calendar 2025 and 2026 remain locked unless a development candidate passes every frozen gate.

No paid data may be acquired and no charge may be incurred.

## 2. Information boundary

Every decision uses only information available at that decision timestamp:

- completed signal-frame candles (M1 for M15 cases, M5 for H1, M15 for H4);
- point-in-time fundamental direction and quality state;
- completed higher-timeframe structure;
- pre-existing structural and liquidity levels;
- session state;
- the already sealed decision-tape features; and
- GC order flow only where already available, with no standalone candidate credit in this base study.

The realised behavioural archetype, future direction, future extrema, MFE, MAE, future stop/target result, and any later candle are forbidden at a decision. The archetype label may be used only after all decisions for descriptive attribution, not for fitting, selection, routing, filtering, or rejection.

## 3. Frozen formation and checkpoints

- Formation opens at the sealed `known_at_utc` for each pullback.
- Formation expires at the sealed `deadline_at_utc`, inherited from the sixteen-parent-bar census deadline.
- Only certified decision-tape checkpoints strictly within that boundary are eligible.
- The decision is made at a completed signal-frame close; entry is at the exact M1 open carrying the same timestamp.
- A checkpoint is unavailable if `checkpoint_feature_available` is false or required geometry/context is unavailable. It is retained and never imputed.

The existing completed-candle auction states are reused without alteration:

- `acceptance_state = +1`: two consecutive closes beyond the trend-side five-bar boundary by more than 0.05 setup ATR.
- `acceptance_state = -1`: two consecutive closes beyond the adverse-side five-bar boundary by more than 0.05 setup ATR.
- `sweep_reclaim_state = -1`: a trend-side boundary sweep followed by a close back inside it.
- `local_structure_score = +1`: the latest known trend-side two-left/two-right fractal has broken.
- `local_structure_score = -1`: the latest known adverse-side two-left/two-right fractal has broken.

## 4. Frozen directional contexts and triggers

`original_direction` is the sealed pullback trend direction.

Fundamental context is observed through the point-in-time `fundamental_alignment_state` already aligned to the original direction:

- Trend side is permitted for `ALIGNED`, `NEUTRAL_OR_WEAK`, or `UNKNOWN`; it is vetoed for `OPPOSED`.
- Reverse side is permitted for `OPPOSED`, `NEUTRAL_OR_WEAK`, or `UNKNOWN`; it is vetoed for `ALIGNED`.

Higher-timeframe context is observed through `higher_timeframe_alignment_fraction`:

- Trend side is permitted when the value is missing or at least 0.50.
- Reverse side is permitted when the value is missing or at most 0.50.

A **trend-side breakout-acceptance trigger** occurs at the first eligible checkpoint where all are true:

1. `acceptance_state == +1`;
2. `local_structure_score == +1`;
3. `current_displacement_atr > 0`;
4. trend-side fundamental and higher-timeframe permissions pass; and
5. executable trend-side stop/target geometry passes.

An observable **trend-side auction attempt** is recorded after a checkpoint when either `acceptance_state == +1` or `sweep_reclaim_state == -1`. This state is irreversible within the case.

A **failed-auction reversal trigger** occurs at the first later eligible checkpoint where all are true:

1. a trend-side auction attempt was recorded at an earlier checkpoint;
2. `acceptance_state == -1`;
3. `local_structure_score == -1`;
4. `current_displacement_atr < 0`;
5. reverse-side fundamental and higher-timeframe permissions pass; and
6. executable reversal stop/target geometry passes.

The strict earlier-checkpoint rule prevents the same candle from creating both the attempt and its failure.

## 5. Frozen execution geometry

### 5.1 Trend-side leg

- Direction: original trend direction.
- Stop: the point-in-time `structural_stop_e8` stored on the trigger checkpoint.
- Target: the point-in-time `liquidity_target_e8` stored on the trigger checkpoint.
- Gate: stop must be adverse to the actual fill and target room must be at least 1.0 stop-distance R.

### 5.2 Reverse-side leg

- Direction: opposite the original trend direction.
- Stop: beyond the completed reversal-trigger signal candle extreme by 0.10 setup ATR (above its high for a short, below its low for a long).
- Target: the original-direction `structural_stop_e8` known at the reversal checkpoint, treated as the nearest registered opposing structural objective.
- Gate: stop must be adverse to the actual fill and target room must be at least 1.0 stop-distance R.

### 5.3 Common mechanics

- Fill: exact M1 open at the checkpoint timestamp.
- Deadline: the original frozen case deadline; it is never extended after a switch.
- Exit priority per M1 bar: structural stop first, then liquidity/structural target; otherwise deadline close.
- A stop/target collision in one bar is stop-first.
- A gap through a stop fills at the worse of stop and bar open.
- Spread: observed nonnegative M1 spread, otherwise $0.30/oz fallback.
- Commission: $0.07/oz round trip.
- Slippage: $0.10/oz round trip.
- Cost stresses: 1.0x, 1.5x, and 2.0x.
- Position sizing: whole ounces, floored so planned price risk plus round-trip cost does not exceed the attempt budget.
- A case is non-executable when one ounce exceeds its attempt budget.
- Missing M1 timestamps or invalid bars anywhere on an attempted entry-to-deadline path make that attempted plan unavailable; they are not imputed.
- Leg MFE and MAE are measured over the complete entry-to-original-deadline M1 path, even when a hard exit occurs earlier, and are diagnostics only.

## 6. Frozen models and risk

Exactly three model families are tested for each timeframe:

1. `CONTINUATION_ONLY_CONTROL`: take the first executable trend trigger; one attempt; $50 maximum planned case risk.
2. `REVERSAL_ONLY`: take the first executable reversal trigger; one attempt; $50 maximum planned case risk.
3. `BIDIRECTIONAL_ONE_FLIP`: take the first executable trigger of either side. Only after that leg stops may the model take the first later executable trigger in the opposite direction. Target or time exit ends the case. At most two legs and one direction switch are allowed.

The bidirectional model has exactly three preregistered first-attempt/reserve risk splits: `$25/$25`, `$35/$15`, and `$15/$35`. Within each outer fold the split is selected using only dates strictly before the validation block. Selection requires the frozen timeframe support floor and chooses the highest training net expectancy among splits with PF at least 1.05 and positive expectancy at 1.5x costs. If none qualifies, the highest-expectancy supported split is used; if none has support, the fixed default `$25/$25` is used. Ties use the lexicographic split identifier.

Across all attempts, maximum total *planned* loss is $50 per case. Gap loss can exceed planned loss and must be reported honestly. There is no compounding.

A flip is recorded as successful only when its second leg has positive net PnL after base costs. This definition is fixed independently of whether that leg hit its target or exited on time.

## 7. Overlap policy

Models are first analysed separately by timeframe. Within each candidate/timeframe, cases are ordered by first entry timestamp and pullback identity. If a new case's first entry occurs before the retained prior case's final exit timestamp, the entire new case is skipped; it is not deferred. The permitted within-case reversal leg is not an overlap violation.

If development candidates pass and a combined portfolio is constructed, simultaneous cases are prioritized `H4`, then `H1`, then `M15`, then lexicographic pullback identity. Only one XAUUSD case may be open.

## 8. Frozen blocked out-of-fold design

Warm-up/training begins 2021-08-01. Validation blocks are:

1. 2021-10-01 through 2021-12-31;
2. 2022-01-01 through 2022-06-30;
3. 2022-07-01 through 2022-12-31;
4. 2023-01-01 through 2023-06-30;
5. 2023-07-01 through 2023-12-31;
6. 2024-01-01 through 2024-06-30;
7. 2024-07-01 through 2024-12-31.

Training for a fold contains only case dates earlier than that fold's validation start. The risk-split selection support floors are M15: 50 trades/34 dates; H1: 20/17; H4: 10/9.

Final candidate support floors are M15: 150 retained cases/100 dates; H1: 60/50; H4: 30/25.

## 9. Frozen statistical and economic gates

For every timeframe/model, report support, cases/month, legs/month, win rate, average win/loss, net expectancy in R, PF, total net R, total and average monthly dollars at $50 maximum case risk, drawdown, 1.5x and 2.0x cost stress, annual/fold/session results, first-attempt stop rate, flip frequency, successful-flip rate, continuation contribution, reversal contribution, and frozen behavioural-oracle capture.

Uncertainty uses 5,000 deterministic trading-date cluster bootstrap resamples with seed 621907. Multiplicity uses Holm correction within each timeframe across the three model families.

A candidate passes only if every gate passes:

- final support floor;
- net OOF expectancy > 0;
- PF >= 1.10;
- clustered 95% expectancy interval lower bound > 0;
- Holm-adjusted one-sided p <= 0.10;
- net expectancy at 1.5x costs > 0;
- at least three positive validation folds;
- at least two positive calendar years;
- no single year contributes more than 70% of positive PnL;
- no single entry-session state contributes more than 70% of positive PnL;
- maximum drawdown <= 15% of $10,000; and
- for the bidirectional model, at least two of the three fixed risk-split neighbours have positive OOF expectancy.

No more than two passing candidates per timeframe may advance, ranked by net expectancy, PF, then support. Zero is acceptable.

The behavioural-oracle comparison reuses the sealed original-direction visual-pivot-to-maximum oracle and is explicitly a diagnostic ceiling, not tradable or a true two-sided oracle.

## 10. Forward and prospective disposition

Only if at least one development candidate passes every gate may the complete candidate definition and any fold-selected parameter disposition be frozen and then applied once, unchanged, to existing 2025 and 2026 data. Those periods are exposed historical robustness evidence and receive no independent-validation credit. No retuning follows.

Only a development-passing, forward-surviving candidate may initialize an append-only prospective paper ledger. Otherwise the forward periods stay locked and no ledger is initialized.

## 11. Reproduction and stopping

Primary and reference implementations must independently reproduce case identities, triggers, entries, exits, risk, costs, results, classifications, checksums, gates, and verdicts. The plan payloads must be byte-identical. Any mismatch is an integrity failure.

No candidate may be inverted, repaired, filtered, or retuned after outcomes are visible. Choppy and losing cases remain. All unsupported and negative results are recorded. This branch stops only for a source-integrity blocker, a reproduction failure, or a potential charge; otherwise it completes with an honest economic verdict.
