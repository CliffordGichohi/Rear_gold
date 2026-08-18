# Gold Casebook Directional-Discovery Research Contract

## Status and authority

This document is the governing contract for the next Gold Market Intelligence
Engine research phase. It supersedes ad hoc strategy searches but does not erase
their evidence. The Gold & USD Market Intelligence Reference Book remains the
business and market-logic specification.

No new strategy family, execution optimization, dataset purchase, or holdout
inspection may be introduced without recording the reason and changing this
contract explicitly.

## Authorized amendment 1: exploratory universal ZN case

On 29 July 2026, before any combined-selector result was calculated, the user
explicitly authorized this narrow amendment:

> Approved. Amend the research contract only to permit the universal four-hour
> ZN-direction rule as an exploratory Milestone 5 candidate. Retain every other
> restriction, freeze the rule without retuning, keep 2024 untouched until
> Milestone 6, and keep 2025 locked.

This amendment permits exactly one exploratory case specification:

- use only the predeclared `cross_zn_v_0_4_hours` feature;
- apply the same rule to London and New York;
- map `POSITIVE` to `LONG`, `NEGATIVE` to `SHORT`, and `FLAT` or `UNKNOWN`
  to `NO_BIAS`;
- treat non-ready, stale, unavailable, or continuous-contract-roll inputs as
  `UNKNOWN`, never as neutral confirmation;
- retain the Milestone 3 execution definition unchanged; and
- label every result exploratory unless it later passes chronological
  validation and the untouched holdout.

The amendment does not permit a ZT fallback, a ZT/ZN confirmation interaction,
session-specific proxy selection, threshold fitting, feature addition,
execution optimization, or inspection of conditional 2024 or 2025 outcomes
during Milestone 5. All other provisions of this contract remain in force.

## Objective

Determine whether information known at a London or New York decision clock can
select a profitable `LONG`, `SHORT`, or `NO_BIAS` case when execution is held
constant.

The research must separate:

1. **information edge** — whether the recorded case selects direction;
2. **execution edge** — how a validated directional case may later be entered,
   invalidated, managed, and exited.

Execution research is out of scope until a directional case passes the gates in
this document.

## Non-objectives

This phase will not:

- optimize reward-to-risk, entries, stops, or targets;
- search for a requested return by increasing risk;
- treat a descriptive correlation as a validated forecast;
- force a long or short decision on every session;
- use information that became available after the decision clock;
- open calendar 2025 before the complete directional specification is frozen;
- present inferred institutional behaviour as observed fact.

## Casebook units

The casebook contains separate, joinable records for:

- London sessions;
- New York sessions;
- scheduled and unscheduled market events;
- weekly positioning states; and
- versioned point-in-time fundamental and cross-market snapshots.

Each session case has an immutable identifier, source-data hash, calculation
version, decision timestamp, availability timestamp, session timezone, and data
quality state.

## Required recorded evidence

### Raw price and session state

- complete XAUUSD one-minute bars and normalized 5-minute, 15-minute, 1-hour,
  4-hour, and daily bars;
- provider, symbol, source record key, bid/ask spread where observed, tick
  activity, missing bars, and session completeness;
- Asia, London, New York, overlap, LBMA, rollover, COMEX, and session-close
  clocks using IANA timezones;
- session open, high, low, close, range, and prior-session relationships;
- prior-day and prior-week high, low, open, close, and range.

### Market structure

- confirmed swing highs and lows;
- higher highs, higher lows, lower highs, and lower lows;
- ranges, support, resistance, and known liquidity levels;
- break of structure and market-structure shift;
- compression, expansion, displacement, and momentum;
- breakout, acceptance, rejection, failed breakout, trapped-breakout state, and
  retest;
- Asian, London, New York, prior-day, and prior-week level interactions; and
- timestamp, price level, timeframe, detection time, method, confidence,
  evidence, and invalidation for every structure detection.

Structure that is confirmed only by later bars must retain both its pivot time
and its later detection time. It is unavailable to an earlier decision.

### Fundamentals and expectations

- CPI, core CPI, PCE, core PCE, payrolls, unemployment, wages, claims, GDP,
  retail sales, and policy-rate state;
- event timestamp, period, forecast, actual, previous, revision, surprise,
  vintage, and first-known time;
- 2-year and 10-year nominal yields, 10-year real yield, breakeven inflation,
  yield-curve state, and changes over declared horizons;
- Fed-path and policy-futures state, including repricing rather than levels
  alone;
- reaction-function classification, dominant driver, contradictions, freshness,
  and evidence coverage.

### Positioning

- CFTC managed-money longs, shorts, net position, weekly changes, percentile,
  total open interest, and commercial positioning where available;
- Tuesday observation date, Friday publication timestamp, ingestion timestamp,
  and eligible first-use time;
- crowding, acceleration, price/positioning divergence, and liquidation or
  short-covering risk, always classified as calculated or inferred rather than
  observed fact.

### Cross-market and event context

- EURUSD or the declared USD proxy, silver, equities, volatility/risk proxy,
  ZT, ZN, ZQ, and SR3 state where available;
- values and changes known before the decision;
- upcoming-event risk and time since the last eligible release;
- post-release gold, USD, and rates reaction stored only after it becomes known.

### Epistemic and quality fields

Every material field must record:

- `OBSERVED`, `CALCULATED`, `INFERRED`, or `UNKNOWN`;
- source and source record identifier;
- observation, release, revision, ingestion, and availability timestamps where
  applicable;
- freshness and data-quality state;
- calculation/ruleset version.

Unknown values remain unknown. They are never silently converted to neutral or
safe.

## Outcome and constant-execution contract

The raw post-decision path is retained, but directional discovery will not
optimize excursions, stops, targets, or reward-to-risk.

Before the first result is calculated, a machine-readable run manifest must
freeze, separately for London and New York:

- decision clock;
- next-bar or other deterministic fill rule;
- fixed exit clock;
- fixed notional convention;
- observed spread treatment;
- commission and slippage assumptions;
- incomplete-session policy; and
- one-position/overlap policy.

The same execution is applied to:

- always long;
- always short;
- a deterministic random-direction control;
- each bullish case;
- each bearish case; and
- the final long/short/no-bias selector.

Profitability is evaluated using fixed-clock net returns after costs. Reward-to-
risk optimization is prohibited in this phase.

## Research sequence and deliverables

1. **Coverage audit**
   - Produce field coverage, source coverage, effective COT observations,
     missing-session counts, and point-in-time eligibility.
2. **Immutable casebook**
   - Produce the session, event, positioning, fundamental, structure, and
     cross-market records with hashes and schema documentation.
3. **Constant-execution baseline**
   - Report always-long, always-short, and random controls for each session.
4. **Relationship discovery**
   - Rank individual variables and transparent interactions by conditional
     direction, net return, support, stability, and uncertainty.
5. **Case specification**
   - Freeze explicit bullish, bearish, and no-bias rules using development data
     only.
6. **Chronological validation**
   - Run the frozen selector without changing its variables or thresholds.
7. **Holdout**
   - Open calendar 2025 once, only after the selector, execution manifest, data
     policy, and promotion gates are frozen.
8. **Execution phase**
   - Begin only if the information edge passes. Study the retained paths to
     design entry, invalidation, stop, target, and exit logic, followed by a new
     untouched or prospective validation.

Required repository artifacts:

- versioned casebook schema and data dictionary;
- machine-readable execution and research manifests;
- coverage and data-quality report;
- baseline report;
- ranked relationship report;
- frozen case definitions;
- chronological and holdout results;
- hashes, commands, logs, and test evidence sufficient to reproduce every
  reported number.

## Promotion and rejection gates

A directional case is not an edge unless it:

- beats the relevant fixed-execution baseline after declared costs;
- has adequate independent support, including effective weekly support for COT;
- is not dependent on one year, regime, event, month, or small group of trades;
- retains the same sign and useful magnitude in chronological validation;
- has uncertainty reported and survives reasonable data/cost checks;
- passes the untouched holdout without rule changes; and
- remains fully point-in-time correct.

Failure triggers a recorded rejection. The same data may not then be mined to
rename or slightly retune the rejected rule.

## Scope and token-control protocol

Work proceeds one incomplete milestone at a time. Each checkpoint must report
only:

1. what artifact was completed;
2. the exact evidence and file path;
3. the material result or blocker;
4. the next contracted step.

Do not launch an unbounded search, add a research branch, acquire paid data, or
change a frozen definition without explicit approval. Tool output is summarized,
not dumped. A negative result ends that hypothesis rather than triggering
unplanned parameter mining.

## User–Codex operating protocol

The user does not need to provide more data or credentials for the initial
casebook phase. Credentials must remain in `.env`, never in chat.

For a resumed session, the user can use this control instruction:

> Continue from `GOLD_CASEBOOK_RESEARCH_CONTRACT.md`. Work only on the current
> incomplete milestone. Do not optimize execution or open 2025. Report the
> completed artifact, exact evidence, and next contracted step. Stop and state
> the blocker if the contract cannot be followed.

The user may request `status against the casebook contract` at any time. The
answer must identify the current milestone, completed artifacts, evidence,
unresolved gaps, and whether any scope change occurred.

Codex must not rely on conversational memory for research state. Repository
artifacts, immutable source records, manifests, hashes, tests, and run results
are the source of truth.

## Current milestone status

As of 29 July 2026:

- milestone 1, **Coverage audit**, is complete;
- the human-readable evidence is in
  `GOLD_CASEBOOK_COVERAGE.md`;
- the machine-readable evidence is in
  `research_artifacts/gold_casebook_coverage_v01.json`;
- the deterministic evidence hash is
  `079f426fe6128a153e8714c814269617b96fa94c38cccacf85a06204c45dfbb6`;
- calendar 2025 was not loaded;
- no directional or execution outcome was calculated; and
- no scope change occurred.

- milestone 2, **Immutable casebook**, is complete;
- the immutable manifest is
  `research_artifacts/gold_casebook_v01/manifest.json`;
- the casebook manifest hash is
  `d1241633b073cd7307f1da00a13a2d76c132f3dccefc52a076be2c641f06b85f`;
- its independent semantic-validation evidence is
  `research_artifacts/gold_casebook_v01/semantic_validation.json`;
- the semantic-validation hash is
  `5ba0f3818dc717f4c8eeace6b69d73f64906a6aeef32f7e7a801fce77dc7a92f`;
- the human-readable milestone evidence is
  `GOLD_CASEBOOK_MILESTONE_2.md`;
- 833 London and 826 New York cases were materialized;
- 1,606,819 unique records passed record and artifact hash verification;
- calendar 2025 remained locked;
- no profitability, directional outcome, or execution optimization was
  calculated; and
- no scope change occurred.

Before any milestone 3 result was calculated, its execution definition was
frozen in
`research_manifests/gold_casebook_constant_execution_v01.json` with manifest
hash
`724a4fef0fa4b526b4d30b9743c2dfa013c53f87b19262a36b05f3fd07c87d76`.
Milestone 3, **Constant-execution baseline**, is now complete:

- the content-addressed baseline bundle is in
  `research_artifacts/gold_casebook_baseline_v01/manifest.json`;
- the bundle manifest hash is
  `dff92e13105b0b6fd6c9a71a5d9f7668384361d37475fac5fc8b2a33521ea032`;
- the machine-readable results are in
  `research_artifacts/gold_casebook_baseline_v01/results.json`;
- the results hash is
  `61624c9bcbf5ef25894c61cd02add0e0d56c2b9ffc9d3f26c54e5ea97a01ab6e`;
- independent semantic validation is in
  `research_artifacts/gold_casebook_baseline_v01/semantic_validation.json`;
- its validation hash is
  `0f56004ea5f486f1d7bd9efc04510c05cecc2283c6fb2a0b7e454b93ee9dbdeb`;
- all 833 London and 826 New York cases were eligible, with zero exclusions;
- 4,977 control trades joined to 3,318 exact immutable one-minute fill bars;
- all six unconditional controls were net negative after frozen costs and none
  is a directional edge;
- a clean rerun reproduced the same bundle and result hashes;
- calendar 2025 remained locked;
- no relationship discovery or execution optimization occurred; and
- no scope change occurred.

Before any milestone 4 conditional result was calculated, its bounded research
definition was frozen in
`research_manifests/gold_casebook_relationship_discovery_v01.json` with
manifest hash
`044b0d1ca776a052b17e18068363f72d5a0edd61408bb94080a413219180b426`.
Milestone 4, **Relationship discovery**, is now complete:

- the content-addressed discovery bundle is in
  `research_artifacts/gold_casebook_relationships_v01/manifest.json`;
- the bundle manifest hash is
  `a89429d80b589ba3cc5eb64f5d9635f5468768a190900fadbbe95ad75ba75b80`;
- the machine-readable rankings are in
  `research_artifacts/gold_casebook_relationships_v01/rankings.json`;
- the rankings hash is
  `a6b487de6fd13ff4bbfe0b2ff082a46b4838ca77faf7d7bfe5b6c6333a4291f2`;
- independent semantic validation is in
  `research_artifacts/gold_casebook_relationships_v01/semantic_validation.json`;
- its validation hash is
  `9c8c73e2af8006357e94da594047efbff86f7d6904351e77f64d89876f4f1d97`;
- 88 features and 17 declared interactions produced 866 observed states across
  582 London and 575 New York development cases;
- 510 states passed the declared support gates;
- the clearest simple relationship was four-hour ZT/ZN direction: falling
  Treasury-futures prices favoured short gold and rising prices favoured long
  gold, consistent with the book's yield-repricing channel;
- the current aggregate macro score did not independently establish a stable
  directional relationship;
- 17 states were stable with positive week-cluster lower bounds, but none
  passed the predeclared 10% Benjamini-Hochberg gate across all eligible tests;
- the strict discovery-lead count is therefore zero;
- a clean rerun reproduced the same bundle and rankings hashes;
- conditional 2024 features and returns remained reserved;
- calendar 2025 remained locked;
- no execution optimization occurred; and
- no scope change occurred.

Authorized amendment 1 permitted the universal four-hour ZN sign rule as one
exploratory Milestone 5 candidate. Before any combined-selector result was
calculated, the complete case definition and chronological-validation gates
were frozen in
`research_manifests/gold_casebook_case_specification_v01.json` with canonical
manifest hash
`a4696482f0db166fab9dd36a6d6742fb5589a1e5f2b6beeb705747a3d059c8de`.

Milestone 5, **Case specification**, is now complete:

- the content-addressed bundle is in
  `research_artifacts/gold_casebook_case_specification_v01/manifest.json`;
- the bundle manifest hash is
  `fb913282121ba527a002a499b3c68b1d175d78a9f1b91e10df2fc24133a4cdfd`;
- the development results hash is
  `4194c2a8399c462c94720c040feb426355d375fcf38dd311e8efd4d315a361c9`;
- the independent semantic-validation hash is
  `ff97ea0f416daa59a3419c64b0dce372e2b04a1b1f62e2506fde2347026afd0f`;
- the human-readable evidence is in `GOLD_CASEBOOK_MILESTONE_5.md`;
- the universal mapping is ZN 4h positive to `LONG`, negative to `SHORT`,
  and flat or unknown to `NO_BIAS` in both sessions;
- 1,101 of 1,157 development cases were directional, with 545 long, 556 short,
  and 56 no-bias;
- the fixed one-ounce selector produced +3.2842 mean net basis points in
  London and +6.0757 in New York after frozen costs;
- both directions, all three development-year buckets, and both chronological
  development halves retained positive mean net returns;
- a clean rerun reproduced the same bundle and artifact hashes;
- 1,506 calendar-2024 baseline rows were skipped before JSON deserialization;
- conditional 2024 features and outcomes remain reserved;
- calendar 2025 remains locked;
- no rule retuning or execution optimization occurred; and
- the result remains exploratory, not a validated edge.

At the end of Milestone 5, the current incomplete milestone was milestone 6,
**Chronological validation**. It was eligible to open calendar 2024 once and
had to apply the frozen selector, execution, data policy, and pass/reject gates
without modification. Calendar 2025 remained locked for milestone 7.

### Milestone 6 authorization

On 29 July 2026, before any conditional 2024 feature or outcome was loaded, the
user authorized the one-time chronological validation:

> Proceed to Milestone 6 under the existing research contract. Open calendar
> 2024 once and apply `UNIVERSAL_ZN_4H_SIGN_V0_1` unchanged, using the frozen
> execution, data policy, and pass/reject gates. Do not retune the rule, add
> variables, optimize execution, or inspect 2025. Record an honest pass or
> rejection and stop after completing Milestone 6.

This authorization opens only the calendar-2024 chronological-validation
reserve. It does not amend the candidate, execution, gates, or holdout policy.

Before any conditional 2024 feature or outcome was loaded, the operational
validation definition was frozen in
`research_manifests/gold_casebook_chronological_validation_v01.json` with
canonical manifest hash
`4e070218bfe2be8d0113762bbc42d944e39fccf8916f9f7286a998c05e170269`.

Milestone 6, **Chronological validation**, is now complete:

- the frozen verdict is `REJECT_CHRONOLOGICAL_VALIDATION`;
- the content-addressed bundle is in
  `research_artifacts/gold_casebook_chronological_validation_v01/manifest.json`;
- the bundle manifest hash is
  `e508b049961c622d09b8474815e0a4d3c8e3c814f03ce1f72b0154116594d3c4`;
- the results hash is
  `4580c8f11242cf1444f7e68de82292bb48c874f4a1195e982fd836e65d069a2d`;
- the independent semantic-validation hash is
  `a6490e0d6297e6d2c3ef53a4625d6c8e064a636350a735c1485df74b4a55a099`;
- the human-readable evidence is in `GOLD_CASEBOOK_MILESTONE_6.md`;
- 502 calendar-2024 session cases produced 470 directional decisions and 32
  no-bias decisions;
- eight of ten frozen gates passed;
- G08 failed because New York ZN-positive to long returned -0.2366 mean net
  basis points;
- G09 failed because the New York early chronological half returned -3.4584
  mean net basis points;
- London passed every individual gate, but a post-result London-only rewrite
  is prohibited;
- a clean rerun reproduced the bundle and artifacts byte-for-byte;
- 139 backend tests and focused Ruff checks passed;
- no selector, threshold, execution, cost, or gate changed;
- calendar 2025 remained unopened; and
- no execution research began.

This branch has no eligible incomplete milestone. Milestone 7 is not opened
because the information edge failed chronological validation, and Milestone 8
is not eligible. Calendar 2024 is consumed and may not be used to retune this
candidate. Any future branch requires an explicit new contract for a genuinely
different hypothesis and new untouched or prospective validation data.
