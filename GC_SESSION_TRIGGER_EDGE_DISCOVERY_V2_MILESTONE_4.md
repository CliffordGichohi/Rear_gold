# GC Session Trigger Edge Discovery V2 — Milestone 4

## Purpose

Milestone 4 is a negative-result attribution audit of the sealed Milestone 3-R1 result artifacts. It does not reopen market sources, discover relationships, create candidates, or alter the Milestone 3-R1 zero-candidate verdict.

## Frozen population

- 72 registered Milestone 3 tests remain recorded.
- 34 Stage-2 tests that failed outcome-blind support remain `SUPPORT_FAIL` and are not reinterpreted.
- Exactly 38 `SUPPORT_ELIGIBLE` tests with the sealed verdict `REJECT` are audited: 19 London and 19 New York.
- Calendar 2025 and 2026 remain locked.

## Ordered formal gates

The original advancement gates are attributed in their frozen order:

1. `frozen_effect_threshold`
2. `bootstrap_effect_lower_bound`
3. `bootstrap_median_lower_bound_gt_zero`
4. `bootstrap_finite_effect_gte_19000`
5. `bootstrap_finite_median_gte_19000`
6. `bh_q_lte_0_05`
7. `directional_symmetry`
8. `annual_stability`
9. `block_stability`
10. `first_event_sensitivity`
11. `gc_not_statistically_opposite`

The 5-, 30-, and 60-minute results remain consistency diagnostics and are never retroactively promoted into formal Milestone 3 gates.

## Frozen attribution taxonomy

Each of the 38 rejected tests receives exactly one descriptive classification:

- `STATISTICALLY_CREDIBLE_REJECTED_OTHER_ROBUSTNESS`: every frozen statistical-credibility gate passed, but at least one other formal robustness gate failed.
- `NO_MEASURABLE_RELATIONSHIP`: the original frozen minimum effect threshold failed.
- `UNSTABLE_RELATIONSHIP`: the minimum effect threshold passed, but directional symmetry, annual stability, chronological-block stability, first-event robustness, or the frozen horizon diagnostic was inconsistent.
- `POTENTIALLY_MEANINGFUL_BUT_UNDERPOWERED`: the minimum effect threshold passed and stability diagnostics did not contradict it, but uncertainty or multiplicity gates failed.

This ordering is deterministic and is not a candidate-ranking rule. “No measurable relationship” means no relationship above the original minimum effect threshold; it is not a universal statement that the feature has exactly zero association.

## Horizon diagnostic

The secondary-horizon diagnostic is `CONSISTENT` only when all three secondary effects are available, at least two are favorable, and none is materially opposite at or below -5 percentage points. It is `MIXED_OR_CONTRADICTORY` otherwise, or `INSUFFICIENT` when any secondary effect is unavailable. This diagnostic cannot change the original verdict.

## Descriptive near-miss ordering

For audit visibility only, rejected tests are ordered within each session by fewest failed formal gates, lowest BH-adjusted q-value, largest primary effect, then lexical test ID. This ordering creates no candidate and receives no validation credit.

## Bounded V3 recommendation rule

Exactly one design is selected from the dominant attribution category across all 38 tests. Ties use this fixed priority: no measurable relationship, instability, underpowered, statistically credible but rejected by robustness.

- Dominant no-measurable result → transparent continuous state-response discovery.
- Dominant instability → preregistered time/regime stability discovery.
- Dominant underpowered result → outcome-blind development-sample expansion.
- Dominant statistically credible but robustness-rejected result → targeted unchanged robustness replication.

The selected design is a research-plan recommendation only. It is not a relationship, candidate, signal, or edge.

## Prohibitions

No market-source reopening, source acquisition, outcome reconstruction, test retuning, inversion, repair, candidate creation, 2025/2026 access, execution optimization, trades, PnL, R multiples, or account returns are permitted.
