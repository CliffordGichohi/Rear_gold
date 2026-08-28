# Gold Coherent-Auction March--May 2022 Outcome Attribution V1

Status: `FROZEN_BEFORE_TRADE_PATH_ATTRIBUTION`

## Purpose

Explain why each of the 27 unchanged-translator trades from March--May 2022
won, lost or scratched without modifying the frozen translator or execution
policy. Separate normal thesis failure from observable entry-timing,
profit-retention and path-sensitivity problems. Quantify whether any bounded
improvement idea would also remove existing winners.

This is an exposed diagnostic. It may generate a later hypothesis but cannot
validate or modify a rule.

## Frozen sources

- The sealed consecutive-month final result and primary/reference daily stream
  bundles only.
- All predecessor hashes must verify before analysis.
- Primary and reference attribution must reproduce exactly.
- No new data, acquisition, fitting or access to 2025/2026 is permitted.

## Common measurements

All path measurements begin at the frozen fill and end at that UTC trading
day's last observed quote. Structural R uses the frozen fill-to-structural-stop
price risk, not a future-derived distance. Record:

- pre-exit MFE and MAE in structural R;
- full-day MFE and MAE in structural R;
- target room in structural R;
- stop overshoot in structural R;
- later fill reclaim, +1R reach and original-target reach after an exit;
- same-bar stop/target ambiguity;
- signal session and elapsed session minutes;
- macro score/state, H4 swing sequence, M15 break age and thesis family.

## Ordered primary attribution

### Losing trades

1. `PROFIT_GIVEBACK_LOSS`: pre-exit MFE reached at least +1.00 structural R
   before the trade finished negative.
2. `STOP_THEN_TARGET`: a structural/gap stop occurred and the original target
   was reached in a strictly later M1 bar before the day ended.
3. `PATH_SENSITIVE_STOP_REVERSAL`: a structural/gap stop overshot the boundary
   by no more than 0.15 structural R and a strictly later bar reclaimed the fill
   and reached at least +1.00 structural R, without satisfying rule 2.
4. `UNRESOLVED_NEGATIVE_TIME_EXIT`: the trade remained live but negative at
   the frozen daily time exit.
5. `NORMAL_THESIS_FAILURE`: every other loss. The planned auction did not
   produce sufficient favourable movement before valid invalidation.

The independent flags above remain reported even when an earlier ordered class
wins precedence. A path-sensitive reversal is the closest operational proxy to
what may colloquially be called bad luck; it is not proof of randomness or
permission to widen a stop.

### Scratches

`CONTROLLED_SCRATCH` applies when absolute net result is no more than 0.05R50.

### Winning trades

1. `FRAGILE_WIN` when pre-exit MAE reached at least 0.75 structural R.
2. `CLEAN_TARGET_WIN` when a non-fragile trade exited through its frozen target.
3. `PROTECTED_WIN` when a non-fragile trade exited through a protected stop.
4. `POSITIVE_TIME_EXIT` for every other non-fragile positive daily time exit.

`UNDERCAPTURED_WIN` is an independent descriptive flag when full-day maximum
favourable movement exceeded realised gross movement by at least 1.00
structural R. It is not a tradable oracle result.

## Frozen low-choke diagnostics

Apply these standalone, point-in-time observable screens to all 27 trades. Do
not combine or tune them:

1. `MACRO_NOT_OPPOSED`: long-side macro score greater than -10.
2. `H4_BULLISH_SEQUENCE`: completed H4 state is `BULLISH_SWING_SEQUENCE`.
3. `M15_BREAK_AGE_LE_60M`: latest completed M15 break is no more than 60
   minutes old.
4. `NOT_LAST_SESSION_HOUR`: signal occurs before minute 180 of its four-hour
   session.
5. `TARGET_ROOM_GE_1P5R`: frozen target room is at least 1.50 structural R.

For each screen report retained trades, winners removed, winning-R retention,
losing-R removal and resulting net R50. A screen receives only a descriptive
`LOW_CHOKE_DIAGNOSTIC` flag if it improves net R, retains at least 90% of
positive R, and removes at least 20% of negative R. It does not become a rule.

## Frozen management diagnostic

Test one shadow overlay without altering the baseline:

- after the first completed M5 close at or above +1.00 structural R, activate a
  cost-adjusted break-even stop from the next M1 bar;
- preserve the original target and use stop-first treatment when break-even and
  target are touched in the same M1 bar;
- report losses saved, winners clipped, scratches changed and net R50 retained;
- do not replace or modify the current M15 +1.25R protection rule.

## Output

Report every trade, every attribution and flag, aggregate category counts and
R, family/month/session breakdowns, all five low-choke screens and the single
shadow-management diagnostic. Recommend only improvements supported by these
measurements and explicitly identify their winner-choking cost.
