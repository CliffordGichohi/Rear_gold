# January H1 swing loss attribution

## Result

| View | Trades | Wins | Stops | Win rate | Net gross | PF | Expectancy |
|---|---:|---:|---:|---:|---:|---:|---:|
| All executable | 88 | 38 | 50 | 43.2% | +11.47R | 1.229 | +0.130R |
| Target room >= 1.5R | 49 | 12 | 37 | 24.5% | +6.64R | 1.180 | +0.136R |
| Target room >= 2.0R | 38 | 8 | 30 | 21.1% | +6.92R | 1.231 | +0.182R |

All figures are exposed January gross geometry before costs and overlap controls.

## Stop-path diagnosis

- Stopped, then unchanged target reached later: **39/50**.
- Stopped and target never reached by month-end: **11/50**.
- Favorable movement before stop: `{"0P25_TO_0P5R": 7, "0P5_TO_1R": 13, "GE_1R": 11, "LT_0P25R": 19}`.

## Threshold retention

- >=1.5R rejects 26 winners (17.82R) and avoids 13 losses.
- >=2.0R rejects 30 winners (24.55R) and avoids 20 losses.

No admission or execution rule was changed.
