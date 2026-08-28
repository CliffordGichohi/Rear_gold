# Gold Auction-Plan Compiler V1 — Semantic Amendment A

Status: `FROZEN_BEFORE_AMENDED_FULL_RECOMPILATION`

## 1. Purpose

This amendment preserves the formal V1 `FAIL_SEMANTIC_FIDELITY_CERTIFICATION` verdict and every V1 artifact and seal. It corrects only a semantic representation defect identified without opening outcomes: V1 forced the M15 setup transition and an optional M5 entry refinement to compete for one `local_trigger` label.

No human annotation is declared market truth. Human annotations are used only to test whether the compiler can represent the stated decision process. A semantic PASS will not establish profitability, directional correctness, or an edge.

## 2. Permitted changes

The amended trigger component must preserve three distinct layers:

1. the existing H4/H1 `governing_auction` and `controlling_structure`;
2. an M15 `setup_transition`, represented by the latest active aligned M15 structural break or, when applicable, the already-defined active M15 balance context;
3. an optional M5 `entry_refinement`, represented by the latest active aligned M5 structural break contained by the M15 setup context.

The previous V1 trigger selected for structural calculations remains recorded as a value-blind `execution_anchor`. This preserves V1 governing-auction, invalidation, and destination calculations exactly while preventing that anchor from erasing the other semantic layer.

The human-family comparator may change only to enforce the already-frozen V1 rule that an M15 range nested inside an H1/H4 trend remains `CONTINUATION_WITH_ROOM`. `RANGE_ROTATION` requires an explicitly controlling H1 or H4 range with premium/discount location.

The previous 75% trigger-timeframe gate is not lowered. It is applied to hierarchy coverage: every M15 or M5 layer explicitly referenced in the annotation must exist in the corresponding compiled field. Extra observable layers are reported but are not treated as disagreement.

## 3. Preserved definitions and prohibitions

The following remain unchanged:

- all point-in-time structural primitives and thresholds;
- H4/H1 governing-auction classification order;
- structural invalidation construction;
- liquidity-destination construction;
- macro treatment as context rather than an admission filter;
- the 30 exposed human cases and 20 exposed GAV signal identities;
- every V1 population count and certification threshold;
- primary/reference reproduction requirements;
- no learned stop, target, family, or outcome input;
- no outcomes, post-decision paths, MFE, MAE, PnL, R, 2025, 2026, fresh period, acquisition, or charge.

The compiler remains a plan compiler. It receives a proposed timestamp, direction, and visible entry reference; it is not yet an independent setup detector.

## 4. Certification disposition

The amended implementation must be frozen before full recompilation. It must pass synthetic hierarchy and causality tests, compile both certified stream implementations, document every mismatch, and record an honest PASS or FAIL.

A PASS authorizes design of a separate blind setup-detection test. It does not authorize a profitability claim or imply that either the human annotations or compiler classifications are objectively correct.
