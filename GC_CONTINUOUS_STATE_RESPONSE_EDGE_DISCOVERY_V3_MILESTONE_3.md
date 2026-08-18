# GC Continuous State-Response Edge Discovery V3 — Milestone 3

## Mandate

Milestone 3 is the single controlled 2021-11-08 through 2024-12-13 development-outcome opening authorized after the sealed Milestone 2-R1 support recertification. It tests continuous point-in-time predictors against subsequent XAUUSD displacement. It does not construct trades or inspect 2025 or 2026.

## Frozen populations

- Exactly 5,984 anchors: 2,992 London and 2,992 New York.
- Exactly nine support-eligible Stage-1 predictors per session.
- Exactly five support-eligible Stage-2 interactions per session.
- `CSR_STRUCTURE_MOMENTUM_15M`, `CSR_SESSION_LEVEL_TENSION`, and `CSR_INT_OFI_SESSION_LEVEL_TENSION` remain explicit `SUPPORT_FAIL` and receive no outcome calculation.

## Outcome construction

For an anchor at `decision_at`, the start price is the close of the exact complete XAUUSD one-minute bar `[decision_at-1m, decision_at)`. A horizon H endpoint is the close of the Hth exact subsequent complete bar in `[decision_at, decision_at+H)`. The displacement is endpoint close minus start close at an exact `1e9` fixed-point scale.

Primary H is 15 minutes. Five, 30, and 60 minutes are diagnostics only. Every usable path minute must be unique, complete, point-in-time valid, and from the unchanged sealed IC Markets MT5 source. A missing or invalid minute makes only the affected frozen anchor/horizon `UNKNOWN`; the anchor is never repaired, dropped from the registry, gap-skipped, interpolated, imputed, or filled from a substitute source. Missing diagnostic horizons are excluded only from their own diagnostics and cannot fail or rescue a primary result. Exact zero is neutral for direction accuracy; neutral observations remain in rank statistics and are excluded only from the non-flat accuracy denominator.

Before any relationship statistic, the 15-minute outcome intersection for each test must retain its frozen Stage-1 80% or Stage-2 70% completeness floor, at least 150 dates and 30 blocks, at least 35 dates and 480 anchors in every validation fold, and at least 80% of each predictor-eligible OOF-year date universe. Failure is `INCONCLUSIVE_OUTCOME_COVERAGE`; no relationship statistic is calculated for that test.

## Stage 1

Each eligible predictor is evaluated independently within each session and frozen chronological fold. Training-only predictor processing uses linear 1st/99th percentile winsorization, median centering, and unscaled MAD; population standard deviation is used only when MAD is zero. A deterministic Huber IRLS regression uses `epsilon=1.35`, slope penalty `alpha=0.0001`, an unpenalized intercept, tolerance `1e-10`, and at most 1,000 iterations.

The directional dose score is the expected-sign-adjusted transformed predictor. It—not an outcome-selected threshold—is used for Spearman correlation and non-flat direction accuracy. The Huber slope supplies the frozen expected-coefficient-sign gate.

## Stage 2

Every eligible interaction is evaluated after the complete Stage-1 family is sealed. Both inputs receive the same training-only transformation. The registered interaction formula is unchanged. A hierarchical ridge model contains both transformed main effects and the interaction, with `alpha=1.0` and an unpenalized intercept. A separately fitted ridge main-effects model supplies the frozen incremental-correlation and MAE comparisons.

## Uncertainty and multiplicity

- Twenty thousand fixed-rank month-week-block bootstrap replicates. The rank vectors are calculated once from the complete OOF sample, blocks are sampled with replacement, and weighted rank correlation and accuracy lift are recomputed. Linear 2.5% and 97.5% quantiles are used; at least 19,000 finite replicates are required.
- One hundred thousand session-date-cluster permutations. Outcome date vectors are permuted within their chronological validation fold and identical anchor-offset signature. All anchors on a date move together. The two-sided p-value uses `(1 + exceedances)/(R + 1)`.
- Base seeds are deterministic unsigned 64-bit values derived from SHA-256 of the frozen branch, session, stage, test ID, and method. Each horizon permutation uses the unsigned first eight bytes of `SHA256(base_seed|Hhorizon)`. All seeds are recorded before outcome access and NumPy PCG64 is frozen.
- Benjamini-Hochberg is applied separately to the complete support-eligible family within each session and stage.
- Five-, 30-, and 60-minute permutation diagnostics are Holm-adjusted within each test and cannot create or rescue a candidate.

## Decision gates

All original V3 gates remain required. Stage 1 requires signed OOF Spearman at least 0.08, non-flat direction accuracy at least 0.54, positive bootstrap lower bounds for correlation and accuracy lift, BH q at most 0.05, positive rho in all folds, at least two folds with rho at least 0.05, positive rho in 2022, 2023, and 2024, and an expected-sign Huber slope in every fold.

Stage 2 requires those gates plus full-model OOF Spearman improvement of at least 0.03 over the main-effects ridge model and OOF MAE reduction of at least 1%.

An eligible test is `INCONCLUSIVE` only if a preregistered outcome-coverage, model-convergence, or finite-resampling technical gate fails. Otherwise it is `PASS` only if every gate passes, and `REJECT` records every failed gate.

## Locks

Stage 1 is fully sealed before Stage 2. No feature, test, sign, transformation, model, threshold, seed, fold, support disposition, or ranking may change after outcome access. At most two provisional development candidates per session may advance. Calendar 2025, calendar 2026, execution, entries, exits, trades, PnL, R multiples, account returns, and target-return claims remain locked.
