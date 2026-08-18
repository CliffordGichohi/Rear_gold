# GC Session Trigger Edge Discovery V2 Milestone 3

Status: `AUTHORIZED_PRE_OUTCOME_FREEZE`

## Purpose

Milestone 3 is the single development relationship-discovery step authorized after the sealed V2-R1 verdict
`PASS_GC_SESSION_TRIGGER_EDGE_V2R1_TECHNICAL_CERTIFICATION`. It asks whether any of the six frozen event families has
directional information for the next fifteen minutes of XAUUSD and whether any already-registered one-context
interaction materially strengthens that relationship.

This milestone does not construct trades. A passing result is a provisional development candidate, not a validated
edge, execution rule, expected return, or account-return claim.

## Immutable predecessors

- Every verdict, artifact, rule, feature, event definition, context definition, support floor, seed rule, stability
  rule, ranking rule, and seal from Milestone 1 through V2-R1 remains unchanged.
- The V1 infrastructure branch remains terminated. V2-R1 is the sole technical input certification for this step.
- The development population is the 374 technically available London/New York sessions in the sealed 188-date sample
  from 2021-11-08 through 2024-12-13. The two Good Friday sessions remain documented unavailable.
- Calendar 2025 and calendar 2026 remain locked.

## Pre-outcome freeze

Before any forward XAUUSD or GC outcome value is read, Milestone 3 must seal:

1. the exact 374-session population and 4,950 technical event-row identities;
2. the exact subset of event rows whose V2-R1 quality state is `ELIGIBLE`;
3. all event-to-test assignments and all outcome-blind support classifications;
4. the exact point-in-time outcome join keys and required one-minute timestamps;
5. the missing-data, flat-outcome, clustering, uncertainty, multiplicity, stability, and ranking rules;
6. the complete Stage-1 and Stage-2 registry, including tests that failed outcome-blind support;
7. the implementation and every source/predecessor hash.

Any pre-outcome seal failure stops the milestone without opening outcomes.

## Outcome construction

- The anchor is the close of the complete IC Markets MT5 XAUUSD one-minute bar ending at `decision_at`.
- Primary outcome is the close ending at `decision_at + 15 minutes` minus the anchor close.
- Five-, thirty-, and sixty-minute displacements are consistency diagnostics only.
- Every complete one-minute bar after the anchor through a horizon is required. No interpolation, imputation, bridge,
  substitute provider, or endpoint-only shortcut is permitted.
- `UP` is displacement strictly above +0.01 USD/oz, `DOWN` strictly below -0.01, and `FLAT` otherwise.
- Any failed timestamp, uniqueness, completeness, availability, record-hash, provider, instrument, timeframe, or
  lineage gate makes only the affected horizon `UNKNOWN`.
- FLAT observations remain in continuous-displacement summaries and leave only binary hit-rate denominators.
- GC fifteen-minute midpoint agreement is consistency-only and cannot create or rescue a candidate.

The sealed XAUUSD source may be streamed once. Two independently implemented arithmetic paths must reproduce every
selected outcome and join exactly before testing begins.

## Stage 1

London and New York are separate multiplicity families. Each session has six pooled, two-sided event-family tests.
Each XAUUSD displacement is multiplied by the event's frozen directional prior. Stage 1 tests favorable-direction
probability against 0.50 using date-cluster sign randomization and selected-month-week block bootstrap uncertainty.

All twelve Stage-1 families are outcome-blind support eligible and must be evaluated. A family can advance only when
every frozen hit-rate, uncertainty, multiplicity, bullish/bearish symmetry, calendar stability, block stability,
first-event, median-displacement, and cross-venue non-contradiction gate passes.

Stage 1 must be independently reproduced and sealed before Stage 2 begins.

## Stage 2

The registry contains sixty event-by-one-context interactions. Only the twenty-six interactions classified
`SUPPORT_ELIGIBLE` by the sealed V2-R1 support report may be evaluated. The other thirty-four remain explicit
`SUPPORT_FAIL` records and receive no outcome-conditioned calculation or p-value.

For an eligible interaction, the condition group is compared with the same event family when the registered context
is known but not aligned. UNKNOWN context rows are excluded and reported. Stage 2 tests favorable hit-rate lift and
favorable median-displacement lift under the same frozen cluster, multiplicity, symmetry, and stability governance.

## Inference and selection

- Primary cluster-bootstrap unit: the 38 sealed selected month-week blocks, 20,000 deterministic resamples.
- Primary randomization unit: session date; all events on a date flip direction together, 100,000 deterministic
  repetitions.
- Multiplicity: Benjamini-Hochberg at q <= 0.05, separately by session and stage, across every support-eligible
  primary-endpoint test in that family.
- Secondary 5/30/60-minute p-values use Holm adjustment within each primary test and cannot affect advancement.
- Annual stability uses only 2022, 2023, and 2024 when the frozen support floor is met; 2021 is descriptive.
- Ordered block stability uses blocks 01-10, 11-20, 21-29, and 30-38.
- At most two passing provisional candidates per session may be retained under the frozen ranking order. Zero is valid.

## Prohibitions and stop

Do not add, remove, invert, retune, repair, rename, or selectively filter a test, event, context, threshold, outcome,
or candidate. Do not inspect 2025 or 2026. Do not optimize execution or calculate entries, fills, stops, targets,
trades, PnL, R multiples, position sizes, or account returns. Do not acquire data or incur a charge.

After complete independent reproduction, seal an honest result and stop.
