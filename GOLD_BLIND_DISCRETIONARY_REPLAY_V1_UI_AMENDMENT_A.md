# Gold Blind Discretionary Replay V1 — Pre-Label UI Amendment A

Status: `FROZEN_DISPLAY_ONLY_BEFORE_IMPLEMENTATION`

Authorized on 2026-08-13 before any human decision was collected. The predecessor pre-label freeze was verified with zero hash mismatches, the next case remained `P-001`, and the decision ledger did not exist.

## Purpose

Improve usability without changing the research question or anything that can affect case selection, information availability, decisions, execution, or scoring.

The amendment permits only:

1. TradingView-like dark chart presentation using teal bullish candles, red bearish candles, dark navy background, grey grid/axis text, blue checkpoint reference, and amber pre-existing levels.
2. A visible chart legend.
3. On-screen instructions describing the required top-down labeling process.
4. Field-level explanations for action, confidence, entry trigger, signed ATR entry offset, stop, target, evidence, thesis, trigger, invalidation, and target rationale.
5. A normalized, arithmetic execution-plan preview calculated exclusively from the already displayed checkpoint reference, M15 ATR, and the participant's current form values. This preview is not an outcome and does not inspect a future bar.
6. Client-side bounds and neutral starting offsets that exactly mirror the already frozen backend validation rules.

## Prohibited changes

This amendment may not change or inspect:

- any case identity, alias, stratum, order, checkpoint, source, chart bar, context field, or source hash;
- practice or scored future paths;
- 2025 or 2026 data;
- `LONG`, `SHORT`, or `NO_TRADE` semantics;
- the fixed execution engine, latency, fills, stops, targets, costs, risk, expiry, ambiguity or overlap rules;
- confidence interpretation, evidence codes, decision fields, append-only ledger semantics, evaluation metrics, support floors, statistical methods, or PASS/REJECT gates;
- any historical outcome, relationship, performance measure, or edge conclusion.

The predecessor freeze and its original hashes remain permanently preserved. After implementation, all tests must pass, the deployed application must still report zero decisions and `P-001`, and a successor UI-amendment seal must record the exact changed-file hashes before labeling begins.
