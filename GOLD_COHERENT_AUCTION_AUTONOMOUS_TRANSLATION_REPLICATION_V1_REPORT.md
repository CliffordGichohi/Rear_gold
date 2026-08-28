# Gold Coherent-Auction Autonomous Translation Replication V1 Report

Verdict: `FAIL_AUTONOMOUS_SEMANTICS`

Evidence status: `EXPOSED_SAME_MONTH_CALIBRATION_ZERO_VALIDATION_CREDIT`

## Direct answer

The unchanged V2 overlay **does** reproduce its original same-month result when
it receives the same sixteen sealed human setups:

- admitted: 11;
- rejected: 5;
- complete-policy result: `+10.68184658R`;
- original complete-policy result: `+10.681846581267534R`;
- absolute reproduction difference: `0.000000001267534R`;
- primary/reference and every sealed per-case result: exact after the frozen
  eight-decimal serialization.

This proves that the V2 admission, protection and runner lifecycle was not
mistranslated.

It does **not** prove that software can find the setups.  V2's original inputs
were the operator's direction, decision time, fill, structural stop, liquidity
target and written auction context.

## Autonomous same-month test

The autonomous scanner received no human decision timestamp, drawing, case
date, case alias, outcome or PnL field.  It scanned every eligible London and
New York five-minute checkpoint on all thirty exposed days using only completed
point-in-time candles, structural/liquidity state, session phase, macro context
and event state.

The outcome-hidden materialization contained:

- 30 sessions;
- 2,393 eligible checkpoint rows;
- 63 semantic-positive training rows around the sixteen human decisions;
- identical primary/reference rows and checksum
  `5f71fdee9825ad6b520be0eca86ac113960fe3d179d929bceeda38e06ff0ab4d`.

A bounded registry of 864 transparent shallow-tree and decision-threshold
configurations was evaluated against human setup timing only.  The selected
translation used a 15-node, depth-six tree, a `0.90` probability threshold and
three consecutive qualifying checkpoints.

| Semantic gate | Required | Achieved | Result |
|---|---:|---:|---|
| Human setup days detected | at least 14 / 16 | 13 / 16 | FAIL |
| False-positive no-trade days | at most 2 / 14 | 9 / 14 | FAIL |
| Median checkpoint difference | at most 15 min | 20 min | FAIL |
| Maximum matched difference | at most 45 min | 40 min | PASS |

The scanner therefore failed before stop/target geometry or economic replay.
No post-decision path was opened for the autonomous scanner, and no autonomous
PnL was calculated.

## What this means

The `+10.6818R` result is an exact exposed result for **your human-selected
setups plus the frozen V2 overlay**.  It is not yet an autonomous strategy.

The current mechanical state representation recognizes broad bullish auction
conditions but does not preserve the operator's selective distinction between:

- a meaningful controlling-timeframe liquidity location and an ordinary
  mechanical pivot;
- a tradable lower-timeframe response and similar-looking internal noise;
- a valid range rotation and a no-trade range;
- the specific structural level that owns invalidation and the next meaningful
  opposing liquidity destination.

The selected tree's reliance on session identity and short-horizon returns is
additional evidence that it found proxies rather than a faithful translation
of the chart reasoning.  Opening a new month with this scanner would test a
different strategy and repeat the earlier mistranslation.

## Disposition

- same-month human-input V2 control: `PASS`;
- same-month autonomous signal translation: `FAIL`;
- autonomous geometry test: `NOT_RUN_UPSTREAM_FAIL`;
- autonomous economic checksum: `NOT_RUN_UPSTREAM_FAIL`;
- fresh 50-case block: `LOCKED_UNOPENED`;
- calendar 2025: `LOCKED_UNOPENED`;
- calendar 2026: `LOCKED_UNOPENED`;
- paid acquisition: none.

The bounded next research step, if authorized, is an outcome-blind
**auction-object translation pass** on these same charts.  It must explicitly
label and learn the controlling level, level lifecycle, response sequence,
invalidation owner and target owner—including negative/no-trade examples—then
rerun this same-month semantic gate.  It must not inspect PnL or open another
month until the semantic gate passes.

## Artifacts

- Contract:
  `GOLD_COHERENT_AUCTION_AUTONOMOUS_TRANSLATION_REPLICATION_CONTRACT_V1.md`
- Exact human-input control:
  `research_artifacts/gold_coherent_auction_autonomous_translation_v1/same_month_overlay_control.json`
- Autonomous semantic result:
  `research_artifacts/gold_coherent_auction_autonomous_translation_v1/semantic_calibration.json`
- Outcome-hidden checkpoint tape:
  `research_artifacts/gold_coherent_auction_autonomous_translation_v1/semantic_checkpoint_rows.parquet`
- Control verifier:
  `tools/verify_gold_coherent_auction_v2_same_month_control.py`
- Semantic scanner:
  `tools/calibrate_gold_coherent_auction_autonomous_semantics_v1.py`

