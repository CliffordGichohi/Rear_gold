# Gold H4 Liquidity-Target Capture Falsification Contract V1

Status: **FROZEN BEFORE 2021-2024 POST-TARGET PATH ACCESS**  
Branch: `GOLD_H4_LIQUIDITY_TARGET_CAPTURE_FALSIFICATION_V1`

## 1. Purpose and preserved evidence

This is the final bounded study of the gold-only 10R/month branch. It preserves the formal `REJECT_NO_DEVELOPMENT_ECONOMIC_EDGE` verdict for the H4 continuation control, the later `UPPER_BOUND_CAPACITY_PRESENT_NOT_DEMONSTRATED` audit verdict, and every preceding artifact and seal.

The sole question is whether an operational, point-in-time management rule at the already-frozen original liquidity target can convert the unchanged H4 continuation entries into at least 10R/month at no more than 1% case risk. It is not permission to alter setup selection, direction, entry, initial stop, initial risk, deadline, session, costs, or the one-open-position rule.

Only the sealed 2021-2024 development sources may be used. Calendar 2025 and 2026 remain locked throughout this contract. The results are post-hoc development evidence and receive no independent-validation credit.

## 2. Frozen population

The exact predecessor population is retained:

- 424 outer-fold H4 continuation-control cases;
- 176 no-trade cases retained in coverage reporting;
- 248 executable cases on which every registered policy is simulated;
- the predecessor control's 198 retained cases and 50 overlap skips must reproduce exactly.

No executable case may be dropped because its original target was missed. Stop-first and time-exit cases reproduce the control because target management never activates. A policy-specific overlap disposition is calculated only after all 248 executable paths have been simulated using the unchanged one-open-position algorithm.

## 3. Frozen source, timing, and ambiguity rules

- Price source: sealed XAUUSD M1, M15, H1, and H4 bars ending before 2025.
- Every case retains its original entry, direction, structural stop, liquidity target, deadline, whole-ounce size, and per-ounce round-trip cost.
- A runner can begin only after the original target is first reached before the original stop.
- Stop and favourable target in the same M1 bar are stop-first. A gap through a protective stop uses the worse of the stop and M1 open.
- A completed-candle decision is actionable at the next exact M1 open. No same-close fill is permitted.
- Missing or invalid required M1 path data fails the study. Missing target-state inputs disable extension and reproduce a full close at the original target.
- Costs remain linear per ounce at 1.0x, 1.5x, and 2.0x the frozen round-trip cost. Multiple scale-out fills do not erase or duplicate the frozen entry cost.

## 4. Frozen point-in-time target state

### ATR

`ATR14_M15_TARGET` is the integer-floor mean of fourteen true ranges from the last fourteen valid M15 bars whose closes are no later than the target-touch M1 open, using the immediately preceding M15 close. Fifteen valid completed M15 bars are required. The value is frozen for the complete target-management episode.

### Confirmed liquidity pivots

A pivot uses two bars left and two bars right. It becomes known only at the close of the second right-hand bar. All five bars must be valid.

- High pivot: center high is strictly above both left highs and greater than or equal to both right highs.
- Low pivot: center low is strictly below both left lows and less than or equal to both right lows.
- A high remains live until a later completed bar trades strictly above it; a low remains live until a later completed bar trades strictly below it.

At target touch, the next-known-liquidity level is the nearest live H1 or H4 pivot at least 0.25 frozen M15 ATR beyond the original target in the trade direction. Distance wins; H1 wins a distance tie; the most recently known pivot wins any remaining tie. If no such pivot exists, the entire position closes at the original target.

### Acceptance and rejection

Classification begins at the first valid M15 close at or after the target-touch M1 close and uses at most two completed M15 bars:

- `ACCEPTED`: direction-signed close minus original target is at least 0.10 ATR, the candle body is direction-aligned, and the close is in the directional final 40% of the candle range.
- `REJECTED`: direction-signed close minus original target is no more than -0.05 ATR.
- `NEUTRAL`: neither condition.
- Two neutral closes cause `NEUTRAL_TIMEOUT_EXIT` at the next M1 open.
- An invalid required M15 decision bar causes `TECHNICAL_EXIT` at the next M1 open.

After acceptance, a close at least 0.05 ATR back inside the original target causes `POST_ACCEPTANCE_REJECTION_EXIT` at the next M1 open.

### Structural trailing

After acceptance only, the remaining runner is protected by the latest still-live, confirmed opposing M15 pivot known at each completed M15 close, buffered by 0.10 frozen ATR. The structural trail may tighten but never loosen the unchanged original stop. If a proposed trail is not at least 0.05 ATR on the protective side of the completed close, the runner exits at the next M1 open instead of installing an invalid stop.

Runner exit priority is: pending completed-candle market exit at M1 open; protective stop before next-liquidity target within an M1 bar; next-known-liquidity target; original deadline. The next liquidity target is frozen at target touch and never extended again.

## 5. Frozen policy registry

`CONTROL_FULL_CLOSE` closes all ounces at the original target and must reproduce the predecessor.

Exactly three research policies are registered:

1. `TARGET_TAKE_25_RUN_75`
2. `TARGET_TAKE_50_RUN_50`
3. `TARGET_TAKE_75_RUN_25`

At original-target touch, realized ounces equal `max(1, ceil(fraction_to_take * whole_ounces))`; runner ounces are the nonnegative remainder. If the runner is zero, ATR is unavailable, or next liquidity is unavailable, the policy becomes the control for that case. Fractions, thresholds, pivot definitions, and exits cannot be fitted or retuned.

## 6. Blocked evaluation and metrics

The seven predecessor validation blocks are unchanged: 2021 Q4, 2022 H1, 2022 H2, 2023 H1, 2023 H2, 2024 H1, and 2024 H2. Because every policy is fully frozen before outcomes, no outcome-based model fitting occurs; each block is an out-of-fold policy evaluation block.

For every policy report:

- all 248 executable cases, target-first cases, managed runners, dates, and overlap dispositions;
- target acceptance, rejection, timeout, technical, trail, next-liquidity, stop, and deadline counts;
- net expectancy, R/month, dollar PnL at $50 risk, dollars/month at 1% risk, win rate, average win/loss, profit factor, and maximum drawdown;
- base, 1.5x, and 2.0x costs;
- paired incremental expectancy and R/month versus the control;
- date-clustered 95% intervals and one-sided p-values for absolute and paired incremental expectancy;
- Holm correction across the three registered policies;
- annual, fold, and entry-session stability; and
- policy-specific overlap effects.

A fixed-disposition, target-only perfect-exit ceiling may be reported as a hindsight impossibility diagnostic. It substitutes the previously sealed stop-feasible maximum only for original target-first cases and leaves stop/time cases unchanged. It is not a policy result.

## 7. Frozen support, selection, and decision rules

A policy has adequate management support only with at least 30 managed runners across at least 20 dates. At most one policy can be frozen, ranked by R/month, profit factor, incremental lower confidence bound, then the larger fraction realized at the original target.

A policy passes only if every gate passes:

- all 248 paths and frozen control economics reproduce;
- management support passes;
- base-cost post-overlap R/month is at least 10.0;
- net expectancy and paired incremental expectancy are positive;
- profit factor is at least 1.10;
- absolute and paired incremental clustered 95% lower bounds are positive;
- Holm-adjusted paired one-sided p-value is at most 0.05;
- 1.5x-cost expectancy is positive;
- at least four of seven folds and three of four calendar years are positive;
- no single positive year or session supplies more than 70% of positive PnL; and
- maximum drawdown at 1% case risk is no more than 15% of the $10,000 account.

If no policy passes, or no policy produces at least 10R/month, the mandatory verdict is `TERMINATE_GOLD_ONLY_10R_BRANCH`. No other gold research branch may be opened under this contract. If a policy passes, freeze exactly one as `PROVISIONAL_TARGET_POLICY_REQUIRES_FORWARD_EVIDENCE`; do not access 2025 or 2026 during this study.

## 8. Integrity and stopping rule

Primary and reference implementations must independently reproduce liquidity catalogs, all 248 paths per policy, target classifications, fills, policy overlap dispositions, per-case rows, statistics, checksums, and verdict. Parquet and JSON outputs must be byte-identical.

Forbidden actions include adding a policy, changing a threshold after outcomes, selecting only target winners, changing initial trade geometry or risk, removing losses, using future pivots, extending the deadline, accessing 2025/2026, acquiring data, or opening another branch. Document every negative result, seal the final verdict, and stop.
