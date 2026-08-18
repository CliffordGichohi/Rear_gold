# GC Microstructure Step 5C — Outcome-Blind Feature Materialization

## Formal verdict

`PASS_STEP_5C_FEATURE_MATERIALIZATION`

## Frozen coverage

- Decision rows: `376` (`188` London and `188` New York).
- Available one-second bucket rows: `336,600`.
- Available sessions: `374`; documented unavailable Good Friday sessions: `2`.
- Raw features: `85`; derived microstructure states: `8`; eligible fundamental contexts: `8`; eligible price/session contexts: `7`.

## Integrity and reproduction

- Formal gates passed: `12/12`.
- Independent reproduction: `PASS`.
- Continuous-matching crossed bucket closes: `0`.
- Source timestamp/order regressions: `0`.
- Publisher/instrument mismatches: `0`.
- Unknown-action or maybe-bad-book rows: `0`.

## Scope boundary

No development outcome was opened or joined. No 2025 or 2026 value was accessed. No relationship, candidate, signal, execution, trade, PnL, R multiple, or return was calculated. No data was acquired and no charge was incurred.

Step 5C is complete. Work stops before outcome access or conditional-edge discovery.
