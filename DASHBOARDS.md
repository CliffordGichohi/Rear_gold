# Dashboard Wireframes

## Implementation note

The Executive, Macro, Positioning, Events, Backtest, and Data Health routes are
runnable. The Events route now includes event-bundle upload, Fed-path-bundle
upload, explicit real-data event-study controls, point-in-time calendar rows,
surprise explanations, exclusions, and reaction summaries. Unconnected surfaces
remain visibly empty rather than rendering placeholder market claims.

## 1. Shared application shell

Desktop uses a left navigation rail and a compact top context bar. Mobile collapses
navigation and stacks panels without removing evidence.

```text
+--------------------------------------------------------------------------+
| GOLD INTELLIGENCE | XAUUSD | As of [timestamp] | Data: DEGRADED | User  |
+-------------------+------------------------------------------------------+
| Overview          |                                                      |
| Macro             |                 active page                          |
| Events            |                                                      |
| Positioning       |                                                      |
| Sessions          |                                                      |
| Cross-Market      |                                                      |
| Backtest Lab      |                                                      |
| Data Health       |                                                      |
+-------------------+------------------------------------------------------+
```

Shared behaviours:

- `as_of` is always visible; historical mode has a prominent banner.
- Synthetic/demo data has a persistent badge and cannot be mistaken for live data.
- Every score/claim opens an evidence drawer containing status, value, source,
  observation period, availability, freshness, quality, rule version, supporting
  facts, contradictions, and calculation formula.
- `UNKNOWN`, stale, delayed, partial, and inferred are visually distinct from
  neutral. Meaning is conveyed with text/icons as well as color.
- All chart timestamps can switch display zone without changing stored/query times.
- The browser never recalculates a score; it renders API components.

## 2. Executive Overview — `/overview`

```text
+------------------+------------------+------------------+------------------+
| Intelligence +63 | Confidence 74%   | Regime           | Session          |
| Mod. bullish     | Execution 39%    | Slowdown/disinfl | LDN-NY overlap   |
+------------------+------------------+------------------+------------------+
| Dominant driver: falling real yield | Next: CPI in 4h | State: WAIT       |
+-------------------------------------+------------------+-------------------+
| Bull/bear/conflict contribution waterfall                               |
+------------------------------------------+-------------------------------+
| What changed?                            | Main contradiction            |
| causal chain with evidence badges        | ETF holdings falling          |
+------------------------------------------+-------------------------------+
| What confirms the view?                  | What invalidates the view?     |
| checklist and live status                | checklist and live status      |
+------------------------------------------+-------------------------------+
| Seven-layer strip: status, contribution, freshness, open evidence        |
+--------------------------------------------------------------------------+
| Risk warnings / highest-risk assumption / data-health warnings           |
+--------------------------------------------------------------------------+
```

The headline bias and execution state use separate cards. `WAIT` can coexist with a
strong bullish bias without appearing contradictory. “What changed?” compares the
current snapshot with a selectable earlier snapshot and attributes deltas to score
components, config changes, newly available facts, and expired/stale evidence.

## 3. Macro Regime — `/macro`

```text
+----------------------+----------------------+-----------------------------+
| Regime and confidence| Reaction profile     | History / transition dates  |
+----------------------+----------------------+-----------------------------+
| Inflation: headline/core CPI and PCE; level, direction, speed            |
+--------------------------------------------------------------------------+
| Growth and labour: payrolls, unemployment, claims, GDP, retail, wages     |
+--------------------------------------------------------------------------+
| Fed path and rates: target/effective, 2Y, 10Y, real, breakeven, curve     |
+--------------------------------------------------------------------------+
| USD and risk context | regime evidence table | contradictions/unknowns    |
+--------------------------------------------------------------------------+
```

Charts show observation date and availability/revision markers. A toggle can show
“latest revised history” versus “what was known as of” so users see why a historical
regime may differ from today's revised chart.

## 4. Expectations and Events — `/events`

```text
+--------------------------------------------------------------------------+
| Calendar: time | event | importance | forecast | previous | status/risk   |
+--------------------------------------------------------------------------+
| Selected event: snapshots of consensus and expected Fed path             |
+--------------------------------------+-----------------------------------+
| Actual / forecast / previous/revision| Raw + standardized surprise       |
+--------------------------------------+-----------------------------------+
| Gold reaction: -pre to +4h, markers at 1m/5m/15m/1h/4h/close             |
+--------------------------------------+-----------------------------------+
| Cross-market reaction                | First move: held/reversed/unknown |
+--------------------------------------+-----------------------------------+
| MFE / MAE / event-impact components  | Similar historical events        |
+--------------------------------------+-----------------------------------+
```

Pre-release events do not display an empty “actual” as zero. When forecast data is
missing, surprise and impact are explicitly unknown. Revised values never replace
the initial-release column.

## 5. Positioning — `/positioning`

```text
+--------------------------------------------------------------------------+
| COT publication age | Observation Tue | Published timestamp | Freshness  |
+--------------------------------------------------------------------------+
| Managed-money long / short / net / point-in-time percentile              |
+--------------------------------------------------------------------------+
| Price vs open interest and volume | probable flow inference + confidence |
+-----------------------------------+--------------------------------------+
| Producer/commercial hedging       | ETF holdings and flows               |
+-----------------------------------+--------------------------------------+
| Fast-money vs slow-money divergence| Central-bank structural context    |
+-----------------------------------+--------------------------------------+
| Options/expiry/IV/gamma availability and licensing status                |
+--------------------------------------------------------------------------+
```

Inference cards always display “probable” and list the observed price/OI facts.
Commercial shorts are labelled as possible hedges. A historical percentile uses
only reports published by the selected `as_of` date.

## 6. Sessions and Structure — `/structure` (implemented)

```text
+--------------------------------------------------------------------------+
| Candles + volume/spread (if valid)                                       |
| Asia/London/New York shading | LBMA markers | rollover marker             |
| swings | support/resistance zones | BOS/MSS | acceptance/rejection        |
+--------------------------------------------------------------------------+
| Session cards: high/low/range/volatility/spread/completeness              |
+--------------------------------------+-----------------------------------+
| Structure event timeline             | Selected detection evidence       |
+--------------------------------------+-----------------------------------+
| Higher-timeframe state               | Confirmation/invalidation status  |
+--------------------------------------+-----------------------------------+
```

The detection panel shows pivot time separately from detection time, preventing a
future-confirmed swing from looking known on the pivot bar. Users can inspect method,
thresholds, confidence, evidence bars, and invalidation for every marker.

The implemented page renders real IC Markets bars when present and otherwise uses
an isolated synthetic dataset. It includes a server-rendered five-minute candlestick
map, DST-adjusted session shading and range cards, six timeframe state cards, and a
recent evidence ledger. Daily bars use the response's named provider session
template; incomplete source intervals are never filled.

The page also exposes the `broker-liquidity-1` execution gate: the latest 15-minute
median spread, spread and one-minute-range percentiles, broker tick-activity
percentile, matched-session baseline size, data quality, and the resulting
execution-confidence multiplier. The Executive Overview blocks execution on
`ELEVATED`, `ABNORMAL`, or `UNKNOWN` liquidity while leaving the macro direction
unchanged.

## 7. Cross-Market — `/cross-market`

```text
+--------------------------------------------------------------------------+
| Synchronized cursor and selectable normalization/change horizon          |
+--------------------------------------------------------------------------+
| Gold              | 2Y yield           | 10Y real yield                  |
+-------------------+--------------------+---------------------------------+
| 10Y nominal/breakeven decomposition   | USD proxy                        |
+---------------------------------------+----------------------------------+
| Equity proxy      | volatility         | silver / Fed path               |
+-------------------+--------------------+---------------------------------+
| Confirmation matrix | divergences | alternative-driver explanations      |
+--------------------------------------------------------------------------+
```

Different source frequencies are never drawn as if synchronized ticks. Step lines,
last-known markers, source latency, and quality badges expose granularity. The view
can say that intraday confirmation is unavailable even when a daily series exists.

The implemented page provides three point-in-time synchronized panels: indexed
gold/USD/equities, raw nominal/real/breakeven yields, and VIX. It also shows the
current Layer 6 contributions, macro-versus-5m confirmation state, and the complete
Layer 6 factor ledger. Silver, safe-haven divergence, and missing licensed inputs
remain visible as `UNKNOWN`.

## 8. Backtest Lab — `/backtests`

```text
+----------------------------+---------------------------------------------+
| Experiment builder         | Validation / plain-language compiled rules  |
| dates and split plan       |                                             |
| signals and thresholds     |                                             |
| entry / invalidation / exit|                                             |
| costs, slippage, latency   |                                             |
| risk and benchmark         | [Run] [Save new version]                    |
+----------------------------+---------------------------------------------+
| Job progress / exclusions / warnings / reproducibility hash             |
+--------------------------------------------------------------------------+
| Equity + drawdown | headline metrics | gross-to-net cost bridge          |
+--------------------------------------------------------------------------+
| Regime/session/year slices | trades | MFE/MAE | confidence intervals      |
+--------------------------------------------------------------------------+
| Parameter stability surface | walk-forward folds | Monte Carlo           |
+--------------------------------------------------------------------------+
| Compare run versions | export results + manifest                         |
+--------------------------------------------------------------------------+
```

Event study is a separate tab with event filters, surprise bins, horizons, and
stratification. Every result foregrounds sample size, excluded observations,
synthetic status, costs, and in/out-of-sample status.

## 9. Data Health and Admin — `/data-health`

```text
+--------------------------------------------------------------------------+
| Overall health | stale/missing/quarantined | failed/running jobs          |
+--------------------------------------------------------------------------+
| Provider | last success | latency | quota/auth/schema | license mode      |
+--------------------------------------------------------------------------+
| Series | last observation | available | ingested | stale at | fitness     |
+--------------------------------------------------------------------------+
| Quality issues and anomalies | owner/status/resolution audit             |
+--------------------------------------------------------------------------+
| Calculation errors | config versions | migration/build version           |
+--------------------------------------------------------------------------+
```

Resolution does not delete an issue. Admin actions create audit events and require a
reason. Provider failure makes dependent intelligence partial/unknown automatically.

## 10. Empty, loading, error, and degraded states

- Skeletons reserve layout but never show placeholder scores that look real.
- Empty state identifies the exact dataset and upload/source action required.
- Partial data renders valid panels while listing unavailable conclusions.
- Stale values retain their last observation with age and decayed influence.
- API errors show a request ID and retry action; invalid data is not silently hidden.
- Long research jobs survive page navigation and can be resumed from their job/run
  resource.

## 11. Accessibility and frontend tests

- Keyboard-accessible chart controls and evidence drawers.
- Text alternatives/tables for charted values and non-color status encoding.
- Focus management for dialogs and async completion.
- Unit tests for formatting, status semantics, and query-state handling.
- Component tests for unknown/stale/inferred/synthetic states.
- End-to-end tests for upload -> calculation -> evidence drawer and backtest run.
- Contract tests fail when generated API types drift.
