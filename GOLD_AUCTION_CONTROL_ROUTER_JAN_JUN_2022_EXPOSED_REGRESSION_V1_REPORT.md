# Gold Auction-Control Router — January–June 2022 Exposed Regression V1 Report

Verdict: `COMPLETE_EXPOSED_ROUTER_REGRESSION_ZERO_VALIDATION_CREDIT`

All six months are exposed historical data and receive zero validation credit.

| Track | Trades | W/L/S | Win rate | Net R | Net USD | Exp R | PF | Max DD R | 1.5x-cost R |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| ORIGINAL_LONG_CONTROL | 37 | 16/17/4 | 43.24% | +5.7492 | +287.46 | +0.1554 | 1.420 | 8.3768 | +5.3116 |
| BUYER_CONTROL_VETO_LONG | 13 | 8/4/1 | 61.54% | +5.3149 | +265.75 | +0.4088 | 3.801 | 0.9162 | +5.2348 |
| SELLER_AUCTION_SHORT | 0 | 0/0/0 | 0.00% | +0.0000 | +0.00 | +0.0000 | N/A | 0.0000 | +0.0000 |
| BIDIRECTIONAL_ONE_PER_DAY | 13 | 8/4/1 | 61.54% | +5.3149 | +265.75 | +0.4088 | 3.801 | 0.9162 | +5.2348 |

## Monthly net R

| Month | Original LONG | Veto LONG | SHORT | Combined |
|---|---:|---:|---:|---:|
| 2022-01 | +2.3686 | -0.0000 | +0.0000 | -0.0000 |
| 2022-02 | +7.0023 | +2.2250 | +0.0000 | +2.2250 |
| 2022-03 | +1.5915 | +0.8444 | +0.0000 | +0.8444 |
| 2022-04 | +2.5030 | +1.9880 | +0.0000 | +1.9880 |
| 2022-05 | -2.6755 | +1.1558 | +0.0000 | +1.1558 |
| 2022-06 | -5.0407 | -0.8983 | +0.0000 | -0.8983 |

## Router audit

- LONG veto counts: `{"RETAINED_LOSS": 4, "RETAINED_SCRATCH": 1, "RETAINED_WIN": 8, "VETOED_LOSS": 13, "VETOED_SCRATCH": 3, "VETOED_WIN": 8}`
- LONG veto R: `{"RETAINED_LOSS": -1.8971923192819098, "RETAINED_SCRATCH": -2.1831425556229077e-14, "RETAINED_WIN": 7.212092627885692, "VETOED_LOSS": -11.806620018652827, "VETOED_SCRATCH": -1.0678125050844755e-13, "VETOED_WIN": 12.240920830121317}`
- Seller-control transitions: `{"LONDON": 129, "NEW_YORK": 117}`
- SHORT rejection reasons: `{"INVALID_SHORT_GEOMETRY": 1, "NEAREST_LIQUIDITY_ROOM_LT_1P5R": 55, "NO_BEARISH_RETEST_WITHIN_6_M5": 76, "NO_EXECUTABLE_M1_BEFORE_SESSION_END": 3, "NO_FAILED_BUYER_AUCTION": 110, "NO_KNOWN_DOWNSIDE_LIQUIDITY": 1}`

The original LONG results were not reconstructed or altered. The veto changed admission only. Every SHORT required the complete frozen seller-auction plan; a bearish break alone was insufficient.
