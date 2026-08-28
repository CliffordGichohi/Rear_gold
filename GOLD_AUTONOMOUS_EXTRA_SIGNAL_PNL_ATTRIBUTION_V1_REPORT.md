# Gold Autonomous Extra-Signal PnL Attribution V1 Report

Verdict: `EXPOSED_CONTROL_ATTRIBUTION_COMPLETE`

This does not reverse the autonomous semantic FAIL. The nine extra
detections had no original geometry, so this report applies the one
pre-path frozen control geometry in the accompanying protocol.

| Case | Signal UTC | Status | Resolution | Net R | Net USD |
|---|---|---|---|---:|---:|
| CBR-2022-004 | 2022-01-10T14:10:00Z | EXECUTED | STRUCTURAL_STOP | -0.9871 | $-49.35 |
| CBR-2022-008 | 2022-01-14T13:40:00Z | EXECUTED | HTF_LIQUIDITY_TARGET | +0.6688 | $+33.44 |
| CBR-2022-011 | 2022-01-19T14:10:00Z | EXECUTED | HTF_LIQUIDITY_TARGET | +0.2832 | $+14.16 |
| CBR-2022-016 | 2022-01-27T13:40:00Z | POINT_IN_TIME_M15_STOP_UNAVAILABLE | — | +0.0000 | $+0.00 |
| CBR-2022-017 | 2022-01-28T16:10:00Z | EXECUTED | STRUCTURAL_STOP | -0.9766 | $-48.83 |
| CBR-2022-018 | 2022-01-31T15:55:00Z | EXECUTED | UTC_DAY_TIME_EXIT | -0.0248 | $-1.24 |
| CBR-2022-021 | 2022-02-03T13:40:00Z | EXECUTED | STRUCTURAL_STOP | -0.9613 | $-48.06 |
| CBR-2022-022 | 2022-02-04T14:45:00Z | EXECUTED | STRUCTURAL_STOP | -0.9778 | $-48.89 |
| CBR-2022-029 | 2022-02-15T16:10:00Z | EXECUTED | UTC_DAY_TIME_EXIT | -0.0759 | $-3.79 |

## Totals

- Extra scanner signals: 9 detected, 8 executable, 1 non-executable.
- Executed outcomes: 2 wins, 6 losses, 0 scratches.
- Nine-signal standalone contribution: `-3.0515R` / `$-152.57`.
- Existing human-input V2 result: `+10.6818R`.
- Requested arithmetic hybrid: `+7.6303R` / `$+381.52` at $50 per R.

## Interpretation limit

The hybrid is not a homogeneous autonomous backtest: its original
component uses human-selected entries/stops/targets, while these nine
rows use the frozen control geometry. It answers the counterfactual
money question, not whether the failed scanner is deployable.

Primary and reference sealed streams produced identical row and summary hashes.
