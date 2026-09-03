# Gold March-April-May 2022 H1 Confirmation-Only Reclaim Application V1

## Authorization and evidence status

- Apply the sealed January confirmation-only V2 policy once and unchanged to each complete calendar month: March, April and May 2022.
- Preserve the January and February source populations, controls, results, charts, verdicts and seals.
- March, April and May were exposed during earlier project work. Treat every result as exposed historical regression evidence, not untouched or prospective validation.
- Evaluate and report each month separately. Do not pool months for selection, ranking or a combined headline.

## Frozen population and execution

- Use only the sealed pre-2025 casebook `price_bars.jsonl.gz`, sourced from IC Markets MT5 XAUUSD, with its existing lineage and hash.
- Use the unchanged confirmed H1 swing detector: two completed bars on each side and minimum prominence `max(0.25 ATR(14), 0.02)`.
- For each month, include every local H1 pivot whose pivot timestamp is inside that calendar month, whose confirmation is available before the next month, and which has a causally known preceding opposite H1 swing and valid geometry.
- The original control enters at the first eligible M1 open following H1 confirmation, places its stop at the source H1 swing, targets the latest causally known preceding opposite H1 swing and uses stop-first treatment on ambiguous M1 bars. Unresolved paths exit at that calendar month's last observed M1 close.
- Do not select by date, session, direction, target room, outcome, volatility or overlap.

## Frozen V2 policy binding

- Bind without change to `GOLD_JANUARY_H1_CONFIRMATION_ONLY_RECLAIM_MILESTONE_V2.md` and the February-certified implementation semantics.
- Open no blanket probe.
- Use the same opposing-M5-pivot confirmation, full `1R` entry, pre-entry H1 sweep review, completed-H1-close invalidation, reclaim confirmation, `0.02` excursion buffer, one-position-per-setup risk cap and calendar-month exit.
- Do not add, remove, invert, retune or reinterpret any state, threshold, stop, target, risk fraction or timing rule between months.

## Point-in-time and source rules

- A bar is usable only when `available_at <= decision timestamp`; all confirmation decisions use completed bars.
- Retain the IC Markets observed-quote path without filling weekends, recurring daily closed intervals or no-tick minutes.
- Before calculating any March-May outcome, verify every predecessor seal and require the generalized runner to reproduce both the sealed January V2 ledger and the sealed February application ledger exactly.
- Parse the casebook independently with the existing primary JSON parser and independent reference field parser. Require exact equality for each monthly population, ledger, metric and chart payload.

## Separate outputs and visual certification

- For each month create its own result JSON, complete CSV ledger, Markdown report, chart payload, HTML visualization, screenshots, browser certificate and manifest.
- Each report must show population construction, control metrics, V2 trades/no-trades, route counts, win rate, net R, profit factor, expectancy, maximum drawdown and dollar illustrations at `$50/R` and `$100/R`.
- Each visualization must retain the February-certified white continuous H1/M15/M5 interface, moderate default candle spacing, pan, zoom, full-month reset, selectable trade rows and locally bounded entry/stop/target lines.
- Browser certification must test each month independently. A failure in one month must be reported for that month and must not be concealed by another month's result.
