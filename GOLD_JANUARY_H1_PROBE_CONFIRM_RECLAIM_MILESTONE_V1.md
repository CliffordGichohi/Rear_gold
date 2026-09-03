# Gold January H1 Probe-Confirm-Reclaim Milestone V1

## Status and purpose

- This is a bounded exposed-January execution diagnostic built on the sealed 88-attempt H1 swing-to-swing population.
- Preserve the original entries, H1 source-swing identities, opposing H1 targets, January horizon and stop-first ambiguity rule as the control.
- Change no swing detector, target-room rule, case identity or market source.
- Results receive zero fresh validation credit. No fresh dates are opened.

## Frozen setup identity

Each confirmed source H1 swing is one setup auction. LONG is armed by a confirmed H1 low and SHORT by a confirmed H1 high. The original opposing H1 target remains unchanged. The original H1 swing remains the initial invalidation level.

## Frozen risk state machine

Total maximum planned risk is `1.00R` per setup auction.

1. At the original causal entry timestamp, open a `0.25R` probe using the original H1 stop and target.
2. At the probe timestamp, freeze the most recently detected opposing M5 pivot: a confirmed M5 high for LONG and a confirmed M5 low for SHORT.
3. Before the probe resolves, initial confirmation occurs on the first subsequently completed M5 candle closing strictly beyond that frozen M5 control pivot in the setup direction.
4. Enter the `0.75R` addition at the first M1 open at or after that M5 candle's availability timestamp, only when its entry remains strictly between the unchanged stop and target.
5. If the target is reached before a valid addition, only the probe participates. If the stop is reached after the addition, total result is `-1.00R` and no recovery is permitted.
6. If the probe stops before an addition, record `-0.25R` and inspect the first subsequently completed H1 candle.
7. If that H1 candle closes strictly beyond the original swing, the auction is invalidated and no recovery is permitted.
8. If it closes back on the valid side of the swing, freeze the most recently detected opposing M5 pivot available at that H1 close. Recovery confirmation requires a later completed M5 close both on the valid side of the original H1 swing and strictly beyond that frozen M5 pivot in the setup direction.
9. Recovery is cancelled if the original target is touched or any completed H1 candle closes beyond the original swing before recovery entry.
10. Enter one recovery only, at the first M1 open at or after the recovery M5 confirmation. Allocate the remaining `0.75R` risk.
11. Recovery stop is the adverse M1 extreme from the original stop bar through the recovery-confirmation timestamp, plus an outward `0.02` XAUUSD price-unit buffer. The unchanged opposing H1 target and January deadline remain in force.
12. If recovery geometry is not strictly stop < entry < target for LONG or target < entry < stop for SHORT, take no recovery.

All timestamps use completed bars and `available_at`; entries use the next eligible M1 open. LONG and SHORT rules are exact mirrors.

## Frozen accounting

- Each tranche is sized from its own entry-to-stop distance so its maximum loss equals its allocated fraction of the original `1R` budget.
- Probe target contribution is `0.25 * probe reward/risk`.
- Addition target contribution is `0.75 * addition reward/risk`.
- Recovery target contribution is `0.75 * recovery reward/risk`, net of the already-realized `-0.25R` probe.
- A stopped probe with no recovery is `-0.25R`; a stopped fully confirmed or recovery sequence is `-1.00R`.
- Any recovery still open at the frozen January deadline is liquidated at the final complete M1 close available before the deadline; its signed price change divided by its own entry-to-stop distance is multiplied by `0.75`.
- Case win rate uses net case R greater than zero.
- Report normalized R and its `$50 per 1R` equivalent.

## Frozen comparison and gates

- Compare against the sealed gross control: 88 attempts, 38 target-first, 50 stop-first and `+11.4687555R`.
- No spread, commission, portfolio-overlap or whole-ounce constraint is introduced because the control excludes them. These must be tested later if this milestone improves the matched gross result.
- Report probe-only targets, confirmed additions, probe-only stops, valid recoveries, recovery targets/stops, H1-close cancellations, case win rate, PF, total R, drawdown and winner-R retention.
- This implementation is an improvement candidate only if it exceeds the matched control total R without exceeding `-1R` per setup and without depending on one case for the entire increment.
- No threshold retuning, alternate risk split, second confirmation rule or target-room filter is permitted after results are opened.
- Primary and reference reconstructions must match exactly.
