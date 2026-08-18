# Phase 1 Milestone Plan

Each milestone ends with a runnable application, migrations, tests, and updated
documentation. A later milestone may add capability but may not bypass or weaken the
point-in-time contract established earlier.

## Implementation checkpoint — 27 July 2026

M0–M7 are implemented as a runnable Docker Compose system. M8 includes real-data
event studies, the transparent strategy runner, transaction costs, confidence
intervals, sensitivity output, and trade-order Monte Carlo; full scheduled
walk-forward orchestration remains a later research increment. M9 is partially
implemented: Data Health, structured logging, validation, tests, and documentation
are present, while production OIDC/RBAC, backup drills, and the optional AI narrator
remain outside the local MVP.

The authoritative current capability and missing-data boundary is
`BOOK_ALIGNMENT.md`. Unknown catalyst risk and unknown liquidity fail closed in
strict backtests. Candidate A has been rejected; no strategy edge is claimed.

## M0 — Architecture checkpoint (complete)

Deliver:

- primary-domain interpretation from the complete reference book;
- assumptions and MVP boundaries;
- system architecture and repository structure;
- source/licensing plan;
- temporal entity model and ER diagrams;
- API, scoring, backtesting, and dashboard designs;
- first vertical-slice specification; and
- risk/mitigation register.

Exit: planning documents are internally consistent and no major implementation has
started. This milestone is the requested review point.

## M1 — Runnable platform skeleton

Deliver:

- root monorepo structure, formatting/lint/type/test commands, and `.env.example`;
- Docker Compose services for TimescaleDB/PostgreSQL, Redis, API, worker, scheduler,
  migration job, and web;
- FastAPI application with liveness/readiness, problem-detail errors, request IDs,
  JSON logs, and generated OpenAPI;
- Next.js shell with typed API client and health state;
- SQLAlchemy/Alembic foundation and Timescale extension migration;
- Celery job envelope, deterministic job key, retry/backoff, and heartbeat;
- local raw-object store interface; and
- backend/frontend CI workflows.

Exit: one command starts the stack; readiness and a browser shell work with an empty
database; unit and migration smoke tests pass.

## M2 — First vertical slice

Implement the exact slice specified below: CSV -> immutable raw -> normalized bars
and observations -> two transparent calculations -> partial score -> API -> Executive
Overview -> point-in-time tests.

Exit: the credential-free seed command produces an explained dashboard from
synthetic data; duplicate ingestion, availability, stale data, and future-confirmed
structure tests pass.

## M3 — Public data and economic-event foundation

Deliver:

- generic CSV/JSON schemas and FRED/ALFRED, BLS, BEA, Federal Reserve/Treasury
  adapters where appropriate;
- canonical Phase 1 series catalog and unit transformations;
- economic calendar, event components, timestamped manual consensus upload,
  initial/revised observation handling, and surprise features;
- data-quality rules for revisions, timestamps, gaps, duplicates, units, and stale
  series; and
- Macro and Events pages with vintage-aware charts.

Exit: CPI/core CPI, PCE/core PCE, NFP, unemployment, policy rate, 2Y, 10Y, real yield,
breakeven, and broad USD can be loaded without overwriting a vintage; a surprise
cannot use a post-release forecast.

## M4 — Regime, expectations, and catalyst layers

Deliver:

- level/direction/rate-of-change feature library;
- deterministic regime-axis and classification rules;
- Fed-path manual/mock snapshot model and hawkish/dovish repricing;
- reaction-function profiles;
- event impact, upcoming-catalyst risk, and completed-horizon reaction facts; and
- complete Layer 1, 2, and 4 evidence/explanation panels.

Exit: historical snapshots reproduce the eligible regime and event interpretation,
and every regime transition and surprise has fact lineage.

## M5 — Positioning layer

Deliver:

- CFTC disaggregated COT adapter and actual publication calendar support;
- managed-money/commercial measures, point-in-time percentiles, crowding, and decay;
- open-interest/price inference rules with explicit `INFERRED` language;
- generic manual/mock ETF, central-bank, and options interfaces; and
- Positioning dashboard including slow/fast-money divergence and missing-source
  states.

Exit: Tuesday data is inaccessible before publication, delayed holiday cases pass,
and crowding alone cannot create or reverse the directional score.

## M6 — Sessions, liquidity, structure, and cross-market

Status: sessions, deterministic structure, the synchronized Cross-Market page, and
the first broker quote/tick-activity liquidity gate are implemented. Exchange-wide
COMEX depth and volume remain a licensed-data extension and are not inferred from
spot tick activity.

Deliver:

- versioned Tokyo/London/New York/overlap/rollover/LBMA/session-close intervals;
- DST materialization and boundary tests;
- multi-timeframe aggregation and deterministic structure detectors;
- session statistics, breakout/acceptance/rejection/handover, spread/volatility
  anomaly rules;
- synchronized gold/yields/real-yield/breakeven/USD/equity/volatility/silver/Fed-path
  comparison where data exists; and
- Sessions/Structure and Cross-Market pages.

Exit: all required timeframes are supported, pivot and detection times are distinct,
and frequency/latency limitations are visible rather than interpolated away.

## M7 — Full scoring, reasoning, and execution intelligence

Deliver:

- versioned driver budgets, correlation groups, caps, reaction multipliers, coverage,
  conflict, neutrality, and confidence;
- score-component waterfall and snapshot-delta attribution;
- structured causal reasoning graph, contradictions, highest-risk assumption,
  confirmations, and invalidations;
- execution state, stop/risk/target calculation interfaces, event/slippage/cluster
  warnings, and daily-loss policy hooks; and
- all seven layers on Executive Overview, including explicit unknowns.

Exit: score recomputation is deterministic and bounded, a bullish bias cannot become
`TRIGGERED` without price/risk gates, and every displayed sentence has evidence.

## M8 — Event study and strategy backtester

Deliver:

- virtual-clock point-in-time repository and deterministic event queue;
- event-study horizons, MFE/MAE, first-move continuation/reversal, stratification,
  and confidence intervals;
- declarative strategy rules, order/fill/position state, costs, spread, slippage,
  latency, risk sizing, and benchmark;
- in/out-of-sample, walk-forward, parameter sensitivity, and Monte Carlo reshuffling;
  and
- Backtest Lab, comparison, saved experiment versions, and exports with manifests.

Exit: correctness micro-scenarios pass, metrics reconcile to trades/equity, and the
user can run both research modes from the UI without database editing.

## M9 — Data Health, security hardening, documentation, and release

Deliver:

- provider/series/job/quality dashboards and issue-resolution audit;
- authentication/authorization interfaces, dev principal, rate limits, secret
  handling, and audit queries;
- integration/end-to-end/load/recovery tests and backup/restore instructions;
- complete run, operations, provider, schema, API, and continuation documentation;
- optional constrained AI narrator behind a disabled-by-default feature flag; and
- final acceptance-criteria traceability report.

Exit: Docker Compose starts cleanly, seed and all required workflows succeed, tests
pass in CI, stale data and partial capability are obvious, and another developer can
continue without oral context.

---

# Exact First Vertical Slice (M2)

## 1. Question answered

> Given the gold bars and real-yield observations that were available at a selected
> time, is falling/rising real yield providing support/pressure, is price accepting a
> recent level, what session is active, and how much of the full intelligence picture
> is still unknown?

This is intentionally a partial market view. Its low evidence coverage is a feature:
it proves the product does not fabricate a full-confidence conclusion from two
inputs.

## 2. Inputs

### Synthetic fixture A: `xauusd_1m.v1.csv`

- five complete trading days of deterministic one-minute bars;
- explicit UTC bar open/close timestamps;
- provider `DEMO_XAUUSD`, `volume_type=TICK`, and `is_synthetic=true`;
- one designed resistance/acceptance sequence and one missing-bar quality case; and
- no claim that the volume represents the global OTC market.

### Synthetic fixture B: `us_real_yield_10y_daily.v1.csv`

- at least 90 business-day observations in percent;
- distinct observation, publication/availability, and ingestion timestamps;
- one deliberately later revision and one stale-as-of scenario; and
- provider `DEMO_MACRO`, `is_synthetic=true`.

Both fixture generators use a fixed seed and write manifests/checksums. Fixtures are
small enough for the repository and clearly watermarked.

## 3. Ingestion and storage

1. `POST /api/v1/ingestions/files` receives either file with an idempotency key.
2. API streams to the raw-object store while hashing; it does not load the whole file
   into memory.
3. Worker validates schema, timezone, ordering, OHLC geometry, unit, duplicates, and
   timestamps.
4. Original rows are appended to `raw.raw_records`.
5. Valid data is appended as observed facts plus `market.price_bars` or
   `market.observations`; the missing bar produces a quality issue.
6. Re-upload returns the original batch and cannot duplicate normalized facts.

## 4. Calculations

### Timeframe/session calculation

- Aggregate only closed one-minute bars into 5-minute bars with completeness state.
- Materialize Tokyo, London, New York, and overlap instances using IANA zones.
- Return the session containing `as_of`; session identity is `CALCULATED` context,
  not directional evidence.

### Signal A: `REAL_YIELD_5D_IMPULSE_V1`

Use the latest observation and the fifth prior eligible business observation as of
the calculation clock. FRED-style percentage-point values are converted to basis
points:

```text
delta_bp = (latest_percent - prior_percent) * 100
direction = clamp(-delta_bp / 20, -1, +1)
strength = min(100, abs(delta_bp) / 20 * 100)
```

The 20 bp full-strength scale, five-observation window, and freshness half-life are
configuration, not code. Falling real yield is positive for gold; rising is negative.
The signal is `CALCULATED`, belongs to Layer 6/driver `REAL_YIELD`, and cites both
observations. A stale latest value decays; a not-yet-available revision is excluded.

### Signal B: `FIVE_MINUTE_ACCEPTANCE_V1`

1. Calculate ATR(14) from fully closed 5-minute bars.
2. Detect a swing high with two left and two right bars and minimum configured
   prominence. The pivot becomes known only when the second right bar closes.
3. Treat the last qualifying pre-break swing high as resistance.
4. Require two consecutive complete 5-minute closes above
   `resistance + max(0.10 * ATR14, 2 * tick_size)`.
5. Store the level, evidence bars, detection time, confidence, and invalidation
   (a configured close back below the accepted zone).

The price facts and arithmetic are calculated; the label “acceptance” is
`INFERRED`. It belongs to Layer 7/driver `PRICE_CONFIRMATION`. An incomplete bar
cannot confirm it.

## 5. Score and layer output

- Use the baseline versioned budget/correlation calculation from
  [SCORING_ENGINE.md](SCORING_ENGINE.md).
- Only `REAL_YIELD` and `PRICE_CONFIRMATION` can contribute.
- Layers 1-4 and any unavailable parts of 5-7 return explicit unknown/partial status.
- Evidence coverage remains low and bounds analysis confidence.
- Execution state is `WAIT` unless acceptance is confirmed and a minimal research
  invalidation exists; even then the slice does not place a trade.
- Dominant driver, contradiction (if the two signals oppose), unknown requirements,
  and stale warnings are returned.

No fixed headline score is expected from the fixtures; tests assert the exact
component math from their data and configuration.

## 6. API surface in the slice

```text
GET  /api/v1/health/live
GET  /api/v1/health/ready
POST /api/v1/ingestions/files
GET  /api/v1/ingestions/{batch_id}
GET  /api/v1/jobs/{job_id}
GET  /api/v1/market-data/bars
POST /api/v1/intelligence/calculations
GET  /api/v1/intelligence/snapshots/latest
GET  /api/v1/intelligence/snapshots/{id}/signals
GET  /api/v1/data-health/summary
```

## 7. Frontend surface in the slice

Executive Overview renders:

- overall/bullish/bearish/neutrality/conflict scores;
- analysis versus execution confidence and evidence coverage;
- real-yield dominant driver or contradiction;
- current session and price acceptance state;
- all seven layer cards with partial/unknown status;
- data-health/missing-bar/stale warnings; and
- evidence drawers for both signals, including source times and formulas.

Other navigation routes may show honest “planned for Mx / required data” states; they
must not show fake charts.

## 8. Required tests before the slice is complete

### Unit/property

- OHLC validation and score bounds;
- real-yield direction/strength at positive, negative, zero, and capped changes;
- freshness decay and hard stale behaviour;
- session/DST interval membership;
- pivot not known before right-side bars close;
- incomplete 5-minute aggregate cannot confirm acceptance; and
- unknown signals contribute zero and reduce coverage.

### Integration

- migration from empty database;
- upload -> raw manifest/records -> normalized facts -> quality issue;
- identical upload is idempotent;
- a revision is excluded before `available_at` and included after it;
- calculation persists component/evidence lineage transactionally; and
- API `as_of` returns the correct historical snapshot.

### Frontend/end-to-end

- seed -> overview loads without direct database work;
- synthetic/partial/stale/inferred badges render;
- evidence drawer exposes formula and fact timestamps; and
- failed jobs and API errors show request/job IDs.

## 9. Definition of done

```text
docker compose up --build
```

starts the infrastructure and applications after documented environment setup. A
documented seed command ingests both fixtures, waits for jobs, calculates a snapshot,
and makes the overview usable. Backend, frontend, integration, and point-in-time
tests pass. OpenAPI and run instructions are current.

## 10. Toolchain to scaffold in M1

Backend/runtime:

- FastAPI, Uvicorn, Pydantic Settings, SQLAlchemy 2, Alembic, asyncpg;
- Celery, Redis, httpx, tenacity, structlog, and python-multipart;
- pandas, NumPy, SciPy, statsmodels, and standard-library `zoneinfo`;
- pytest, pytest-asyncio, Hypothesis, Ruff, and mypy.

Frontend:

- Next.js, React, TypeScript, Tailwind CSS, Recharts;
- TanStack Query, Zod, generated OpenAPI types/client;
- Vitest, React Testing Library, Playwright, and accessibility checks.

Infrastructure/quality:

- Docker Compose, PostgreSQL/TimescaleDB, Redis, GitHub Actions, and pre-commit;
- pinned dependency lock files, container health checks, JSON logs, and coverage
  thresholds established after the first slice rather than gamed with empty code.

## Session-edge research increment

The post-MVP strategy-research sequence is now:

| Milestone | Deliverable | Completion evidence |
|---|---|---|
| SE1 (complete) | Frozen C1 hypothesis and all-session opportunity contract | `SESSION_EDGE_RESEARCH.md`, versioned defaults, no hidden exclusions |
| SE2 (complete) | Point-in-time opportunity kernel | Deterministic aggregation, DST clocks, level map, sweep/reclaim/displacement, outcomes |
| SE3 (complete) | Persistence and API | Migration `0009`, append-only run/session rows, run and ledger endpoints |
| SE4 (complete) | Backtest Lab research view | Funnel, cohort comparison, opportunity evidence, explicit research status |
| SE5 (complete) | Observed-data discovery | 457 requested 2023-2024 sessions, 97 triggers, exact combined hash, edge not established |
| SE6 (complete) | Frozen executable C1 strategy | Price control: 19 trades, +0.164 R net, development PASS; fundamental primary: 8 trades, -0.044 R, development FAIL |
| SE7 (locked, not consumed) | One-shot validation | 2025 remains unopened because the primary failed the predeclared continuation gate |
| SE8 | New York extension | Intraday Treasury/USD confirmation and exact historical event clocks |

SE1-SE3 form the first vertical slice:

```text
observed IC Markets 1m bars + point-in-time fundamentals
-> immutable five-minute/session facts
-> London liquidity interaction
-> normalized outcome paths
-> persisted cohort study
-> API and Backtest Lab
```

The application remains runnable after each milestone. SE6 confirms a cost-robust
mechanical lead but rejects the current fundamental-aligned primary. The price
control is retained as a benchmark; it is not promoted as the intended
book-aligned strategy. SE7 remains locked until a materially improved causal-bias
contract passes development without consulting 2025.
