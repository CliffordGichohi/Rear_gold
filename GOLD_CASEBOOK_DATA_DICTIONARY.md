# Gold Casebook v0.1 Data Dictionary

## Authority and scope

This dictionary defines milestone 2 of
`GOLD_CASEBOOK_RESEARCH_CONTRACT.md`. The Gold & USD Market Intelligence
Reference Book remains the market-logic specification.

The case interval is `2021-08-01T00:00:00Z` through, but excluding,
`2025-01-01T00:00:00Z`. Earlier records may appear only as declared warm-up
evidence. Calendar 2025 is locked and is not loaded.

This casebook is descriptive. It contains no optimized entry, stop, target,
reward-to-risk, profit, MFE, MAE, or directional outcome label.

## Bundle and integrity

The immutable bundle is `research_artifacts/gold_casebook_v01/`.

| File | Grain | Purpose |
|---|---|---|
| `manifest.json` | One bundle | Contract, versions, counts, source manifests, file SHA-256 hashes, known limits, and bundle hash |
| `price_bars.jsonl.gz` | One XAUUSD bar | Observed 1-minute IC Markets bars and deterministic 5m, 15m, 1h, 4h, and New-York-trading-day bars |
| `structure_snapshots.jsonl.gz` | One unique decision/close timestamp | Point-in-time six-timeframe deterministic market structure |
| `fundamentals.jsonl.gz` | One raw observation, policy record, or decision snapshot | Vintages, first-known times, levels, changes, transparent regime/components, and provenance |
| `positioning.jsonl.gz` | One CFTC publication | Full disaggregated categories, Tuesday observation, Friday publication, changes, percentile, and explicitly inferred positioning states |
| `events.jsonl.gz` | One event version | Release components, forecast eligibility, revisions, surprises, and fixed post-release observations |
| `cross_market_snapshots.jsonl.gz` | One unique requested timestamp | Point-in-time XAUUSD, EURUSD, XAGUSD, US500, ZT, ZN, ZQ, and SR3 values and changes |
| `sessions.jsonl.gz` | One London or New York case | Decision-known state, separate later observation, levels, interactions, source paths, and joins to other records |

Every JSONL row has:

- `record_type`: schema discriminator;
- `record_id`: deterministic immutable join key;
- `casebook_version`: `GOLD_CASEBOOK_V0_1`;
- `schema_version`: `gold-casebook-schema-0.1.0`;
- `epistemic_status`: epistemic class for the record as a whole;
- `holdout_loaded`: always `false`; and
- `record_hash`: SHA-256 of canonical JSON before `record_hash` is added.

Gzip files use a zero modification time, sorted JSON keys, UTF-8, and compact
JSON so identical inputs reproduce identical bytes.

## Epistemic states

| State | Meaning |
|---|---|
| `OBSERVED` | Direct source value with source record identity and availability |
| `CALCULATED` | Deterministic arithmetic or deterministic rule applied to observed inputs |
| `INFERRED` | Interpretation supported by multiple facts but not directly observed |
| `UNKNOWN` | Missing, stale, not licensed, or not point-in-time verified |
`UNKNOWN` is never converted to zero, neutral, safe, or no-event.

## Time fields and availability

All datetimes are timezone-aware ISO-8601 and materialized as UTC. Session
clocks are constructed with IANA `Asia/Tokyo`, `Europe/London`, and
`America/New_York`; daylight-saving changes therefore alter UTC timestamps
without altering the local session clock.

| Field | Meaning |
|---|---|
| `open_time`, `close_time` | Price interval boundaries |
| `observation_time` / `observation_date` | Economic period or COT Tuesday state |
| `scheduled_at` | Declared event clock; not proof the schedule was known earlier |
| `released_at` | Source release clock |
| `available_at` | Earliest time the particular fact may enter a simulation |
| `ingested_at` | When this system stored the record; it is not market availability |
| `decision_at` | London or New York local session open |
| `observation_end` | Fixed local session close, stored separately from decision state |
| `detected_at` | First time a structure detection could be confirmed |
| `timestamp` | Structure pivot/action time, which may precede `detected_at` |

No nested fact may be used before its own `available_at`, even when it lives in
a retrospective event or session record.

## Price bars

`PRICE_BAR` records contain:

- provider, instrument, and timeframe;
- OHLC, tick volume, observed broker spread, and availability;
- `complete` and `missing_source_minutes`;
- source batch/key bounds, source count, and `source_hash`; and
- a calculation version.

The 1-minute rows are `OBSERVED`. Higher timeframes are `CALCULATED`.
Intraday bars are fixed UTC buckets. Daily bars use the existing IC Markets
New York trading-day template, including its Monday start and scheduled pause.
Broker tick activity is not centralized COMEX volume.

## Structure snapshots

`STRUCTURE_SNAPSHOT` is calculated only from complete bars whose close and
availability are no later than `as_of`.

It contains all required timeframes: `1m`, `5m`, `15m`, `1h`, `4h`, and `1d`.
Each timeframe records:

- source/complete bar counts and last close;
- ATR, trend, support, resistance, and range;
- compression and momentum state; and
- detections for swings, HH/HL/LH/LL, support/resistance, break of structure,
  market-structure shift, breakout, acceptance, rejection, failed breakout,
  trapped breakout, retest, compression, expansion, displacement, and momentum
  when the configured deterministic rules detect them.

Each detection preserves timestamp, `detected_at`, price, timeframe, method,
confidence, evidence, epistemic status, and invalidation. Source-bar lists are
compacted to count, first/last ID, and a SHA-256 hash.

The declared finite lookback is a feature definition, not a performance-tuned
parameter: 720 bars for each intraday timeframe and 500 daily bars.

## Fundamental records

`FUNDAMENTAL_OBSERVATION` retains the source value, unit, observation time,
availability, vintage, revision status, superseded identity, ingestion batch,
and source key. Later revisions never overwrite original vintages.

`POLICY_PATH_POINT` is reserved for exact meeting distributions when licensed
or otherwise available. The initial pre-2025 bundle has no such records.

`POLICY_EXPECTATION_WINDOW` contains real Atlanta Fed market-probability
tracker quarterly SOFR distributions. It must not be relabelled as exact
meeting-level FedWatch probability.

`FUNDAMENTAL_SNAPSHOT` is created at each session decision clock. It includes:

- the latest point-in-time eligible value for every series;
- prior value, absolute/percent change, change per day, vintage, and staleness;
- the transparent Reference-Book-aligned fundamental engine state;
- component/layer explanations and source evidence;
- COT join, event risk, reaction function, regime, contradictions, and missing
  drivers; and
- a warning that score is an inferred feature, not a trade or win probability.

The series set covers CPI/core CPI, PCE/core PCE, payrolls, unemployment,
wages, claims, GDP, retail sales, policy rate, 2-year/10-year nominal yields,
10-year real yield, breakeven inflation, dollar, equities, volatility, high
yield spreads, and financial stress where available.

## Positioning

`POSITIONING_REPORT` retains all observed disaggregated futures-only CFTC
categories:

- managed money;
- producer/merchant;
- swap dealer; and
- other reportable.

Observed fields include longs, shorts, spreading, trader counts, percentages
of open interest, total open interest, Tuesday observation date, Friday
publication time, ingestion time, source key, and availability quality.

Calculated fields include net values, weekly changes, change acceleration,
historical percentile using only already-published reports, open-interest
change, and gold-price change between publications.

Crowding, probable fresh participation, short covering, long liquidation, and
liquidation/covering risk are `INFERRED`; the record states that motives are
not directly observed.

## Events

`EVENT_CASE` retains event versions rather than overwriting them. Each record
contains release components, observation period, actual, previous,
revised-previous, unit, vintage, forecast, forecast availability, raw and
standardized surprise evidence, and fixed reaction snapshots.

Historical MetaQuotes calendar schedules and consensus have release-boundary
availability but no verified earlier first-publication timestamp. Therefore:

- `schedule_verified_for_pre_event_use` is false;
- `pre_event_state.schedule` and `.consensus` are `UNKNOWN`; and
- the same forecast may be used after release to calculate a surprise but may
  not be used to claim a pre-release forecast edge.

Reactions use the reference, +1m, +5m, +15m, +1h, +4h, and New York daily-close
snapshots where available. They are descriptive fixed-horizon calculations.
No MFE, MAE, entry, stop, or target is calculated.

## Cross-market snapshots

`CROSS_MARKET_SNAPSHOT` retains as-of values plus fixed 5-minute, 1-hour,
4-hour, 1-day, and 5-day changes.

- XAUUSD, EURUSD, XAGUSD, and US500 are observed IC Markets broker prices.
- ZT and ZN are observed continuous Treasury-futures price proxies, not
  observed yields.
- ZQ and SR3 prices are observed; `100 - price` is stored as a calculated
  implied-rate percentage.
- A change crossing a Databento `instrument_id` roll is `UNKNOWN`.
- A stale US500 value after its January 2022 source end is `STALE`, never
  carried forward as current confirmation.

Daily FRED nominal/real yields and breakeven inflation live in the fundamental
snapshot; CME futures supply separate intraday pricing context.

## Session cases

`SESSION_CASE` is the joinable unit for later information-edge research.

The London decision is 08:00 Europe/London and the New York decision is 08:00
America/New_York. Both observations end at 12:00 local time. A case is admitted
only when all prerequisite 5-minute source buckets are complete.

`decision_state` contains only facts available at `decision_at`:

- Asia/London/New York window state as then known;
- prior same session, prior trading day, and prior week;
- known Asia/London/prior-day/prior-week levels;
- structure, fundamental, cross-market, and latest eligible COT joins.

`subsequent_observation` is explicitly `decision_eligible: false` and contains:

- session OHLC/range and close availability;
- close-time structure;
- level breach, two-close acceptance, rejection, and failed accepted break;
- the complete 5-minute path with hashes; and
- a precise reference to the immutable one-minute rows.

`research_policy` confirms that the case has no assigned direction, return,
MFE, MAE, or optimized execution.

## Known unavailable or partial information

- No verified historical pre-event schedule or consensus vintage.
- No licensed historical unscheduled-news feed.
- No centralized intraday COMEX gold open interest/volume in the initial data.
- US500 intraday data ends on 14 January 2022.
- Quarterly SOFR expectation windows are not exact FOMC meeting probabilities.
- Continuous CME futures prices can contain contract changes; affected changes
  are rejected rather than spliced silently.

These limitations remain visible in records and the bundle manifest.
