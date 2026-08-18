# Gold Macro-Acceptance Source Inventory V1

## Scope and controls

- Audit type: metadata-only source inventory and deduplication audit.
- Development boundary: 2021-08-01 through 2024-12-31 unless a source carries earlier support history.
- Market-value and outcome fields: not selected, inspected, or reported; only metadata fields were used.
- Relationship, outcome, signal, trade, and PnL calculations: none performed.
- Acquisition, provider jobs, and charges: none.
- 2025 and 2026 market values/outcomes: not opened.
- Classification vocabulary: `PRESENT_AND_ADEQUATE`, `PRESENT_BUT_PARTIAL`, `MISSING`, and `NOT_REQUIRED`.
- All timestamps below are UTC unless a local session timezone is stated explicitly.

## Verdict

The existing sealed sources are sufficient to start a defensible **proxy-based, post-release Gold Macro-Acceptance study without buying or downloading anything**. The study can measure whether gold accepts or rejects a released macro impulse using XAUUSD, ZT, ZN, EURUSD, the MT5 event timestamp, point-in-time FRED/ALFRED context, COT context, and the existing session/structure fields.

The source set is not sufficient to call every proxy the exact underlying market. Exact intraday DXY is absent, intraday US500 ends in January 2022, the ZQ/SR3 sources are front continuous contracts rather than a complete policy strip, and GC order-book coverage is a frozen 188-date sample rather than every development day. Those limits must remain explicit.

There is **no blocking acquisition** for the first proxy-based study. The smallest fidelity-upgrade list is DX and ES one-minute bars. Full-period GC one-minute bars and a multi-contract policy strip are optional extensions, not prerequisites.

## Requirement disposition

| Requirement | Classification | Exact coverage and resolution | Fitness for purpose |
|---|---|---|---|
| XAUUSD outcome, session path, price levels, structure | `PRESENT_AND_ADEQUATE` | IC Markets MT5, 1-minute: 1,218,292 unique timestamps from 2021-07-23T14:05:00Z through 2024-12-31T23:58:00Z; derived 5m/15m/1h/4h/1d bars; 1,659 sealed London/New York cases | Primary gold response and acceptance outcome; no full-period GC purchase is required for the first study |
| GC top-ten book and event flow | `PRESENT_BUT_PARTIAL` | Databento GLBX.MDP3 `GC.v.0`, MBO and MBP-10, 188 exact research dates from 2021-11-08 through 2024-12-13; 40 request intervals per schema | Suitable for a preregistered microstructure subset, not every development session |
| ZT two-year Treasury futures proxy | `PRESENT_AND_ADEQUATE` | Databento `ZT.v.0` OHLCV-1m: 1,034,835 unique rows, 2021-07-01T00:09:00Z through 2024-12-31T21:59:00Z | Intraday front-end rate response; continuous-roll boundaries remain unknown |
| ZN ten-year Treasury futures proxy | `PRESENT_AND_ADEQUATE` | Databento `ZN.v.0` OHLCV-1m: 1,182,295 unique rows, 2021-07-01T00:00:00Z through 2024-12-31T21:59:00Z | Intraday long-end nominal-rate response; continuous-roll boundaries remain unknown |
| ZQ Fed-funds futures | `PRESENT_BUT_PARTIAL` | Databento `ZQ.v.0` OHLCV-1m: 254,591 unique trade bars, 2021-07-01T02:33:00Z through 2024-12-31T21:58:00Z | Front continuous contract only; trade-bar sparsity and no complete meeting path |
| SR3 SOFR futures | `PRESENT_BUT_PARTIAL` | Databento `SR3.v.0` OHLCV-1m: 611,426 unique trade bars, 2021-07-01T01:00:00Z through 2024-12-31T21:59:00Z | Front continuous contract only; not a multi-expiry policy curve |
| EURUSD dollar proxy | `PRESENT_AND_ADEQUATE` | IC Markets MT5, 1-minute: 1,283,406 canonical unique timestamps from 2021-07-23T00:00:00Z through 2024-12-31T23:58:00Z | Usable as an explicitly named inverse-dollar proxy; must not be presented as DXY |
| Exact intraday DXY/DX | `MISSING` | No sealed exact DXY or ICE DX one-minute development source | Required only if the study must distinguish EURUSD-specific moves from the dollar basket |
| Daily rates, real yield, breakeven, broad USD, Fed rate | `PRESENT_AND_ADEQUATE` | Official FRED daily observations with conservative availability timestamps through 2024-12-31 | Slow-moving, point-in-time macro context; ZT/ZN provide the intraday response |
| Inflation, labour, growth vintages | `PRESENT_AND_ADEQUATE` | Official ALFRED vintage observations, monthly/weekly/quarterly, available through December 2024 | Point-in-time state and revision-aware context; exact event response comes from MT5 timestamps |
| Scheduled macro releases and exact response timestamps | `PRESENT_AND_ADEQUATE` | MetaQuotes calendar via IC Markets MT5: 412 sealed US events, 2021-07-28T18:00:00Z through 2024-12-26T13:30:00Z | Adequate for post-release macro acceptance and event taxonomy |
| Verifiable pre-release consensus/schedule vintages | `NOT_REQUIRED` | The existing MT5 calendar has forecasts, but none of the 412 historical event cases is approved for pre-release use | The proposed design is post-release. This becomes a separate missing requirement only if a pre-release surprise strategy is authorized |
| CFTC gold COT | `PRESENT_AND_ADEQUATE` | 260 weekly reports; observation 2020-01-07 through 2024-12-24; publication/availability 2020-01-10T20:30:00Z through 2024-12-27T20:30:00Z | Weekly positioning context, point-in-time constrained to Friday publication; not an intraday trigger |
| Daily equity, volatility, credit/stress context | `PRESENT_AND_ADEQUATE` | FRED SP500 and VIX daily through 2024-12-31; STLFSI4 weekly through 2024-12-28; high-yield OAS daily from 2023-07-25 through 2024-12-31 | Adequate for slow risk-regime context; high-yield history is partial before July 2023 |
| Intraday US equity-risk response | `PRESENT_BUT_PARTIAL` | MT5 US500 snapshots observed from 2021-07-23T19:30:00Z through 2022-01-15T00:00:00Z; 581 ready and 3,692 stale snapshots in the sealed casebook | Not adequate after 2022-01-14; ES one-minute data is the clean upgrade |
| Session, DST, structure, and price-level context | `PRESENT_AND_ADEQUATE` | 833 London and 826 New York cases from 2021-08-02 through 2024-12-31; IANA `Europe/London` and `America/New_York`; sealed one-minute-derived structure | Directly fit for acceptance/rejection conditioning |
| Atlanta Fed policy-expectation distributions | `PRESENT_BUT_PARTIAL` | 5,028 windows; observation dates 2023-03-29 through 2024-12-30; available through 2024-12-31T23:59:59.999999Z | Useful supplementary policy context, but not a complete 2021-2024 intraday meeting-by-meeting path |
| ETF flows, options/dealer gamma, central-bank purchases, licensed news | `NOT_REQUIRED` | Not required by the bounded first macro-acceptance question | May be added later as separate, licensed hypothesis families; absence must remain `UNKNOWN` |
| 2025 and 2026 values/outcomes | `NOT_REQUIRED` | Intentionally not inventoried beyond pre-existing metadata references and not opened | Locked/excluded under this audit instruction |

## Exact sealed lineage and hashes

| Payload | Lineage | Records/bytes | SHA-256 |
|---|---|---:|---|
| `price_bars.jsonl.gz` | IC Markets MT5 XAUUSD, normalized casebook bars | 1,570,471 / 258,834,096 | `0758f9a759bf63064d0ed4478383c10f9afd860bf993528b7909965c1639090e` |
| `structure_snapshots.jsonl.gz` | Deterministic structure rules over sealed XAUUSD bars | 3,270 / 41,815,377 | `31eea2decc8ed3f8d3e498a9339e7f59ee101e7c787da47a831e63bfb97c1064` |
| `sessions.jsonl.gz` | DST-aware London/New York session cases | 1,659 / 8,571,382 | `2695a2c0b9e8f41fcbf64c9f388e8883ebf7e1f0b3b09b90fb3a60ba7e64966a` |
| `events.jsonl.gz` | MetaQuotes calendar transported through IC Markets MT5 | 412 / 890,158 | `c7875e09d9ed831ece0f223b8be5efb75550af5bf1996a2dfea9d6119b24e35f` |
| Raw MT5 calendar CSV | MetaQuotes/IC Markets terminal export | 18,595 rows | `620e6897df79a44877ed703ef5fe11313319ddfe4c305855949d038db2872f7b` |
| `fundamentals.jsonl.gz` | FRED, ALFRED, and Atlanta Fed MPT normalized facts/snapshots | 26,394 / 8,511,617 | `d2b776f60c4535978bbfb28706b4700e6d054a10f8d57cfee171c83b212b7235` |
| `positioning.jsonl.gz` | CFTC Public Reporting, gold contract code 088691 | 260 / 92,793 | `e6d1aabf0d4401f3af4e54dc8ef4c0e4074772ec3f2199cfe9009b5a0b267228` |
| `cross_market_snapshots.jsonl.gz` | MT5 plus Databento cross-market normalization | 4,353 / 6,229,504 | `470a2e1c020cd2f97f2ad5b0d7f9c5220aff4f644689c4d680c24373964eb285` |
| V3 session case matrix | All preceding casebook artifacts joined point-in-time | 1,659 / 103,763,781 | `d0f5120713b5f9ce641c6285941bfc23d3aac3b83b561c8fc1138e33a5ede9b9` |
| CME OHLCV-1m source manifest | Databento job `GLBX-20260728-3SHU3737P8`; `ZT.v.0, ZN.v.0, ZQ.v.0, SR3.v.0` | 3,083,147 rows / four annual DBN sources | `fa99630c051cb6ffbb71bb1320698fa6cba8a40dc9464725a6af09843441cd0b` (file hash) |
| CME normalized lineage manifest | Deterministic annual normalization | 3,083,147 declared rows | `1e957829b3e96018c5499232da8c5d13a64df6db3dc4727accb867e6eb86dfcc` |
| GC acquisition manifest | Databento GLBX.MDP3 `GC.v.0` MBO/MBP-10, 80 requests | 188 dates / 1,311,616 bytes | `b4e64d508790364dbd400da1478b139bb643d2b7afc9c97ff6691958365c5ccc` |
| GC source verification | 936 sealed files; provider DBN, normalized payload, lineage and quality records | 39,857,519,209 verified bytes | `f36180c5adcbf12f0c0d518ea6f3511593a6cb120a33a74f8fafe2a6f163e657` |

The exact 188-date GC registry and every individual source/payload hash remain in the acquisition manifest above; duplicating that 1.3 MB registry into this audit would create a second authority, so this audit binds to it by hash.

### Databento OHLCV annual source hashes

| Year | Raw DBN SHA-256 | Normalized CSV SHA-256 |
|---:|---|---|
| 2021 | `78dd2363f2800a0ae7b91905c73a9917be3c9b7208312b4f1103360777a33cd1` | `cc772c5056dadca944c1aad18961f3c452df7fa05636512c35b67d75b38c2ced` |
| 2022 | `d87b30868761712f5a534bc25c8054c5f1b7ec20f4a8794713979497890b91d7` | `35f762edade525a5206d8dd68d949fae53564a4ef41018b12a3d139938b932f3` |
| 2023 | `ded98448b822428b0d0f702242e778824206f918072094704e8f5cd9872b02d1` | `80c5e005ec806559ef051421b35102cf931790aaf09ddbcfbcad181c737e42ae` |
| 2024 | `e8eda0dd921b40b3e488c7c6d54a61882e23c3b6c58d1b90809840975ff00c25` | `18c7d75ae505fae433378721146487778594a34be81cfe7518c2bc6738c735c1` |

## Fundamental observation coverage

The `observation` range is the source observation timestamp. `available` is the conservative point-in-time eligibility timestamp stored in the sealed casebook.

| Internal series (external code) | Frequency | Rows | Observation range | Available range |
|---|---:|---:|---|---|
| `USD_BROAD_NOMINAL` (`DTWEXBGS`) | daily | 4,762 | 2006-01-02T21:00:00Z – 2024-12-30T21:00:00Z | 2006-01-03T05:00:00Z – 2024-12-31T05:00:00Z |
| `US_TREASURY_2Y` (`DGS2`) | daily | 1,250 | 2020-01-02T21:00:00Z – 2024-12-30T21:00:00Z | 2020-01-03T05:00:00Z – 2024-12-31T05:00:00Z |
| `US_TREASURY_10Y` (`DGS10`) | daily | 1,250 | 2020-01-02T21:00:00Z – 2024-12-30T21:00:00Z | 2020-01-03T05:00:00Z – 2024-12-31T05:00:00Z |
| `US_REAL_YIELD_10Y` (`DFII10`) | daily | 1,250 | 2020-01-02T21:00:00Z – 2024-12-30T21:00:00Z | 2020-01-03T05:00:00Z – 2024-12-31T05:00:00Z |
| `US_BREAKEVEN_10Y` (`T10YIE`) | daily | 1,250 | 2020-01-02T21:00:00Z – 2024-12-30T21:00:00Z | 2020-01-03T05:00:00Z – 2024-12-31T05:00:00Z |
| `US_FED_FUNDS_EFFECTIVE` (`DFF`) | daily | 1,826 | 2020-01-01T21:00:00Z – 2024-12-30T21:00:00Z | 2020-01-02T05:00:00Z – 2024-12-31T05:00:00Z |
| `US_CPI_HEADLINE` (`CPIAUCSL`) | monthly/vintage | 214 | 2020-01-01T00:00:00Z – 2024-11-01T00:00:00Z | 2020-02-14T05:00:00Z – 2024-12-12T05:00:00Z |
| `US_CPI_CORE` (`CPILFESL`) | monthly/vintage | 212 | 2020-01-01T00:00:00Z – 2024-11-01T00:00:00Z | 2020-02-14T05:00:00Z – 2024-12-12T05:00:00Z |
| `US_PCE_HEADLINE` (`PCEPI`) | monthly/vintage | 400 | 2020-01-01T00:00:00Z – 2024-11-01T00:00:00Z | 2020-02-29T05:00:00Z – 2024-12-21T05:00:00Z |
| `US_PCE_CORE` (`PCEPILFE`) | monthly/vintage | 398 | 2020-01-01T00:00:00Z – 2024-11-01T00:00:00Z | 2020-02-29T05:00:00Z – 2024-12-21T05:00:00Z |
| `US_NONFARM_PAYROLLS` (`PAYEMS`) | monthly/vintage | 324 | 2020-01-01T00:00:00Z – 2024-11-01T00:00:00Z | 2020-02-08T05:00:00Z – 2024-12-07T05:00:00Z |
| `US_UNEMPLOYMENT_RATE` (`UNRATE`) | monthly/vintage | 125 | 2020-01-01T00:00:00Z – 2024-11-01T00:00:00Z | 2020-02-08T05:00:00Z – 2024-12-07T05:00:00Z |
| `US_AVERAGE_HOURLY_EARNINGS` (`CES0500000003`) | monthly/vintage | 282 | 2020-01-01T00:00:00Z – 2024-11-01T00:00:00Z | 2020-02-08T05:00:00Z – 2024-12-07T05:00:00Z |
| `US_INITIAL_JOBLESS_CLAIMS` (`ICSA`) | weekly/vintage | 1,088 | 2020-01-04T00:00:00Z – 2024-12-21T00:00:00Z | 2020-01-10T05:00:00Z – 2024-12-27T05:00:00Z |
| `US_REAL_GDP` (`GDPC1`) | quarterly/vintage | 113 | 2020-01-01T00:00:00Z – 2024-07-01T00:00:00Z | 2020-04-30T04:00:00Z – 2024-12-20T05:00:00Z |
| `US_RETAIL_SALES` (`RSAFS`) | monthly/vintage | 434 | 2020-01-01T00:00:00Z – 2024-11-01T00:00:00Z | 2020-02-15T05:00:00Z – 2024-12-18T05:00:00Z |
| `US_EQUITY_PROXY` (`SP500`) | daily | 1,257 | 2020-01-02T21:00:00Z – 2024-12-30T21:00:00Z | 2020-01-03T05:00:00Z – 2024-12-31T05:00:00Z |
| `US_VOLATILITY_INDEX` (`VIXCLS`) | daily | 1,276 | 2020-01-02T21:00:00Z – 2024-12-30T21:00:00Z | 2020-01-03T05:00:00Z – 2024-12-31T05:00:00Z |
| `US_FINANCIAL_STRESS` (`STLFSI4`) | weekly | 1,618 | 1993-12-31T21:00:00Z – 2024-12-27T21:00:00Z | 1994-01-01T05:00:00Z – 2024-12-28T05:00:00Z |
| `US_HIGH_YIELD_OAS` (`BAMLH0A0HYM2`) | daily | 378 | 2023-07-24T20:00:00Z – 2024-12-30T21:00:00Z | 2023-07-25T04:00:00Z – 2024-12-31T05:00:00Z |

## Event coverage and response-path availability

| Family | Events | Released-at range |
|---|---:|---|
| CPI | 41 | 2021-08-11T12:30:00Z – 2024-12-11T13:30:00Z |
| FOMC | 28 | 2021-07-28T18:00:00Z – 2024-12-18T19:00:00Z |
| GDP | 40 | 2021-07-29T12:30:00Z – 2024-12-19T13:30:00Z |
| Jobless claims | 179 | 2021-07-29T12:30:00Z – 2024-12-26T13:30:00Z |
| NFP | 41 | 2021-08-06T12:30:00Z – 2024-12-06T13:30:00Z |
| PCE | 42 | 2021-07-30T12:30:00Z – 2024-12-20T13:30:00Z |
| Retail sales | 41 | 2021-08-17T12:30:00Z – 2024-12-17T13:30:00Z |

Exact minute endpoints present among the 412 event timestamps:

| Source | 0m | 1m | 5m | 15m | 30m | 60m | All six |
|---|---:|---:|---:|---:|---:|---:|---:|
| XAUUSD | 409 | 409 | 409 | 409 | 409 | 409 | 409 |
| EURUSD | 411 | 411 | 411 | 411 | 411 | 411 | 411 |
| ZT.v.0 | 411 | 411 | 411 | 409 | 409 | 411 | 408 |
| ZN.v.0 | 411 | 411 | 411 | 411 | 411 | 411 | 411 |
| ZQ.v.0 | 364 | 337 | 291 | 246 | 230 | 190 | 92 |
| SR3.v.0 | 388 | 381 | 373 | 358 | 358 | 363 | 300 |

This confirms why ZQ/SR3 trade bars are partial for an exact event-path study and why ZT/ZN are the stronger intraday rate-response sources already owned.

## Deduplication audit

1. **XAUUSD:** 42 pre-2025 raw CSVs, 149,997,122 bytes, 1,218,292 rows and 1,218,292 unique timestamps. Duplicate timestamp count: zero. File-inventory SHA-256: `470a967e087130d749e12d13ec7014f9ed6b171edaa8244b183cf97d62da7744`.
2. **EURUSD:** 46 raw CSVs contain 1,312,129 rows but only 1,283,406 unique timestamps. All 28,723 duplicate timestamp occurrences come from one wholly redundant export: `eurusd_1m_ic_markets_mt5_20221205T0000_20230102T2358.csv`, SHA-256 `c2e13bca6a79d8a63f044fef2fb4f0cc4b07b4a578a2d064756b462cb5cb4504`. The canonical read set excludes that file without deleting or modifying it: 45 files, 158,962,791 bytes, 1,283,406 unique timestamps, canonical file-inventory SHA-256 `2876497d48f833144db12b61c3e876721ba0a1fe6475167362a5fb1bc732dfae`.
3. **ZT/ZN/ZQ/SR3:** 3,083,147 total OHLCV-1m rows; zero duplicate timestamps inside each continuous symbol. The existing Databento job and annual files are authoritative—do not request them again.
4. **Casebook:** all 1,606,819 sealed records have unique record IDs and verified record hashes. The V3 case matrix has 1,659 unique session keys.
5. **GC:** Step 5B.2 independently verified 80 unique provider requests, 80 unique source seals, 936 files, and 39,857,519,209 bytes. The source-inventory checksum is `41b380dc697bf57dad709ccc45b40a0acea5d980bd38804688377be005139bfd`. Reacquisition would duplicate already sealed data.
6. **MT5 calendar versus ALFRED:** these are not duplicates. MT5 supplies exact event/release timestamps and released calendar fields; ALFRED supplies conservative vintage-aware slow macro history. Keep the roles separate.
7. **Daily FRED rates versus ZT/ZN:** these are not duplicates. FRED supplies daily observed levels; futures supply intraday market repricing. Neither should silently replace the other.

## Minimal missing-data acquisition list

### Blocking

None. Freeze the first study as proxy-based and begin with existing sealed sources.

### Smallest recommended fidelity upgrade, only if exact markets are required

1. **Exact dollar basket:** Databento ICE US Futures, continuous front DX (`DX.v.0`), one-minute OHLCV, 2021-08-01T00:00:00Z through 2025-01-01T00:00:00Z. This replaces no source; it complements EURUSD.
2. **Intraday US risk:** Databento CME, continuous front ES (`ES.v.0`), one-minute OHLCV, the same interval. This replaces the stale post-January-2022 US500 path while retaining daily SP500/VIX context.

No request or estimate was submitted in this audit.

### Optional, not required for the first study

1. Full-period `GC.v.0` OHLCV-1m for exact COMEX price confirmation outside the 188 microstructure dates. XAUUSD remains the primary full-period gold outcome.
2. A preregistered multi-expiry ZQ/SR3 strip using stable calendar ranks and quote/settlement data if the research question explicitly requires the complete expected Fed path. Do not reacquire `ZQ.v.0` or `SR3.v.0` front continuous trade bars.
3. A licensed point-in-time consensus source only if a future contract changes the question from post-release acceptance to pre-release surprise prediction.

## Explicit no-repurchase list

Do not reacquire XAUUSD, EURUSD, the MT5 calendar, FRED/ALFRED history, CFTC COT, `ZT.v.0`, `ZN.v.0`, `ZQ.v.0`, `SR3.v.0`, or the existing 188-date `GC.v.0` MBO/MBP-10 set. All are already present with sealed lineage.

## Audit stop

The inventory and deduplication audit is complete. No market relationship was calculated, no holdout was opened, and no acquisition was initiated.
