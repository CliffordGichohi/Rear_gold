# Gold LONG Multi-Opportunity Auction Lifecycle and Structural Profit-Protection Research V1

Status: implementation protocol to be sealed before exposed path calculation.

## Objective

Determine why the frozen working LONG control produces positive but modest returns and whether two bounded, observable changes improve monetization without changing its model, thresholds, initial geometry, costs, or LONG direction:

1. permit distinct later LONG auction opportunities after the prior position has resolved; and
2. replace fixed-R protection with completed-M5 governing-structure failure and protection.

This is an exposed 2022 regression study. It creates no validation credit and must not open another date.

## Frozen population and exclusions

- Use only the 95 already-opened trading days from 2022-01-03 through 2022-02-16 and 2022-03-01 through 2022-05-31.
- Preserve the frozen LONG control exactly, including its one London trade, for reproduction and comparison.
- Search for additional opportunities only in New York, 08:00 through 12:00 America/New_York.
- SHORT is quarantined. No SHORT probability, signal, trade, displacement, or result may enter this branch.
- Keep 2022-02-17 through 2022-02-28, the random 50-case block, 2025, and 2026 closed.
- Acquire no data and incur no charge.

## Opportunity identity

Use the existing frozen translator, preprocessing, probability threshold 0.90, geometry trees, family router, actual-fill 1.5R room gate, costs, latency, target, initial stop, and deadline unchanged.

A later opportunity is emitted only when either:

- the LONG probability has remained below 0.90 for 15 consecutive one-minute checkpoints and then reaches 0.90; or
- while probability remains at least 0.90, a newly active completed-candle M15 bullish-structure identity appears.

Remaining above threshold cannot produce repeated minute-by-minute opportunities. A signal formed while a position is open is recorded as overlap and cannot be deferred. Re-entry requires a later independently emitted opportunity. Positions never overlap.

## Structural management

- Direction is LONG only.
- Entry, original structural stop, original absolute target, quantity, cost convention, and UTC-day deadline remain unchanged.
- The governing M5 low at entry is the latest causally confirmed M5 swing low.
- A completed bullish M5 structural break may advance the stop to its confirmed protected low minus max(0.05 M5 ATR, $0.02). Stops never move lower.
- A completed bearish M5 structural break of the current governing-low identity exits all remaining quantity at the next M1 open.
- Same-bar ambiguity remains stop-first.
- The existing 80/20 target/runner split and target-acceptance requirement remain. No hindsight maximum, future swing, MFE, MAE, or realised archetype may influence a decision.

## Four required tracks

1. `FROZEN_LONG_CONTROL`: exact sealed current result.
2. `MULTI_OPPORTUNITY_CONTROL_MANAGEMENT`: later opportunities, existing management.
3. `FIRST_OPPORTUNITY_STRUCTURAL_MANAGEMENT`: original opportunity only, structural management.
4. `MULTI_OPPORTUNITY_STRUCTURAL_MANAGEMENT`: later opportunities plus structural management.

Report all emitted, rejected, overlapping, and executed opportunities. Attribute the incremental result in the stated order: additional opportunity count, additional-opportunity PnL, management delta on original trades, and management delta on later trades.

## Checkpoint and reproduction contract

- Freeze source hashes, ordered population, implementation, tests, and this protocol before calculating results.
- Run primary and reference passes sequentially.
- Write one immutable checkpoint per session-day and pass. Each record contains the prior checkpoint hash, day identity, result hash, and cumulative count.
- Resume only after verifying the full checkpoint hash chain and frozen source hashes. Never rewrite or silently skip a completed day.
- Maintain an atomic status file identifying phase, pass, completed days, remaining days, and last checkpoint. `status` reads only technical artifacts.
- Print a progress line after every completed day.
- Finalize only after all 95 primary and 95 reference checkpoints agree exactly by row identity, contents, diagnostics, and checksums.

## Interpretation gates

This exposed study may recommend freezing a policy for a later unopened chronological month only if the combined track:

- improves net R over the exact control;
- has positive expectancy and profit factor at least 1.10;
- remains positive at 1.5x costs;
- does not worsen maximum drawdown by more than 25%;
- is positive in at least three represented calendar-month segments; and
- does not derive more than 70% of positive gross R from one month.

Failure preserves the working LONG control and rejects only the added mechanism. No threshold repair, alternative buffer, second rearm interval, trade deletion, or SHORT experiment is permitted in this run.
