# Gold Point-in-Time Auction-State and Adaptive Trade-Management Edge Discovery Contract V1

Status: **FROZEN BEFORE DECISION-TAPE MARKET VALUES OR CHECKPOINT OUTCOMES**

## Objective

Test whether an interpretable, continuously updated estimate of the gold auction state can retain an economically useful fraction of the de-duplicated pullback opportunity. This branch replaces the rejected fixed-entry, stop-only and fixed sequential-confirmation branches. Their verdicts and artifacts remain unchanged.

The research question is not whether a realised archetype can be identified retrospectively. It is whether completed-candle information available at each checkpoint can estimate continuation, failure, excursion and time-to-event well enough to support a profitable probe-confirm-add-scratch policy after costs.

## Sources and locks

- Development sources: only existing sealed point-in-time 2021-08-01 through 2024-12-31 sources.
- Population: exactly 8,653 de-duplicated STANDARD M15, H1 and H4 pullbacks from the sealed behavioural-atlas identity registry: 6,633 M15, 1,576 H1 and 444 H4.
- A `pullback_id` occurs once. The six rejected source entry models are not duplicated into this population.
- Every case remains in the denominator. Missing paths, levels or predictors are explicit technical unavailability, never silent filtering.
- Calendar 2025 and 2026 remain locked until a complete development policy is frozen.
- Existing GC MBO/MBP-10 may be used only on its covered development dates as a separately reported incremental study.
- No paid acquisition or card charge is authorized.

## Point-in-time decision tape

Each case begins at its sealed `known_at_utc`. Its deterministic deadline is the close of the sixteenth completed parent bar after that timestamp. This reuses the prior constant-execution maximum horizon and is not selected from outcomes.

| Setup timeframe | Checkpoint timeframe | Maximum parent horizon |
|---|---:|---:|
| M15 | M1 | 16 M15 bars |
| H1 | M5 | 16 H1 bars |
| H4 | M15 | 16 H4 bars |

- Checkpoints are exact completed bars, beginning at the first checkpoint close no earlier than `known_at_utc` and ending strictly before the deadline.
- An action decided at a checkpoint is filled at the next checkpoint-bar open, which must correspond to an exact sealed M1 timestamp.
- Expected component bars must be complete and contiguous. A gap makes the affected checkpoint technically unavailable; time is never compressed across a gap.
- Tape identities, timestamps, source lineage and predictor columns must be materialized and independently reproduced before any future path is joined.
- The tape includes every checkpoint. Model training may use an outcome-blind, case-balanced sample of at most 32 uniformly spaced checkpoints per case, always including the first and last available checkpoint. Policy inference uses every available checkpoint.

## Eligible information

Only completed, available-at-or-before-checkpoint information is eligible:

- point-in-time fundamental score, confidence, coverage, regime, reaction function, event risk and transparent component contributions;
- point-in-time COT state under its publication clock;
- completed H1, H4, daily and weekly structure and alignment;
- setup pivot, confirmation extreme, reference level, prior-day, Asia and known swing liquidity levels;
- setup impulse, pullback, compression, retracement, rejection and response facts known at the original setup timestamp;
- current displacement, running favourable/adverse excursion, recent path efficiency, volatility, spread, volume and candle geometry;
- deterministic sweep, reclaim, break, two-close acceptance, rejection, failed acceptance, first retest and local fractal structure states;
- DST-aware session phase, elapsed fraction and time remaining.

Running excursion *through the current checkpoint* is observed information. Eventual MFE, MAE, realised archetype, structural resolution, future extrema, future direction and future target/stop result are forbidden predictors.

## Structural execution facts

At a checkpoint, the proposed fill is the next checkpoint-bar open.

- Base invalidation for an UP case: setup pivot minus 0.15 setup ATR.
- Base invalidation for a DOWN case: setup pivot plus 0.15 setup ATR.
- A signal-timeframe fractal requires two complete bars on each side and becomes known only at the close of the second right-hand bar.
- The current structural stop may tighten to the latest known adverse fractal plus/minus 0.10 setup ATR, but may never widen beyond the base invalidation and must remain adverse to the proposed fill.
- The liquidity target is the nearest known, not-yet-broken trend-side STANDARD swing at the checkpoint, using the sealed swing and break registries.
- A proposed action is unavailable when stop, target, exact fill, future deadline path, or at least one whole ounce is unavailable, or when target room is below 1.00 stop-distance R.

These calculations use only information known at the checkpoint. No future MAE percentile or future-formed level is permitted.

## Frozen checkpoint outcomes

Outcome labels are training/evaluation targets and can never become predictors.

From the next-open hypothetical fill through the case deadline, calculate with stop-first ambiguous-bar treatment:

- `CONTINUATION_1R_FIRST`, `FAILURE_STOP_FIRST`, or `UNRESOLVED`;
- whether +2R occurs before the structural stop;
- MFE and MAE in stop-distance R;
- time to the first +1R/stop passage or censoring;
- terminal net R under the checkpoint's frozen stop, liquidity target and deadline after costs.

The model must estimate the three-class response probability, +2R probability, expected MFE, expected MAE, expected time-to-first-passage and expected terminal net value.

## Frozen predictors and transformations

The protocol registry is exhaustive. It contains setup geometry, continuously updated macro/positioning, higher-timeframe alignment, price path, level interaction, candle/liquidity proxy and clock variables. No predictor may be added after checkpoint outcomes are opened.

- Numeric clipping limits, medians, scaling moments and quantile cut points are learned from the outer-fold fitting subset only.
- Missing numeric values use the training median plus a missingness indicator.
- Missing categoricals are `UNKNOWN`; unseen categories are `OTHER`.
- Categorical vocabulary may be frozen from the outcome-blind tape before outcome access.
- No row is dropped because a predictor is missing.

## Model registry

Exactly two transparent model families exist per timeframe:

1. `LINEAR_COMPETING_RISK_V1`: regularized multinomial logistic response model, regularized binary +2R model and ridge regressions for MFE, MAE, time and terminal net R.
2. `ADDITIVE_BINNED_COMPETING_RISK_V1`: the same estimands using training-only quintile bins for numeric predictors, categorical main effects and exactly four preregistered interactions: macro score x higher-timeframe alignment, reference location x acceptance state, displacement x volatility, and session x elapsed phase.

Regularization grids are fixed in the protocol. Calibration uses a training-only chronological calibration segment and a fixed temperature grid. Models must expose coefficients or additive bin effects and field lineage. No neural network, unrestricted tree ensemble or opaque representation is allowed.

## Chronological evaluation

The complete tape covers 2021-08-01 through 2024-12-31. August and September 2021 are causal warm-up because no earlier population exists. Strict expanding-window OOF validation begins 2021-10-01:

1. 2021-10-01 through 2021-12-31;
2. 2022-01-01 through 2022-06-30;
3. 2022-07-01 through 2022-12-31;
4. 2023-01-01 through 2023-06-30;
5. 2023-07-01 through 2023-12-31;
6. 2024-01-01 through 2024-06-30;
7. 2024-07-01 through 2024-12-31.

For each fold, the most recent 20% of training dates is the calibration/policy-selection segment; earlier dates are the fitting segment. Hyperparameters, calibration temperature and policy thresholds are selected without accessing the outer validation block. Insufficient early-fold support is recorded, not repaired.

## Adaptive action policy

Only `NO_TRADE`, `OPEN_PROBE`, `ADD_TO_NORMAL_RISK`, `HOLD`, `SCRATCH`, `STRUCTURAL_EXIT`, `LIQUIDITY_TARGET_EXIT` and `TIME_EXIT` are permitted.

- `OPEN_PROBE` requires all selected probability and expected-value thresholds plus executable stop/target geometry.
- A probe risks at most $12.50.
- One `ADD_TO_NORMAL_RISK` is permitted when continuation probability improves by the selected increment and expected net value remains positive. Added planned risk is at most $37.50.
- Total planned stop-plus-cost risk may never exceed $50 per setup on a static $10,000 account.
- `SCRATCH` requires two consecutive checkpoints below the selected continuation threshold or at/below zero expected net value.
- Hard structural stop, liquidity target and setup deadline always override model actions.
- The stop and target fixed at initial entry cannot be widened or moved farther away. The stop may tighten after an add only to a newly known structural level.
- One XAUUSD position may be open across the combined portfolio. At identical timestamps use H4, H1, then M15, followed by deterministic case ID.

Two execution tracks use the same selected entry and management signals:

- `CONSTANT_50`: deploy the complete $50 planned risk at `OPEN_PROBE`.
- `ADAPTIVE_12P5_PLUS_37P5`: deploy the probe, then the single permitted add.

Observed spread or $0.30/oz fallback, $0.07/oz commission, $0.10/oz slippage, one-checkpoint latency, whole-ounce sizing, no compounding, gap-aware stops and 1.0x/1.5x/2.0x cost stresses are retained.

## Policy selection and multiplicity

The complete threshold grid is frozen in the protocol. Within each fold and model family, choose the policy with the highest calibration-segment net expectancy among policies satisfying calibration support, PF at least 1.05 and positive 1.5x-cost expectancy. If none satisfy those conditions, choose the highest-expectancy supported policy and preserve its failure status. No validation-block repair is allowed.

Candidate identity is timeframe x model family x execution track. Holm correction is applied within each timeframe across the four candidates. At most two candidates per timeframe may pass.

## Formal PASS gates

Post-overlap OOF support floors are M15 150 trades/100 dates, H1 60/50, and H4 30/25. Every formal candidate additionally requires:

- positive net OOF expectancy;
- profit factor at least 1.10;
- trading-date-clustered 95% confidence lower bound above zero;
- Holm-adjusted one-sided p no greater than 0.10;
- positive expectancy at 1.5x costs;
- at least three positive validation folds;
- at least two positive calendar years;
- no single positive year or session contributing more than 70% of positive PnL;
- OOF continuation Brier skill above zero and expected-calibration error no greater than 0.10;
- positive expectancy in at least 60% of the frozen immediate policy neighbours;
- normalized maximum drawdown no greater than 15% of the static $10,000 account.

Report the percentage of the de-duplicated oracle retained. Do not optimize against $1,000/month. If average monthly PnL is positive, report the linear risk scaling required to reach $1,000 and reject that scaling when it exceeds the $50 setup-risk cap or implies drawdown above 15%.

## GC incremental study

On existing GC-covered dates, derive value-blind preceding-60-second aggression, quote OFI, depth imbalance, microprice pressure, absorption and liquidity-fragility fields from technically valid continuous-market states. Compare base versus base-plus-GC models on identical cases and folds. Report incremental calibration and economics. The limited subset receives no standalone full-history candidate or validation credit and is never extrapolated to uncovered dates.

## Forward and stopping policy

If development candidates pass, seal their fitted-development specification and policy before opening existing 2025 and 2026 through 2026-07-29 once. These exposed periods receive robustness evidence only, never independent-validation credit. Initialize an append-only prospective paper ledger for the next eligible checkpoint.

If no development candidate passes, leave 2025/2026 locked and do not initialize a ledger. Deterministic value-blind engineering corrections are permitted only when they leave this contract, feature registry, outcomes, models, folds, policy grid and gates unchanged and are recorded in the audit trail.

Independent implementations must reproduce tape identities, predictors, outcome joins, OOF probabilities, actions, trades, summaries and checksums. Every unavailable row, unsupported fold, rejected candidate and negative result remains recorded.
