# Gold H1 Confirmation Entry and Structural-Stop Geometry Audit V1

## Purpose and evidence boundary

This is a matched-case geometry audit of the preserved confirmation-only V2 branch. It does not replace, reject, retune or reinterpret that branch.

- Use only the already exposed calendar months January through May 2022.
- Freeze the population as all 326 trades actually executed by the sealed V2 monthly ledgers: January 65, February 61, March 79, April 60 and May 61.
- Preserve every original direction, setup identity, target, calendar-month deadline and stop-first ambiguous-bar convention.
- Do not remove a trade because its reward multiple is small or because an alternative geometry performs poorly.
- Do not inspect another month, 2025 or 2026. Acquire no data and incur no charge.
- Results have zero validation credit and are diagnostic evidence only.

## Point-in-time structural-stop registry

All structural inputs must have `available_at <=` the original V2 entry timestamp. A candidate uses an outward buffer of `max(0.05 * ATR(14) on its source timeframe, 0.02 XAUUSD price units)`. A candidate that is unavailable, not adverse to entry, produces invalid stop-entry-target ordering, or is not strictly closer than the V2 control stop falls back to the unchanged control stop. Every original trade therefore remains represented.

1. `CONTROL_V2_FILLED_STOP`: the exact stop used by the sealed V2 ledger.
2. `M5_LATEST_CONFIRMED_OPPOSING_SWING_ELSE_CONTROL`: the latest confirmed M5 low for LONG or M5 high for SHORT known at entry, plus the frozen outward buffer.
3. `M15_LATEST_CONFIRMED_OPPOSING_SWING_ELSE_CONTROL`: the latest confirmed M15 low for LONG or M15 high for SHORT known at entry, plus the frozen outward buffer.
4. `H1_SOURCE_SWING_BUFFERED_ELSE_CONTROL`: the original source H1 pivot that armed the setup, plus the frozen outward H1 buffer. This can replace the control only where it is closer, principally after a reclaim excursion.

The M5 stop represents immediate timing invalidation, M15 represents active lower-timeframe auction invalidation, and H1 represents governing-thesis invalidation. These are calculated structural alternatives, not claims of observed institutional orders.

## Point-in-time entry registry

The exact broken M5 control and confirmation bar used by V2 must be reconstructed and must reproduce the sealed V2 entry before any alternative is evaluated.

1. `CONTROL_NEXT_M1_OPEN`: exact V2 entry at the first eligible M1 open after the completed M5 confirmation.
2. `M5_BROKEN_CONTROL_FIRST_RETEST`: after confirmation, place one limit order at the broken, previously frozen M5 control level. It is live for the next 15 minutes using `[entry_at, entry_at + 15 minutes)` and is cancelled by stop, target or expiry before fill. It may remain unfilled; this is reported, never hidden.
3. `CONFIRMED_25_75_RETEST_SPLIT`: allocate 25% of the case risk to the exact control entry and reserve 75% for the identical retest order. This is not the rejected pre-confirmation probe: both tranches are authorized only after the original completed M5 confirmation. If no retest occurs, the initial 25% remains the only exposure. Maximum combined planned risk remains 1R.

For a limit-order bar containing both the candidate stop and limit, assume fill then stop. If a not-yet-filled bar contains both target and limit without the stop, classify the limit fill as unresolved intrabar and cancel it rather than claiming a favourable fill. Once stop or target resolves the case, no later entry or re-entry is permitted.

## Frozen lifecycle and accounting

- Evaluate the complete `3 entry policies x 4 stop policies` matrix for every original executed trade.
- Use the unchanged absolute target and the final observed M1 close before the original calendar-month deadline.
- Apply stop before target whenever both occur in one M1 bar.
- Normalize each full-risk leg so its selected entry-to-stop distance is 1R. A split result is `0.25 * control-leg R + 0.75 * retest-leg R` when the retest fills, otherwise `0.25 * control-leg R`.
- Preserve the original gross-before-cost V2 convention so the geometry effect is isolated. Do not claim live profitability from this audit.
- Also report stop-distance ratio to control, MFE and MAE in selected-stop R, winner survival, original winners converted to losses, original winners left unfilled, retest fill rate, and fallbacks.

## Required monthly and combined reporting

Report January, February, March, April and May separately for every matrix cell:

- fixed population;
- filled cases and retest fills;
- wins, losses and time exits;
- win rate;
- net R;
- expectancy per original case and per filled case;
- profit factor;
- maximum drawdown;
- dollars at the preserved `$50` maximum case risk;
- control-winner retention and conversion;
- stop replacement and fallback counts.

The report must distinguish an improved reward multiple from a genuinely safer stop. No winner may disappear from the audit population merely because a proposed order did not fill.

## Integrity gates

1. Verify every predecessor source/result seal used by the audit.
2. Reconstruct all five sealed monthly V2 ledgers exactly before evaluating alternatives.
3. Prove direction symmetry, point-in-time swing availability, invalid-candidate fallback, stop-first ambiguity, retest expiry and split-risk arithmetic on synthetic paths.
4. Parse the sealed casebook independently through the existing primary and reference readers.
5. Require exact agreement on the 326 identities, reconstructed confirmations, geometry rows, lifecycle rows, monthly metrics, diagnostics and canonical checksums.
6. Preserve a complete CSV ledger, JSON result, separate monthly reports, protocol freeze, synthetic proof and cryptographic manifest.

No visualization is required for this audit. If implementation fidelity is challenged, the sealed ledger must contain sufficient timestamp and level identities to render disputed cases without rerunning or changing the rules.
