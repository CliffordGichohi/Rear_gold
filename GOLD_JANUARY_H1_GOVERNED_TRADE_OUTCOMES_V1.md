# Gold January H1-Governed Trade Outcomes V1

## Purpose

Open the post-decision January 2022 price path for the twelve already frozen
H1-governed plans without changing their identities, direction, entry, stop,
target, or admission logic. Present the complete month as one continuous chart,
not as isolated cases.

## Frozen population

- Input plans: the sealed `GOLD_H1_GOVERNED_TRADE_SCANNER_V1` January output.
- Population: exactly twelve plans from 2022-01-03 through 2022-01-31.
- No plan may be added, removed, inverted, retuned, or reclassified.
- Primary and reference source implementations must reproduce exactly.

## Outcome construction

- Price authority: sealed observed XAUUSD M1 OHLC.
- A plan becomes active at its frozen `decision_at` using its frozen entry level.
- The first eligible bar opens exactly at `decision_at`.
- LONG target passage: M1 high is greater than or equal to the frozen target.
- LONG stop passage: M1 low is less than or equal to the frozen stop.
- SHORT target passage: M1 low is less than or equal to the frozen target.
- SHORT stop passage: M1 high is greater than or equal to the frozen stop.
- If stop and target occur in the same M1 bar, record
  `STOP_FIRST_AMBIGUOUS`; do not infer an advantageous within-bar sequence.
- If neither level is reached by 2022-02-01T00:00:00Z, record
  `MONTH_END_MARK` at the last completed January M1 close.
- Target R equals the frozen target distance divided by the frozen stop distance.
- A stop is -1R. A month-end mark uses signed close displacement divided by the
  frozen stop distance.
- Results are gross geometric outcomes. No spread, slippage, commission,
  position sizing, overlap constraint, or portfolio PnL is introduced here.

## Continuous display

- Display one continuous January timeline with H1, M15, and M5 choices.
- Default to the complete M15 month.
- Show every plan on the same timeline with locally bounded entry, stop, target,
  and resolution annotations; no line may run across unrelated history.
- Show TARGET, STOP, STOP_FIRST_AMBIGUOUS, and MONTH_END_MARK distinctly.
- Permit chart zoom and pan only through visible controls.
- An outcome row may highlight a plan but must not replace the continuous chart
  with an isolated case chart.

## Interpretation boundary

This is an exposed January plan-outcome audit. It describes how the already
frozen plans resolved under one deterministic first-passage convention. It is
not fresh validation, execution-cost testing, a portfolio backtest, or an edge
claim.
