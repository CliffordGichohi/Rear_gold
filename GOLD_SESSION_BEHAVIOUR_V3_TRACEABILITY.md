# Gold Session Behaviour V3 — Reference-Book-to-Field Traceability

## Decision

The Reference Book has been mapped into **75 explicit field requirements**
before V3 case construction or relationship discovery.

Machine-readable catalog:

`research_manifests/gold_session_behaviour_v3_traceability_v01.json`

Catalog hash:

`8707c39eb75bf3c74ce33908b0a3f4b0a1f679ee68848f1d10dce25e4bdf6bb4`

Reference Book SHA-256:

`3e7ddc561932a859a4c9043a38ff71b7003907963fb52247e41edaeefc8ac42a`

Contract-manifest hash:

`79a74f81bce0b80ca6c5da6b420400479013484a4bb759684402546672fa140b`

This catalog is a field and evidence specification. It contains no 2025/2026
values, no relationship result, no candidate, and no directional conclusion.

## What “aligned with the book” means

Alignment does not mean forcing the book's examples to win a backtest. It means
that the case matrix preserves the complete reading chain:

```text
market mechanics
→ liquidity
→ market structure
→ macro regime
→ expectations
→ positioning
→ catalyst
→ session
→ cross-market confirmation
→ execution and risk
```

V3 records the chain through cross-market confirmation. The final execution
and risk stage is explicitly cataloged but excluded under the V3 no-execution
boundary.

Every catalog row contains:

- the relevant book chapters and requirement;
- exact V3 case-matrix field paths;
- decision-state, outcome, governance, or out-of-scope role;
- permitted epistemic classes;
- point-in-time timing rule;
- development source lineage;
- current development coverage;
- limitations; and
- no candidate eligibility or empirical result.

## Development traceability summary

| Coverage class | Requirements | Meaning |
|---|---:|---|
| `PRESENT` | 34 | Reusable point-in-time representation already exists in the immutable development casebook |
| `DERIVABLE` | 14 | Required source records exist, but V3 has not materialized the field |
| `PARTIAL` | 18 | Some source, timestamp, resolution, or lineage exists, but the full book requirement is not met |
| `UNAVAILABLE` | 6 | No valid point-in-time development source is currently present |
| `OUT_OF_SCOPE` | 3 | Deliberately excluded execution/risk requirements |
| **Total** | **75** | Complete frozen catalog |

`PRESENT` does not mean validated as predictive. `DERIVABLE` does not authorize
calculation in Milestone 1. `PARTIAL` may not be silently promoted.

## Chapter coverage

| Book area | V3 mapping |
|---|---|
| Chapter 0 — facts, assumptions, workflow | lineage, epistemic class, `UNKNOWN`, audit controls |
| Chapters 1–4 — instrument, participants, liquidity, orders | broker-instrument identity, price, spread, tick volume, unavailable depth/resilience, inferred motive |
| Chapters 5–7 — levels, structure, plumbing | swings, HH/HL/LH/LL, trend/range, support/resistance, BOS/MSS, compression, displacement, acceptance/rejection, futures and COT lineage |
| Chapters 8–11 — Fed, macro, yields, dollar, regimes | inflation, labour, growth, policy rate, 2Y/10Y/real yield, breakeven, curve, USD, risk and regime/reaction-function state |
| Chapter 12 — market regime | complete level/direction/rate-of-change regime branch |
| Chapter 13 — expectations and pricing | actual/forecast/previous/revision/surprise, policy-path shape and repricing, explicit exact-FedWatch gap |
| Chapter 14 — positioning | COT categories, changes, percentiles, OI, crowding inferences, explicit ETF/central-bank/options gaps |
| Chapter 15 — catalysts | event clocks, components, proximity, fixed reactions, event path, Fed/auction and unscheduled-event gaps |
| Chapter 16 — sessions and liquidity | Asia/London/New York clocks, handovers, overlap, benchmark and rollover windows, session structure outcomes |
| Chapter 17 — cross-market confirmation | synchronized rates, USD, equities, volatility, silver, policy proxies, confirmation/divergence states |
| Chapter 18 — execution and risk | cataloged as `OUT_OF_SCOPE`; no entry, stop, target, R:R, sizing, or portfolio trade field |
| Chapters 19–21 — workflows and scenarios | evidence-chain, session-path, event-path, contradiction, and risk-assumption fields |
| Chapters 22–24 — sources, journal, glossary | provider lineage, availability, hashes, definitions, and audit state |

## Fields already represented in development

The immutable 2021-2024 bundle already provides reusable evidence for:

- XAUUSD OHLC, broker spread, tick volume, completeness, and source hashes;
- six-timeframe deterministic structure;
- prior session/day/week levels and level-interaction records;
- vintage-aware CPI, core CPI, PCE, core PCE, payrolls, unemployment,
  earnings, claims, GDP, retail sales, Fed rate, nominal yields, real yield,
  breakeven inflation, dollar, equities, volatility, high-yield spreads, and
  financial-stress series;
- transparent regime, reaction-function, component evidence, contradictions,
  and missing-driver outputs;
- full disaggregated CFTC gold positioning with Tuesday observation and Friday
  publication;
- scheduled economic-release identities, release components, revisions,
  surprises where calculable, and fixed reaction snapshots;
- IANA/DST-correct Asia, London, and New York session construction;
- XAUUSD, EURUSD, XAGUSD, US500, ZT, ZN, ZQ, and SR3 cross-market snapshots;
  and
- complete five-minute session paths, one-minute lineage, and interactions
  with decision-known levels.

These are data fields, not proven predictors.

## Derivable but not calculated in Milestone 1

The source records are sufficient to define later, under a frozen Milestone 2
measurement manifest:

- neutral 5m/15m/30m/60m/close displacement;
- absolute displacement and high-low range;
- maximum upward and downward displacement from the neutral reference;
- high/low timestamps and their order;
- close location and path efficiency;
- session confirmation, reversal, acceptance, rejection, and failed-break
  labels;
- yield-curve slope;
- book-defined cross-market confirmation/divergence and rates-driver states;
- session handover/overlap and London benchmark-window facts;
- event-path summaries whose horizons were complete before a later decision;
  and
- explicitly inferred liquidity-zone or participant-context statements.

None of these fields was materialized, distributed, joined to conditions, or
ranked during Milestone 1.

## Partial fields and their restrictions

| Requirement | What exists | Restriction |
|---|---|---|
| Centralized gold volume | IC Markets tick volume | Must not be called COMEX contract volume |
| 2Y and 10Y intraday context | Daily FRED yields plus ZT/ZN futures prices | Futures price is not an observed yield; roll-crossing changes are `UNKNOWN` |
| Dollar | Daily broad-dollar index plus EURUSD | Neither proxy may be silently relabelled DXY |
| Equity risk | Daily public series and partial intraday US500 | Intraday US500 after 14 January 2022 is stale |
| Historical consensus | MetaQuotes release-boundary forecasts | Generally not verified for pre-release use |
| Economic surprise | Actual and forecast values | Pre-event edge unavailable unless forecast availability is verified |
| Fed path | Quarterly Atlanta Fed SOFR windows plus ZQ/SR3 | Not exact meeting-level FedWatch probabilities |
| Open interest | Weekly CFTC total open interest | No intraday COMEX gold OI |
| Fast/slow money divergence | Detailed COT categories | ETF and central-bank slow-money series are absent |
| Event calendar | Economic event and release metadata | Historical schedule availability before the event is not generally verified |
| Fed/auction events | Partial event taxonomy | Completeness is not established |
| Session liquidity | Broker spread and volatility | No depth or resilience |
| Cross-market panel | Multiple daily and intraday sources | Resolution, staleness, and roll quality remain per-field |

## Unavailable fields

The catalog deliberately exposes six unavailable requirements:

1. historical order-book depth, resilience, and trade-level price impact;
2. exact meeting-level historical Fed cut/hike probability curves;
3. versioned point-in-time gold ETF holdings and flows;
4. point-in-time central-bank gold demand;
5. historical COMEX options chains, implied-volatility surfaces, and defensible
   dealer-gamma estimates; and
6. licensed point-in-time unscheduled geopolitical/financial news.

These fields are `UNKNOWN`. The absence of the source cannot be interpreted as:

- no ETF flow;
- no central-bank activity;
- no options concentration;
- neutral dealer gamma;
- normal depth;
- no geopolitical event; or
- confirmation of either direction.

Adding one later requires a versioned data amendment, point-in-time lineage,
and coverage freeze before the relevant development outcomes are inspected.

## Execution boundary

The book's execution layer remains important, but it answers a later question.
The following three catalog groups are `OUT_OF_SCOPE`:

- bias/trigger/invalidation/risk conversion;
- entry, exit, stop, target, spread/slippage/latency, R:R, and sizing; and
- portfolio-cluster, daily-loss, and live execution-risk management.

The neutral V3 outcome reference is not an entry. No trade side, fill, MFE,
MAE, P&L, R multiple, or account scaling exists in the V3 case schema.

## Point-in-time invariants

- `available_at <= decision_at` for every decision-state fact.
- A structure pivot is eligible at `detected_at`, not its earlier visual pivot
  timestamp.
- COT availability is Friday publication, not Tuesday observation.
- Revisions enter only at their own release/availability time.
- A fixed event reaction enters a later decision only after its horizon closes.
- Post-decision session behaviour always has `decision_eligible=false`.
- Continuous-futures roll crossings are `UNKNOWN`.
- Stale fields remain stale/unknown, never neutral.
- Institutional motives are `INFERRED` unless directly sourced.

## Forward coverage

This catalog does not infer 2025 or 2026 source coverage from development
history. Forward timestamp and identifier coverage is reported independently
in:

`research_artifacts/gold_session_behaviour_v3_coverage_v01.json`

That audit is metadata-only and does not inspect market values or outcomes.
