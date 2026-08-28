# Gold Auction Family Router Exposed Regression V1 - Result

Verdict: `COMPLETE_EXPOSED_FAMILY_ROUTER_REGRESSION_ZERO_VALIDATION_CREDIT`

This is an exposed matched-data regression with zero validation credit. The immutable rollback baseline remains byte-for-byte restorable.

| Period | Days | Control R | Rigid R | Router trades | Router R | Win % | Exp R | PF | Max DD R |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| JANUARY | 18 | +3.3123 | -0.9919 | 5 | +2.3686 | 40.00 | +0.4737 | 3.4599426374090534 | 0.9629 |
| FEBRUARY_TO_DATE | 12 | +7.3813 | +4.5143 | 4 | +4.7773 | 75.00 | +1.1943 | None | 0.0000 |
| MARCH | 23 | -0.1521 | +3.2284 | 7 | +3.5321 | 42.86 | +0.5046 | 4.591496308095738 | 0.9835 |
| APRIL | 20 | +2.7496 | +2.1297 | 5 | +1.8220 | 40.00 | +0.3644 | 5.559559559559772 | 0.3996 |
| MAY | 22 | -3.5396 | -3.6847 | 8 | -3.7159 | 25.00 | -0.4645 | 0.23724662243440534 | 4.3765 |
| COMBINED | 95 | +9.7514 | +5.1959 | 29 | +8.7841 | 41.38 | +0.3029 | 2.217023422019627 | 4.3765 |

## Family contributions

| Family | Signal days | Trades | Net R | PF |
|---|---:|---:|---:|---:|
| CONTINUATION_WITH_ROOM | 40 | 25 | +7.8481 | 2.5050889702993135 |
| RANGE_ROTATION | 5 | 3 | -1.5081 | 0.24719634974514104 |
| STRUCTURAL_REPAIR | 15 | 1 | +2.4440 | None |

## Matched comparison

- Control: +9.7514R.
- Rejected rigid two-stage confirmation: +5.1959R.
- Family router: +8.7841R.
- Router minus rigid: +3.5882R.
- Valid control winners rejected by router: 4 (+2.3067 control R).
- Control winners lost by rigid but recovered by router: 3.

The complete 95-day ledger is sealed in `research_artifacts/gold_auction_family_router_exposed_regression_v1/daily_ledger.csv`.
