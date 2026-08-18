# Data-Source Plan

Verified against official source documentation on 27 July 2026. Provider terms,
interfaces, and release schedules can change, so every adapter exposes a health and
metadata check rather than assuming permanent availability.

## 1. Source policy

1. Prefer official government, central-bank, exchange, or properly licensed feeds.
2. Preserve the original payload and its retrieval/publication metadata.
3. Never infer a precise publication timestamp from an observation date without a
   documented policy and quality warning.
4. Do not scrape protected calendars, benchmarks, or exchange pages.
5. Treat redistribution and non-display analytical rights as separate license
   questions.
6. Keep the credential-free demo runnable with synthetic fixtures.
7. A missing paid dataset produces an `UNKNOWN` layer/signal, not fabricated data.

## 2. Phase 1 matrix

| Domain | Phase 1 source | Access mode | Point-in-time treatment | Later option |
|---|---|---|---|---|
| XAUUSD OHLCV | User/demo CSV | Required adapter | Explicit bar open/close and provider availability | Licensed spot or broker feed |
| COMEX contract OHLCV/OI/volume | CSV interface only | Optional | Contract identity and publication/fill latency required | Licensed CME feed/DataMine |
| 2Y/10Y nominal, 10Y real, breakeven | FRED/ALFRED; optional Treasury verification | Public API | Preserve vintages and actual source availability; daily data is not intraday confirmation | Licensed intraday Treasury feed |
| Dollar | Fed nominal broad dollar index `DTWEXBGS`; IC Markets EURUSD bars | Public FRED/H.10 plus observed broker feed | Weekly broad index is daily context only; completed EURUSD bars are an `INFERRED` inverse intraday-USD proxy and are never relabelled DXY | Licensed DXY and broader real-time FX basket |
| CPI/core CPI/NFP/unemployment | BLS plus ALFRED vintages | Public API | Exact scheduled/release time plus initial/revised values | Licensed normalized macro feed |
| PCE/core PCE | BEA plus ALFRED vintages | Public API | Exact release and vintage identity | Licensed normalized macro feed |
| Fed policy rate | Federal Reserve/FRED | Public API | Target range/effective rate series with release availability | Direct licensed policy feed unnecessary |
| Consensus forecasts | Manual JSON or licensed Trading Economics adapter | Required | Every snapshot has `available_at`; last eligible pre-release snapshot wins | Additional licensed consensus provider |
| Fed path/probabilities | Atlanta Fed MPT quarterly SOFR distributions; optional licensed CME FedWatch EOD | Public download / optional license | Historical observation date is delayed conservatively; exact meeting snapshots retain official publication clocks | Licensed intraday futures-derived path |
| COT | CFTC public reporting data | Public download/API | Tuesday observation is unavailable until actual publication | Same interface for licensed normalized feed |
| ETF flows/holdings | Manual licensed upload or mock | Optional | Publication delay and vintage retained | Authorized WGC/vendor feed |
| Central-bank demand | Manual/mock | Optional | Slow-moving, publication-lagged; never used for a five-minute explanation | Authorized WGC/IMF/vendor feed |
| Options/strikes/IV/gamma | Mock/provider interface | Out of scored Phase 1 when absent | Dealer gamma always `INFERRED`; quality requires coverage | Licensed CME/options vendor |
| Equity/VIX | FRED public market series | Public API | Conservative next-day availability; daily confirmation only | Licensed intraday market-data feed |
| Silver | Generic timestamped CSV | Optional | Provider and exact availability required | Licensed market-data feed |
| Event metadata | MT5 calendar, U.S. Treasury Fiscal Data auctions, Federal Reserve RSS, plus manual JSON | Public/broker/manual | Scheduled time can change; versions retained; released RSS items are not a forward calendar | Licensed economic calendar |
| News/geopolitical events | Manual event metadata | Optional | Source and first-known timestamp required | Licensed news/event feed |

## 3. Official public adapters

### FRED and ALFRED

The [FRED observations API](https://fred.stlouisfed.org/docs/api/fred/series_observations.html)
supports real-time periods, vintage dates, and an initial-release-only output. The
[ALFRED documentation](https://alfred.stlouisfed.org/help) explicitly supports
retrieving values that were available on past dates. These capabilities are the
default public path for revision-aware macro research.

Initial canonical series:

| Canonical series | FRED ID | Native use |
|---|---|---|
| `us_treasury_2y` | `DGS2` | Daily 2-year nominal yield |
| `us_treasury_10y` | `DGS10` | Daily 10-year nominal yield |
| `us_tips_10y_real` | `DFII10` | Daily 10-year TIPS real yield |
| `us_breakeven_10y` | `T10YIE` | Daily 10-year breakeven inflation |
| `usd_broad_nominal` | `DTWEXBGS` | Fed nominal broad dollar index |
| `us_equity_proxy` | `SP500` | Daily S&P 500 equity-risk proxy |
| `us_volatility_index` | `VIXCLS` | Daily implied-volatility/risk proxy |
| `us_financial_stress` | `STLFSI4` | Weekly St. Louis Fed Financial Stress Index |
| `us_high_yield_oas` | `BAMLH0A0HYM2` | Daily US high-yield option-adjusted spread |
| `cpi_all_items` | `CPIAUCSL` | CPI index; MoM/YoY are calculated features |
| `cpi_core` | `CPILFESL` | Core CPI index |
| `pce_price_index` | `PCEPI` | PCE price index |
| `pce_core_price_index` | `PCEPILFE` | Core PCE price index |
| `nonfarm_payrolls` | `PAYEMS` | Total nonfarm payroll level/change |
| `unemployment_rate` | `UNRATE` | Unemployment rate |
| `fed_funds_effective` | `DFF` | Effective federal funds rate |
| `fed_target_upper` | `DFEDTARU` | Target-range upper bound |
| `fed_target_lower` | `DFEDTARL` | Target-range lower bound |

The source catalog verifies title, unit, frequency, seasonal adjustment, and current
source metadata before activating a series. A series-ID match alone is insufficient.
The public graph adapter also enforces the requested start/end dates after parsing:
FRED can return a discontinued series' full archive even when query dates were
supplied. Genuine out-of-range rows are not admitted to a newly declared batch.

Daily FRED values do not become intraday observations merely because the API returns
them. For example, the [Federal Reserve H.10 release](https://www.federalreserve.gov/Releases/H10/)
publishes the prior week's daily dollar observations on a weekly schedule. The engine
therefore shows its latency and does not use it to claim five-minute USD confirmation.

The Treasury's [daily interest-rate feed](https://home.treasury.gov/treasury-daily-interest-rate-xml-feed)
is a secondary authoritative source and metadata cross-check. The adapter records
the source actually used; values from different series are not silently merged.

### BLS

The [BLS Public Data API](https://www.bls.gov/developers/home.htm) supplies published
time-series data. BLS release-calendar metadata supplies scheduled timestamps for
CPI and Employment Situation events. ALFRED or retained original payloads provide
the revision history needed for point-in-time studies.

The event record stores individual components. A payroll headline cannot overwrite
wages, unemployment, participation, or revisions, and an economic-surprise feature
links to the exact component it describes.

### BEA

The [BEA API](https://apps.bea.gov/api/signup/) provides NIPA data including PCE and
GDP. Original release payloads and ALFRED vintages are retained because BEA revises
historical values. Release events link headline and core series without combining
their surprises.

### Federal Reserve

Federal Reserve calendars, statements, target-range changes, projections, and
speeches are official event metadata. Phase 1 scores structured policy-rate/path
facts only; it does not apply unconstrained sentiment analysis to speeches.

The implemented RSS adapter consumes the Federal Reserve's official speech and
monetary-policy feeds. It preserves the feed publication timestamp and classifies
released statements, projections, minutes, press conferences, and speeches as
event metadata. Every RSS item is `RELEASED`, has
`forward_calendar_eligible=false`, and carries no hawkish/dovish direction unless a
separate, versioned text model is later implemented and validated.

### U.S. Treasury auctions

The implemented adapter uses the official Treasury Securities Auctions Data API.
It stores the announcement date, auction date, security term/type, CUSIP, offering
amount, and the competitive bid close. The source's Eastern-time close is converted
with `America/New_York`, so daylight-saving changes are deterministic. Where the
source supplies only an announcement date, availability is conservatively the end
of that New York date. The auction is a scheduled catalyst, not a directional
signal before its result is known.

### CFTC COT

The [CFTC COT documentation and API entry point](https://www.cftc.gov/MarketReports/CommitmentsofTraders/index.htm)
states that reports generally contain Tuesday data and are published Friday at
15:30 US Eastern time. The separate
[release schedule](https://www.cftc.gov/MarketReports/CommitmentsofTraders/ReleaseSchedule/index.htm)
contains holiday-shifted dates.

Adapter rules:

- use the disaggregated report for managed money and producer/merchant categories;
- retain futures-only versus futures-and-options-combined identity;
- map the provider's gold market code through catalog metadata, not name matching on
  every run;
- store the Tuesday observation date and actual publication timestamp separately;
- never expose a report before `publication_at`;
- derive net, weekly change, percentile, and crowding as calculated features; and
- mark price/open-interest interpretations as `INFERRED`.

CFTC notes that a complete historical list of actual release dates is not published.
For an unverified historical week, Phase 1 either requires an imported publication
timestamp or uses a deliberately conservative availability date after the normal
window and emits `DQ_IMPRECISE_AVAILABILITY`. Backtest sensitivity reports disclose
that policy. It never silently assumes Friday for every week.

## 4. Licensed or manual sources

### Gold prices, volume, and open interest

COMEX is the transparent exchange proxy, but CME distinguishes data licenses for
display, non-display analysis, and distribution. The
[CME licensing page](https://www.cmegroup.com/market-data/license-data.html) is the
governing starting point. Phase 1 therefore supports a documented CSV contract and
does not redistribute bundled CME history.

Spot XAUUSD rows always carry a provider/venue label. Spot `volume` must declare
whether it is tick volume, provider volume, or unknown; it is never described as
global gold volume.

The connected IC Markets MT5 export supplies completed one-minute OHLC,
`tick_volume`, and broker `spread_points`. Terminal metadata validated XAUUSD at
two decimals with `SYMBOL_POINT=0.01`, so the normalized adapter can derive
`spread_price`. This is a broker quote and activity sample: it supports execution
friction and abnormal-liquidity warnings, but it is neither COMEX depth nor
centralized gold volume. A future exchange adapter must use `volume_type=EXCHANGE`
and retain its own venue and license metadata.

The same provider-independent price contract now accepts `EURUSD_1M` with
`SYMBOL_POINT=0.00001`. The observed store contains 1,283,406 completed IC Markets
EURUSD one-minute bars from 23 July 2021 through 31 December 2024. Research uses
only completed EURUSD bars as an inverse intraday-USD proxy: rising EURUSD can
confirm weak-dollar support for long gold and falling EURUSD can confirm
strong-dollar pressure for short gold. That relationship is `INFERRED`, not an
observed DXY fact. It supplies no intraday Treasury-yield or Fed-path evidence.

The normalized store also contains 1,221,634 completed IC Markets XAGUSD
one-minute bars from 21 July 2021 through 31 December 2024. XAGUSD is an
`OBSERVED` broker silver quote and its relationship to gold is a calculated or
inferred confirmation, not proof of institutional activity.

The immutable local research archive contains 1,212,998 completed IC Markets
US500 minutes over the same pre-2025 boundary and 328,177 TLT.NAS minutes from
21 July 2021 through 31 December 2024. The first 173,860 US500 bars, through
15 January 2022 00:00 UTC, are normalized in PostgreSQL; the frozen
cross-market study streamed the full monotonic CSV archive directly and
required complete five-minute buckets. TLT.NAS is an `OBSERVED` ETF price but
only an `INFERRED` inverse nominal-yield proxy. It is never presented as an
observed Treasury yield, and its exchange hours leave London-session rate
confirmation unavailable.

The frozen cross-instrument transfer archive adds six previously untested
IC Markets instruments. It was exported read-only from the connected
`ICMarketsKE-Demo` terminal, ends at the exclusive `2025-01-01` boundary, and
contains 7,595,984 observed one-minute broker bars in 132 immutable CSV chunks:

| Instrument | One-minute bars | First broker bar | Final pre-2025 broker bar |
|---|---:|---|---|
| AUDUSD | 1,302,348 | 2021-07-01 00:00 UTC | 2024-12-31 23:58 UTC |
| GBPUSD | 1,305,872 | 2021-07-01 00:00 UTC | 2024-12-31 23:58 UTC |
| USDJPY | 1,305,828 | 2021-07-01 00:00 UTC | 2024-12-31 23:58 UTC |
| USTEC | 1,240,097 | 2021-07-01 01:00 UTC | 2024-12-31 23:59 UTC |
| DE40 | 1,205,174 | 2021-07-01 01:02 UTC | 2024-12-30 23:58 UTC |
| XTIUSD | 1,236,665 | 2021-07-01 01:00 UTC | 2024-12-31 23:58 UTC |

The short initial index/energy gaps occur before the August research start and
reflect the first broker trading session, not imputed prices. The research
loader rejects duplicate or out-of-order minutes, requires five consecutive
observed minutes for every five-minute bucket, and never fills a market closure.
These rows are broker CFD/FX observations and tick activity, not exchange
consolidated volume.

Every transfer backtest uses the historical per-minute broker spread. The Raw
Spread FX planning model also charges 3.50 USD per standard lot per side, as
described by IC's
[Raw Spread account page](https://www.icmarkets.com/global/en/trading-accounts/raw-spread-account).
USDJPY uses a deliberately conservative fixed price equivalent for that USD
commission. IC's published
[index specification](https://www.icmarkets.com/global/en/trading-markets/indices)
states no index commission, and its
[commodity specification](https://cdn.icmarkets.com/uploads/FSA/Commodity-Specification-Sheet.pdf)
lists zero Raw Spread commission for commodities. Additional adverse slippage
is still charged per side and every result is repeated at 1.50 times total
friction. These public specifications are research assumptions, not a substitute
for reconciling the user's exact IC Markets KE account statement before paper or
live deployment.

At the 27 July 2026 provider audit, the same terminal catalog exposed
`DXY_U6` (US Dollar Index September 2026 CFD) and `UST10Y_U6` (US 10-year
Treasury-note September 2026 CFD). It exposed no 2-year Treasury contract. Direct
read-only history requests returned recent bars for `DXY_U6` but no bars for the
January 2024 research probe; `UST10Y_U6` likewise returned no January 2024 bars.
These current-contract symbols can support prospective cross-market observation
after contract-identity/roll handling is implemented. They cannot supply
historical intraday confirmation for the 2023-2024 discovery ledger, and the
system must not backfill that gap with current or daily values.

### Acquired historical rates/path dataset

The non-duplicative acquisition was CME exchange history, not another gold
broker feed. Databento batch job `GLBX-20260728-3SHU3737P8` completed on
2026-07-28 for `GLBX.MDP3`, `ohlcv-1m`, from 2021-07-01 through the exclusive
2025-01-01 boundary. The provider billed `11.25590525567532 USD` of historical
credit and returned `3,083,147` records in four annual DBN files.

The acquired symbols are:

- `ZT.v.0`: volume-led 2-year Treasury-note future;
- `ZN.v.0`: volume-led 10-year Treasury-note future;
- `ZQ.v.0`: volume-led 30-day Fed-funds future; and
- `SR3.v.0`: volume-led three-month SOFR future.

The immutable download, provider manifest, request condition, metadata,
normalization manifest, and normalized gzip CSVs live under the gitignored
`data/raw/databento_cme_pre2025/` directory. Every downloaded file passed a
SHA-256 comparison against both the Databento manifest and the local acquisition
manifest. Coverage begins at `2021-07-01T00:00:00Z` and the final bar begins at
`2024-12-31T21:59:00Z`; no 2025 record is present.

Databento's
[continuous-contract documentation](https://databento.com/docs/standards-and-conventions/symbology)
states that these map to actual contracts over time and return original,
unadjusted prices. Normalization therefore retains `instrument_id` on every
bar. Returns spanning an instrument-ID change are `UNKNOWN`, never interpreted
as market moves. The point-in-time feature loader makes each minute bar
available at interval start plus one minute, never fabricates volume, carries
Treasury prices for at most 10 minutes and policy-futures prices for at most
60 minutes, and reports older values as `UNKNOWN`.

The resumable acquisition command is `tools/databento_cme_history.py`; its
request fingerprint prevents a power loss from creating a duplicate batch
order. The credential remains only in `DATABENTO_API_KEY` in the gitignored
root `.env`. [Databento historical pricing](https://databento.com/pricing)
describes the usage-based service. Official
[CME DataMine](https://www.cmegroup.com/datamine.html) remains the
direct-exchange fallback.

### Fed expectations

[CME FedWatch](https://www.cmegroup.com/en/markets/interest-rates/cme-fedwatch-tool.html)
has a published methodology and an official licensed End-of-Day API. The MVP never
scrapes the webpage. The licensed adapter and manual fallback both retain every
meeting bucket and probability so the engine can calculate the expected rate,
first-move timing, total easing/tightening, destination, and path repricing—not
merely a single next-meeting probability.

### LBMA windows and benchmark data

The [LBMA source page](https://www.lbma.org.uk/prices-and-data/lbma-precious-metal-prices)
confirms auctions commencing at 10:30 and 15:00 London time and states that use of
real-time or historical benchmark data requires licensing. Phase 1 uses the times as
session markers through `Europe/London`; it does not ingest benchmark values unless
the operator supplies licensed data.

### ETF and central-bank data

World Gold Council datasets are valuable but access and usage terms must be honored.
Its [ETF holdings and flows page](https://www.gold.org/goldhub/data/gold-etfs-holdings-and-flows)
describes weekly/monthly update timing. Phase 1 accepts authorized manual files,
preserves the publication delay, and otherwise reports the signal as unknown.

Central-bank demand is slow-moving structural context. It can support a monthly or
quarterly thesis but cannot be selected as the cause of an intraday spike unless a
new, timestamped disclosure is present.

## 5. Canonical file contracts

All files are UTF-8 with a header, schema version, provider code, and explicit time
zone in either the timestamp or file manifest. Naive timestamps are rejected.

### `price_bars.v1.csv`

Required:

```text
instrument,provider,timeframe,bar_open_at,bar_close_at,open,high,low,close
```

Optional:

```text
volume,volume_type,bid,ask,spread,spread_points,source_sequence,source_published_at
```

`spread_points` is accepted only when the provider contract defines its point size.
Otherwise use a price-denominated `spread` or leave it unknown.

### `series_observations.v1.csv`

```text
series_code,provider,observation_start,observation_end,value,unit,
source_published_at,available_at,vintage_date,revision_no
```

### `economic_events.v1.csv`

```text
event_key,event_type,country,title,scheduled_at,actual_release_at,importance,status
```

### `forecast_snapshots.v1.csv`

```text
event_key,series_code,provider,consensus,high,low,forecaster_count,unit,available_at
```

### `cot_disaggregated.v1.csv`

```text
market_code,report_type,observation_date,publication_at,category,long,short,
spreading,change_long,change_short,pct_oi_long,pct_oi_short
```

JSON ingestion uses equivalent versioned Pydantic contracts. Unknown columns are
retained in the raw payload but do not enter normalized tables until the schema is
explicitly extended.

The implemented JSON contract nests forecasts and release components under a
versioned event. It additionally requires `forecast_as_of`, forecast
`available_at`, release `released_at`, release `available_at`, vintage identity,
unit, and an explicit bundle-level `is_synthetic` flag. The sample file under
`data/sample` is synthetic by construction and is excluded from every
`REAL_ONLY` query.

## 6. Data-quality and staleness policy

Each series definition declares expected frequency, maximum normal latency, hard
stale threshold, unit, and range policy. Checks include:

- missing/duplicate periods and unexpected calendar gaps;
- out-of-order or overlapping bars;
- invalid OHLC geometry and non-positive prices;
- unit or seasonal-adjustment changes;
- future timestamps and publication-before-observation anomalies;
- revision sequence conflicts;
- forecast snapshots arriving after release;
- COT publication/observation misalignment;
- implausible jumps using robust rolling statistics; and
- provider freshness and schema drift.

A suspect observation remains auditable but receives lower quality or quarantine.
The UI shows last observation, last availability, ingestion time, stale threshold,
and any open issue. Staleness decay is handled by the scoring engine; source values
are never modified to represent decay.

## 7. Provider interface

Every adapter implements the same conceptual contract:

```text
describe() -> provider/dataset metadata and capabilities
health() -> authentication, quota, schema, and freshness status
fetch(cursor, requested_range) -> immutable source envelopes
parse(envelope, schema_version) -> validated source records
normalize(record) -> observed facts with temporal metadata
checkpoint() -> resumable cursor/watermark
```

Capabilities declare supported history, revisions, forecast snapshots, timestamp
precision, update cadence, and license restrictions. Analytics depends on canonical
series and facts, never on adapter classes.

## 8. Implemented credential-free adapters

`FRED_PUBLIC` currently retrieves one series per request from the public FRED graph
CSV endpoint: `DGS2`, `DGS10`, `DFII10`, `T10YIE`, `DTWEXBGS`, `DFF`, `SP500`,
`VIXCLS`, `STLFSI4`, and `BAMLH0A0HYM2`. Requests are serialized to respect the
low-volume endpoint. These daily or weekly values receive a conservative
`NEXT_CALENDAR_DAY_00_ET` availability clock, so a London decision cannot see the
same US close. This adapter is deliberately not used as a substitute for
ALFRED-style vintages of revisable CPI, PCE, growth, or labour data.

`CFTC_PUBLIC` uses the official Disaggregated Futures Only dataset and COMEX gold
contract-market code `088691`. It retains producer/merchant, swap-dealer,
managed-money, and other-reportable long/short/spreading fields plus open interest
and trader counts. The 2026 official release schedule is encoded exactly, including
holiday-shifted Monday releases. Older rows are labelled
`ESTIMATED_STANDARD_FRIDAY`; they receive lower data quality and must not be used for
a strict historical decision near a holiday until an exact historical calendar is
loaded.

The current store contains 19,920 normalized FRED public observations, 4,845
ALFRED vintage observations, and 342 gold COT reports. The 27 July refresh exposed
an upstream graph-endpoint edge case:
two discontinued/lagged series returned genuine older history outside the requested
range. Those immutable real observations were preserved; the adapter now applies a
tested local date fence so later batches cannot misstate their range. Both raw
datasets remain content-addressed and append-only. Public endpoints require no
credential. A free FRED API key is required for the separate official API/ALFRED
vintage adapter; licensed forecasts, ETF, options, depth, and dealer-gamma data
remain separate provider contracts.

The credential-free official-catalyst adapter has also stored 248 Treasury auction
events and 30 released Federal Reserve communications. Treasury events use exact
competitive bid closes and conservative announcement availability. Federal Reserve
RSS rows are retrospective released metadata only; they are excluded from the
forward-calendar and directional-tone contracts.

## 9. Current event-data boundary

The platform has a working provider-independent intake, surprise engine, and
reaction study. The connected IC Markets MetaTrader terminal supplied a real
MetaQuotes economic-calendar archive covering July 2021 through July 2026:

| Stage | Rows |
|---|---:|
| Immutable US source rows | 18,595 |
| Selected Phase 1 macro components | 1,119 |
| Grouped economic releases | 588 |
| Observed component releases | 1,117 |
| Consensus snapshots | 1,059 |

The raw file hash, exporter clocks, terminal offset, component identifiers, source
names, units, multipliers, and annual bundle hashes are retained for audit. The
selected families are headline/core CPI, headline/core PCE, payrolls,
unemployment, hourly earnings, jobless claims, GDP, retail sales, and FOMC target
rate decisions. Non-scope rows remain in the immutable raw export rather than
silently disappearing.

This archive does not reveal when each historical consensus was first published.
Accordingly, archived consensus is available only at the exact release boundary.
It is valid for post-release surprise/reaction studies and unavailable to a
pre-release backtest decision. This is deliberately conservative and is not a
substitute for a timestamped institutional forecast-vintage feed.

## 10. Implemented ALFRED vintage adapter

`ALFRED_OFFICIAL` calls the official `fred/series/observations` endpoint with
`output_type=1`, the real-time-period format that returns observation date, value,
real-time start, and real-time end for each revision. Output types 2 and 3 are
vintage-date cross-tabulations and are intentionally not parsed as row-wise
revisions. The adapter covers:

| External | Internal |
|---|---|
| `CPIAUCSL` | `US_CPI_HEADLINE` |
| `CPILFESL` | `US_CPI_CORE` |
| `PCEPI` | `US_PCE_HEADLINE` |
| `PCEPILFE` | `US_PCE_CORE` |
| `GDPC1` | `US_REAL_GDP` |
| `RSAFS` | `US_RETAIL_SALES` |
| `PAYEMS` | `US_NONFARM_PAYROLLS` |
| `UNRATE` | `US_UNEMPLOYMENT_RATE` |
| `CES0500000003` | `US_AVERAGE_HOURLY_EARNINGS` |
| `ICSA` | `US_INITIAL_JOBLESS_CLAIMS` |

The free official API key is mandatory. Raw responses never store or expose it.
Because ALFRED real-time periods are dates, not exact release instants, each row is
made eligible only at 00:00 New York on the following date. This is conservative
for intraday backtesting and distinct from the exact-timestamp event contract.

## 11. Implemented MetaQuotes/MT5 calendar adapter

`METAQUOTES_MT5_CALENDAR` uses the terminal-only MQL5 Calendar API through
`GoldIntelCalendarExport.mq5`; the host bridge then copies and audits the CSV before
normalization. Mapping is by stable MetaQuotes event ID plus exact name, code,
country, currency, unit, and multiplier checks. A provider rename or contract
change therefore fails closed instead of being guessed.

IC Markets KE calendar timestamps were validated against both summer and winter US
release clocks and use the versioned `IC_MARKETS_KE_FIXED_UTC_PLUS_3_V1` policy.
The importer rejects any different runtime offset until that broker policy is
explicitly revalidated. Raw records are content-hashed and normalized into annual,
idempotent bundles through the normal `/events/bundles` API.

The source classifications are:

- release values: `OBSERVED`;
- actual-minus-consensus and standardized surprise: `CALCULATED`;
- the configured gold-direction interpretation: `INFERRED`;
- absent consensus or unsupported fields: `UNKNOWN`.

FOMC target decisions contain observed outcomes but no usable consensus target in
this archive. The system leaves those surprises unknown; it does not fabricate a
forecast. Meeting-by-meeting expected paths remain a separate CME/manual contract.

## 12. Licensed expectations adapters

### Atlanta Fed Market Probability Tracker

`ATLANTA_FED_MPT` downloads the historical workbook through the explicit
[Atlanta Fed Market Probability Tracker](https://www.atlantafed.org/research-and-data/data/market-probability-tracker)
download link. It does not scrape page markup or call an undocumented endpoint.
The workbook contains real distributions estimated from CME three-month SOFR
options, including distribution mean/mode/25th/75th percentiles, cut and hike
probabilities, and 25-basis-point probability bins.

The live file validated on 24 July 2026 contains 10,023 reference windows across
833 observation dates from 29 March 2023 through 22 July 2026. The adapter stores
the original XLSX unchanged by SHA-256, validates its embedded license wording,
and normalizes each future three-month reference window. It is labelled
`QUARTERLY_AVERAGE_SOFR_DISTRIBUTION`; it is never relabelled as an exact FOMC
meeting probability.

The download provides observation dates but no historical publication timestamps.
Each observation is therefore ineligible until 23:59:59 UTC on the next US federal
business day. This deliberately sacrifices some timeliness to prevent look-ahead.
The workbook permits personal and educational use only. Commercial deployment or
redistribution requires separate permission or a licensed replacement.

No API key is needed:

```powershell
Invoke-RestMethod -Method Post -Uri http://localhost:8000/api/v1/providers/atlanta-fed-mpt/sync
```

### Trading Economics

`TRADING_ECONOMICS` calls the licensed US economic-calendar endpoint in bounded
date chunks and maps the supported CPI, PCE, payrolls, unemployment, wages, claims,
GDP, retail-sales, and FOMC components into the provider-independent event
contract. Raw source rows remain immutable. Credentials are never written into raw
metadata.

The provider returns historical consensus but not the timestamp when that
consensus first became visible. Those forecasts receive
`HISTORICAL_RELEASE_BOUNDARY` availability and can support post-release surprise
analysis only. A future/live snapshot receives the engine's real retrieval clock
and may support pre-event decisions from that point forward. This deliberately
forgoes false historical precision.

### CME FedWatch End-of-Day

`CME_FEDWATCH_EOD` uses CME OAuth client credentials and the official
`/fedwatch/v1/forecasts` contract. It obtains past and future FOMC meeting dates,
requests bounded reporting-date/meeting-date grids, validates that every meeting
distribution sums to one, and retains the source lower/upper target-range bounds.
The stored expected rate is the exact range midpoint; the integer outcome key is
the range upper bound.

CME documents each `reportingDt` forecast as published at 01:45 UTC on business
days. That clock becomes both `snapshot_as_of` and `available_at`. Ingestion time
is retained separately. One sync is limited to 367 calendar days to protect API
quotas. There is no assumed free historical FedWatch feed; the manual JSON contract
remains available when no entitlement is connected.
