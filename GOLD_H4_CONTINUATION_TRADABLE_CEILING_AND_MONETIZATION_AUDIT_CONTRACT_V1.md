# Gold H4 Continuation Tradable-Ceiling and Monetization Audit V1

Status: **FROZEN BEFORE H4 PATH REOPENING**  
Branch: `GOLD_H4_CONTINUATION_TRADABLE_CEILING_V1`

## 1. Purpose and preserved verdict

This is a diagnostic audit, not a new strategy study. It preserves the sealed `REJECT_NO_DEVELOPMENT_ECONOMIC_EDGE` verdict from Gold Bidirectional Auction-Resolution V1 and every earlier result, rejection, artifact, and seal.

The only question is whether the frozen H4 continuation control contains enough *point-in-time and stop-feasible* movement capacity to make 10R per month possible at no more than 1% maximum case risk. No entry, stop, target, filter, session, feature, candidate, or risk rule may be changed or optimized.

Calendar 2025 and 2026 remain locked. No data may be acquired and no charge may be incurred.

## 2. Frozen population and denominator

The population is the exact H4 `CONTINUATION_ONLY_CONTROL` outer-fold validation population already sealed by the predecessor branch:

- 424 OOF H4 cases;
- 176 `NO_TRADE` cases, retained as coverage loss;
- 248 executable pre-overlap cases forming the matched numerical waterfall;
- 50 executable cases skipped by the frozen overlap rule; and
- 198 retained executed cases forming the predecessor economic result.

The executable 248 cases must retain identical entry, direction, stop, target, deadline, cost, whole-ounce size, session, and overlap disposition. A case may not be added, dropped, imputed, reordered, or relabelled.

All stage totals use the same 248 matched executable cases. At post-overlap stages the 50 skipped cases receive exactly zero PnL; they do not disappear from the denominator. The 176 no-trade cases are reported separately and never assigned a hypothetical entry.

## 3. Frozen path and ambiguity semantics

- Path source: the sealed XAUUSD M1 source already used by the predecessor.
- Interval: M1 bars from the exact frozen entry open through the original frozen deadline, inclusive of the bar closing at that deadline.
- Direction, entry, structural stop, known-liquidity target, deadline, whole ounces, and round-trip cost are unchanged.
- A missing or invalid M1 bar invalidates the matched case; no repair or substitution is permitted.
- Stop first-passage includes the entry bar.
- If stop and any favourable extreme occur in the same M1 bar, the stop is first and that bar contributes no favourable excursion.
- A gap through the stop uses the worse of the stop and M1 open.
- All perfect-exit quantities are hindsight diagnostic ceilings and can never be described as tradable results.

## 4. Frozen main waterfall

Dollar PnL is normalized by the predecessor's $50 maximum planned case risk. `R/month = total dollars / 50 / 39` for the 39 validation months. Scaling to 1% risk on $10,000 uses $100 per case and changes dollars, not R/month.

### Stage A — behavioural oracle

`BEHAVIOURAL_ORACLE`: the sealed original-direction visual-pivot-to-maximum `oracle_r × $50` for each of the 248 executable cases. It is a non-tradable reference and uses different geometry from later stages.

### Stage B — first-observable-entry ceiling

`OBSERVABLE_ENTRY_PERFECT_EXIT_GROSS`: using the frozen actual entry and whole-ounce size, capture the maximum direction-aligned M1 excursion from entry through deadline; ignore stop, target, time exit, and costs.

### Stage C — stop-feasible ceiling

`STOP_FEASIBLE_PERFECT_EXIT_GROSS`:

- if the structural stop occurs on the entry bar, use the frozen stop-first gap-adjusted stop fill;
- if it occurs later, take the maximum nonnegative favourable excursion available strictly before the stop bar;
- if no stop occurs, take the maximum nonnegative favourable excursion through deadline.

This is still a perfect-hindsight exit ceiling, but it cannot use price after structural invalidation.

### Stage D — frozen execution before costs

`FROZEN_EXECUTION_GROSS_PRE_OVERLAP`: reproduce the predecessor's first stop, known target, or deadline exit with the frozen whole-ounce size, before transaction costs.

### Stage E — frozen execution after costs

`FROZEN_EXECUTION_NET_PRE_OVERLAP`: Stage D less the frozen round-trip spread, commission, and slippage for every entered ounce.

### Stage F — frozen overlap result

`FROZEN_EXECUTION_NET_AFTER_OVERLAP`: Stage E for the 198 retained cases and zero for the 50 skipped cases. This must exactly reproduce the predecessor H4 continuation-control result.

## 5. Frozen operational upper-bound branch

The operational ceiling is not a strategy result. It retains the perfect stop-feasible exit but adds real costs and the frozen overlap restriction:

- `STOP_FEASIBLE_NET_BASE_COST`: Stage C less base round-trip costs.
- `STOP_FEASIBLE_NET_1P5X_COST`: Stage C less 1.5 times round-trip costs.
- `STOP_FEASIBLE_NET_BASE_COST_AFTER_OVERLAP`: base-cost stop-feasible PnL for retained cases and zero for skipped cases.
- `STOP_FEASIBLE_NET_1P5X_COST_AFTER_OVERLAP`: the corresponding 1.5×-cost result.

The base-cost after-overlap value is the frozen decision quantity for the 10R ceiling gate.

## 6. Frozen path diagnostics

For every executable case calculate:

- full-path MFE and MAE in frozen stop-distance R;
- maximum favourable excursion strictly before invalidation;
- first stop, target, and deadline exit classification;
- for stopped cases, whether +1R, +2R, and the original target were reached strictly after the stop bar and before deadline;
- target-exit truncation: positive full-path perfect-exit gross PnL minus frozen gross target PnL;
- time-exit truncation: positive full-path perfect-exit gross PnL minus frozen gross deadline PnL;
- stop-management gap: stop-feasible perfect-exit gross PnL minus frozen gross stop PnL;
- costs; and
- signed overlap effect.

Report counts, frequencies, means, medians, 25th/75th percentiles, total R, and R/month where applicable. Attribute the Stage C-to-D gap separately to `STRUCTURAL_STOP`, `KNOWN_TARGET`, and `TIME_EXIT` cases.

## 7. Frozen feasibility decision

- `MATHEMATICAL_CAPACITY_PRESENT` only if Stage B is at least 10R/month.
- `STOP_FEASIBLE_OPERATIONAL_CAPACITY_PRESENT` only if `STOP_FEASIBLE_NET_BASE_COST_AFTER_OVERLAP` is at least 10R/month.
- `DEMONSTRATED_10R_PRESENT` only if Stage F is at least 10R/month.

If the stop-feasible operational ceiling is below 10R/month, the required verdict is `TERMINATE_GOLD_ONLY_OPTIMIZATION_BRANCH`: the current frozen H4 opportunity cannot reach the target even with perfect hindsight exits after respecting entry, structural invalidation, costs, and overlap.

If that ceiling is at least 10R/month, report that 10R is not ruled out by the upper bound but remains unproven. Identify exactly one dominant monetization bottleneck using the largest positive total-R loss among structural-stop constraint, frozen exit capture (subdivided by stop/target/time), costs, and overlap. Recommend exactly one corresponding bounded research direction without implementing it.

## 8. Reproduction and forbidden actions

Primary and reference implementations must independently reproduce all 424 identities, 248 matched paths, bar allocations, first passages, per-case stages, diagnostics, totals, checksums, and verdict. Per-case Parquet payloads and result JSON must be byte-identical.

Forbidden actions include creating or evaluating a new strategy, changing the current H4 rule, optimizing an exit, selecting a subgroup, removing losses, using an archetype at a decision, accessing 2025/2026, acquiring data, or calculating a favourable alternative policy. The audit stops after its sealed verdict.
