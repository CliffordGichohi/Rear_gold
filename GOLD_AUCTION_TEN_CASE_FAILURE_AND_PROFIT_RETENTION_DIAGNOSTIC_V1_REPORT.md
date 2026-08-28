# Gold Auction Ten-Case Failure and Profit-Retention Diagnostic V1 Report

Status: `PASS_EXPOSED_DIAGNOSTIC_REPRODUCTION_ZERO_VALIDATION_CREDIT`

This is a ten-case exposed descriptive diagnostic, not edge validation.

## Case-level attribution

| Date | Side | Family | Category | Baseline R | MFE R | MAE R | Overlay | Effective R |
|---|---|---|---|---:|---:|---:|---|---:|
| 2022-01-10 | LONG | RANGE_ROTATION_WITH_LTF_CONTROL | NO_MEANINGFUL_FAVOURABLE_AUCTION | -0.96 | 0.48 | 1.07 | UNCHANGED | -0.96 |
| 2022-01-03 | LONG | TREND_PULLBACK_WITH_LTF_CONTROL | NO_MEANINGFUL_FAVOURABLE_AUCTION | -1.17 | 0.07 | 1.31 | UNCHANGED | -1.17 |
| 2022-01-12 | LONG | TREND_PULLBACK_WITH_LTF_CONTROL | MONETIZED_SUCCESS | +1.59 | 1.66 | 0.64 | UNCHANGED | +1.59 |
| 2022-01-31 | LONG | TRANSITIONAL_CONTEXT_WITH_LTF_CONTROL | MONETIZED_SUCCESS | +2.53 | 2.71 | 0.85 | TARGET_PRECEDED_OVERLAY | +2.53 |
| 2022-02-02 | LONG | TRANSITIONAL_CONTEXT_WITH_LTF_CONTROL | NO_MEANINGFUL_FAVOURABLE_AUCTION | -0.81 | 0.02 | 0.81 | UNCHANGED | -0.81 |
| 2022-05-30 | SHORT | RANGE_ROTATION_WITH_LTF_CONTROL | MONETIZED_SUCCESS | +0.58 | 0.89 | 0.24 | UNCHANGED | +0.58 |
| 2022-01-17 | SHORT | TREND_PULLBACK_WITH_LTF_CONTROL | NO_MEANINGFUL_FAVOURABLE_AUCTION | -0.86 | 0.40 | 0.85 | UNCHANGED | -0.86 |
| 2022-01-21 | SHORT | TREND_PULLBACK_WITH_LTF_CONTROL | DIRECTIONALLY_USEFUL_UNMONETIZED | -0.89 | 1.48 | 0.91 | M5_1R_NET_BREAK_EVEN | +0.00 |
| 2022-01-11 | SHORT | TRANSITIONAL_CONTEXT_WITH_LTF_CONTROL | DIRECTIONALLY_USEFUL_UNMONETIZED | -0.05 | 1.17 | 0.42 | M5_1R_NET_BREAK_EVEN | +0.00 |
| 2022-01-14 | SHORT | TRANSITIONAL_CONTEXT_WITH_LTF_CONTROL | MONETIZED_SUCCESS | +2.46 | 2.57 | 0.74 | M5_1R_NET_BREAK_EVEN | +0.00 |

## Aggregate execution

- Baseline: **+2.4296R50**, PF 1.51, maximum drawdown 2.17R50.
- Universal M5 +1R break-even overlay: **+0.9052R50**, PF 1.24, maximum drawdown 2.12R50.
- Increment: **-1.5244R50**; activated 4, changed 3, saved losses 2, clipped winners 1.

## Pre-entry descriptive contrasts

No contrast below is a filter or candidate rule.

| Field | Useful N | Useful mean | Useful median | Failed N | Failed mean | Failed median |
|---|---:|---:|---:|---:|---:|---:|
| planned_r | 6 | 2.73 | 2.56 | 4 | 3.24 | 2.59 |
| macro_alignment_score | 6 | 0.26 | -6.63 | 4 | -7.32 | -10.41 |
| macro_confidence | 6 | 50.52 | 54.35 | 4 | 44.24 | 40.60 |
| h1_range_location | 6 | 0.75 | 0.59 | 4 | 0.91 | 0.90 |
| h4_range_location | 6 | 0.37 | 0.49 | 4 | 0.67 | 0.59 |
| distance_from_m5_break_atr | 6 | 0.33 | 0.30 | 4 | 0.44 | 0.55 |
| risk_in_break_atr | 6 | 2.70 | 2.79 | 4 | 2.33 | 2.56 |
| local_m15_liquidity_room_r | 6 | 1.42 | 1.37 | 4 | 1.16 | 0.85 |

Categorical distributions are preserved in the sealed JSON result. With n=10, no statistical inference, classifier, veto, or edge claim is permitted.
