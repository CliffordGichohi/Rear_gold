# Gold Auction-Semantic Family Router V2-R1 — Result

Verdict: `PASS_V2_R1_SEMANTIC_INTEGRATION_REPLAY_ZERO_VALIDATION_CREDIT`

This is an exposed implementation-correction regression with zero validation credit. It does not reject or validate the strategy.

| Period | Control R | Router V1 R | Failed V2 R | V2-R1 trades | V2-R1 R | Win % | PF | DD R |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| JANUARY | +3.3123 | +2.3686 | +0.0000 | 3 | +2.4631 | 66.67 | 17.11082040739398 | 0.1529 |
| FEBRUARY_TO_DATE | +7.3813 | +4.7773 | +0.0000 | 2 | -0.5284 | 50.00 | 0.4279581333200911 | 0.9237 |
| MARCH | -0.1521 | +3.5321 | -0.1019 | 5 | -3.1205 | 0.00 | 0.0 | 3.1205 |
| APRIL | +2.7496 | +1.8220 | +0.0000 | 1 | +0.3204 | 100.00 | None | 0.0000 |
| MAY | -3.5396 | -3.7159 | -0.9675 | 4 | -2.6743 | 0.00 | 0.0 | 2.6743 |
| COMBINED | +9.7514 | +8.7841 | -1.0695 | 15 | -3.5398 | 26.67 | 0.4848608517273833 | 6.3982 |

## Disposition

- V2-R1 minus failed V2: -2.4703R.
- V2-R1 minus Router V1: -12.3238R.
- V2-R1 minus control: -13.2912R.
- Valid control winners rejected: 15 (+17.4501 control R).
- Avoided control losses: 6 (-3.9970 control R).
- The sealed failed V2 remains an implementation-failure record, not a strategy rejection.
- No fresh period was opened.

The complete ledger is sealed in `research_artifacts/gold_auction_semantic_family_router_exposed_regression_v2_r1/daily_ledger.csv`.
