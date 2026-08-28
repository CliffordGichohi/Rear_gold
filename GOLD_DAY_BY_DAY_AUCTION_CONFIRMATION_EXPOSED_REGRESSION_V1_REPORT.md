# Gold Day-by-Day Auction-Confirmation Exposed Regression V1 — Result

Verdict: `COMPLETE_EXPOSED_DAY_BY_DAY_REGRESSION_ZERO_VALIDATION_CREDIT`

This is an exposed regression with zero validation credit. The random 50-case population and 2022-02-17 through 2022-02-28 were not opened.

| Period | Days | Control trades | Control R | Corrected trades | Corrected R | Win % | Exp R | PF | Max DD R |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| JANUARY | 18 | 6 | +3.3123 | 2 | -0.9919 | 0.00 | -0.4959 | 0.0 | 0.9919 |
| FEBRUARY_TO_DATE | 12 | 5 | +7.3813 | 5 | +4.5143 | 80.00 | +0.9029 | 10.385151474234316 | 0.4810 |
| MARCH | 23 | 12 | -0.1521 | 9 | +3.2284 | 44.44 | +0.3587 | 2.656857763143211 | 0.9920 |
| APRIL | 20 | 6 | +2.7496 | 6 | +2.1297 | 66.67 | +0.3550 | 3.315231920321839 | 0.9199 |
| MAY | 22 | 9 | -3.5396 | 7 | -3.6847 | 28.57 | -0.5264 | 0.2306410370425658 | 3.6847 |
| COMBINED | 95 | 38 | +9.7514 | 29 | +5.1959 | 48.28 | +0.1792 | 1.5690665251984288 | 3.6847 |

## Fixed-order value attribution

- Unchanged control: +9.7514R
- After original-fill 1.5R room screen: +11.5092R (+1.7578R incremental)
- After frozen M5 confirmation and delayed entry: +4.0060R (-7.5033R incremental)
- After M5-close +1R break-even: +5.1959R (+1.1899R incremental)

The attribution is descriptive and order-dependent; it is not a second strategy search.

## Daily ledger

The complete 95-day ledger is sealed in `research_artifacts/gold_day_by_day_auction_confirmation_exposed_regression_v1/daily_ledger.csv`.
