# Gold Coherent-Auction Human-Policy Reconstruction V2

Status: `FROZEN_EXPOSED_CALIBRATION_ZERO_VALIDATION_CREDIT`

## 1. Purpose and preserved evidence

V1 is preserved with its formal verdict `REJECT_ZERO_EXECUTABLE_TRADES_OVERFILTERED`. This V2 branch corrects the translation error; it does not overwrite V1 and it does not claim fresh evidence.

The population is the same 16 sealed human LONG decisions in `CBR-2022-001` through `CBR-2022-030`. Their decisions, annotations, drawings, actual fills, source costs and post-decision paths are already exposed. The V2 rules are therefore outcome-informed calibration rules with zero research-validation credit.

The unopened 50-case block and calendar 2025/2026 remain locked. No paid data may be acquired.

## 2. Correct interpretation of the operator's method

The human decision is the setup signal in this calibration. V2 does not pretend to rediscover that signal autonomously from a generic fractal scanner.

The point-in-time hierarchy is:

1. macro and fundamentals describe the environment and conviction;
2. completed higher-timeframe structure describes the prevailing auction and location;
3. a pre-existing inferred liquidity-shift/decision zone describes where a response is being considered;
4. completed M15 structure, or M5 structure nested inside an M15 auction, supplies the local response;
5. the operator's sealed structural invalidation owns the stop;
6. the operator's sealed next opposing liquidity area owns the target;
7. later trade management may react only to completed candles.

A liquidity-shift zone is an inferred decision area, not observed institutional orders. Being inside or responding from such a zone is location evidence and is never a universal blocker. Macro opposition is a warning and confidence input, not a veto for a fully specified range rotation or structural repair.

## 3. Semantic-fidelity gate

Before outcome-path simulation, all 16 sealed trade records must reproduce as coherent human setup intentions using only their sealed point-in-time decision form:

- direction is LONG or SHORT;
- entry, adverse stop and forward target are present and ordered;
- higher-timeframe context/location is stated;
- M15/M5 transition or response is stated;
- invalidation and target logic are stated.

This gate certifies translation of the human record. It is not evidence that software can find the setup without the human.

## 4. Thesis-family mapping

The ordered mapping is symmetric and contains no case aliases.

1. `STRUCTURAL_REPAIR`: objective H4 damage exists at the decision checkpoint and the proposed trade points against that damage.
2. `RANGE_ROTATION`: the sealed human context explicitly identifies H1 or H4 as the controlling range and price as discounted for LONG or premium for SHORT.
3. `CONTINUATION_WITH_ROOM`: every other coherent setup, including an M5 rotation inside an M15 pullback/range when H1/H4 supplies the directional auction.

An M15 range nested inside a directional H1/H4 auction is not automatically reclassified as a higher-timeframe range rotation.

## 5. Corrected contextual admission policy

The sealed human setup is first marked `INTENT_DETECTED`. It becomes `NO_TRADE` only for one of these exact point-in-time conditions:

1. `GEOMETRY_OR_REQUIRED_CONTEXT_UNAVAILABLE`: required fields, bars or lineage are unavailable; stop/entry/target ordering is invalid; or whole-ounce sizing is impossible.
2. `NO_ACTIVE_M15_DIRECTIONAL_STRUCTURE`: no still-active completed M15 structural break exists in the proposed direction at the checkpoint.
3. `UNRESOLVED_TIER1_EVENT_AUCTION`: the existing Tier-1 event protocol is locked at the checkpoint.
4. `EXTREME_HTF_EXTENSION_INTO_OPPOSING_AUCTION`: H4 24-bar range location is at least `0.80` in the proposed direction and signed H4 15-bar displacement is at least `+3.00 ATR` in that direction.
5. `SEVERE_OPPOSING_HTF_IMPULSE`: H4 damage is active and signed H4 15-bar displacement is at most `-3.00 ATR` in the proposed direction. A lower-timeframe response does not relabel this as ordinary continuation.
6. `HTF_PREMIUM_RANGE_ROTATION_CONFLICT`: a LONG higher-timeframe range rotation is proposed with H4 24-bar location at or above `0.80`, or the symmetric SHORT state at or below `0.20`.

The rules are ordered as written. All triggered reasons are reported, but the first is the primary disposition.

The following are warnings only and cannot independently reject a trade:

- macro opposition or conflict;
- price responding inside an engaged inferred decision zone;
- H4 damage when the trade is explicitly treated as bounded structural repair and the severe-impulse gate is absent;
- high H4 location without the displacement or controlling-range conjunction;
- an M15 range nested inside directional H1/H4 context.

These thresholds were selected from the already-exposed diagnostic. They are not independently validated and may not be changed after this freeze before opening the fresh block.

## 6. Entry, stop, target and risk

- Entry is the already-sealed actual fill; no later entry may be searched.
- Initial stop is the operator's sealed adverse structural invalidation. V2 does not substitute the generic latest-fractal stop that caused the V1 translation failure.
- Main target is the operator's sealed next opposing liquidity/decision area. V2 does not substitute the nearest mechanically confirmed swing.
- Total planned loss including frozen round-trip source cost is capped at `$50` on the `$10,000` reference account.
- Quantity is `floor(50 / (absolute fill-to-stop distance + frozen round-trip cost per ounce))` whole ounces.
- One position per case; no re-entry, pyramid, direction switch or deadline extension.
- Stop-first treatment applies when stop and target are touched in the same M1 bar.

## 7. Management tracks and attribution

Every admitted case is reported under three nested tracks so that no improvement can be misattributed:

1. `FAITHFUL_FIXED_GEOMETRY`: sealed actual fill, sealed stop, sealed target and time exit, after costs.
2. `PROTECTED_FIXED_GEOMETRY`: Track 1 plus one protection rule. After a completed M15 candle closes at or beyond `+1.25R` in the trade direction, the stop becomes net break-even at the next M1 open. A wick does not arm protection.
3. `COMPLETE_V2_POLICY`: Track 2 plus the already-registered bounded runner. At the main target, close the whole-ounce core of `quantity - floor(0.20 * quantity)`. Retain the runner only if the target-touch M15 candle closes beyond the target by `0.10 * M15 ATR(14)`; otherwise exit it at the next M1 open. An accepted runner trails the latest confirmed protected M15 swing and exits there or at the original deadline. Range rotation and structural repair close fully at their sealed target and have no runner.

The `+1.25R` protection threshold is explicitly exposed-sample calibration. For auditability, the prior diagnostic alternatives `1.00R`, `1.50R` and `2.00R` must be reported and may not be hidden. The complete V2 policy is the only policy frozen for later fresh evaluation.

For the protection trigger, one structural `R` is the absolute entry-to-sealed-stop price distance. Economic results remain normalized to the fixed `$50` maximum planned-loss reporting unit after costs.

## 8. Required reporting and pass interpretation

Report every admitted and rejected trade, including valid winners rejected and losing trades admitted. Report:

- semantic-fidelity count;
- selection confusion against already-known terminal direction, clearly marked post-hoc attribution;
- fixed-geometry, protected and complete-policy R and dollars;
- win rate, expectancy, profit factor and maximum drawdown;
- protection and runner contributions separately;
- 1.5x-cost stress;
- all threshold-sensitivity alternatives;
- primary/reference reproduction hashes.

An exposed result above `0R` is `PROMISING_EXPOSED_CALIBRATION`, not a validated edge. A result around `11R` in this small sample is not `11R/month` and cannot authorize live trading. Only the unopened block or later prospective decisions can supply validation evidence.

## 9. Locks

- V1 verdict and artifacts: preserved.
- Fresh 50 cases: `LOCKED_UNOPENED`.
- Calendar 2025: `LOCKED_UNOPENED`.
- Calendar 2026: `LOCKED_UNOPENED`.
- Paid acquisition: prohibited.
- Case aliases in policy code: prohibited.
- Outcome fields in pre-path classification: prohibited.
