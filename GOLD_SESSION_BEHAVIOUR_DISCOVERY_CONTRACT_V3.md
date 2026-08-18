# Gold Session Behaviour and Conditional Bias Discovery Contract V3

## Authority and current boundary

This contract starts a new research branch. It preserves—without renaming,
repairing, or reopening—the original Gold Casebook research and Discovery V2.

It was authorized on 30 July 2026 by this instruction:

> Create Gold Session Behaviour and Conditional Bias Discovery Contract V3.
> Preserve all prior results and rejections. Use 2021-08-01 through 2024-12-31
> for development, treat 2025 as an exposed historical forward test, and keep
> 2026 values locked as the independent year-to-date holdout followed by
> prospective tracking. Permit descriptive neutral session-path measurements
> but no execution optimization. Complete only the contract,
> Reference-Book-to-field traceability catalog, metadata-only coverage audit,
> comprehensive case-matrix schema, and V3 state file. Do not inspect 2025 or
> 2026 values, calculate relationships, or begin candidate discovery. Stop
> after Milestone 1.

The machine-readable authority is
`research_manifests/gold_session_behaviour_discovery_contract_v03.json`.

Canonical contract-manifest hash:

`79a74f81bce0b80ca6c5da6b420400479013484a4bb759684402546672fa140b`

Only V3 Milestone 1 is authorized. Completing it is a mandatory stop; no
development cases, outcome distributions, relationships, or candidates may be
calculated in this milestone.

## Research objective

The objective is to learn, without prescribing the answer:

> Which conditions known at the London or New York decision clock, if any,
> provide a stable and explainable conditional bias for the direction and path
> gold subsequently takes during that session?

The order matters:

1. Record the complete point-in-time state.
2. Record what the session subsequently did in neutral, non-trade terms.
3. Describe behaviour before asking why it occurred.
4. Freeze a bounded eligible-feature universe.
5. Test simple conditional relationships on development data only.
6. Freeze candidates and pass/reject gates.
7. Evaluate the frozen candidates on forward segments without repair.
8. Study execution only under a separate future contract if a bias survives.

The target is an information edge, not a requested account return. Ten percent
per month, 10R per month, leverage, lot size, or any other desired profit
cannot select a condition, threshold, candidate, or conclusion.

## Reference Book authority

`Gold_USD_Market_Intelligence_Reference_Book.pdf` is the primary business and
market-logic specification.

SHA-256:

`3e7ddc561932a859a4c9043a38ff71b7003907963fb52247e41edaeefc8ac42a`

The book governs:

- the causal chain from mechanics and liquidity through structure, macro,
  expectations, positioning, catalysts, sessions, and cross-market context;
- point-in-time and revision-vintage requirements;
- `OBSERVED`, `CALCULATED`, `INFERRED`, and `UNKNOWN` labels;
- the separation of bias, trigger, invalidation, and risk; and
- the requirement that every interpretation be linked to evidence.

It does not predetermine an empirical sign or force a relationship to exist.
Book-consistent hypotheses may be confirmed, qualified, contradicted, or
rejected by data.

The frozen field-by-field mapping is
`research_manifests/gold_session_behaviour_v3_traceability_v01.json`.

## Preserved research history

All earlier artifacts remain immutable evidence. V3 neither deletes negative
evidence nor grants it a new label.

### Original research

`UNIVERSAL_ZN_4H_SIGN_V0_1` remains:

**`REJECT_CHRONOLOGICAL_VALIDATION`**

Authoritative result manifest:

`research_artifacts/gold_casebook_chronological_validation_v01/manifest.json`

Manifest hash:

`e508b049961c622d09b8474815e0a4d3c8e3c814f03ce1f72b0154116594d3c4`

### Discovery V2

The complete V2 chain is preserved:

| V2 artifact | Manifest hash | Preserved result |
|---|---|---|
| Descriptive outcome atlas | `e1493d2734109a07b83da1f60768def696201c9a67df1cd75e3d11bec5a484fc` | Descriptive session movement only |
| Bounded relationship discovery | `0ffc6d7b5f243d21490b23fa5af649cc94b921bd8223f188b5e81004427591b2` | Development evidence only |
| Internal expanding walk-forward | `8609875313770bbcb947d1e785633471c1a706ee775abf132b87cd49529ba7b5` | `PASS_INTERNAL_WALK_FORWARD_STABILITY` for the post-hoc London candidate |
| Shortlist freeze | `774655f1dcfb0ebd95b6ec3e50fd480e2c5d5ea75abd4221dd5e7e79986f22ac` | One London candidate; zero New York candidates |
| Calendar-2025 forward test | `110018f6997b7b96c55398696f68a70b1935f9a488dfe39bcc204e9ea5bb6d68` | `REJECT_CALENDAR_2025_HOLDOUT` |

`LONDON_ZN_4H_POSTHOC_V0_1` therefore remains:

**`REJECT_CALENDAR_2025_HOLDOUT`**

Its positive internal evidence is not erased, but the failed forward result
controls its verdict. Neither rejected ZN rule may be inverted, thresholded,
filtered, session-switched, renamed, or presented as a new edge. ZN may remain
a descriptive rates-context field. A future use would require a genuinely
different, preregistered hypothesis and cannot claim continuity with either
rejected rule.

The immutable 2021-2024 casebook remains preserved at:

`research_artifacts/gold_casebook_v01/manifest.json`

Manifest hash:

`d1241633b073cd7307f1da00a13a2d76c132f3dccefc52a076be2c641f06b85f`

## Time partitions

### Development: 2021-08-01 through 2024-12-31

Session dates from 1 August 2021 through 31 December 2024 are development
data. The interval is
`2021-08-01T00:00:00Z <= t < 2025-01-01T00:00:00Z`.

These data have been observed. They may later be used for case construction,
description, discovery, and internal chronology-aware stability, but never be
called independent validation.

### Exposed historical forward test: calendar 2025

Calendar 2025 is real forward data, but it was opened under V2. It is therefore
**exposed**, not untouched.

- It cannot influence V3 fields, transforms, thresholds, candidates, or gates.
- A V3 candidate may later be applied to it only after that candidate is
  frozen without 2025.
- Results must be labelled historical forward evidence with no independent
  validation credit.
- During Milestone 1, only metadata may be read. No 2025 values or outcomes
  may be opened again.

### Locked independent YTD holdout: 2026-01-01 through 2026-07-29

Session dates from 1 January through 29 July 2026 form the locked independent
year-to-date holdout. The date boundary is fixed by this contract, not selected
from market behaviour.

No 2026 market, macro, positioning, event, structure, or outcome values may be
read for V3 until:

1. Milestones 2–5 are separately authorized and completed;
2. the candidate shortlist, field lineage, missing-data policy, controls,
   costs if any, and pass/reject gates are immutable;
3. candidate-specific 2026 source coverage is sealed using metadata only; and
4. V3 Milestone 6 is explicitly authorized.

### Prospective 2026 tracking

Prospective evidence begins on the first complete eligible session strictly
after the immutable shortlist-freeze timestamp, and never retroactively before
30 July 2026. Each decision record must be sealed before its outcome becomes
available. Prospective failures are recorded; rules may not be repaired during
the tracking segment.

## Independent session units

London and New York are separate research units.

| Session | Decision clock | Observation end | IANA timezone |
|---|---|---|---|
| London | 08:00 local | 12:00 local | `Europe/London` |
| New York | 08:00 local | 12:00 local | `America/New_York` |

Daylight-saving conversion uses the IANA timezone database. A London result
does not automatically transfer to New York, and one session does not fail
only because another fails. Combined results are descriptive only.

## Comprehensive case-matrix rule

The V3 case matrix has one immutable row per `session_code × session_date`.
Its schema is
`research_schemas/gold_session_behaviour_v3_case_matrix.schema.json`.

Every row has two strictly separated halves:

- `decision_state`: only facts whose individual `available_at <= decision_at`;
- `subsequent_behaviour`: later descriptive facts with
  `decision_eligible=false`.

Every fact carries epistemic status, availability, quality, and source
lineage. Missing, stale, unlicensed, roll-crossing, or not point-in-time
verified facts are `UNKNOWN`; they are never silently treated as zero,
neutral confirmation, no event, or safety.

Institutional motives are never asserted as directly observed. For example,
price up plus open interest up may support an `INFERRED` fresh-participation
interpretation, but it is not proof of who traded or why.

## Neutral session-path measurements

V3 may later describe the path after the decision clock without pretending a
trade was placed.

The neutral coordinate is the open of the first complete observed XAUUSD
one-minute bar whose timestamp is 08:01 local. It is an outcome reference, not
an entry or assumed fill. The observation ends at 12:00 local.

Permitted descriptive fields include:

- signed and absolute fixed-clock displacement;
- high-low range;
- maximum upward and maximum downward displacement from the neutral reference;
- time and order of the session high and low;
- fixed 5m, 15m, 30m, 60m, and close path states;
- prior-level touch, breach, acceptance, rejection, and failed-break facts;
- close location within the range; and
- path completeness and quality.

These are not long-side MFE, short-side MFE, MAE, entries, exits, stops,
targets, fills, P&L, reward-to-risk, or position sizing. No execution
optimization is permitted anywhere in V3. Execution research requires a new
contract after a conditional-bias candidate earns independent or prospective
evidence.

## Point-in-time and source policy

- Raw records are append-only or versioned.
- Observation period, release/publication time, earliest market availability,
  ingestion time, and vintage/source version remain distinct.
- Economic revisions never overwrite the originally released vintage.
- COT uses Tuesday observation and Friday publication; no report may enter a
  decision before publication.
- Continuous-futures changes crossing a roll remain `UNKNOWN` unless a
  preregistered construction resolves them.
- No pseudo market history may replace missing real data.
- Official or licensed sources are required; protected websites may not be
  scraped in violation of their terms.
- Acquisition and source coverage do not authorize value inspection.

## Bounded future discovery

Candidate discovery is not authorized now. If Milestone 4 is later opened:

- the eligible feature registry, states, transforms, interactions, support
  floors, uncertainty method, multiplicity method, and ranking order are
  frozen before results;
- variables are examined before interactions;
- a candidate contains no more than two transparent conditions;
- at most two candidates per session may advance;
- zero candidates is an acceptable result;
- opaque machine learning is prohibited;
- missing inputs cannot count as confirmation;
- every candidate has explicit bullish, bearish, neutral/unknown, highest-risk
  assumption, and invalidation definitions; and
- a failed forward result ends the candidate rather than starting threshold
  mining.

## Milestones

### V3 Milestone 1 — contract, traceability, metadata, schema, state

Produce only:

- this contract and machine manifest;
- Reference-Book-to-field traceability catalog;
- metadata-only development/2025/2026 coverage audit;
- comprehensive empty case-matrix schema;
- V3 state file and validation report.

No case materialization, descriptive distributions, relationships, candidate
work, or value access is allowed. Stop after completion.

### V3 Milestone 2 — development case matrix

After separate authorization, materialize point-in-time decision states and
neutral subsequent paths for development only. Validate lineage, DST,
availability, completeness, revisions, COT publication timing, and duplicate
keys. Do not test relationships.

### V3 Milestone 3 — development behaviour atlas

After separate authorization, describe London and New York paths, level
interactions, direction frequencies, excursion distributions, timing, and
calendar stability. Do not attribute cause or select candidate conditions.

### V3 Milestone 4 — bounded conditional-bias discovery

After separate authorization and a pre-result feature-registry freeze, test
simple book-traceable conditions separately for London and New York on
development only.

### V3 Milestone 5 — internal stability and shortlist freeze

Apply chronology-aware internal stability, realistic support floors,
cluster-aware uncertainty, multiple-testing control, negative controls, and
sensitivity checks. Freeze zero to two candidates per session with exact
forward gates.

### V3 Milestone 6 — forward evaluation

After explicit authorization, apply candidates unchanged and report separately:

1. exposed calendar 2025;
2. independent locked 2026 YTD through 29 July; and
3. genuinely prospective post-freeze 2026 sessions.

The independent and prospective segments control any claim of a current edge.
No failed candidate may be repaired.

### V3 Milestone 7 — prospective tracking

Append decisions before outcomes and continue honest monitoring. Any new
hypothesis begins a separately versioned research branch.

### Separate execution research contract

Entry, trigger, stop, target, exit, reward-to-risk, and risk sizing are outside
V3. They may be studied only after new explicit authorization and a valid
out-of-sample plan.

## Reproducibility and anti-drift protocol

The repository, not chat memory, is the source of truth.

For every milestone:

1. Read this contract and the V3 state before acting.
2. Work only on the one authorized incomplete milestone.
3. Freeze its pre-result definitions before accessing results.
4. Link every empirical claim to an immutable path, hash, interval, count, and
   measurement definition.
5. Report `UNKNOWN` instead of filling a gap with memory or assumption.
6. Record negative evidence and blockers.
7. Do not pivot, add fields, add candidates, or broaden the objective without
   an explicit versioned amendment.
8. Stop at the contracted boundary and wait for authorization.

This protocol is designed to prevent circular research, hindsight relabelling,
conversation-driven drift, and unsupported claims.

## Current status

V3 Milestone 1 is the only authorized milestone.

It ends when its ten declared artifacts validate. Milestone 2 is not
authorized and must not begin automatically.
