# Gold Coherent-Auction March--May 2022 Outcome Attribution V1 — Report

Verdict: `PASS_EXPOSED_OUTCOME_ATTRIBUTION_NO_RULE_CHANGE`

- Trades: `27`; wins/losses/scratches: `10` / `14` / `3`.
- Baseline: `-0.942133R`.
- Primary/reference attribution reproduced exactly.

## Primary attribution

| Attribution | Trades | Wins | Losses | Scratches | Net R |
|---|---:|---:|---:|---:|---:|
| CLEAN_TARGET_WIN | 1 | 1 | 0 | 0 | +0.7124 |
| CONTROLLED_SCRATCH | 3 | 0 | 0 | 3 | -0.0000 |
| FRAGILE_WIN | 1 | 1 | 0 | 0 | +0.6810 |
| NORMAL_THESIS_FAILURE | 6 | 0 | 6 | 0 | -5.4771 |
| PATH_SENSITIVE_STOP_REVERSAL | 2 | 0 | 2 | 0 | -1.9197 |
| POSITIVE_TIME_EXIT | 8 | 8 | 0 | 0 | +9.1853 |
| PROFIT_GIVEBACK_LOSS | 3 | 0 | 3 | 0 | -2.3402 |
| STOP_THEN_TARGET | 2 | 0 | 2 | 0 | -1.7298 |
| UNRESOLVED_NEGATIVE_TIME_EXIT | 1 | 0 | 1 | 0 | -0.0540 |

## Independent flags

- `profit_giveback`: `3`
- `stop_then_target`: `3`
- `path_sensitive_stop_reversal`: `2`
- `unresolved_negative_time_exit`: `2`
- `fragile_win`: `1`
- `undercaptured_win`: `2`
- `same_exit_bar_target_touch_ambiguous`: `1`

## Low-choke standalone screens

| Screen | Kept | Winners excluded | Losses excluded | Win-R retained | Loss-R removed | Net R | Change R | Flag |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| MACRO_NOT_OPPOSED | 9 | 8 | 9 | 13.7% | 58.2% | -3.3605 | -2.4184 | NO |
| H4_BULLISH_SEQUENCE | 3 | 9 | 12 | 4.9% | 82.9% | -1.4554 | -0.5132 | NO |
| M15_BREAK_AGE_LE_60M | 4 | 7 | 13 | 29.8% | 93.2% | +2.3680 | +3.3101 | NO |
| NOT_LAST_SESSION_HOUR | 21 | 1 | 4 | 88.9% | 24.4% | +0.6976 | +1.6398 | NO |
| TARGET_ROOM_GE_1P5R | 22 | 1 | 4 | 93.3% | 29.8% | +1.7844 | +2.7265 | LOW_CHOKE_DIAGNOSTIC |

## Shadow M5 +1R break-even overlay

- Activations: `11`.
- Losses saved / winners clipped: `2` / `1`.
- Baseline / shadow net: `-0.9421R` / `+0.3175R`.
- Net change: `+1.2596R`.

## Every trade

| Date | Session | Family | Resolution | Outcome | Attribution | Net R | MFE R | MAE R | Later target | Path-sensitive | Undercaptured |
|---|---|---|---|---|---|---:|---:|---:|---|---|---|
| 2022-03-01 | NEW_YORK | CONTINUATION_WITH_ROOM | UTC_DAY_TIME_EXIT | WIN | POSITIVE_TIME_EXIT | +0.8984 | 1.32 | 0.54 | NO | NO | NO |
| 2022-03-03 | NEW_YORK | CONTINUATION_WITH_ROOM | STRUCTURAL_STOP | LOSS | PROFIT_GIVEBACK_LOSS | -0.9725 | 1.75 | 1.11 | YES | NO | NO |
| 2022-03-14 | NEW_YORK | STRUCTURAL_REPAIR | STRUCTURAL_STOP | LOSS | NORMAL_THESIS_FAILURE | -0.7886 | 0.24 | 1.17 | NO | NO | NO |
| 2022-03-17 | NEW_YORK | CONTINUATION_WITH_ROOM | UTC_DAY_TIME_EXIT | LOSS | UNRESOLVED_NEGATIVE_TIME_EXIT | -0.0540 | 0.26 | 0.35 | NO | NO | NO |
| 2022-03-18 | NEW_YORK | STRUCTURAL_REPAIR | SEALED_TARGET | WIN | CLEAN_TARGET_WIN | +0.7124 | 0.76 | 0.41 | YES | NO | NO |
| 2022-03-21 | NEW_YORK | STRUCTURAL_REPAIR | STRUCTURAL_STOP | LOSS | STOP_THEN_TARGET | -0.9115 | 0.30 | 1.04 | YES | NO | NO |
| 2022-03-22 | NEW_YORK | CONTINUATION_WITH_ROOM | STRUCTURAL_STOP | LOSS | NORMAL_THESIS_FAILURE | -0.9295 | 0.43 | 1.21 | NO | NO | NO |
| 2022-03-23 | NEW_YORK | CONTINUATION_WITH_ROOM | UTC_DAY_TIME_EXIT | WIN | POSITIVE_TIME_EXIT | +1.1732 | 1.63 | 0.38 | NO | NO | NO |
| 2022-03-25 | NEW_YORK | STRUCTURAL_REPAIR | STRUCTURAL_STOP | LOSS | NORMAL_THESIS_FAILURE | -0.9270 | 0.37 | 1.02 | NO | NO | NO |
| 2022-03-28 | NEW_YORK | CONTINUATION_WITH_ROOM | STRUCTURAL_STOP | LOSS | PROFIT_GIVEBACK_LOSS | -0.9681 | 1.45 | 1.01 | NO | NO | NO |
| 2022-03-29 | NEW_YORK | STRUCTURAL_REPAIR | STRUCTURAL_STOP | LOSS | STOP_THEN_TARGET | -0.8183 | 0.24 | 1.14 | YES | NO | NO |
| 2022-03-30 | NEW_YORK | STRUCTURAL_REPAIR | UTC_DAY_TIME_EXIT | WIN | POSITIVE_TIME_EXIT | +3.4333 | 5.31 | 0.03 | NO | NO | YES |
| 2022-04-04 | NEW_YORK | CONTINUATION_WITH_ROOM | UTC_DAY_TIME_EXIT | WIN | POSITIVE_TIME_EXIT | +0.5150 | 1.06 | 0.33 | NO | NO | NO |
| 2022-04-05 | NEW_YORK | CONTINUATION_WITH_ROOM | UTC_DAY_TIME_EXIT | LOSS | PROFIT_GIVEBACK_LOSS | -0.3996 | 1.03 | 0.84 | NO | NO | NO |
| 2022-04-06 | NEW_YORK | CONTINUATION_WITH_ROOM | PROTECTED_STOP | SCRATCH | CONTROLLED_SCRATCH | -0.0000 | 3.88 | 0.53 | NO | NO | NO |
| 2022-04-07 | NEW_YORK | CONTINUATION_WITH_ROOM | UTC_DAY_TIME_EXIT | WIN | FRAGILE_WIN | +0.6810 | 2.12 | 0.93 | NO | NO | YES |
| 2022-04-08 | NEW_YORK | CONTINUATION_WITH_ROOM | UTC_DAY_TIME_EXIT | WIN | POSITIVE_TIME_EXIT | +1.7066 | 2.17 | 0.71 | NO | NO | NO |
| 2022-04-28 | NEW_YORK | STRUCTURAL_REPAIR | UTC_DAY_TIME_EXIT | WIN | POSITIVE_TIME_EXIT | +0.2466 | 0.41 | 0.31 | NO | NO | NO |
| 2022-05-02 | NEW_YORK | CONTINUATION_WITH_ROOM | STRUCTURAL_STOP | LOSS | NORMAL_THESIS_FAILURE | -0.9205 | 0.26 | 1.06 | NO | NO | NO |
| 2022-05-04 | NEW_YORK | CONTINUATION_WITH_ROOM | UTC_DAY_TIME_EXIT | WIN | POSITIVE_TIME_EXIT | +0.6606 | 1.58 | 0.68 | NO | NO | NO |
| 2022-05-10 | NEW_YORK | CONTINUATION_WITH_ROOM | PROTECTED_STOP | SCRATCH | CONTROLLED_SCRATCH | -0.0000 | 2.60 | 0.16 | NO | NO | NO |
| 2022-05-12 | NEW_YORK | CONTINUATION_WITH_ROOM | STRUCTURAL_STOP | LOSS | NORMAL_THESIS_FAILURE | -0.9137 | 0.51 | 1.00 | NO | NO | NO |
| 2022-05-19 | NEW_YORK | RANGE_ROTATION | UTC_DAY_TIME_EXIT | WIN | POSITIVE_TIME_EXIT | +0.5516 | 0.97 | 0.03 | NO | NO | NO |
| 2022-05-25 | NEW_YORK | CONTINUATION_WITH_ROOM | STRUCTURAL_STOP | LOSS | NORMAL_THESIS_FAILURE | -0.9979 | 0.30 | 1.08 | NO | NO | NO |
| 2022-05-26 | NEW_YORK | RANGE_ROTATION | PROTECTED_STOP | SCRATCH | CONTROLLED_SCRATCH | +0.0000 | 3.03 | 0.15 | YES | NO | NO |
| 2022-05-30 | NEW_YORK | CONTINUATION_WITH_ROOM | STRUCTURAL_STOP | LOSS | PATH_SENSITIVE_STOP_REVERSAL | -0.9465 | 0.63 | 1.06 | NO | YES | NO |
| 2022-05-31 | NEW_YORK | CONTINUATION_WITH_ROOM | STRUCTURAL_STOP | LOSS | PATH_SENSITIVE_STOP_REVERSAL | -0.9732 | 0.32 | 1.11 | NO | YES | NO |

No baseline rule, trade or result was changed. All screen and overlay results are exposed diagnostics only.
