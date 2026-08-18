# Reference-Book Alignment and Remaining Data Boundary

## Authority and decision contract

`Gold_USD_Market_Intelligence_Reference_Book.pdf` is the primary business and
market-logic specification. The canonical runtime ruleset is
`gold-reference-book-7-layer-v1`; the registered evidence contract is
`gold-reference-book-2026-07-v8`.

The engine implements the book as an ordered decision process, not seven equal
votes:

```text
Layers 1-4 and 6 -> directional evidence
Layer 5          -> session, liquidity, and price-acceptance gate
Layer 7          -> trigger, invalidation, and risk gate
```

A macro bias can never create an entry. Missing evidence is `UNKNOWN`, reduces
coverage, and can force `WAIT`; it is never converted to neutral evidence.

The canonical live artifact is:

```text
POST /api/v1/decisions/snapshots
GET  /api/v1/decisions/snapshots/latest?instrument=XAUUSD
```

The older `/api/v1/intelligence/*` vertical-slice endpoints remain only for
compatibility and are marked deprecated in OpenAPI.

## Seven-layer implementation matrix

| Layer | Implemented and traceable now | Remaining boundary |
|---|---|---|
| 1. Market regime | Vintage-aware CPI, core CPI, PCE, core PCE, GDP, retail sales, payrolls, unemployment, wages, claims; Fed rate; 2Y/10Y nominal and 10Y real yields; breakeven; curve; broad USD; equities, VIX, and financial-stress context; level, direction, and rate of change | Structured SEP projections remain `UNKNOWN` until official projection contents are normalized |
| 2. Expectations and pricing | Actual-versus-consensus, actual-versus-previous, revisions, standardized surprise; real Atlanta Fed quarterly SOFR probability distributions; full-path level and repricing rules | Exact meeting-by-meeting FedWatch history, exact first expected FOMC move, and rule-derived statement/press-conference tone require entitled CME data, timestamped manual data, or a future official-text normalizer |
| 3. Positioning and institutional behaviour | CFTC managed-money long/short/net/change/percentile, producer hedging, COMEX report open interest, price/open-interest motive rules labelled `INFERRED` | Authorized ETF and central-bank files; licensed options strikes/expiries/call-put OI/IV/delta/gamma; complete fast-money versus slow-money divergence |
| 4. Catalysts and event risk | Real MT5 calendar archive, forecasts with explicit temporal restrictions, releases/revisions/surprises, 1m/5m/15m/1h/4h/daily reactions, MFE/MAE and first-move reversal; official Treasury auction closes; released Fed speech and monetary-policy metadata | Forward Fed speech calendar and unscheduled geopolitical/financial news remain `UNKNOWN` without a timestamped official/manual calendar or licensed news feed |
| 5. Sessions and liquidity | DST-aware Asia/London/New York/overlap, rollover, LBMA windows, session handovers; broker spread, tick activity, range volatility, abnormal-liquidity classification; six-timeframe structure and acceptance/rejection | Centralized depth, resilience, and market-impact estimates require a suitable broker depth feed or licensed exchange data |
| 6. Cross-market confirmation | Point-in-time daily gold, 2Y/10Y nominal, real yield, breakeven, broad USD, equities, VIX, stress, nominal decomposition, confirmation and contradiction logic; synchronized observed IC Markets EURUSD bars as a clearly labelled inverse intraday-USD proxy | Intraday 2Y/real-yield/Fed-path confirmation, licensed DXY, and optional silver confirmation remain unavailable; EURUSD is not relabelled as any of them |
| 7. Execution and risk | Bias, trigger, invalidation, stop distance, target, reward-to-risk, event gate, liquidity/slippage gate, and daily research risk budget are separate server outputs | Account equity, live total open risk, portfolio clusters, daily-loss state, and final lot size remain `UNKNOWN` until an explicitly enabled read-only account-risk adapter is connected |

## Coverage semantics

At the 27 July 2026 alignment checkpoint, the registry reports:

| Measurement | Value | Meaning |
|---|---:|---|
| Registry factors | 97 | Full evidence catalog, including two non-layer market-mechanics contracts |
| Layered book factors known | 69 / 95 (72.63%) | A real evidence contract exists and has data |
| Phase 1 factors known | 69 / 80 (86.25%) | Phase 1 implementation coverage |
| Layered factors usable at 07:21 UTC | 54 / 95 (56.84%) | Evidence was also fresh enough at that exact clock |

Known coverage and live usability are intentionally different. Weekend closures,
stale daily releases, or an old broker bar reduce *usable now* without erasing the
fact that the provider is connected. Directional-component coverage is a third,
narrower measurement and must never be presented as full-book coverage.
Per-series observation counts on the operational report use a bounded ten-year
window to keep sparse macro hypertables responsive; older immutable raw and
normalized history remains stored and point-in-time queryable.

## Free and licensed source boundary

| Source | Cost/access | Runtime treatment |
|---|---|---|
| IC Markets MT5 XAUUSD bars/spread/tick volume | Existing broker demo/live terminal; no separate market-data API fee for the current bridge | `OBSERVED` broker data; not centralized COMEX volume or depth |
| IC Markets MT5 EURUSD bars/spread/tick volume | Existing broker terminal; no separate market-data API fee for the current bridge | `OBSERVED` EURUSD data and an `INFERRED` inverse intraday-USD confirmation proxy; not licensed DXY or intraday rates |
| FRED market series and CFTC public reports | Free official endpoints | Connected |
| ALFRED vintage macro | Free FRED API key | Connected |
| MetaQuotes economic calendar | Included in the connected MT5 terminal | Connected; archived consensus is eligible only at the release boundary because its first-publication time is unavailable |
| Atlanta Fed Market Probability Tracker | No API key; workbook terms are personal/educational only | Connected as quarterly SOFR distributions, never relabelled exact FedWatch |
| U.S. Treasury Fiscal Data auctions | Free official API | Connected with exact Eastern-time competitive close and conservative announcement availability |
| Federal Reserve RSS | Free official feed | Connected for released communications only; not a forward speech calendar and not a tone model |
| Exact CME FedWatch meeting history | Entitled/licensed CME API or timestamped user file | `UNKNOWN` until supplied |
| COMEX options, dealer gamma, depth | Licensed exchange/vendor data | `UNKNOWN` until supplied |
| WGC ETF/central-bank datasets | Authorized download/API subject to terms | `UNKNOWN` until an authorized file is supplied |
| Real-time institutional consensus/news | Licensed provider or timestamped manual input | `UNKNOWN` until supplied |

No protected website is scraped, no license restriction is bypassed, and no paid
field is replaced with pseudo-data.

## Backtest alignment

`BOOK_ALIGNED_ASIA_ACCEPTANCE_RESEARCH_V1` version `1.5.0` is an auditable research
candidate, not a proven strategy. It uses:

```text
point-in-time macro permission
-> known catalyst-risk gate
-> session and broker-liquidity gate
-> closed-bar price acceptance
-> next-bar fill
-> structure/ATR invalidation
-> risk-based sizing
-> modeled spread, slippage, and commission
```

The book-aligned defaults fail closed when either catalyst risk or liquidity is
unknown. The Backtest Lab exposes `allow_unknown_event_risk` and
`allow_unknown_liquidity` only as explicit, stored research overrides. Results
created with either override are useful ablations but are not strict book-aligned
evidence.

The current Asia/London acceptance hypothesis has been falsified on an untouched
2023 interval. Strict v1.5 rejected all 61 candidates because historical
pre-release catalyst risk was unknown
(`fddda1a6-f5c2-432c-ae4b-ed9030ee2dbc`). The explicit catalyst-risk override
retained 16 trades but lost 0.414617 R per trade and 649.48 USD, with a 0.542568
profit factor and 11.333195% drawdown
(`fd03a168-48e0-4f25-a9dd-c9bcfb6de956`). No edge is claimed. Broader 2021-2024
tests of London/New York continuation, rejection, retest, post-event, multilevel
reclaim, and EURUSD-confirmation variants also failed the predeclared stability
gates. The next valid research target is the book's full post-event causal chain:
surprise, Fed-path repricing, intraday 2Y/real-yield and USD confirmation, then
gold structure acceptance.

## Completion definition

The software framework is aligned when every book factor is represented,
implemented factors are traceable and point-in-time correct, unavailable factors
remain visible as `UNKNOWN`, and execution fails closed where missing evidence
changes risk. It does **not** require buying every institutional dataset before the
MVP can run. It does require those missing datasets before making claims that rely
on them.
