# Gold Casebook Coverage Audit

## Decision

Milestone 1 is complete for the development interval `2021-08-01T00:00:00+00:00` through `2025-01-01T00:00:00+00:00`. This audit loaded no calendar-2025 row and calculated no directional or execution outcome.

Deterministic evidence hash: `079f426fe6128a153e8714c814269617b96fa94c38cccacf85a06204c45dfbb6`.

## Session completeness

| Slice | Weekdays | Asia | London | New York | London cases | New York cases |
|---|---:|---:|---:|---:|---:|---:|
| all | 892 | 840 | 874 | 872 | 833 | 826 |
| 2021 | 110 | 94 | 107 | 107 | 92 | 92 |
| 2022 | 260 | 249 | 256 | 257 | 249 | 249 |
| 2023 | 260 | 246 | 252 | 249 | 241 | 234 |
| 2024 | 262 | 251 | 259 | 259 | 251 | 251 |

A London case requires complete Asia and London windows. A New York case requires complete Asia, London, and New York windows. Exchange holidays remain recorded as incomplete weekdays.

## Observed market sources

| Instrument | Provider | Rows | First | Last | Spread | Volume | PIT-valid |
|---|---|---:|---|---|---:|---:|---:|
| EURUSD | IC_MARKETS_MT5 | 1274793 | 2021-08-02T00:03:00+00:00 | 2024-12-31T23:58:00+00:00 | 1274793 | 1274793 | 1274793 |
| US500 | IC_MARKETS_MT5 | 162868 | 2021-08-02T01:00:00+00:00 | 2022-01-14T23:59:00+00:00 | 162868 | 162868 | 162868 |
| XAGUSD | IC_MARKETS_MT5 | 1210606 | 2021-08-02T01:00:00+00:00 | 2024-12-31T23:58:00+00:00 | 1210606 | 1210606 | 1210606 |
| XAUUSD | IC_MARKETS_MT5 | 1210817 | 2021-08-02T01:02:00+00:00 | 2024-12-31T23:58:00+00:00 | 1210817 | 1210817 | 1210817 |

Databento CME rates contain **3,083,147** normalized pre-2025 one-minute rows. File hashes and row counts match the normalization manifest.

| CME symbol | Rows | First | Last | Contract IDs |
|---|---:|---|---|---:|
| SR3.v.0 | 611426 | 2021-07-01T01:00:00+00:00 | 2024-12-31T21:59:00+00:00 | 17 |
| ZN.v.0 | 1182295 | 2021-07-01T00:00:00+00:00 | 2024-12-31T21:59:00+00:00 | 15 |
| ZQ.v.0 | 254591 | 2021-07-01T02:33:00+00:00 | 2024-12-31T21:58:00+00:00 | 36 |
| ZT.v.0 | 1034835 | 2021-07-01T00:09:00+00:00 | 2024-12-31T21:59:00+00:00 | 15 |

## Point-in-time fundamental coverage

| Series | London eligible | New York eligible | Effective London records |
|---|---:|---:|---:|
| USD_BROAD_NOMINAL | 100.0% | 100.0% | 805 |
| US_AVERAGE_HOURLY_EARNINGS | 100.0% | 100.0% | 42 |
| US_BREAKEVEN_10Y | 100.0% | 100.0% | 807 |
| US_CPI_CORE | 100.0% | 100.0% | 45 |
| US_CPI_HEADLINE | 100.0% | 100.0% | 45 |
| US_EQUITY_PROXY | 100.0% | 100.0% | 813 |
| US_FED_FUNDS_EFFECTIVE | 100.0% | 100.0% | 833 |
| US_FINANCIAL_STRESS | 100.0% | 100.0% | 179 |
| US_HIGH_YIELD_OAS | 42.8571% | 42.8571% | 357 |
| US_INITIAL_JOBLESS_CLAIMS | 100.0% | 100.0% | 179 |
| US_NONFARM_PAYROLLS | 100.0% | 100.0% | 42 |
| US_PCE_CORE | 100.0% | 100.0% | 42 |
| US_PCE_HEADLINE | 100.0% | 100.0% | 42 |
| US_REAL_GDP | 100.0% | 100.0% | 42 |
| US_REAL_YIELD_10Y | 100.0% | 100.0% | 807 |
| US_RETAIL_SALES | 100.0% | 100.0% | 45 |
| US_TREASURY_10Y | 100.0% | 100.0% | 807 |
| US_TREASURY_2Y | 100.0% | 100.0% | 807 |
| US_UNEMPLOYMENT_RATE | 100.0% | 100.0% | 43 |
| US_VOLATILITY_INDEX | 100.0% | 100.0% | 829 |

## Positioning, expectations, and events

- COT is eligible for 100.0% of complete London cases and 100.0% of complete New York cases. The London cases use 179 distinct published weekly observations.
- Atlanta Fed expectation windows are eligible for 51.7407% of London coverage probes; they are quarterly policy distributions, not meeting-level FedWatch.
- The store has 742 historical release-boundary consensus rows and 0 verified pre-event rows. Consequently historical catalyst schedules and consensus remain UNKNOWN before release.

## Field status

- `AVAILABLE`: 31
- `DERIVABLE_PENDING_CASEBOOK`: 14
- `MISSING`: 2
- `PARTIAL`: 4
- `POST_RELEASE_ONLY`: 1

## Material gaps

- **NO_VERIFIED_HISTORICAL_PRE_EVENT_CALENDAR** (`MATERIAL`): Upcoming-event risk and historical consensus must be UNKNOWN before release; release-boundary consensus remains usable afterward.
- **NO_CENTRALIZED_INTRADAY_GC_VOLUME_OPEN_INTEREST** (`LIMITATION`): Broker tick activity and weekly CFTC open interest cannot be represented as centralized intraday COMEX activity.
- **NO_LICENSED_UNSCHEDULED_EVENT_HISTORY** (`LIMITATION`): Historical unscheduled-event state remains UNKNOWN.
- **FED_PATH_IS_QUARTERLY_WINDOW** (`LIMITATION`): 443 Atlanta Fed observation dates do not equal meeting-level FedWatch history.
- **PARTIAL_INTRADAY_US500** (`MATERIAL`): Observed US500 minute history ends at 2022-01-14T23:59:00+00:00.
- **CATALOG_PROVENANCE_METADATA_MISMATCH** (`DATA_QUALITY`): US_REAL_YIELD_10Y catalog metadata says synthetic_fixture while normalized rows and FRED batches are non-synthetic.

These gaps are recorded, not filled or treated as neutral. They do not prevent materializing price, structure, macro, COT, and post-release case facts, but they limit pre-event and some cross-market cases.

## Next contracted step

Milestone 2 is the immutable casebook and data dictionary. It was not started by this audit run.

## Reproduce

```powershell
docker compose --profile test run --rm `
  -v "${PWD}:/workspace" `
  backend-test python tools/audit_gold_casebook_coverage.py `
  --start 2021-08-01 --end 2025-01-01 `
  --cme-normalization /workspace/data/raw/databento_cme_pre2025/GLBX-20260728-3SHU3737P8/normalized/normalization.json `
  --json-output /workspace/research_artifacts/gold_casebook_coverage_v01.json `
  --markdown-output /workspace/GOLD_CASEBOOK_COVERAGE.md
```
