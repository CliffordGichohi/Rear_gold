# Gold February 2022 H1 Confirmation-Only Reclaim Application V1

## Authorization and evidence status

- Apply the sealed January confirmation-only V2 policy once and unchanged to calendar February 2022: `[2022-02-01T00:00:00Z, 2022-03-01T00:00:00Z)`.
- Preserve all January controls, V1 and V2 artifacts and verdicts.
- February 1 through 16 was exposed in earlier project work. February 17 through 28 was previously unopened and is authorized for opening by this application. Report the full calendar month and the two exposure segments separately.
- This is historical robustness evidence, not independent prospective validation.

## Frozen population construction

- Use the sealed pre-2025 casebook `price_bars.jsonl.gz`, sourced from IC Markets MT5 XAUUSD, with its existing manifest hash and record lineage.
- Use the unchanged confirmed-swing detector: two completed bars on each side, minimum prominence `max(0.25 ATR(14), 0.02)`.
- Include every H1 pivot whose pivot timestamp is in February, whose confirmation is available before March 1, which has a causally known preceding opposite H1 swing and valid entry/stop/target geometry.
- Original control enters at the first eligible M1 open after H1 confirmation, stops at the source H1 swing and targets the latest causally known preceding opposite H1 swing. Resolve stop first on an ambiguous M1 bar; otherwise target, stop or month-end time exit.
- No date, session, direction, target-room or overlap selection is permitted.

## Frozen V2 policy binding

- Bind without change to `GOLD_JANUARY_H1_CONFIRMATION_ONLY_RECLAIM_MILESTONE_V2.md` and its sealed implementation semantics.
- Open no blanket probe.
- Use the same opposing-M5-pivot confirmation, full `1R` entry, pre-entry H1 sweep review, H1-close invalidation, reclaim confirmation, `0.02` excursion buffer, one-position risk cap and month-end exit.
- Do not add, remove, retune or reinterpret any state, threshold, stop, target, risk fraction or timing rule.

## Required certification and reporting

- The IC Markets source emits no synthetic bars during its recurring daily closed interval. For this month, timestamp-only certification found the first observed February M1 bar at `2022-02-01T01:02:00Z` and the final observed M1 bar at `2022-02-28T23:58:00Z`; the same `01:02` reopening recurs on every February trading date. Treat this documented observed-quote boundary as valid coverage and never impute the closed interval.
- Before February evaluation, prove the casebook reader reproduces the sealed January V2 routes, fills and R exactly.
- Parse the casebook independently using the existing primary JSON and reference field parser and require exact equality.
- Report population construction, trades, no-trades, route counts, win rate, net R, PF, expectancy, maximum drawdown and `$50/R` and `$100/R` illustrations.
- Report February 1-16 and February 17-28 separately without changing the policy between them.
- Render all executed February trades on one continuous white chart with H1, M15 and M5 views; entry, stop and target lines must be local to each trade interval.
- Seal the result, complete ledger, chart data, HTML and browser-regression evidence.
