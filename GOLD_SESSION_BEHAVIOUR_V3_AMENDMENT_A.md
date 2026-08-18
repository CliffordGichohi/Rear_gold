# Gold Session Behaviour V3 — Amendment A

## Status and authority

This amendment is authorized solely for V3 Milestone 5 by the user's
instruction dated 2026-07-30.

It does not alter, reinterpret, or reverse the sealed Milestone 4 result:

- London M4 provisional candidates: zero
- New York M4 provisional candidates: zero
- M4 status: complete, independently reproduced, mandatory stop

The four Milestone 5 families are explicitly post-hoc hypotheses selected
from the already exposed 2021–2024 development results. They receive no
development-validation credit even if they pass internal stability.

## Exact authorized candidate families

No other candidate may be added, substituted, inverted, repaired, or
renamed.

### `LONDON_ASIA_DIRECTION_REVERSAL_V0_1`

- session: London
- condition: `SESSION_ASIA_DIRECTION = DOWN`
- exact complement: `SESSION_ASIA_DIRECTION = UP`
- excluded known state: `FLAT`
- expected effect: condition UP rate minus complement UP rate is positive
- M4 lineage:
  - `SINGLE__SESSION_ASIA_DIRECTION__DOWN`
  - `SINGLE__SESSION_ASIA_DIRECTION__UP`

### `LONDON_VOLATILITY_DIRECTION_V0_1`

- session: London
- condition: `MACRO_VOLATILITY_CHANGE = FALLING`
- exact complement: `MACRO_VOLATILITY_CHANGE = RISING`
- excluded known state: `UNCHANGED`
- expected effect: condition UP rate minus complement UP rate is positive
- M4 lineage:
  - `SINGLE__MACRO_VOLATILITY_CHANGE__FALLING`
  - `SINGLE__MACRO_VOLATILITY_CHANGE__RISING`

### `NEW_YORK_FINANCIAL_STRESS_DIRECTION_V0_1`

- session: New York
- condition: `MACRO_FINANCIAL_STRESS_CHANGE = FALLING`
- exact complement: `MACRO_FINANCIAL_STRESS_CHANGE = RISING`
- excluded known state: `UNCHANGED`
- expected effect: condition UP rate minus complement UP rate is positive
- M4 lineage:
  - `SINGLE__MACRO_FINANCIAL_STRESS_CHANGE__FALLING`
  - `SINGLE__MACRO_FINANCIAL_STRESS_CHANGE__RISING`

### `NEW_YORK_SOFR_CUT_2Y_FALLING_V0_1`

- session: New York
- exact condition:
  - `EXPECT_SOFR_WINDOW_CUT_HIKE_BALANCE = CUT_DOMINANT`
  - `MACRO_TREASURY_2Y_CHANGE = FALLING`
- complement: every other jointly known combination of those two frozen
  features
- expected effect: condition UP rate minus complement UP rate is positive
- M4 lineage: `INT_SOFR_CUT_2Y_FALLING`

The SOFR/2Y candidate is admitted as a post-hoc family by this explicit
amendment. This does not repair or erase its M4 constituent-support failure,
and M4 remains rejected. M5 tests the unchanged joint condition directly
under newly frozen post-hoc stability rules.

## Primary measurement

The primary outcome remains the frozen neutral `SESSION_CLOSE` direction:

- UP: signed close displacement greater than +$0.01/oz
- DOWN: signed close displacement less than -$0.01/oz
- FLAT: absolute displacement at or below $0.01/oz

Flat outcome cases are retained in path summaries and excluded from the
binary UP/DOWN contingency table. The primary effect is the condition UP
rate minus the exact frozen complement UP rate.

## Full-development support and effect gates

All gates are conjunctive.

- joint-known coverage: at least 50%
- condition binary cases:
  - at least 80 for a complementary-state single
  - at least 60 for the SOFR/2Y interaction
- complement binary cases: at least 80
- distinct condition source signatures: at least 8
- distinct complement source signatures: at least 8
- condition state episodes: at least 8
- complement state episodes: at least 8
- minimum full-development effect:
  - +7.5 percentage points for the three complementary-state candidates
  - +10.0 percentage points for SOFR/2Y
- Newcombe-Wilson 95% effect interval must exclude zero on the positive side
- condition median signed close displacement must be positive
- exact complementary-state median must be negative where applicable

## Multiplicity

One two-sided Fisher exact p-value is calculated for each of the four
families. Holm-Bonferroni step-down adjustment is applied across the fixed
family of four at alpha 0.10.

An unsupported candidate remains in the family with p=1.0. The family size
cannot shrink after support is observed. Adjusted p-values provide only an
internal screen because the hypotheses were selected post hoc.

## Calendar stability

The exact blocks are:

- 2021-08-01 through 2021-12-31
- calendar 2022
- calendar 2023
- calendar 2024

A calendar block is eligible only when it has:

- at least 12 condition binary cases
- at least 20 complement binary cases
- at least 50 combined binary cases
- at least 35% joint-known coverage

Calendar stability requires:

- at least three eligible blocks
- positive effect in at least 75% of eligible blocks
- median eligible-block effect of at least +3 percentage points
- no eligible block at or below the negative of the candidate's frozen
  full-development minimum
- the latest eligible block must be positive

## Rolling stability

Rolling blocks are deterministic:

- 126 chronological session rows per window
- 63 rows per step
- append one terminal 126-row window when the regular grid does not end on
  the final row

Each rolling block requires:

- condition cases:
  - at least 20 for a complementary-state single
  - at least 12 for SOFR/2Y
- complement cases: at least 30
- combined cases: at least 60
- joint-known coverage: at least 35%

Rolling stability requires:

- at least six eligible blocks
- positive effect in at least 70% of eligible blocks
- median effect of at least +3 percentage points
- no more than two consecutive eligible opposite-effect blocks
- the latest eligible block must be positive

Overlapping rolling blocks are stability diagnostics, not independent
observations and not a source of p-values.

## Ranking and shortlist

Passing candidates are ranked separately within London and New York by:

1. all gates passed
2. lower Holm-adjusted p-value
3. higher rolling positive-effect fraction
4. higher annual positive-effect fraction
5. larger full-development effect
6. larger condition support
7. candidate code

At most two candidates per session may be frozen. Zero is acceptable. Any
shortlisted item is labelled
`INTERNALLY_STABLE_POST_HOC_NO_FORWARD_VALIDATION_CREDIT`.

## Prohibitions

Milestone 5 may not:

- inspect 2025 or 2026 values
- optimize entry, exit, stop, target, sizing, execution, or costs
- calculate trades, returns, PnL, or R multiples
- use COT as a pass gate
- add, substitute, repair, invert, or retune a candidate
- change block construction or thresholds after chronology is observed
- reopen any rejected ZN rule

Milestone 5 ends after internal stability, shortlist freeze, independent
validation, documentation, and state sealing. Milestone 6 requires separate
explicit authorization.
