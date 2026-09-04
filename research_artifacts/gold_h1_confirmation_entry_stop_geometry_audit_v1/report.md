# Gold H1 Confirmation Entry and Structural-Stop Geometry Audit V1

**Verdict:** `PASS_EXPOSED_MATCHED_CASE_GEOMETRY_AUDIT_REPRODUCTION`

This completed the frozen 3 x 4 matched-case audit over all 326 original executed trades from January-May 2022. It is exposed diagnostic evidence, not a validated edge.

## Combined matrix

| Entry | Stop | Filled | Win rate | Net R | Delta vs control | PF | Max DD | $ at $50/case | Winner kept/lost/unfilled |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| control entry | control stop | 326/326 | 55.2% | +22.681 | +0.000 | 1.158 | 19.519 | $+1,134.07 | 180/0/0 |
| control entry | latest M5 swing | 326/326 | 37.7% | -6.164 | -28.846 | 0.969 | 45.963 | $-308.22 | 123/57/0 |
| control entry | latest M15 swing | 326/326 | 48.8% | +22.926 | +0.245 | 1.138 | 27.651 | $+1,146.31 | 159/21/0 |
| control entry | buffered source H1 | 326/326 | 54.6% | +23.208 | +0.527 | 1.160 | 24.724 | $+1,160.42 | 178/2/0 |
| M5 retest only | control stop | 201/326 | 51.7% | +18.933 | -3.749 | 1.195 | 10.830 | $+946.64 | 103/0/77 |
| M5 retest only | latest M5 swing | 201/326 | 30.3% | -8.681 | -31.362 | 0.938 | 26.589 | $-434.04 | 61/42/77 |
| M5 retest only | latest M15 swing | 200/326 | 44.0% | +17.556 | -5.125 | 1.157 | 11.196 | $+877.81 | 88/15/77 |
| M5 retest only | buffered source H1 | 201/326 | 51.2% | +20.925 | -1.756 | 1.214 | 13.865 | $+1,046.27 | 102/1/77 |
| 25/75 split | control stop | 326/326 | 55.5% | +19.870 | -2.811 | 1.183 | 11.709 | $+993.50 | 180/0/0 |
| 25/75 split | latest M5 swing | 326/326 | 37.7% | -8.052 | -30.733 | 0.948 | 28.775 | $-402.58 | 123/57/0 |
| 25/75 split | latest M15 swing | 326/326 | 48.8% | +18.899 | -3.783 | 1.151 | 14.595 | $+944.93 | 159/21/0 |
| 25/75 split | buffered source H1 | 326/326 | 54.9% | +21.496 | -1.185 | 1.196 | 15.204 | $+1,074.80 | 178/2/0 |

## Structural-stop survival

- `CONTROL_V2_FILLED_STOP`: replaced 0; fallbacks 0; kept 180 original winners; converted 0 original winners to losses; net +22.681R.
- `M5_LATEST_CONFIRMED_OPPOSING_SWING_ELSE_CONTROL`: replaced 310; fallbacks 16; kept 123 original winners; converted 57 original winners to losses; net -6.164R.
- `M15_LATEST_CONFIRMED_OPPOSING_SWING_ELSE_CONTROL`: replaced 253; fallbacks 73; kept 159 original winners; converted 21 original winners to losses; net +22.926R.
- `H1_SOURCE_SWING_BUFFERED_ELSE_CONTROL`: replaced 37; fallbacks 289; kept 178 original winners; converted 2 original winners to losses; net +23.208R.

## Exposure-ranked result

The largest in-sample/exposed matrix result was `CONTROL_NEXT_M1_OPEN` with `H1_SOURCE_SWING_BUFFERED_ELSE_CONTROL` at +23.208R, versus the exact control at +22.681R. This ranking receives no candidate or validation credit.

A smaller stop is not automatically safer. At fixed risk a stop-out still loses 1R; the only economic benefit comes when a closer point-in-time structural stop survives and enlarges the unchanged target multiple. Converted original winners quantify where the control width genuinely protected the trade.

Separate monthly reports contain all twelve policy cells.
