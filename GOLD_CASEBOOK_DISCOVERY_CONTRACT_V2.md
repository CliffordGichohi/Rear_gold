# Gold Casebook Discovery Contract V2

## Status and authority

This is a new research contract. It does not amend, erase, rename, or reopen the
completed Gold Casebook Directional-Discovery Research Contract.

The prior universal candidate, `UNIVERSAL_ZN_4H_SIGN_V0_1`, retains its frozen
verdict:

**`REJECT_CHRONOLOGICAL_VALIDATION`**

The authoritative evidence remains:

- `GOLD_CASEBOOK_MILESTONE_6.md`;
- `research_manifests/gold_casebook_chronological_validation_v01.json`; and
- `research_artifacts/gold_casebook_chronological_validation_v01/manifest.json`.

The rejection applies to the universal London-and-New-York package exactly as
tested. Nothing in this contract converts that result into a pass.

This V2 contract was authorized on 29 July 2026 by the following instruction:

> Create the Gold Casebook Discovery Contract V2. Preserve the original
> rejection, treat 2021-2024 as development, recognize London ZN as a post-hoc
> candidate with no 2024 validation credit, separate London and New York, keep
> execution constant, and keep 2025 locked. Complete only the contract and
> coverage audit first. Do not begin relationship discovery or inspect 2025
> outcomes.

The machine-readable freeze is
`research_manifests/gold_casebook_discovery_contract_v02.json`.

Canonical contract-manifest hash:

`81e39b469111bb92a46c0d2c70f863cba438b647345104d4b8e8bc1a9e4d8188`

## Research objective

Determine, from point-in-time data, which transparent conditions consistently
select London and New York gold direction when execution is held constant.

This is a search for an information edge. It is not a search for a requested
return, leverage level, reward-to-risk ratio, stop, target, or attractive
backtest chart.

The Gold & USD Market Intelligence Reference Book remains authoritative for:

- domain vocabulary;
- required data and timestamps;
- causal channels worth recording;
- epistemic labels;
- point-in-time rules; and
- explanation requirements.

It is not an instruction to force a preferred relationship, sign, or result.
The data may confirm, contradict, qualify, or fail to support a book-consistent
channel.

## Preserved prior evidence

The following facts are immutable inputs to this new branch:

1. `UNIVERSAL_ZN_4H_SIGN_V0_1` was rejected with eight of ten gates passing.
2. New York failed direction-mapping consistency and early-half stability.
3. London passed every individual frozen 2024 gate.
4. London was not a separately frozen candidate before calendar 2024 was
   opened.
5. Selecting London after seeing the session split is post-hoc and receives no
   independent validation credit from 2024.
6. Calendar 2025 was not opened by the prior branch.

The rejected universal rule and a New-York-only clone of its four-hour ZN sign
mapping may not be renamed, lightly filtered, or retuned in V2.

## Time partitions

### Development: 2021-08-01 through 2024-12-31

All immutable casebook records from `2021-08-01T00:00:00Z` through
`2025-01-01T00:00:00Z` are development data in V2.

Calendar 2024 is reclassified as development because it has already been
observed. It may be used for description, relationship discovery, and internal
stability analysis, but it may never again be described as untouched,
out-of-sample, or independent validation data.

### Locked holdout: calendar 2025

Calendar 2025 remains the one-time untouched holdout.

Before the final candidate rules, feature lineage, missing-data policy,
execution definition, costs, and pass/reject gates are frozen, no process may:

- read 2025 OHLC or market values;
- calculate 2025 direction, return, P&L, excursion, or session outcome;
- calculate a 2025 feature value;
- join a 2025 feature to a 2025 outcome;
- rank or filter a candidate using 2025; or
- inspect a chart or row-level payload that reveals 2025 price behaviour.

A metadata-only coverage audit is permitted. It may inspect only filenames,
hashes, byte sizes, row counts, source/provider identifiers, time bounds,
timestamp completeness, non-null counts, synthetic flags, and point-in-time
ordering counts.

The audit must not select or deserialize price-value, release-value,
position-value, forecast-value, or probability columns.

### Calendar 2026

Calendar 2026 is outside V2 development and holdout. It must not be used to
repair a failed 2025 result or to influence the V2 shortlist.

## Independent session research units

London and New York are separate research units.

- A London candidate receives a London verdict.
- A New York candidate receives a New York verdict.
- One session is not rejected merely because the other fails.
- Combined statistics are descriptive only and cannot override a session
  failure.
- Candidate selection, controls, uncertainty, stability, and holdout gates are
  reported separately by session.

This corrects the packaging error in the prior universal experiment without
rewriting its result.

## Frozen constant execution

V2 inherits, without modification:

`research_manifests/gold_casebook_constant_execution_v01.json`

Canonical execution-manifest hash:

`724a4fef0fa4b526b4d30b9743c2dfa013c53f87b19262a36b05f3fd07c87d76`

For both sessions:

- decision: 08:00 in the session's IANA timezone;
- entry: the 08:01 one-minute bar;
- exit: the fixed 12:00 local session clock;
- instrument/provider: IC Markets MT5 XAUUSD one-minute bars;
- notional: one ounce, equivalent to 0.01 lot under the declared 100-ounce
  contract convention;
- spread: observed entry and exit spreads;
- slippage: USD 0.05 per ounce per side;
- commission: USD 7.00 per lot round turn;
- no stop, target, early exit, leverage, account scaling, or reward-to-risk
  optimization; and
- the same incomplete-session and overlap policies as the frozen manifest.

Execution cannot change anywhere in V2 discovery, internal validation, or the
2025 holdout. Execution research is a later contract and is permitted only for
a candidate that passes its session-specific 2025 holdout.

## Post-hoc London candidate

V2 recognizes exactly one inherited post-hoc candidate:

`LONDON_ZN_4H_POSTHOC_V0_1`

Its frozen definition is:

- session: London only;
- feature: `cross_zn_v_0_4_hours`;
- ZN four-hour change positive: `LONG`;
- ZN four-hour change negative: `SHORT`;
- zero, unavailable, stale, non-ready, or continuous-contract-roll input:
  `NO_BIAS`;
- no threshold;
- no ZT fallback;
- no confirmation variable;
- no session or volatility filter; and
- frozen constant execution.

Its 2021-2024 evidence is development evidence only. Its positive 2024 London
result receives zero validation credit because London was selected after the
universal result was known.

The rule may occupy at most one of the two London shortlist slots. It may not be
retuned before or after the 2025 holdout.

## Bounded discovery policy

Relationship discovery must be data-first and bounded.

- Use only fields already recorded in the immutable casebook or explicitly
  added under a point-in-time, versioned data amendment before their outcomes
  are inspected.
- Freeze the feature registry, transforms, states, interactions, support gates,
  uncertainty method, multiplicity method, and ranking order in a
  machine-readable manifest before Milestone 3 results are calculated.
- Evaluate individual variables first.
- A candidate rule may contain no more than two transparent conditions.
- No opaque machine-learning selector is permitted.
- Missing, stale, roll-crossing, or unavailable inputs remain `UNKNOWN` and
  cannot be treated as confirmation.
- A result must be reported even if it is negative.
- A failed hypothesis ends; it does not trigger threshold mining.
- The requested economic return, including 10R or 10% per month, is not a
  discovery objective and cannot be a ranking criterion.

The exact numerical support, cluster-bootstrap, multiplicity, walk-forward,
cost-stress, and promotion gates must be frozen before the corresponding
milestone opens. They cannot be selected after seeing the result.

## Candidate and holdout budget

Before calendar 2025 is opened:

- at most two London candidates may be frozen;
- at most two New York candidates may be frozen;
- `LONDON_ZN_4H_POSTHOC_V0_1` may consume one London slot;
- every candidate must have an explicit `LONG`, `SHORT`, and `NO_BIAS` mapping;
- every candidate must state its highest-risk assumption and invalidation
  evidence;
- all candidates must use the same constant execution; and
- the candidate-specific 2025 source coverage must be complete or the
  candidate is blocked before holdout access.

The 2025 holdout is opened once for the entire frozen shortlist. It cannot be
used to choose which candidate to report. Each session/candidate receives an
honest pass or rejection under predeclared multiplicity-aware gates.

No 2025 repair, threshold change, feature addition, session switch, execution
change, or candidate replacement is permitted.

## Research milestones

### V2 Milestone 1: Contract and metadata-only coverage audit

Produce:

- this human-readable contract;
- its machine-readable manifest;
- a deterministic development/holdout coverage report;
- source and artifact hashes;
- an explicit list of data that is present, missing, or only partial; and
- evidence that no 2025 outcome or value column was inspected.

No outcome atlas, relationship discovery, candidate ranking, or holdout
calculation is permitted.

### V2 Milestone 2: Descriptive outcome atlas

Using 2021-2024 only, record how fixed-clock London and New York outcomes are
distributed through time. This milestone describes the target separately by
session and does not test explanatory relationships or optimize execution.

Its measurement manifest must be frozen before the atlas is calculated.

### V2 Milestone 3: Bounded relationship discovery

Freeze the eligible field and interaction universe, then rank transparent
point-in-time relationships separately for London and New York using the
constant outcome.

### V2 Milestone 4: Internal expanding walk-forward stability

Test candidate-generation stability through chronological development folds.
Because all 2021-2024 data is development data, this is internal stability
evidence, not independent validation.

### V2 Milestone 5: Shortlist freeze

Freeze no more than two candidates per session, their rules, data lineage,
execution, costs, missing-data policy, controls, and exact 2025 pass/reject
gates. A session may freeze zero candidates.

### V2 Milestone 6: One-time calendar-2025 holdout

Acquire and seal any missing candidate-specific 2025 inputs without examining
outcomes, verify their hashes and completeness, then open the holdout once.
Record a pass or rejection for every frozen candidate and stop.

### V2 Milestone 7: Execution research

This milestone requires a new explicit authorization and is eligible only for a
session-specific candidate that passes Milestone 6. It may study entry,
invalidation, stop, target, and exit logic using a new untouched or prospective
validation plan.

## Promotion principles

A shortlist candidate must, under gates frozen before its results:

- be point-in-time correct with zero unresolved lineage errors;
- have adequate case and independent week support;
- be positive after frozen costs;
- beat the relevant same-period always-long and always-short controls;
- retain its intended directional mapping;
- demonstrate chronological and calendar stability;
- report cluster-aware uncertainty;
- survive the frozen cost stress;
- survive the declared multiple-testing procedure; and
- remain simple enough to explain from its structured evidence.

Passing development gates does not establish an edge. Only the untouched
session-specific 2025 result can provide the first independent validation in
V2.

## Reproducibility and operating protocol

Every milestone must produce:

1. a pre-result machine-readable manifest;
2. content-addressed artifacts;
3. an independent validator where outcomes are calculated;
4. exact commands and test evidence; and
5. a short checkpoint stating artifact, path, result or blocker, and next
   milestone.

Repository artifacts, not conversational memory, are the source of truth.

Work only on one authorized milestone at a time. Do not automatically continue
because a milestone passes. Do not add data, features, filters, candidates, or
research branches without a recorded amendment.

## Current status

V2 Milestone 1 is the only authorized milestone.

It ends after the contract and metadata-only coverage audit are complete.
Milestone 2 must not begin without a new explicit user instruction.
