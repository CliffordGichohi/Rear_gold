# Gold Coherent-Auction End-to-End Same-Month Replication V1

Status: `FROZEN_BEFORE_NEW_POSTDECISION_PATH_RUN`

## Purpose

Perform the test that was previously left incomplete: provide only the sealed
same-month market/context streams to an autonomous translator and require it to
produce setup timing, direction, entry, structural stop, liquidity target,
V2 admission, management and PnL. Do not combine autonomous detections with
stored human executions.

This is an in-sample translation audit. It can show that the human policy was
encoded rather than mistranslated; it cannot validate an edge.

## Preserved evidence

- `PROMISING_EXPOSED_CALIBRATION_NOT_VALIDATED` for the human-input V2 policy:
  `+10.68184658R` from 11 admitted human setups.
- `SEALED_FAIL_AUTONOMOUS_SEMANTICS` for Autonomous Translation V1.
- The later `+7.63034801R` hybrid attribution is preserved as a separate
  counterfactual and is prohibited as the autonomous benchmark.
- The fresh 50-case block and calendar 2025/2026 remain locked.

## Frozen population and sources

- Cases: `CBR-2022-001` through `CBR-2022-030`.
- Market/context inputs: only the certified primary/reference replay streams.
- Calibration labels: only the 30 sealed visible human records (16 LONG and 14
  NO_TRADE). Outcome ledgers, terminal direction, MFE, MAE and PnL are forbidden
  during translator fitting.
- Inference runs in a separate process and may open only the frozen translator
  artifact plus certified raw streams. It may not read the human ledger,
  prepath classifications, stored scanner rows/timestamps, comparison results,
  case-specific rules or outcome artifacts.

Case alias is permitted only as an output/source-join identity. Calendar date,
case alias, absolute timestamp and absolute price are prohibited model inputs.

## Frozen decision grid and feature registry

- Scan every observed minute in the London 08:00–12:00 local session and New
  York 08:00–12:00 local session, DST-aware, in chronological order.
- A human trade day's calibration universe ends at its sealed decision minute;
  a human no-trade day retains the complete grid. The decision minute alone is
  positive. Autonomous inference scans the complete grid and takes the first
  signal only.
- Use the existing outcome-blind semantic feature registry for completed M5,
  M15, H1 and H4 candles, structure, liquidity-shift chains, session phase,
  point-in-time macro and Tier-1 event state.
- Add the identical normalized completed-M1 candle/structure registry: ATR,
  1/3/6-bar returns, range, body, efficiency, alternation, swing-range
  position, causal structural breaks and sweep/reclaim flags.
- Missing numeric values use a `-999` sentinel plus an explicit missing flag.
  Categorical values use frozen one-hot levels. No future-formed object is
  eligible before its `detected_at`/`available_at`.

## Frozen transparent translator

### Setup timing

Fit a single CART classifier with Gini impurity and random seed `20220821`.
Search only this preregistered semantic-complexity grid:

- maximum depth: `6, 8, 10, 12, 16, unlimited`;
- maximum leaves: `16, 32, 64, 128, unlimited`;
- minimum leaf size: `1`;
- positive class weight: exact negative/positive row ratio;
- probability threshold: `0.50, 0.75, 0.90`;
- consecutive qualifying minutes: exactly `1`.

Rank by: semantic PASS, matched trade days, fewer no-trade false positives,
smaller median timing error, smaller maximum timing error, fewer nodes, shallower
depth, higher threshold. Semantic PASS requires all 16 human trade days within
one minute, zero signals on all 14 no-trade days, median timing error at most one
minute and maximum timing error at most one minute. If it fails, stop before
economic inference.

### Geometry and thesis family

At the exact 16 positive calibration checkpoints, use the latest completed M1
close as the price reference and completed M15 ATR(14) as scale. Fit three
single CART translators with seed `20220821`, unlimited depth and leaf size 1:

- adverse stop distance in M15 ATR;
- forward target distance in M15 ATR;
- `CONTINUATION_WITH_ROOM`, `RANGE_ROTATION`, or `STRUCTURAL_REPAIR`.

These models must reproduce all 16 positive-checkpoint stop and target levels
within `$0.01` and all 16 families exactly. They may not output absolute price.
Failure stops the audit before outcome inference.

The frozen artifact must contain the preprocessing schema and complete tree
nodes so inference can be performed without scikit-learn objects or the human
ledger.

## Frozen autonomous execution

1. Direction is LONG because the exposed calibration population contains no
   human SHORT example. This limitation must be reported.
2. At the first signal, reconstruct stop and target from the current completed
   M1 reference, completed M15 ATR and frozen geometry trees.
3. Fill at the first observed M1 open strictly after the signal, adding half
   the observed spread and `$0.05/oz` entry slippage.
4. Estimated round-trip cost is the decision-time observed spread plus
   `$0.10/oz` slippage; commission remains `$0.00/oz`.
5. Quantity is `floor(50 / (absolute fill-to-stop distance + estimated
   round-trip cost per ounce))`, capped at `$50` planned loss.
6. Apply the unchanged V2 contextual gates using the model-produced thesis
   family and geometry. Human annotations are unavailable and cannot be used.
7. Apply `COMPLETE_V2_POLICY` unchanged: completed-M15 `+1.25R` protection,
   bounded 20% continuation runner, stop-first ambiguity and UTC-day time exit.
8. One decision and at most one position per case. Invalid geometry is an
   explicit no-trade, never repaired.

## Frozen replication gates and reporting

The end-to-end replication PASS requires:

- semantic and geometry calibration gates PASS before path access;
- inference reads no prohibited human or result artifact;
- autonomous primary/reference decisions and results match exactly;
- 16 setup days, 14 no-trade days, 11 V2 admissions and 5 V2 rejections match;
- autonomous complete-policy PnL is within `1.00R` of `+10.68184658R`;
- two complete inference reruns have identical decision/result checksums.

Report every autonomous signal, geometry, admission/rejection and result, plus
the exact comparison with human V2. A failure of any gate is an honest FAIL,
not permission to retune. No new rule, fallback, hard-coded timestamp or hybrid
arithmetic is permitted after the model artifact is frozen.
