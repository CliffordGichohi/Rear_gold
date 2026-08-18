# GC Continuous State-Response Edge Discovery Contract V3

Contract version: `GC_CSR_EDGE_DISCOVERY_V3_CONTRACT_V1_0`

## 1. Mandate and preserved record

This branch asks whether continuous, point-in-time market pressure explains the subsequent gold response. It does not attempt to rescue or relabel the rejected binary event-trigger branch.

The following records remain final and unchanged:

- V2 Milestone 3-R1: `PASS_M3_R1_DISCOVERY_ZERO_CANDIDATES`.
- V2 Milestone 4: `PASS_M4_NEGATIVE_RESULT_ATTRIBUTION`.
- All 38 support-eligible binary relationships failed the original minimum-effect gate.
- No prior rejection receives V3 development or validation credit.

## 2. Research boundary

- Development sources: only the already sealed 2021-11-08 through 2024-12-13 microstructure sample and the existing sealed 2021-2024 point-in-time casebook sources.
- London and New York are separate research populations, multiplicity families, rankings, and candidate lists.
- Calendar 2025 and 2026 remain locked.
- V3 Milestone 1 may create only this contract, registries, traceability, metadata-only coverage/power audit, state, and seals.
- No development outcome may be read, reconstructed, joined, summarized, or inferred in Milestone 1.

## 3. Outcome-blind sampling frame

V3 does not use the six rejected event families as sampling conditions or predictors. Each available session receives a fixed grid of 16 anchors at session-open plus `0, 15, ..., 225` minutes. The primary 15-minute response therefore ends no later than the frozen four-hour session close.

- Expected available session dates: 187 London and 187 New York.
- Expected anchors: 2,992 per session and 5,984 total before technical missingness.
- Feature windows are right-closed at the decision boundary: only one-second buckets with `bucket_end <= decision_at` may enter.
- Frozen windows are W60 and W900 seconds; neither may be selected or changed after outcome access.
- Anchors are identified before any outcome join and remain fixed even when predictors later become `UNKNOWN`.

## 4. Endpoint contract

- Primary endpoint for a later authorized discovery milestone: signed 15-minute XAUUSD displacement from the last complete one-minute bar available at the anchor to the close of the fifteenth subsequent complete bar.
- Diagnostics only: signed 5-, 30-, and 60-minute displacement.
- Secondary horizons cannot create or rescue a candidate.
- No stop, target, excursion, execution, trade, PnL, R multiple, or account return is defined.

## 5. Continuous feature policy

The frozen eligible registry contains ten signed standalone features and two non-directional modifiers. All are traceable to the reference book and existing sealed sources.

No outcome-derived threshold, discretization, sign inversion, feature repair, proxy substitution, or post-result transformation is permitted. Training-only robust scaling and winsorization are model mechanics, not feature-selection authority.

Deferred fields remain visible rather than silently omitted:

- COT positioning is deferred because the prior certified decision projection reported zero known COT decisions.
- Historical release surprise and upcoming-catalyst states are deferred because pre-event availability was not generally verified.
- ETF, central-bank, options/gamma, intraday open interest, and unscheduled-news histories remain unavailable.

## 6. Missing-data and point-in-time rules

- `UNKNOWN` is never converted to neutral or zero.
- No cross-date, future, backward, median, model-based, or cross-provider imputation is permitted.
- A W60 feature requires at least 57 valid one-second states where state observations are required; W900 requires at least 855.
- Flow ratios with a zero denominator are `UNKNOWN`, not zero.
- A terminal book feature requires the latest valid uncrossed `F_LAST` state at or before the anchor.
- Any continuous-matching crossed terminal state remains `UNAVAILABLE_TECHNICAL` until the next valid recovery state.
- Fundamental and structure facts require `available_at <= decision_at` and retain their original staleness and vintage rules.
- All transformations are fitted within each training fold only.

## 7. Frozen model order

### Stage 1 — standalone dose response

Exactly ten registered features per session are evaluated with a univariate Huber linear model:

- `epsilon=1.35`
- `alpha=0.0001`
- intercept enabled
- predictor winsorization at training-fold 1st/99th percentiles
- predictor scaling by training-fold median and MAD; standard deviation fallback only when MAD is zero
- outcome is never winsorized

Stage 1 is completed and sealed before Stage 2 begins.

### Stage 2 — bounded interactions

Exactly six preregistered interactions per session are evaluated regardless of Stage-1 results when their outcome-blind support floor passes. The model is hierarchical ridge regression containing both main effects and the frozen interaction score, with fixed `alpha=1.0`. No other interaction may be added.

## 8. Chronology-aware evaluation

The 38 frozen month-week blocks are ordered chronologically.

- Fold 1: train blocks 1-10; validate 11-19.
- Fold 2: train blocks 1-19; validate 20-28.
- Fold 3: train blocks 1-28; validate 29-38.
- Blocks 1-10 train the first model and receive no out-of-fold performance credit.
- Every transformation and coefficient is fitted independently inside the applicable training set.
- Session dates are the permutation clusters; month-week blocks are the bootstrap units.
- All anchors from one session date remain together.

## 9. Support floors

For each session and test:

- at least 150 distinct eligible session dates overall;
- at least 30 distinct month-week blocks;
- each validation fold has at least 35 dates and 480 complete anchors;
- each required calendar year 2022, 2023, and 2024 has at least 35 out-of-fold dates;
- Stage-1 predictor completeness is at least 80%;
- Stage-2 joint predictor completeness is at least 70%;
- both positive and negative predictor values occur on at least 40 dates;
- any failed support gate is `SUPPORT_FAIL` with no relationship statistic calculated.

## 10. Effect, uncertainty, multiplicity, and stability

Primary Stage-1 gates, all required:

1. Expected-sign out-of-fold Spearman correlation at least `0.08`.
2. Out-of-fold non-flat direction accuracy at least `0.54`.
3. Twenty-thousand month-week block bootstrap replicates; 95% lower bounds for both signed correlation and accuracy lift above zero.
4. One-hundred-thousand session-date cluster permutations; two-sided p-value.
5. Benjamini-Hochberg q-value at most `0.05`, separately by session and stage across the complete registered family.
6. Positive signed correlation in all three validation folds, at least two folds at or above `0.05`, and none below zero.
7. Positive signed out-of-fold correlation in each supported required year 2022-2024.
8. Expected coefficient sign in every fitted fold.

Primary Stage-2 gates add:

- out-of-fold signed-correlation improvement of at least `0.03` over the frozen main-effects model;
- out-of-fold MAE reduction of at least `1%`;
- the same uncertainty, multiplicity, fold, and annual stability requirements.

Five-, 30-, and 60-minute consistency is Holm-adjusted within each test and descriptive only.

## 11. Candidate policy

- `PASS` requires every frozen gate.
- `REJECT` records every failed gate.
- `SUPPORT_FAIL` records the exact outcome-blind deficiency.
- `INCONCLUSIVE` is permitted only for a sealed technical or power limitation explicitly defined before outcomes.
- At most two provisional, unvalidated candidates may advance per session; zero is acceptable.
- Ranking: lowest BH q, highest bootstrap lower correlation, highest accuracy, highest minimum fold correlation, greatest date support, lexical test ID.
- A development pass is not a validated edge and cannot authorize trading.

## 12. Power interpretation

The repeated anchors improve estimation but do not create 2,992 independent days. The metadata-only power audit must show both an optimistic anchor-independent bound and a conservative session-date-cluster bound. If the conservative detectable effect exceeds the minimum effect gate, the study is explicitly labelled underpowered for small effects rather than weakening the gate.

## 13. Milestone sequence

1. M1: contract, registries, traceability, coverage/power audit, state, seals.
2. M2: outcome-blind continuous predictor materialization and independent reproduction.
3. M3: one controlled 2021-2024 outcome opening and frozen Stage-1/Stage-2 discovery.
4. M4: candidate freeze and pre-holdout readiness, only if M3 produces a pass.
5. M5: exposed 2025 historical forward test, only under separate authorization.
6. M6: locked 2026 evaluation/prospective tracking, only under separate authorization.

## 14. Prohibitions

No outcome access in M1/M2; no 2025/2026 access; no feature additions after freeze; no retuning, inversion, repair, selective filtering, opaque model, execution optimization, trades, PnL, R multiples, position sizes, or return claims.
