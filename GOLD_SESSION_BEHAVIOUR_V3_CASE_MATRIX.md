# Gold Session Behaviour V3 — Comprehensive Case Matrix

## Purpose

The V3 case matrix is the immutable evidence table for answering:

> Given everything legitimately known at the London or New York decision
> clock, what did gold subsequently do during that session?

Schema:

`research_schemas/gold_session_behaviour_v3_case_matrix.schema.json`

One row represents one `session_code × session_date`. No rows are created in
V3 Milestone 1; this document defines the shape only.

## Grain and clocks

| Field | London | New York |
|---|---|---|
| Decision clock | 08:00 Europe/London | 08:00 America/New_York |
| Neutral outcome reference | Open of first complete 1m bar at 08:01 local | Open of first complete 1m bar at 08:01 local |
| Observation end | 12:00 local | 12:00 local |
| DST rule | IANA timezone database | IANA timezone database |

The 08:01 price is an outcome coordinate, not a trade entry or fill.

## Top-level topology

```text
case
├── case_metadata
├── lineage
├── decision_state                 available_at <= decision_at
│   ├── market_mechanics
│   ├── market_structure           1m / 5m / 15m / 1h / 4h / 1d
│   ├── levels
│   ├── layers
│   │   ├── market_regime
│   │   ├── expectations
│   │   ├── positioning
│   │   ├── catalysts
│   │   ├── sessions_and_liquidity
│   │   └── cross_market
│   ├── synthesis
│   └── unknowns
├── subsequent_behaviour           decision_eligible = false
│   ├── neutral_reference
│   ├── fixed_horizons
│   ├── neutral_excursions
│   ├── extremes
│   ├── level_interactions
│   ├── path
│   ├── close_location
│   └── path_classification
├── quality
└── research_policy
```

## Common fact envelope

Every atomic fact records:

- `value` and `unit`;
- `epistemic_status`;
- `as_of` and `available_at`;
- `quality`;
- calculation or interpretation method;
- explanation and evidence;
- source-record references and hashes; and
- an invalidation statement where relevant.

Allowed epistemic states are:

| State | Rule |
|---|---|
| `OBSERVED` | Directly received from an identified source |
| `CALCULATED` | Deterministic transform of observed inputs |
| `INFERRED` | Transparent interpretation with evidence and limitations |
| `UNKNOWN` | Missing, stale, roll-crossing, unavailable, unlicensed, or not point-in-time verified |

An `UNKNOWN` fact must have `value=null`. It cannot silently become zero,
neutral, safe, or no-event.

## Decision state

### Market mechanics

The schema requires slots for:

- instrument identity;
- XAUUSD price;
- spread;
- tick volume;
- COMEX volume;
- depth;
- resilience;
- price impact; and
- participant-activity interpretations.

Unavailable fields still have explicit `UNKNOWN` fact objects. This prevents
the absence of depth or centralized volume from disappearing from the row.

### Market structure and levels

All six required timeframes carry:

- source-bar counts and hashes;
- swing and trend state;
- range, support, and resistance;
- BOS and market-structure shift;
- breakout/acceptance/rejection state;
- compression, expansion, displacement, and momentum; and
- detailed detections.

Each level preserves its type, price, timeframe, detection and availability
times, method, confidence, evidence, invalidation, and any explicitly
`INFERRED` liquidity-zone interpretation.

### Six condition layers

The first six book layers are decision-state inputs:

1. market regime;
2. expectations and pricing;
3. positioning;
4. catalysts;
5. sessions and liquidity; and
6. cross-market confirmation.

The book's seventh layer—execution and risk—is excluded because V3 does not
construct trades.

The schema includes explicit slots for fields that are currently unavailable:
exact Fed meeting probabilities, ETF flows, central-bank demand, options and
gamma, unscheduled events, depth, resilience, and centralized COMEX activity.

### Synthesis

Synthesis records supporting evidence, contradicting evidence, and the
highest-risk assumption. These remain transparent research inputs. They are
not a validated directional signal and do not assign a trade.

## Subsequent behaviour

The outcome branch is permanently marked `decision_eligible=false`.

It stores:

- signed and absolute displacement at 5m, 15m, 30m, 60m, and session close;
- maximum upward and downward displacement from the neutral reference;
- session range;
- session high and low, their timestamps, and their order;
- touch, breach, acceptance, rejection, failed-break, and retest facts for
  levels that were already known at the decision;
- complete five-minute path plus one-minute source count and hash;
- close location; and
- a deterministic descriptive path class.

The terms `maximum_upward_displacement` and
`maximum_downward_displacement` are deliberately side-neutral. They are not
long MFE, short MFE, or MAE.

## Lineage and quality gates

Each row binds to:

- V3 contract hash
  `79a74f81bce0b80ca6c5da6b420400479013484a4bb759684402546672fa140b`;
- traceability hash
  `8707c39eb75bf3c74ce33908b0a3f4b0a1f679ee68848f1d10dce25e4bdf6bb4`;
- source bundle manifests;
- individual source-record identities;
- source-record hash aggregate; and
- transform versions.

A row cannot be `VALID` unless point-in-time, outcome separation, DST,
duplicate-key, one-minute-source, and path-completeness checks all pass.

Additional validators for Milestone 2 must enforce:

- exactly one row per session/date;
- exactly one structure record for each of the six timeframes;
- session code and timezone consistency;
- `decision_state.*.available_at <= decision_at`;
- observation start and end clocks;
- no COT use before Friday publication;
- no revision use before its own availability;
- no unverified forecast treated as pre-event known;
- no stale US500 treated as current;
- no roll-crossing futures change treated as valid; and
- exact source counts and hashes.

## Explicitly prohibited fields

The schema's `research_policy` fixes all of the following to `false`:

- trade direction assigned;
- candidate or relationship label present;
- entry or exit assumed;
- stop or target assigned;
- position size assigned;
- execution optimized;
- MFE or MAE calculated;
- P&L or R multiple calculated; and
- account return calculated.

Those questions require a separate later execution-research contract.

## Partition labels

The same schema supports four access classes while governance controls when
they may be materialized or read:

| Partition | Access label | V3 role |
|---|---|---|
| 2021-08-01 through 2024-12-31 | `DEVELOPMENT` | Case construction, description, later bounded discovery |
| Calendar 2025 | `EXPOSED_HISTORICAL_FORWARD_TEST` | Later frozen-rule historical forward evaluation only |
| 2026-01-01 through 2026-07-29 | `LOCKED_INDEPENDENT_HOLDOUT` | Values locked until Milestone 6 |
| Post-freeze 2026 | `PROSPECTIVE` | Decisions sealed before outcomes |

Milestone 1 defines these labels but materializes none of their case rows.
