# Gold Continuation True-Negation Matched-Case Attribution V1 Report

Verdict: `COMPLETE_MATCHED_CASE_ATTRIBUTION_EXPOSED_ZERO_VALIDATION_CREDIT`

This is a descriptive audit of the same 434 exposed continuation identities. It changes no trade and retains every overlapping setup.

## Net result and negation change

| Track | Trades | Win rate | Net R | PF |
|---|---:|---:|---:|---:|
| Original | 434 | 46.31% | -71.7264 | 0.57 |
| Fixed-quantity negation | 434 | 52.07% | +53.1780 | 1.52 |
| Change from negation | 434 |  | +124.9043 |  |

## Matched outcome transitions

| Transition | Cases |
|---|---:|
| ORIGINAL_LOSS__NEGATED_LOSS | 7 |
| ORIGINAL_LOSS__NEGATED_WIN | 226 |
| ORIGINAL_WIN__NEGATED_LOSS | 201 |

## Matched execution-resolution transitions

| Transition | Cases |
|---|---:|
| ORIGINAL_STOPPED__NEGATED_TARGET_HIT | 155 |
| ORIGINAL_TARGET_HIT__NEGATED_STOPPED | 152 |
| ORIGINAL_TIME_EXIT__NEGATED_TIME_EXIT | 110 |
| ORIGINAL_POST_FILL_GEOMETRY_INVALID__NEGATED_POST_FILL_GEOMETRY_INVALID | 14 |
| ORIGINAL_POST_FILL_GEOMETRY_INVALID__NEGATED_STOPPED | 3 |

## Stop attribution

| Track | Stops | Then target | Then entry reclaim | Confirmed to deadline | Pre-stop MFE R | Recovery opportunity R | Ambiguous |
|---|---:|---:|---:|---:|---:|---:|---:|
| Original | 155 | 25 | 39 | 91 | 63.6805 | 49.9827 | 0 |
| Negated | 155 | 51 | 64 | 40 | 39.8270 | 79.9742 | 0 |

## Profit and exit attribution

| Track | Targets | Deadline better | Deadline worse | Deadline delta R | Post-target extension R | Time exits | Time-exit uncaptured MFE R |
|---|---:|---:|---:|---:|---:|---:|---:|
| Original | 152 | 60 | 92 | -35.1062 | 141.8678 | 110 | 23.0467 |
| Negated | 155 | 66 | 89 | -31.5781 | 195.6602 | 110 | 27.6029 |

## Execution and available movement

| Track | Cost drag R | Market entry degradation R | Total entry degradation R | Available MFE R | MFE not captured R | Structural/execution disagreements |
|---|---:|---:|---:|---:|---:|---:|
| Original | 9.6358 | -8.2064 | -2.2550 | 420.5562 | 325.0897 | 19 |
| Negated | 8.9699 | +8.2064 | +14.1578 | 535.2526 | 378.9225 | 16 |

`Available MFE` and recovery figures are hindsight attribution ceilings, not executable strategy returns.

## Point-in-time descriptive group tables

### original_direction

| State | N | Original win | Original R | Negated win | Negated R | Delta R |
|---|---:|---:|---:|---:|---:|---:|
| LONG | 228 | 40.79% | -52.9741 | 57.89% | +42.6819 | +95.6560 |
| SHORT | 206 | 52.43% | -18.7523 | 45.63% | +10.4961 | +29.2483 |

### month

| State | N | Original win | Original R | Negated win | Negated R | Delta R |
|---|---:|---:|---:|---:|---:|---:|
| 2022-01 | 78 | 53.85% | -7.9495 | 42.31% | +4.5783 | +12.5278 |
| 2022-02 | 47 | 34.04% | -14.7194 | 65.96% | +11.8269 | +26.5463 |
| 2022-03 | 82 | 47.56% | -15.7961 | 52.44% | +13.4834 | +29.2796 |
| 2022-04 | 71 | 35.21% | -18.6041 | 63.38% | +16.0928 | +34.6969 |
| 2022-05 | 66 | 43.94% | -7.5902 | 53.03% | +5.0691 | +12.6593 |
| 2022-06 | 90 | 55.56% | -7.0670 | 43.33% | +2.1275 | +9.1945 |

### context_family

| State | N | Original win | Original R | Negated win | Negated R | Delta R |
|---|---:|---:|---:|---:|---:|---:|
| RANGE_OPPOSITE_HALF_WITH_LTF_CONTROL | 27 | 70.37% | +5.4507 | 29.63% | -7.3385 | -12.7891 |
| RANGE_ROTATION_WITH_LTF_CONTROL | 2 | 0.00% | -1.8117 | 100.00% | +1.6545 | +3.4662 |
| TRANSITIONAL_CONTEXT_WITH_LTF_CONTROL | 217 | 44.70% | -44.4390 | 53.46% | +35.4291 | +79.8681 |
| TREND_PULLBACK_WITH_LTF_CONTROL | 188 | 45.21% | -30.9264 | 53.19% | +23.4328 | +54.3592 |

### macro_alignment

| State | N | Original win | Original R | Negated win | Negated R | Delta R |
|---|---:|---:|---:|---:|---:|---:|
| NEUTRAL_OR_UNKNOWN | 434 | 46.31% | -71.7264 | 52.07% | +53.1780 | +124.9043 |

### macro_state

| State | N | Original win | Original R | Negated win | Negated R | Delta R |
|---|---:|---:|---:|---:|---:|---:|
| ALIGNED | 46 | 43.48% | -14.8287 | 56.52% | +13.0232 | +27.8520 |
| NEUTRAL_OR_CONFLICTED | 301 | 50.17% | -28.8444 | 47.84% | +16.3777 | +45.2221 |
| OPPOSED | 87 | 34.48% | -28.0533 | 64.37% | +23.7770 | +51.8303 |

### h1_structure_state

| State | N | Original win | Original R | Negated win | Negated R | Delta R |
|---|---:|---:|---:|---:|---:|---:|
| DOWN_TREND | 133 | 56.39% | +1.5885 | 41.35% | -7.4337 | -9.0222 |
| MIXED_OR_RANGE | 200 | 49.00% | -36.4908 | 50.00% | +27.6946 | +64.1854 |
| UP_TREND | 101 | 27.72% | -36.8240 | 70.30% | +32.9171 | +69.7411 |

### h1_alignment

| State | N | Original win | Original R | Negated win | Negated R | Delta R |
|---|---:|---:|---:|---:|---:|---:|
| ALIGNED | 117 | 45.30% | -16.3437 | 52.99% | +11.6222 | +27.9658 |
| CONTRADICTED | 117 | 42.74% | -18.8918 | 54.70% | +13.8613 | +32.7531 |
| MIXED_OR_RANGE | 200 | 49.00% | -36.4908 | 50.00% | +27.6946 | +64.1854 |

### h4_structure_state

| State | N | Original win | Original R | Negated win | Negated R | Delta R |
|---|---:|---:|---:|---:|---:|---:|
| DOWN_TREND | 156 | 42.95% | -33.2854 | 55.77% | +26.6781 | +59.9634 |
| MIXED_OR_RANGE | 165 | 53.33% | -14.7436 | 44.85% | +7.9997 | +22.7433 |
| UP_TREND | 113 | 40.71% | -23.6974 | 57.52% | +18.5002 | +42.1976 |

### h4_alignment

| State | N | Original win | Original R | Negated win | Negated R | Delta R |
|---|---:|---:|---:|---:|---:|---:|
| ALIGNED | 114 | 50.88% | -7.2671 | 48.25% | +2.8147 | +10.0818 |
| CONTRADICTED | 155 | 35.48% | -49.7158 | 62.58% | +42.3636 | +92.0793 |
| MIXED_OR_RANGE | 165 | 53.33% | -14.7436 | 44.85% | +7.9997 | +22.7433 |

### target_timeframe

| State | N | Original win | Original R | Negated win | Negated R | Delta R |
|---|---:|---:|---:|---:|---:|---:|
| H1 | 392 | 45.66% | -72.4938 | 53.06% | +55.3132 | +127.8070 |
| H4 | 42 | 52.38% | +0.7674 | 42.86% | -2.1352 | -2.9027 |

### local_m15_matches_htf_target_level

| State | N | Original win | Original R | Negated win | Negated R | Delta R |
|---|---:|---:|---:|---:|---:|---:|
| DIFFERENT_OR_MISSING | 260 | 40.00% | -71.5808 | 57.69% | +61.8981 | +133.4789 |
| MATCH | 174 | 55.75% | -0.1456 | 43.68% | -8.7202 | -8.5746 |

### former_quality_state

| State | N | Original win | Original R | Negated win | Negated R | Delta R |
|---|---:|---:|---:|---:|---:|---:|
| CHASE_AND_ROOM | 189 | 56.61% | -10.1221 | 41.80% | +4.2075 | +14.3295 |
| CHASE_ONLY | 79 | 21.52% | -31.2979 | 78.48% | +27.6266 | +58.9246 |
| NONE | 56 | 19.64% | -26.5405 | 76.79% | +22.7074 | +49.2479 |
| ROOM_ONLY | 110 | 60.00% | -3.7659 | 38.18% | -1.3635 | +2.4024 |

### planned_r_bin

| State | N | Original win | Original R | Negated win | Negated R | Delta R |
|---|---:|---:|---:|---:|---:|---:|
| 0.5-1.0 | 106 | 58.49% | +4.8655 | 40.57% | -9.3008 | -14.1663 |
| 1.0-1.5 | 52 | 34.62% | -10.5425 | 63.46% | +8.4178 | +18.9603 |
| 1.5-2.0 | 36 | 25.00% | -10.0650 | 75.00% | +8.2948 | +18.3598 |
| <0.5 | 141 | 65.96% | -8.2109 | 31.91% | +3.7270 | +11.9379 |
| >=2.0 | 99 | 19.19% | -47.7735 | 78.79% | +42.0392 | +89.8126 |

### break_distance_bin

| State | N | Original win | Original R | Negated win | Negated R | Delta R |
|---|---:|---:|---:|---:|---:|---:|
| 1-2 | 100 | 46.00% | -10.8031 | 54.00% | +6.6126 | +17.4157 |
| 2-4 | 107 | 45.79% | -21.2402 | 51.40% | +17.8829 | +39.1230 |
| <1 | 166 | 46.39% | -30.3064 | 51.20% | +21.3439 | +51.6502 |
| >=4 | 61 | 47.54% | -9.3767 | 52.46% | +7.3386 | +16.7154 |

### decision_phase

| State | N | Original win | Original R | Negated win | Negated R | Delta R |
|---|---:|---:|---:|---:|---:|---:|
| 08:00-09:30 | 119 | 41.18% | -26.6654 | 58.82% | +20.7925 | +47.4579 |
| 09:30-10:30 | 110 | 50.91% | -13.4026 | 49.09% | +7.5486 | +20.9512 |
| 10:30-11:30 | 133 | 47.37% | -23.3805 | 52.63% | +18.5903 | +41.9709 |
| 11:30-12:00 | 72 | 45.83% | -8.2778 | 44.44% | +6.2465 | +14.5244 |

### time_remaining_bin

| State | N | Original win | Original R | Negated win | Negated R | Delta R |
|---|---:|---:|---:|---:|---:|---:|
| 30-60m | 63 | 47.62% | -10.7522 | 52.38% | +8.7711 | +19.5234 |
| 60-120m | 125 | 52.80% | -15.6042 | 47.20% | +10.1883 | +25.7924 |
| <30m | 60 | 43.33% | -6.7533 | 45.00% | +4.9112 | +11.6646 |
| >=120m | 186 | 42.47% | -38.6166 | 57.53% | +29.3073 | +67.9240 |

### pivot_age_bin

| State | N | Original win | Original R | Negated win | Negated R | Delta R |
|---|---:|---:|---:|---:|---:|---:|
| 15-30m | 141 | 43.26% | -28.2622 | 53.90% | +21.3249 | +49.5870 |
| 30-60m | 144 | 53.47% | -4.9587 | 45.14% | +0.0052 | +4.9639 |
| <15m | 95 | 34.74% | -32.7225 | 64.21% | +27.2931 | +60.0156 |
| >=60m | 54 | 55.56% | -5.7830 | 44.44% | +4.5548 | +10.3378 |

### target_age_bin

| State | N | Original win | Original R | Negated win | Negated R | Delta R |
|---|---:|---:|---:|---:|---:|---:|
| 1-4h | 43 | 76.74% | +8.8599 | 20.93% | -10.7231 | -19.5831 |
| 4-24h | 175 | 33.71% | -63.0213 | 63.43% | +53.7483 | +116.7697 |
| <1h | 26 | 65.38% | +1.5286 | 34.62% | -2.9061 | -4.4347 |
| >=24h | 190 | 48.42% | -19.0936 | 51.05% | +13.0589 | +32.1525 |

### continuation_ordinal_label

| State | N | Original win | Original R | Negated win | Negated R | Delta R |
|---|---:|---:|---:|---:|---:|---:|
| FIRST_IN_RUN | 130 | 45.38% | -18.4898 | 51.54% | +12.7249 | +31.2147 |
| FOURTH_PLUS_IN_RUN | 134 | 46.27% | -26.0269 | 53.73% | +20.3599 | +46.3868 |
| SECOND_IN_RUN | 99 | 48.48% | -9.0421 | 49.49% | +4.4592 | +13.5013 |
| THIRD_IN_RUN | 71 | 45.07% | -18.1676 | 53.52% | +15.6340 | +33.8015 |

## Integrity

- All 434 original and negated identities and original quantities matched their predecessor seals.
- Primary and reference case rows, matrices, aggregates and checksums matched exactly.
- All overlapping setups remained in the audit; no one-trade or wait-for-resolution rule was applied.
- No rule was changed, no setup removed, no new date opened, and 2025/2026 remained locked.
- This is exposed post-result attribution with zero validation credit.
