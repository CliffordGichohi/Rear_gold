# Gold Coherent-Auction Exposed-Policy Regression Protocol V1

Status: `FROZEN_BEFORE_NEW_REGRESSION_CALCULATION`

## Evidence boundary

This is a zero-credit regression over the already exposed matched-human cases. It tests whether the exact mechanical corrections carried into `GOLD_COHERENT_AUCTION_BLIND_VALIDATION_CONTRACT_V1.md` behave as intended before any fresh validation decision is collected. It cannot validate an edge. Calendar 2025 and 2026 remain locked.

No result from this regression may be described as blind, forward, independent, or prospective evidence.

## Frozen population and inputs

- Population: all 16 sealed human LONG decisions in `CBR-2022-001` through `CBR-2022-030`; no case may be removed.
- Entries, actual fills, original human H1 targets, original deadlines, per-ounce costs, and full price paths remain unchanged.
- Initial stop, eligibility, and whole-ounce quantity come unchanged from `research_artifacts/gold_coherent_auction_management_v1/coherent_auction_management_result.json`.
- The existing corrected fixed-H1 track is the control and must reproduce exactly to eight decimal places case by case and in aggregate.
- The challenger is the single frozen `PROTECTION_80_20_RUNNER` track from the blind-validation contract. No alternative split, threshold, swing width, ATR buffer, or exception is permitted.

## Point-in-time structural definitions

- ATR(14) is the arithmetic mean of the latest 14 completed true ranges, including the current completed candle.
- A confirmed five-bar swing has two completed candles on each side, a unique extreme, and prominence of at least `0.25 * ATR`, with a `$0.02` minimum. It becomes available only when the second right-hand candle completes.
- All management evidence must be available before it can act. A completed-candle signal exits at the first subsequent M1 open.
- Same-M1-bar ambiguity is stop first.
- The initial risk-price unit is `actual fill - corrected initial stop`.

## Frozen Track B implementation

### Before the H1 target

1. Retain the corrected initial stop.
2. Arm protection only after an observed M1 high first reaches `actual fill + 1.0 * initial risk-price unit` without the stop having resolved first.
3. Once armed, inspect completed M5 candles. Use the latest confirmed M5 swing low available no later than the breaking M5 candle's open.
4. If the completed M5 close is below that swing low by at least `0.10 * that completed M5 candle's ATR(14)`, exit the full position at the first subsequent M1 open.

### At and after the H1 target

1. On first target touch, realize the whole-ounce core at the frozen H1 target.
2. The runner is `floor(0.20 * entry quantity)` whole ounces; the core is the remainder. If this produces zero runner ounces, close the complete position at target.
3. Keep the runner at the initial stop until the target-touch M15 candle completes.
4. Acceptance requires that exact completed M15 candle to close at or above `target + 0.10 * its ATR(14)`.
5. Without acceptance, exit the runner at the first subsequent M1 open. This is the causal whole-ounce implementation of the frozen conditional 20% rule; retroactive execution at the earlier target price is prohibited.
6. With acceptance, trail the runner using the latest confirmed M15 swing low available no later than each completed M15 candle's open, buffered by `0.10 * that candle's ATR(14)`. The stop may only rise.
7. Exit the runner on the first stop touch, a gap through the stop, or the original session deadline.

Each ounce incurs the unchanged sealed round-trip cost exactly once, regardless of exit track. There is no pyramiding, re-entry, direction switch, or target replacement.

## Required comparison

Report every case with:

- original recorded R;
- corrected fixed-H1 control R;
- frozen Track B R;
- incremental Track B R;
- entry eligibility and failure reason;
- protection armed, protection exit, H1 core realization, acceptance, runner activation, and runner exit;
- whether the rule improved or degraded the case;
- whether it addressed each previously identified correct-direction round trip (`CBR-2022-005`, `CBR-2022-014`, `CBR-2022-030`);
- whether it preserved the large corrected-control winners (`CBR-2022-023`, `CBR-2022-024`, `CBR-2022-027`).

Also report the four known direction-wrong cases (`CBR-2022-007`, `CBR-2022-009`, `CBR-2022-019`, `CBR-2022-026`) separately.

## Important testability boundary

The blind contract's auction-family, H4-state, location, stop-basis, and macro-override fields are mandatory human observations, not deterministic entry filters. This regression may verify that each known failure mode has a place to be recorded, but it must not claim those fields automatically reject a bad trade. Retroactively assigning a favourable `NO_TRADE` decision is prohibited.

Accordingly, the regression has two distinct verdicts:

1. `MECHANICAL_REGRESSION_PASS` only if the fixed-H1 control reproduces exactly, both implementations of Track B agree case by case, all point-in-time and integrity gates pass, and all 16 cases remain represented.
2. `CORRECTION_CAPTURE` is descriptive and must state exactly which prior problems Track B did and did not address. It is never an edge verdict.

Fresh 50-case collection remains paused until this regression is complete and any non-executable ambiguity is resolved without inspecting fresh outcomes.

