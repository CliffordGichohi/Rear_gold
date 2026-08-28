# Gold Auction-Semantic Family Router Exposed Regression V2 - Result

Verdict: `COMPLETE_EXPOSED_AUCTION_SEMANTIC_ROUTER_V2_ZERO_VALIDATION_CREDIT`

This is an exposed matched-data regression with zero validation credit. Every predecessor remains byte-for-byte restorable.

| Period | Days | Control R | Rigid R | Router V1 R | V2 trades | V2 R | Win % | Exp R | PF | DD R |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| JANUARY | 18 | +3.3123 | -0.9919 | +2.3686 | 0 | +0.0000 | 0.00 | +0.0000 | None | 0.0000 |
| FEBRUARY_TO_DATE | 12 | +7.3813 | +4.5143 | +4.7773 | 0 | +0.0000 | 0.00 | +0.0000 | None | 0.0000 |
| MARCH | 23 | -0.1521 | +3.2284 | +3.5321 | 1 | -0.1019 | 0.00 | -0.1019 | 0.0 | 0.1019 |
| APRIL | 20 | +2.7496 | +2.1297 | +1.8220 | 0 | +0.0000 | 0.00 | +0.0000 | None | 0.0000 |
| MAY | 22 | -3.5396 | -3.6847 | -3.7159 | 1 | -0.9675 | 0.00 | -0.9675 | 0.0 | 0.9675 |
| COMBINED | 95 | +9.7514 | +5.1959 | +8.7841 | 2 | -1.0695 | 0.00 | -0.5347 | 0.0 | 1.0695 |

## Compiled-family contributions

| Family | Rows | Trades | Net R | PF |
|---|---:|---:|---:|---:|
| CONTINUATION_WITH_ROOM | 22 | 1 | -0.1019 | 0.0 |
| RANGE_ROTATION | 4 | 1 | -0.9675 | 0.0 |
| STRUCTURAL_REPAIR | 11 | 0 | +0.0000 | None |

## Matched verdict

- Control: +9.7514R.
- Rigid confirmation: +5.1959R.
- Router V1: +8.7841R.
- Auction-semantic Router V2: -1.0695R.
- V2 minus V1: -9.8535R.
- Valid control winners rejected by V2: 17 (+21.3617 control R).
- Losing V2 trades later reaching +1R / destination: 2 / 1.

The complete ledger is sealed in `research_artifacts/gold_auction_semantic_family_router_exposed_regression_v2/daily_ledger.csv`.
