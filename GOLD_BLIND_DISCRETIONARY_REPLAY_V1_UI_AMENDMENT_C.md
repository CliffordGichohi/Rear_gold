# Gold Blind Discretionary Replay V1 — Pre-Label UI Amendment C

Status: `FROZEN_INTERACTION_AND_DISPLAY_ONLY_BEFORE_IMPLEMENTATION`

Authorized on 2026-08-13 before any human decision was collected. The sealed UI Amendment B predecessor was verified with zero mismatches, zero decisions, an absent decision ledger and next case `P-001`.

## Purpose

Make the blind replay workstation behave more like a practical chart-replay terminal without changing the frozen study, the execution model, or the information available at a decision.

## Permitted changes

1. Add a concise macro pulse assembled only from the existing point-in-time fundamental component records. Display the component's own explanation, direction, epistemic status and quality; never invent a causal statement or silently convert an unknown component into a known one.
2. Improve long/short drawings so entry, stop-loss and take-profit are three explicit marked price levels with labelled TradingView-style risk/reward areas, a live construction preview and an executable/non-executable status.
3. Permit browser-local selection and deletion of drawings. Deleting a position drawing must also clear its mapped, unsubmitted execution plan. Drawings remain disposable and have no research credit.
4. Add a browser-local position inspector and remark input. The remark maps to the existing frozen `thesis` decision field; entry, stop and target geometry may prefill the existing trigger, invalidation and target-explanation fields with transparent normalized-price descriptions that remain participant-editable.
5. Add a bottom relative-time axis based only on the already-public bar ordinal and selected timeframe. Absolute calendar dates and clock times remain hidden. Calendar labels may not be exposed until the blind protocol is completed or separately terminated before labeling.
6. Add an explicit armed paper-trade workflow. A completed executable position may be armed; pressing the dedicated Play/Place control then submits the same existing append-only decision form. It may not bypass required confidence, evidence, remark, trigger, invalidation or target rationale. Arming is required to prevent accidental irreversible submission.
7. Practice future bars may be animated only after the practice decision has been locked and returned by the existing API. Scored future bars remain hidden. No new outcome endpoint or source access is permitted.
8. Add keyboard-safe selection/deletion, clearer instructions and automated interaction tests.

## Frozen safeguards

- The existing visible-history Replay control continues to animate only past candles already present in the certified display payload.
- A chart drawing alone is never a trade. Only an armed, valid plan with every frozen decision requirement satisfied may invoke the existing append-only submission.
- The maximum planned risk remains `$50`; costs, latency, entry semantics, stop/target bounds, expiry, stop-first ambiguity and all evaluation rules remain unchanged.
- A position whose geometry lies outside frozen execution bounds may be displayed for diagnosis but must be clearly marked non-executable and may not be armed or submitted.
- Selecting, editing visually through re-drawing, annotating or deleting an unsubmitted tool does not alter any source or case record.

## Prohibited changes

This amendment may not change or inspect population identities, case ordering, aliases, checkpoints, source histories, hashes, practice/scored outcome construction, 2025/2026 values, decision schema, execution rules, risk, cost, statistics, scoring or PASS/REJECT gates. It may not auto-select direction, confidence, evidence or a trade and may not use an outcome to change a displayed plan.

The UI Amendment B predecessor remains permanently preserved. A successor seal may pass only if all research/data/backend predecessor hashes remain unchanged, zero decisions and `P-001` still hold, automated tests cover macro rendering, relative labels, position construction/deletion and armed submission safety, the deployed route is healthy, and no acquisition or charge occurs.
