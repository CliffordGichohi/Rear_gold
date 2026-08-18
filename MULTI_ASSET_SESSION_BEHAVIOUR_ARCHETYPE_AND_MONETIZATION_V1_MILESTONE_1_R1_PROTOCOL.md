# Multi-Asset Session Behaviour V1 — Milestone 1-R1 Protocol

Status: **frozen before timestamp-level metadata access**

The Milestone 1 verdict `FAIL_MILESTONE_1_COVERAGE_STOP` remains unchanged. This protocol diagnoses only why the universal every-minute rule failed.

## Failed units

- `EURUSD|ASIA_SESSION`
- `USDJPY|ASIA_SESSION`
- `XAGUSD|ASIA_SESSION`
- `US500|LONDON_SESSION`
- `XTIUSD|LONDON_SESSION`

## Passing metadata controls

- `EURUSD|LONDON_SESSION`
- `EURUSD|NEW_YORK_SESSION`
- `USDJPY|LONDON_SESSION`
- `USDJPY|NEW_YORK_SESSION`
- `XAGUSD|LONDON_SESSION`
- `XAGUSD|NEW_YORK_SESSION`
- `USTEC|LONDON_SESSION`
- `USTEC|US_CASH_SESSION`
- `US500|US_CASH_SESSION`
- `XTIUSD|US_ENERGY_SESSION`

## Ordered tests

1. `T01_VERIFY_ALL_PREDECESSOR_AND_SOURCE_SEALS`
2. `T02_VERIFY_FROZEN_IDENTITY_COUNT_KEYS_AND_SESSION_CLOCKS_UNCHANGED`
3. `T03_READ_ONLY_OPEN_TIME_AND_CERTIFY_DUPLICATES_ORDER_FIRST_LAST_AND_DEVELOPMENT_FILTER`
4. `T04_EXTRACT_EVERY_MAXIMAL_CONSECUTIVE_MISSING_MINUTE_RUN_IN_START_INCLUSIVE_END_EXCLUSIVE`
5. `T05_CLASSIFY_RUN_BOUNDARY_POSITION_AND_LENGTH_BIN`
6. `T06_MAP_RUNS_TO_FROZEN_SESSION_LOCAL_CLOCK_WEEKDAY_AND_DST_STATE`
7. `T07_MAP_RUNS_TO_PROVIDER_SERVER_CLOCK_PROXY_AND_CURRENT_DOCUMENTED_SCHEDULE_SHAPE`
8. `T08_MEASURE_EXACT_RUN_SIGNATURE_RECURRENCE_BY_CALENDAR_YEAR_WITH_ALL_FROZEN_UNIT_DATES_AS_DENOMINATOR`
9. `T09_MEASURE_CROSS_INSTRUMENT_SAME_UTC_MINUTE_ABSENCE`
10. `T10_AUDIT_ACQUISITION_CHUNK_AND_LINEAGE_FAILURE_METADATA`
11. `T11_APPLY_CLASSIFICATION_PRECEDENCE_WITHOUT_VALUE_ACCESS`
12. `T12_COMPARE_ALL_TEN_PASSING_UNITS_AS_CONTROLS`
13. `T13_REQUIRE_PRIMARY_REFERENCE_EXACT_RECORD_SUMMARY_CLASSIFICATION_AND_CHECKSUM_PARITY`

## Classification discipline

The frozen precedence is documented closure, recoverable sealed source, explicit source failure, normal no-tick bar emission, then unresolved. A current IC schedule is not sufficient historical proof by itself. It can support `DOCUMENTED_MARKET_UNAVAILABLE` only when the identical provider-clock pattern recurs on at least 80% of frozen dates in **every** development year and all other frozen gates pass.

MetaTrader's official timeseries documentation establishes that an M1 interval without a tick does not produce a bar. `NORMAL_NO_TICK_BAR_EMISSION` is therefore permitted only for an interior one- or two-minute gap with both adjacent minutes present, low exact-clock recurrence, no broad cross-instrument outage, and no lineage failure. It is a technical disposition, not a claim about unseen prices.

Protocol hash: `938f33fe21e9bd73170a97a918aa5b8ae198368cec1316d910fe3907255884ab`  
Schedule-evidence hash: `f44991c021bb11126587373f4c75360649054de6696e64d91bdc0eacb3a04145`

No market value, outcome, behaviour, edge or PnL may be accessed or calculated. R1 can recommend one bounded correction but cannot implement it.
