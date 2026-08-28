# Gold Hybrid Structural Execution Research Contract V1

Status: `AUTHORIZED_EXPOSED_EXECUTION_RESEARCH`

Preserve every previous result, rejection, artifact and seal. Preserve the
sealed hybrid direction assignment for all 729 January-June 2022 transition
identities, including all 648 mechanically executable identities, 434
continuation identities, 180 selectively negated continuation identities and
468 preserved identities. Do not alter the direction router, add a daily cap,
suppress overlapping signals or wait for another position to resolve.

This is explicitly post-hoc research on already exposed data. It receives zero
validation credit. Keep the unopened 2022-02-17 through 2022-02-28 interval,
calendar 2025 and calendar 2026 closed. Acquire no data and incur no charge.

## Book-aligned execution premise

Separate bias, trigger, invalidation, size and target. A stop must represent a
point-in-time structural failure, not merely the old target after a direction
flip. A wider logical stop must reduce quantity. A chart high or low is a
decision reference, not direct evidence of institutional orders. Acceptance
and rejection must be defined by completed traded-price bars.

## Frozen entry and invalidation modes

Apply all three modes to the same frozen population:

1. `E0_CONTROL_MECHANICAL`
   - Preserve the sealed hybrid plan exactly.
   - This reproduces the sealed no-upsize/$50-risk Track B control.

2. `E1_IMMEDIATE_LOCAL_M15_INVALIDATION`
   - Preserved-direction and non-continuation plans remain unchanged.
   - For a negated plan, retain the original decision checkpoint and selected
     direction.
   - Use the decision-time nearest unconsumed M15 destination on the original
     direction's side as the selected direction's invalidation reference.
   - LONG stop: local M15 low minus the frozen decision-time active-M15 break
     buffer. SHORT stop: local M15 high plus that buffer.
   - If the level or buffer is unavailable, or stop/target geometry is not
     positive in the selected direction, record `NO_TRADE_UNRESOLVED`.

3. `E2_M5_SWEEP_RECLAIM_POST_STRUCTURE`
   - Preserved-direction and non-continuation plans remain unchanged.
   - For a negated plan, require the decision-time local M15 reference and
     active-M15 buffer.
   - Use source M1 bars opening at or after the original decision to construct
     UTC-aligned, completed M5 bars from exactly five consecutive complete M1
     bars. Confirmation exists only at the completed M5 close.
   - LONG confirmation: the first M5 bar whose low is strictly below the local
     M15 low and whose close is strictly above it.
   - SHORT confirmation: the first M5 bar whose high is strictly above the
     local M15 high and whose close is strictly below it.
   - Enter after the completed confirmation with the unchanged one-minute
     latency. LONG invalidation is the confirmation low minus the frozen
     buffer; SHORT invalidation is the confirmation high plus the buffer.
   - If no confirmation completes before the preserved noon-New-York deadline,
     or the resulting geometry is invalid, record `NO_TRADE_NO_CONFIRMATION`.

## Frozen target and management modes

Cross every entry/invalidation mode with exactly these three exit modes,
forming nine and only nine policies:

1. `T0_PRIMARY_LIQUIDITY_FULL`
   - Preserve the selected plan's existing absolute known-liquidity target and
     noon deadline.

2. `T1_LOCAL_M15_FIRST_FULL`
   - For preserved-direction plans only, use the decision-time local M15
     destination when it lies strictly in the selected direction and is closer
     than the existing target. Otherwise retain the existing target.
   - Negated-plan targets remain the selected plan's existing target, which is
     the previously known opposing protected structure.

3. `T2_HALF_AT_1R_THEN_PRIMARY`
   - Retain the primary target.
   - If whole-ounce quantity is at least two and the primary target is beyond
     +1R measured from the actual fill to the structural stop, close
     `floor(quantity / 2)` ounces at first +1R and hold the remainder to the
     primary target, structural stop or deadline.
   - Do not move the stop to break-even and do not trail it.
   - On ambiguous bars, the stop is evaluated first. A target/partial limit
     reached without a simultaneous stop receives the same fill convention as
     the existing target limit.

## Frozen execution and risk

- Entry fill: first eligible M1 open after the unchanged one-minute latency.
- Preserve existing observed spread, $0.05/ounce slippage, target-limit fill
  convention, stop-first ambiguity treatment and noon-New-York deadline.
- Quantity is
  `min(sealed_original_quantity, floor(50 / selected_displayed_stop_distance))`.
- Never upsize after changing geometry. Maximum displayed planned risk is $50
  per setup. Retain zero-quantity identities as
  `RISK_INFEASIBLE_WHOLE_OUNCE`.
- Keep every valid overlapping setup. Report actual concurrent exposure.

## Frozen evaluation

The sealed control is +21.312216428575976R under the strict no-upsize risk
track. The fixed-quantity comparison benchmark remains
+45.772787857150256R, but its unsafe quantities are not reused.

Report each policy's support, skipped negated confirmations, trades per month,
win rate, expectancy, profit factor, net R and dollars, drawdown, monthly,
direction, route and resolution contributions, maximum trade risk and maximum
concurrent risk. Report the negated subset separately.

Use deterministic day-cluster bootstrap with seed `20260827` and 5,000 draws.
For each of the eight non-control policies, use a Bonferroni-adjusted 99.375%
interval for its paired daily-R difference from control.

A provisional execution policy passes the exposed-development improvement gate
only if:

- at least 50 negated setups execute;
- complete-portfolio net R exceeds control by at least 2R;
- profit factor is at least the control profit factor;
- maximum drawdown does not exceed control;
- at least four of six calendar months are positive;
- the multiplicity-adjusted paired improvement interval has a lower bound
  above zero;
- no displayed trade risk exceeds $50 and no quantity is upsized; and
- primary/reference results reproduce exactly.

Record separately whether any policy reaches +45.772787857150256R. Permit no
more than two provisional policies, ranked by: improvement-gate pass,
benchmark attainment, net R, profit factor, lower drawdown and stable policy
identifier. Zero provisional policies is acceptable.

Do not alter a rule after viewing outcomes, remove losing cases, add another
entry, stop, target or management mode, inspect a fresh period or claim an edge
from these exposed results. Independently reproduce, document every negative
result, seal the final verdict and stop.
