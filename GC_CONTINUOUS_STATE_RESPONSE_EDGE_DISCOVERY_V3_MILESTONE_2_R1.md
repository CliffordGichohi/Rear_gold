# GC Continuous State-Response Edge Discovery V3 — Milestone 2-R1

## Scope

This is a narrow, outcome-blind support-feasibility and source-coverage disposition amendment to the sealed Milestone 2 result. It preserves `PASS_V3_M2_OUTCOME_BLIND_PREDICTOR_MATERIALIZATION`, all 5,984 anchor rows, all 12 predictors, transformations, chronological folds, tests, interactions, missing-data rules, model gates, artifacts, verdicts, and seals.

Milestone 2-R1 does not open or join development outcomes. It does not access 2025 or 2026, acquire data, create candidates, calculate relationships, optimize execution, or calculate trades or PnL.

## Sole support-gate amendment

The structurally infeasible `each_required_year_oof_dates_gte_35` rule is replaced by `each_required_year_oof_coverage_gte_80pct`.

For each session and calendar year 2022, 2023, and 2024:

1. The denominator is the complete set of frozen out-of-fold session dates assigned to that calendar year by the unchanged blocked-fold registry, independent of predictor availability.
2. The numerator is the number of those dates on which the predictor, or both members of a registered interaction, is available.
3. The minimum is `ceil(0.80 × denominator)`.
4. Every numerator, denominator, minimum, percentage, and disposition is reported.

Every other support, model, stability, uncertainty, multiplicity, ranking, and candidate rule remains unchanged.

## Metadata-only source-coverage disposition

The diagnostic is limited to `CSR_STRUCTURE_MOMENTUM_15M`, `CSR_SESSION_LEVEL_TENSION`, and registered interactions containing either field. It may access only anchor identities, timestamps, session/DST metadata, availability codes, available-at timestamps, lineage hashes, frozen window requirements, and the timestamp/quality metadata of the existing sealed XAUUSD one-minute source.

Each unavailable anchor receives exactly one disposition:

- `RECOVERABLE_EXISTING_SEALED_SOURCE`: every frozen required minute is present and point-in-time valid, but the sealed predictor remains technically unavailable.
- `REQUIRES_ADDITIONAL_SOURCE`: at least one required minute lies outside the local UTC-date envelope of the existing sealed valid-minute source.
- `DEFINITION_INDUCED_UNAVAILABLE`: required price timestamps are present, while a frozen non-price requirement or explicit formula-domain rule remains unavailable.
- `GENUINE_SOURCE_GAP`: all missing required minutes lie inside their respective local UTC-date source envelopes.
- `UNRESOLVED`: the metadata does not satisfy exactly one of the preceding rules.

No source record is repaired, replaced, filtered, relabelled, or acquired. At most one bounded recovery path may be recommended, but it is not implemented here.

## Decision rule

Milestone 2-R1 passes only if predecessor seals remain valid, the amendment was sealed before R1 row access, both independent readers agree exactly, all unavailable target anchors receive one frozen disposition, no forbidden source is opened, and the amended eligible-test registry is reproduced exactly. The report must state whether each session has at least one preregistered test eligible for Milestone 3.

